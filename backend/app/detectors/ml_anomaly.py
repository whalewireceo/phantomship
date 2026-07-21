"""ML-based behavioral anomaly detection (Isolation Forest).

We train an Isolation Forest on synthetic 'normal' motion features at startup,
then score each live vessel. The model captures multivariate outliers in the
feature space — vessels whose combination of speed, course volatility, and
recent displacement is inconsistent with the rest of the fleet — without
needing labeled training data.

This complements the rule-based detectors: rules catch things we know to
look for, while the model catches behavior that's just *off* even when no
single rule fires.
"""
from __future__ import annotations

import math
import random
from typing import Optional

import numpy as np
from sklearn.ensemble import IsolationForest

from app.data.simulator import haversine_nm
from app.detectors.base import Detector
from app.models import DetectorType, Severity, Threat, Vessel


# Score threshold below which we flag (Isolation Forest decision_function
# returns higher = more normal, negative = more anomalous).
ANOMALY_THRESHOLD = -0.08


def _features_from_track(v: Vessel) -> Optional[np.ndarray]:
    """Compute a 5-dimensional motion feature vector for a vessel.

    Returns None if the track isn't long enough yet.
    """
    if len(v.track) < 3:
        return None
    speeds = [p.speed_knots for p in v.track[-6:]] + [v.last_position.speed_knots]
    courses = [p.course for p in v.track[-6:]] + [v.last_position.course]

    mean_speed = float(np.mean(speeds))
    std_speed = float(np.std(speeds))

    # Circular-mean variance for course (handle 359 -> 1 wrap)
    course_radians = np.deg2rad(courses)
    sin_mean = float(np.mean(np.sin(course_radians)))
    cos_mean = float(np.mean(np.cos(course_radians)))
    course_var = 1.0 - math.sqrt(sin_mean ** 2 + cos_mean ** 2)

    # Recent net displacement vs straight-line distance traveled
    p0 = v.track[-min(6, len(v.track))]
    net_nm = haversine_nm(p0.lon, p0.lat, v.last_position.lon, v.last_position.lat)
    path_nm = 0.0
    pts = v.track[-min(6, len(v.track)):] + [v.last_position]
    for a, b in zip(pts[:-1], pts[1:]):
        path_nm += haversine_nm(a.lon, a.lat, b.lon, b.lat)
    straightness = net_nm / path_nm if path_nm > 1e-6 else 1.0

    return np.array([mean_speed, std_speed, course_var, net_nm, straightness], dtype=float)


class MLAnomalyDetector(Detector):
    detector_type = DetectorType.ML_ANOMALY

    def __init__(self, contamination: float = 0.03, seed: int = 7) -> None:
        self.model = IsolationForest(
            n_estimators=120,
            contamination=contamination,
            random_state=seed,
        )
        self._fit_synthetic(seed)

    def _fit_synthetic(self, seed: int) -> None:
        """Generate a synthetic 'normal' dataset and fit the model."""
        rng = random.Random(seed)
        np_rng = np.random.default_rng(seed)
        n = 2000
        # Normal cargo/tanker motion: speeds 8-22, low variance, low course
        # variability, modest displacement, near-straight tracks.
        speeds = np_rng.uniform(8.0, 22.0, n)
        std_speeds = np_rng.uniform(0.1, 1.2, n)
        course_var = np_rng.uniform(0.0, 0.05, n)
        net_nm = speeds * np_rng.uniform(0.05, 0.15, n)  # ~few NM per 5 ticks
        straightness = np_rng.uniform(0.85, 1.0, n)
        X = np.column_stack([speeds, std_speeds, course_var, net_nm, straightness])
        # Add a handful of slower fishing-vessel patterns
        m = 400
        s2 = np_rng.uniform(4.0, 9.0, m)
        std2 = np_rng.uniform(0.5, 2.5, m)
        cv2 = np_rng.uniform(0.05, 0.25, m)
        net2 = s2 * np_rng.uniform(0.03, 0.10, m)
        straight2 = np_rng.uniform(0.5, 0.9, m)
        X2 = np.column_stack([s2, std2, cv2, net2, straight2])
        X = np.vstack([X, X2])
        self.model.fit(X)

    def scan(self, vessels: list[Vessel]) -> list[Threat]:
        threats: list[Threat] = []
        feats: list[np.ndarray] = []
        owners: list[Vessel] = []
        for v in vessels:
            f = _features_from_track(v)
            if f is None:
                continue
            feats.append(f)
            owners.append(v)
        if not feats:
            return threats
        X = np.vstack(feats)
        scores = self.model.decision_function(X)
        for v, score, feat in zip(owners, scores, feats):
            if score < ANOMALY_THRESHOLD:
                # Rough severity grading
                if score < -0.18:
                    sev = Severity.HIGH
                elif score < -0.13:
                    sev = Severity.MEDIUM
                else:
                    sev = Severity.LOW
                threats.append(Threat(
                    id=self.make_id("ml", v.mmsi, str(v.last_position.timestamp)),
                    mmsi=v.mmsi,
                    vessel_name=v.name,
                    detector=DetectorType.ML_ANOMALY,
                    severity=sev,
                    title="ML behavioral anomaly",
                    description=(
                        f"{v.name} flagged by behavioral model "
                        f"(score {score:+.3f}). Motion pattern is statistically "
                        f"inconsistent with the rest of the fleet."
                    ),
                    evidence={
                        "anomaly_score": round(float(score), 4),
                        "features": {
                            "mean_speed_knots": round(float(feat[0]), 2),
                            "std_speed_knots":  round(float(feat[1]), 2),
                            "course_variance":  round(float(feat[2]), 3),
                            "net_displacement_nm": round(float(feat[3]), 1),
                            "straightness":       round(float(feat[4]), 3),
                        },
                    },
                    lat=v.last_position.lat,
                    lon=v.last_position.lon,
                    detected_at=self.now_iso(),
                ))
        return threats
