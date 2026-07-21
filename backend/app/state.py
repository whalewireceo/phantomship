"""Application state engine.

Wraps the data source (simulator or live AISStream) and a stack of detectors.
A background asyncio task ticks the simulator and re-runs all detectors at a
fixed cadence; the API reads from the cached state.
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import SETTINGS
from app.data.ais_stream import AISStreamFeed
from app.data.critical_zones import CRITICAL_ZONES
from app.data.simulator import Simulator
from app.detectors import default_detectors
from app.models import Severity, Threat, Vessel


log = logging.getLogger(__name__)


_SEVERITY_SCORE = {
    Severity.LOW: 0.25,
    Severity.MEDIUM: 0.5,
    Severity.HIGH: 0.75,
    Severity.CRITICAL: 1.0,
}


class StateEngine:
    """Central application state."""

    def __init__(self) -> None:
        self.mode: str = SETTINGS.data_source
        self.simulator: Optional[Simulator] = None
        self.live: Optional[AISStreamFeed] = None
        self.detectors = default_detectors()
        # Threats ordered by detection time (newest at end). Cap to last N.
        self.threats: "OrderedDict[str, Threat]" = OrderedDict()
        self.threat_cap = 250
        self._task: Optional[asyncio.Task] = None
        self._tick_n = 0
        self._started_at: Optional[datetime] = None

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
                self.simulator = Simulator()
        else:
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
        # Newest first
        return list(self.threats.values())[::-1]

    def find_threat(self, threat_id: str) -> Optional[Threat]:
        return self.threats.get(threat_id)

    def find_vessel(self, mmsi: str) -> Optional[Vessel]:
        for v in self.vessels_including_dark():
            if v.mmsi == mmsi:
                return v
        return None

    def stats(self) -> dict:
        sev_counts = {s.value: 0 for s in Severity}
        det_counts: dict[str, int] = {}
        for t in self.threats.values():
            sev_counts[t.severity.value] += 1
            det_counts[t.detector.value] = det_counts.get(t.detector.value, 0) + 1
        vessels = self.vessels()
        return {
            "mode": self.mode,
            "uptime_seconds": int((datetime.now(timezone.utc) - self._started_at).total_seconds()) if self._started_at else 0,
            "tick": self._tick_n,
            "vessels_tracked": len(vessels),
            "vessels_dark": sum(1 for v in self.vessels_including_dark() if v.is_dark),
            "threats_active": len(self.threats),
            "threats_by_severity": sev_counts,
            "threats_by_detector": det_counts,
            "critical_zones": len(CRITICAL_ZONES),
        }

    # ------------------------------------------------------------ internal #
    async def _loop(self) -> None:
        while True:
            try:
                if self.simulator:
                    self.simulator.tick()
                self._tick_n += 1
                self._run_detectors()
                self._expire_old_threats()
                self._recompute_threat_scores()
            except Exception:
                log.exception("tick failed")
            await asyncio.sleep(SETTINGS.sim_tick_seconds)

    def _run_detectors(self) -> None:
        vessels = self.vessels()
        for det in self.detectors:
            try:
                new = det.scan(vessels)
            except Exception:
                log.exception("%s scan failed", det.__class__.__name__)
                continue
            for t in new:
                if t.id not in self.threats:
                    self.threats[t.id] = t
                    if len(self.threats) > self.threat_cap:
                        self.threats.popitem(last=False)

    def _expire_old_threats(self) -> None:
        """Drop threats older than 30 minutes to keep the live feed actionable."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        to_drop = [tid for tid, t in self.threats.items() if t.detected_at < cutoff]
        for tid in to_drop:
            self.threats.pop(tid, None)

    def _recompute_threat_scores(self) -> None:
        """Aggregate threat scores per vessel for visualization color-grading."""
        score_by_mmsi: dict[str, float] = {}
        for t in self.threats.values():
            s = _SEVERITY_SCORE[t.severity]
            score_by_mmsi[t.mmsi] = max(score_by_mmsi.get(t.mmsi, 0.0), s)
        for v in self.vessels_including_dark():
            v.threat_score = score_by_mmsi.get(v.mmsi, 0.0)


# Singleton, imported by FastAPI app
state_engine = StateEngine()
