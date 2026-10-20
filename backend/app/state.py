"""Application state engine.

Wraps the data source (simulator or live AISStream) and a stack of detectors.
A background asyncio task ticks the source and re-runs all detectors at a
fixed cadence; the API reads from the cached state.

Alerts are episodes. Detectors re-evaluate every vessel on every scan, so a
condition that persists (a ship loitering for an hour, a transponder stuck
on a bad speed) is reported again and again. Those repeats update one alert
(last_seen_at, occurrences, latest evidence) instead of creating new ones,
and an alert expires once its condition has not been seen for a while.
Without this, one live run wrote 32,000 alerts in eight minutes.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import SETTINGS
from app.data.ais_stream import AISStreamFeed
from app.data.critical_zones import CRITICAL_ZONES
from app.data.geo import haversine_nm
from app.data.simulator import Simulator
from app.detectors import default_detectors
from app.detectors.base import ScanContext
from app.detectors.ml_anomaly import MLAnomalyDetector
from app.models import SEVERITY_RANK, Severity, Threat, Vessel


log = logging.getLogger(__name__)


_SEVERITY_SCORE = {
    Severity.LOW: 0.25,
    Severity.MEDIUM: 0.5,
    Severity.HIGH: 0.75,
    Severity.CRITICAL: 1.0,
}

COVERAGE_RECENT_MINUTES = 10.0


class CoverageIndex:
    """Grid of recently heard vessels, for 'is anyone else heard here?'."""

    def __init__(self, vessels: list[Vessel], now: datetime) -> None:
        cutoff = now - timedelta(minutes=COVERAGE_RECENT_MINUTES)
        self._cells: dict[tuple[int, int], list[tuple[str, float, float]]] = {}
        for v in vessels:
            p = v.last_position
            if p.timestamp < cutoff:
                continue
            self._cells.setdefault((int(p.lat // 1), int(p.lon // 1)), []).append((v.mmsi, p.lon, p.lat))

    def __call__(self, lon: float, lat: float, exclude_mmsi: str) -> int:
        need = SETTINGS.dark_coverage_min_neighbors
        radius = SETTINGS.dark_coverage_radius_nm
        n = 0
        ci, cj = int(lat // 1), int(lon // 1)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                j = ((cj + dj + 180) % 360) - 180
                for mmsi, olon, olat in self._cells.get((ci + di, j), ()):
                    if mmsi == exclude_mmsi:
                        continue
                    if haversine_nm(lon, lat, olon, olat) <= radius:
                        n += 1
                        if n >= need:
                            return n
        return n


class StateEngine:
    """Central application state."""

    def __init__(self) -> None:
        self.mode: str = SETTINGS.data_source
        self.simulator: Optional[Simulator] = None
        self.live: Optional[AISStreamFeed] = None
        self.detectors = default_detectors()
        # Alerts ordered by last activity (most recent at the end).
        self.threats: "OrderedDict[str, Threat]" = OrderedDict()
        self.threat_cap = SETTINGS.threat_cap
        self._active_key: dict[tuple[str, str, str], str] = {}
        self._key_of: dict[str, tuple[str, str, str]] = {}
        self._event_ids: dict[str, set[str]] = {}
        self._task: Optional[asyncio.Task] = None
        self._tick_n = 0
        self._started_at: Optional[datetime] = None
        self._last_scan_ms = 0.0
        self._slow_warned_at = 0.0
        self._findings_written = 0
        self._detector_quality: dict[str, int] = {}

    # ----------------------------------------------------------------- API #
    async def start(self) -> None:
        self._started_at = datetime.now(timezone.utc)
        if self.mode == "live":
            try:
                self.live = AISStreamFeed()
                await self.live.start()
                log.info("PhantomShip started in LIVE mode (AISStream)")
            except Exception as e:
                log.warning(
                    "Falling back to simulator mode (%s). Set AISSTREAM_API_KEY to enable live data.", e
                )
                self.mode = "simulator"
                self.live = None
                self.simulator = Simulator()
        else:
            if self.mode != "simulator":
                log.warning("Unknown PHANTOMSHIP_DATA_SOURCE %r; using simulator", self.mode)
                self.mode = "simulator"
            self.simulator = Simulator()
            log.info("PhantomShip started in SIMULATOR mode (%d vessels)", len(self.simulator.vessels))
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self.live:
            await self.live.stop()

    def _source(self):
        return self.simulator if self.mode == "simulator" else self.live

    def vessels(self) -> list[Vessel]:
        src = self._source()
        return src.all_vessels() if src else []

    def vessels_including_dark(self) -> list[Vessel]:
        src = self._source()
        return src.all_vessels_including_dark() if src else []

    def threats_list(self) -> list[Threat]:
        # Most recently active first
        return list(self.threats.values())[::-1]

    def find_threat(self, threat_id: str) -> Optional[Threat]:
        return self.threats.get(threat_id)

    def find_vessel(self, mmsi: str) -> Optional[Vessel]:
        src = self._source()
        return src.get(mmsi) if src else None

    def ml_status(self) -> Optional[dict]:
        for d in self.detectors:
            if isinstance(d, MLAnomalyDetector):
                return d.status()
        return None

    def data_quality(self) -> dict[str, int]:
        # Detector counters are copied at the end of each scan (see
        # _scan_all), so this never iterates a dict the scan thread is writing.
        dq: dict[str, int] = dict(self._detector_quality)
        src = self._source()
        for k, v in dict(getattr(src, "quality", None) or {}).items():
            dq[k] = dq.get(k, 0) + v
        return dict(sorted(dq.items()))

    def stats(self) -> dict:
        sev_counts = {s.value: 0 for s in Severity}
        det_counts: dict[str, int] = {}
        for t in self.threats.values():
            sev_counts[t.severity.value] += 1
            det_counts[t.detector.value] = det_counts.get(t.detector.value, 0) + 1
        vessels = self.vessels()
        everything = self.vessels_including_dark()
        out = {
            "mode": self.mode,
            "uptime_seconds": int((datetime.now(timezone.utc) - self._started_at).total_seconds()) if self._started_at else 0,
            "tick": self._tick_n,
            "scan_ms": round(self._last_scan_ms, 1),
            "vessels_tracked": len(vessels),
            "vessels_dark": sum(1 for v in everything if v.is_dark),
            "threats_active": len(self.threats),
            "threats_by_severity": sev_counts,
            "threats_by_detector": det_counts,
            "findings_written": self._findings_written,
            "critical_zones": len(CRITICAL_ZONES),
            "ml": self.ml_status(),
            "data_quality": self.data_quality(),
            "ai_enabled": bool(SETTINGS.anthropic_api_key),
        }
        if self.live is not None:
            out["feed"] = dict(self.live.status)
        return out

    # ------------------------------------------------------------ internal #
    async def _loop(self) -> None:
        while True:
            try:
                started = time.perf_counter()
                src = self._source()
                if src is not None:
                    src.tick()
                self._tick_n += 1
                await self._run_detectors_async()
                self._expire_old_threats()
                self._recompute_threat_scores()
                self._last_scan_ms = (time.perf_counter() - started) * 1000.0
                if (self._last_scan_ms > SETTINGS.sim_tick_seconds * 1000.0
                        and time.monotonic() - self._slow_warned_at > 60):
                    self._slow_warned_at = time.monotonic()
                    log.warning("detector scan took %.0f ms for %d vessels", self._last_scan_ms, len(self.vessels()))
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(SETTINGS.sim_tick_seconds)

    def _prepare_scan(self) -> tuple[list[Vessel], ScanContext]:
        vessels = self.vessels()
        now = datetime.now(timezone.utc)
        coverage = CoverageIndex(vessels, now) if self.mode == "live" else None
        return vessels, ScanContext(mode=self.mode, now=now, coverage=coverage)

    def _scan_all(self, vessels: list[Vessel], ctx: ScanContext) -> list[Threat]:
        """Run every detector. Touches only detector state, so it can run in
        a worker thread while the event loop keeps reading the live feed."""
        found: list[Threat] = []
        for det in self.detectors:
            try:
                found.extend(det.scan(vessels, ctx))
            except Exception:
                log.exception("%s scan failed", det.__class__.__name__)
        dq: dict[str, int] = {}
        for det in self.detectors:
            for k, v in det.quality.items():
                dq[k] = dq.get(k, 0) + v
        self._detector_quality = dq
        return found

    def _run_detectors(self) -> None:
        """Synchronous scan + merge (used by tests and tools)."""
        vessels, ctx = self._prepare_scan()
        for t in self._scan_all(vessels, ctx):
            self._merge_threat(t, ctx.now)

    async def _run_detectors_async(self) -> None:
        vessels, ctx = self._prepare_scan()
        found = await asyncio.to_thread(self._scan_all, vessels, ctx)
        # Merging happens back on the event loop, where API handlers read
        # the alert list, so the two never race.
        for t in found:
            self._merge_threat(t, ctx.now)

    def _merge_threat(self, t: Threat, now: datetime) -> None:
        key = (t.detector.value, t.mmsi, t.kind())
        existing_id = self._active_key.get(key)
        ex = self.threats.get(existing_id) if existing_id else None
        if ex is None and t.id in self.threats:
            ex, existing_id = self.threats[t.id], t.id

        if ex is not None:
            ex.last_seen_at = now
            events = self._event_ids.setdefault(existing_id, set())
            if t.id not in events and len(events) < 1000:
                events.add(t.id)
                ex.occurrences += 1
            ex.evidence = t.evidence
            ex.description = t.description
            ex.vessel_name = t.vessel_name
            ex.lat, ex.lon = t.lat, t.lon
            self.threats.move_to_end(existing_id)
            if SEVERITY_RANK[t.severity] > SEVERITY_RANK[ex.severity]:
                ex.severity = t.severity
                ex.title = t.title
                self._record_finding(ex, event="escalated")
            return

        t.last_seen_at = now
        vessel = self.find_vessel(t.mmsi)
        if vessel is not None:
            t.vessel_snapshot = vessel.snapshot()
        self.threats[t.id] = t
        self._active_key[key] = t.id
        self._key_of[t.id] = key
        self._event_ids[t.id] = {t.id}
        self._record_finding(t, event="new", vessel=vessel)
        while len(self.threats) > self.threat_cap:
            old_id, _ = self.threats.popitem(last=False)
            self._forget(old_id)

    def _forget(self, threat_id: str) -> None:
        key = self._key_of.pop(threat_id, None)
        if key is not None and self._active_key.get(key) == threat_id:
            del self._active_key[key]
        self._event_ids.pop(threat_id, None)

    def _record_finding(self, threat: Threat, event: str, vessel: Optional[Vessel] = None) -> None:
        """Append a new or escalated alert to the findings log as one JSON line.

        Each record carries the data source ('live' or 'simulator') so real
        findings are never confused with planted demo anomalies, plus the
        vessel's recent track so the detection can be verified later.
        Recording must never break detection, so failures are only logged.
        """
        try:
            record = threat.to_public()
            record["event"] = event
            record["source"] = self.mode
            record["recorded_at"] = datetime.now(timezone.utc).isoformat()
            vessel = vessel or self.find_vessel(threat.mmsi)
            if vessel is not None:
                record["vessel"] = {
                    "type": vessel.vessel_type.value,
                    "flag": vessel.flag,
                    "length_m": vessel.length_m,
                    "destination": vessel.destination,
                }
                record["track"] = [
                    p.model_dump(mode="json")
                    for p in (vessel.track + [vessel.last_position])
                ]
            path = SETTINGS.findings_path
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            self._rotate_if_large(path)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            self._findings_written += 1
        except Exception:
            log.exception("failed to record finding %s", threat.id)

    @staticmethod
    def _rotate_if_large(path: str) -> None:
        """Keep the log bounded: past the size limit it moves to .1 (replacing
        any older .1) and a fresh file starts."""
        try:
            if os.path.getsize(path) > SETTINGS.findings_max_mb * 1024 * 1024:
                os.replace(path, path + ".1")
        except FileNotFoundError:
            pass

    def _expire_old_threats(self) -> None:
        """Drop alerts whose condition has not been seen for a while."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=SETTINGS.threat_expire_minutes)
        to_drop = [tid for tid, t in self.threats.items() if (t.last_seen_at or t.detected_at) < cutoff]
        for tid in to_drop:
            self.threats.pop(tid, None)
            self._forget(tid)

    def _recompute_threat_scores(self) -> None:
        """Aggregate threat scores per vessel for visualization color-grading."""
        score_by_mmsi: dict[str, float] = {}
        for t in self.threats.values():
            s = _SEVERITY_SCORE[t.severity]
            score_by_mmsi[t.mmsi] = max(score_by_mmsi.get(t.mmsi, 0.0), s)
        for v in self.vessels_including_dark():
            s = score_by_mmsi.get(v.mmsi, 0.0)
            if v.threat_score != s:
                v.threat_score = s


# Singleton, imported by FastAPI app
state_engine = StateEngine()
