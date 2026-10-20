"""ML-based behavioral anomaly detection (Isolation Forest).

The model learns what "normal" movement looks like from the fleet it is
actually watching, then flags vessels whose movement is unusual compared to
that fleet. It needs no labeled data.

Why it learns online instead of shipping with a fixed baseline: the first
version trained on synthetic cargo ships doing 8 to 22 knots. Real oceans
are full of anchored ships, tugs, ferries and fishing boats, so in live mode
it flagged almost everything (2,704 of 3,221 alerts in one run, over 90% of
them ships that were simply stationary). A baseline is only meaningful if it
comes from the same population and the same data source it is scoring.

How it works:
  * Only vessels under way (mean speed at least 3 knots, all speeds and
    courses available) are modelled. "Stationary" is not a behaviour the
    model can say anything useful about, and the loitering rule covers it.
  * Features do not depend on how often a vessel reports: mean speed,
    speed variability, course variability, track straightness, and how well
    the distance actually covered matches the speed being reported.
  * Each eligible vessel contributes at most one sample per minute to a
    rolling baseline. The model stays quiet (status "learning") until the
    baseline has enough samples from enough distinct vessels, and refits
    periodically as traffic changes.
  * The alert threshold comes from the baseline itself: a vessel must score
    as more unusual than 99.8% of the baseline samples, and do so in at
    least 3 of its last 5 evaluations, so one odd reading does not alert.
  * ML alerts are LOW or MEDIUM. A statistical outlier is a reason to look,
    not evidence of anything on its own.
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from app.config import SETTINGS
from app.data.geo import haversine_nm
from app.detectors.base import Detector, ScanContext, full_track, recent
from app.models import DetectorType, Severity, Threat, Vessel, VesselType


log = logging.getLogger(__name__)

FEATURE_NAMES = (
    "mean_speed_knots", "std_speed_knots", "course_variance",
    "straightness", "speed_consistency",
)
MIN_UNDERWAY_KNOTS = 3.0
# Free AIS feeds deliver a report every few minutes per ship, so the window
# is long and the point count modest.
WINDOW_MINUTES = 30.0
MIN_POINTS = 5
MIN_SPAN_SECONDS = 45.0
BASELINE_MAX = 20_000
PERSIST_WINDOW = 5
PERSIST_HITS = 3
SCORE_INTERVAL_S = 10.0
THRESHOLD_QUANTILE = 0.002


# Classes whose normal movement is erratic by design (pilot boats, tugs,
# fishing, leisure craft, fast ferries). In the live replay they made up most
# of what the model flagged, and the rule based detectors already cover them.
_EXCLUDED_TYPES = {
    VesselType.TUG, VesselType.SERVICE, VesselType.FISHING, VesselType.PLEASURE,
    VesselType.HIGH_SPEED, VesselType.SPECIAL_OPS,
}


def _features_from_track(v: Vessel) -> Optional[np.ndarray]:
    """Rate-independent motion features, or None if the vessel is not eligible."""
    if v.vessel_type in _EXCLUDED_TYPES:
        return None
    pts = recent(full_track(v), v.last_position.timestamp, WINDOW_MINUTES)
    if len(pts) < MIN_POINTS:
        return None
    if not all(p.speed_available and p.course_available for p in pts):
        return None
    span_s = (pts[-1].timestamp - pts[0].timestamp).total_seconds()
    if span_s < MIN_SPAN_SECONDS:
        return None

    speeds = np.array([p.speed_knots for p in pts], dtype=float)
    mean_speed = float(speeds.mean())
    if mean_speed < MIN_UNDERWAY_KNOTS:
        return None
    std_speed = float(speeds.std())

    rad = np.deg2rad([p.course for p in pts])
    course_var = 1.0 - math.hypot(float(np.mean(np.sin(rad))), float(np.mean(np.cos(rad))))

    # Path length on a thinned track (points at least 20 s apart) so GPS
    # jitter between rapid reports does not dominate.
    thinned = [pts[0]]
    for p in pts[1:]:
        if (p.timestamp - thinned[-1].timestamp).total_seconds() >= 20.0:
            thinned.append(p)
    if thinned[-1] is not pts[-1]:
        thinned.append(pts[-1])
    path_nm = sum(
        haversine_nm(a.lon, a.lat, b.lon, b.lat) for a, b in zip(thinned[:-1], thinned[1:])
    )
    net_nm = haversine_nm(pts[0].lon, pts[0].lat, pts[-1].lon, pts[-1].lat)
    straightness = net_nm / path_nm if path_nm > 1e-6 else 1.0
    implied = path_nm / (span_s / 3600.0)
    consistency = min(implied / mean_speed, 3.0)

    return np.array([mean_speed, std_speed, course_var, straightness, consistency], dtype=float)


class MLAnomalyDetector(Detector):
    detector_type = DetectorType.ML_ANOMALY

    def __init__(self, contamination: Optional[float] = None, seed: int = 7) -> None:
        super().__init__()
        self.contamination = contamination if contamination is not None else SETTINGS.ml_contamination
        self.seed = seed
        self.model: Optional[IsolationForest] = None
        self._baseline: deque[tuple[str, np.ndarray]] = deque(maxlen=BASELINE_MAX)
        self._last_sample: dict[str, float] = {}
        self._last_scored: dict[str, float] = {}
        self._history: dict[str, deque[bool]] = {}
        self._fitted_at: float = 0.0
        self._fit_count = 0
        self.threshold = 0.0
        self._status = self._compute_status()

    # ------------------------------------------------------------ status #
    def status(self) -> dict:
        """Last status computed by scan(). Safe to read from another thread."""
        return self._status

    def _compute_status(self) -> dict:
        vessels = len({m for m, _ in self._baseline})
        return {
            "state": "active" if self.model is not None else "learning",
            "baseline_samples": len(self._baseline),
            "baseline_vessels": vessels,
            "min_samples": SETTINGS.ml_min_samples,
            "min_vessels": SETTINGS.ml_min_vessels,
            "fits": self._fit_count,
            "threshold": round(self.threshold, 4),
        }

    # -------------------------------------------------------------- scan #
    def scan(self, vessels: list[Vessel], ctx: Optional[ScanContext] = None) -> list[Threat]:
        now = time.monotonic()
        feats: list[np.ndarray] = []
        owners: list[Vessel] = []
        for v in vessels:
            if now - self._last_scored.get(v.mmsi, -1e9) < SCORE_INTERVAL_S:
                continue
            self._last_scored[v.mmsi] = now
            f = _features_from_track(v)
            if f is None:
                continue
            if now - self._last_sample.get(v.mmsi, -1e9) >= SETTINGS.ml_sample_interval_s:
                self._last_sample[v.mmsi] = now
                self._baseline.append((v.mmsi, f))
            feats.append(f)
            owners.append(v)

        self._maybe_fit(now)
        self._prune(vessels)
        self._status = self._compute_status()
        if self.model is None or not feats:
            return []

        scores = self.model.decision_function(np.vstack(feats))
        threats: list[Threat] = []
        for v, score, feat in zip(owners, scores, feats):
            hist = self._history.setdefault(v.mmsi, deque(maxlen=PERSIST_WINDOW))
            hit = bool(score < self.threshold)
            hist.append(hit)
            if not hit or sum(hist) < PERSIST_HITS:
                continue
            threats.append(self._make_threat(v, float(score), feat, sum(hist), len(hist)))
        return threats

    def _maybe_fit(self, now: float) -> None:
        n = len(self._baseline)
        if n < SETTINGS.ml_min_samples:
            return
        if self.model is not None and now - self._fitted_at < SETTINGS.ml_refit_seconds:
            return
        if len({m for m, _ in self._baseline}) < SETTINGS.ml_min_vessels:
            return
        X = np.vstack([f for _, f in self._baseline])
        model = IsolationForest(
            n_estimators=120,
            contamination=self.contamination,
            random_state=self.seed,
        )
        model.fit(X)
        # Alert threshold: more extreme than all but the most unusual
        # THRESHOLD_QUANTILE of the baseline itself, and never above 0.
        base_scores = model.decision_function(X)
        self.threshold = min(0.0, float(np.quantile(base_scores, THRESHOLD_QUANTILE)))
        self.model = model
        self._fitted_at = now
        self._fit_count += 1
        log.info("ML baseline fitted on %d samples (fit #%d)", n, self._fit_count)

    def _prune(self, vessels: list[Vessel]) -> None:
        if len(self._last_scored) <= 4 * max(len(vessels), 1000):
            return
        live = {v.mmsi for v in vessels}
        for d in (self._last_scored, self._last_sample, self._history):
            for k in [k for k in d if k not in live]:
                del d[k]

    def _make_threat(self, v: Vessel, score: float, feat: np.ndarray, hits: int, window: int) -> Threat:
        sev = Severity.MEDIUM if score < min(-0.1, 2 * self.threshold) else Severity.LOW
        return Threat(
            id=self.make_id("ml", v.mmsi),
            mmsi=v.mmsi,
            vessel_name=v.name,
            detector=DetectorType.ML_ANOMALY,
            severity=sev,
            title="ML behavioral anomaly",
            description=(
                f"{v.name}'s movement is unusual compared with the vessels currently "
                f"under way in this feed (score {score:+.3f}, anomalous in {hits} of its "
                f"last {window} checks). Worth a look; not evidence on its own."
            ),
            evidence={
                "kind": "ml_anomaly",
                "anomaly_score": round(score, 4),
                "persistence": f"{hits}/{window}",
                "baseline_samples": len(self._baseline),
                "features": {
                    name: round(float(x), 3) for name, x in zip(FEATURE_NAMES, feat)
                },
            },
            lat=v.last_position.lat,
            lon=v.last_position.lon,
            detected_at=self.now_iso(),
        )
