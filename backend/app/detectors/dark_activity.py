"""Dark-activity detection.

When a vessel disables its AIS transponder near sensitive infrastructure or
in a chokepoint, that is a hallmark of sanctions evasion, illicit
ship-to-ship transfers, and cable interference operations.

This detector tracks gaps in broadcast and flags vessels whose silence
started inside a critical zone.

Going quiet is ambiguous in live data. Terrestrial AIS receivers have
limited range, so ships "disappear" all the time simply by sailing out of
coverage, and ships in port often switch AIS off legitimately. In live mode
an alert therefore needs all of:

  * the silence started inside a watch zone, outside a port area, and the
    ship was not reporting itself moored;
  * the ship had been reporting regularly before it stopped;
  * the area still has receiver coverage: other vessels near the last
    known position are still being heard. If nobody nearby is heard either,
    the gap says more about the receivers than about the ship.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.config import SETTINGS
from app.data.critical_zones import zone_containing
from app.data.ports import port_area_at
from app.detectors.base import Detector, ScanContext, full_track, recent
from app.models import DetectorType, Severity, Threat, Vessel


MIN_REPORTS_BEFORE_SILENCE = 5      # in the hour before going quiet
FORGET_AFTER_MINUTES = 24 * 60


@dataclass
class _LastSeen:
    ts: datetime
    lat: float
    lon: float
    name: str
    reports_last_hour: int
    nav_status: Optional[int]


class DarkActivityDetector(Detector):
    detector_type = DetectorType.DARK_ACTIVITY

    def __init__(self) -> None:
        super().__init__()
        self._last_seen: dict[str, _LastSeen] = {}
        self._skipped: set[tuple[str, datetime]] = set()

    def scan(self, vessels: list[Vessel], ctx: Optional[ScanContext] = None) -> list[Threat]:
        ctx = ctx or ScanContext()
        threats: list[Threat] = []
        now = ctx.now
        current = {v.mmsi for v in vessels}

        for v in vessels:
            p = v.last_position
            prev = self._last_seen.get(v.mmsi)
            if prev is not None and prev.ts == p.timestamp:
                continue
            self._last_seen[v.mmsi] = _LastSeen(
                ts=p.timestamp, lat=p.lat, lon=p.lon, name=v.name,
                reports_last_hour=len(recent(full_track(v), p.timestamp, 60.0)),
                nav_status=p.nav_status,
            )

        for mmsi, ls in list(self._last_seen.items()):
            if mmsi in current:
                continue  # still broadcasting
            silent_for = (now - ls.ts).total_seconds() / 60.0
            if silent_for > FORGET_AFTER_MINUTES:
                del self._last_seen[mmsi]
                self._skipped.discard((mmsi, ls.ts))
                continue
            if silent_for < SETTINGS.dark_minutes_threshold:
                continue

            reason = self._skip_reason(mmsi, ls, ctx)
            if reason:
                key = (mmsi, ls.ts)
                if key not in self._skipped:
                    self._skipped.add(key)
                    self.count(reason)
                continue

            zone = zone_containing(ls.lon, ls.lat)
            if zone is None:
                # Simulator only: very long silence anywhere is worth a note.
                if silent_for > 120.0:
                    threats.append(self._make_threat(mmsi, ls, silent_for, None, None, Severity.LOW))
                continue
            severity = Severity.HIGH if zone.category == "cable" else Severity.MEDIUM
            threats.append(self._make_threat(mmsi, ls, silent_for, zone.name, zone.category, severity))

        if len(self._skipped) > 100_000:
            self._skipped.clear()
        return threats

    @staticmethod
    def _skip_reason(mmsi: str, ls: _LastSeen, ctx: ScanContext) -> Optional[str]:
        if ls.nav_status == 5 or port_area_at(ls.lon, ls.lat) is not None:
            return "dark_in_port_ignored"
        if not ctx.live:
            return None
        if zone_containing(ls.lon, ls.lat) is None:
            return "dark_outside_zone_ignored"
        if ls.reports_last_hour < MIN_REPORTS_BEFORE_SILENCE:
            return "dark_irregular_reporter"
        if ctx.coverage is not None:
            if ctx.coverage(ls.lon, ls.lat, mmsi) < SETTINGS.dark_coverage_min_neighbors:
                return "dark_no_receiver_coverage"
        return None

    def _make_threat(
        self, mmsi: str, ls: _LastSeen, silent_min: float,
        zone_name: str | None, zone_category: str | None, severity: Severity,
    ) -> Threat:
        if zone_name:
            description = (
                f"{ls.name} (MMSI {mmsi}) went silent inside {zone_name} ({zone_category}) "
                f"and has been dark for {silent_min:.0f} minutes while other vessels "
                f"nearby are still being received."
            )
            title = f"Dark activity in {zone_name}"
        else:
            description = (
                f"{ls.name} (MMSI {mmsi}) AIS dark for {silent_min:.0f} minutes. "
                f"Not currently inside a critical zone."
            )
            title = "Prolonged AIS silence"
        return Threat(
            # One alert per silence episode, keyed on when the silence began.
            id=self.make_id("dark", mmsi, ls.ts.isoformat()),
            mmsi=mmsi,
            vessel_name=ls.name,
            detector=DetectorType.DARK_ACTIVITY,
            severity=severity,
            title=title,
            description=description,
            evidence={
                "kind": f"dark:{zone_name or 'open_sea'}",
                "silent_minutes": round(silent_min, 1),
                "silent_since": ls.ts.isoformat(),
                "last_lat": ls.lat,
                "last_lon": ls.lon,
                "zone": zone_name,
                "zone_category": zone_category,
                "reports_in_hour_before": ls.reports_last_hour,
            },
            lat=ls.lat,
            lon=ls.lon,
            detected_at=self.now_iso(),
        )
