"""Loitering detection.

Vessels moving at near-zero speed inside critical zones (cable corridors,
chokepoints) for extended periods are a notable signature. State-linked
research and survey vessels associated with the Russian 'GUGI' fleet, for
example, have repeatedly been observed loitering on top of subsea cables,
and several Baltic cable cuts were caused by ships dragging anchor.

Most slow ships inside a zone are doing something ordinary, so live traffic
needs these rules:

  * Duration is measured from report timestamps, not from how many times
    the scanner ran, so a ship that stops reporting does not keep "loitering".
  * Ports and anchorages inside the zones (Singapore, Port Said, Stockholm
    and others, see app/data/ports.py) are excluded, as are ships reporting
    themselves moored, and tugs, pilot boats and other harbour service craft.
  * An unknown speed (AIS "not available") neither extends nor resets the clock.
  * Severity follows what the behaviour suggests: anchoring in a cable
    corridor outside a port is the strongest signal; waiting at anchor in a
    chokepoint is routine and stays low.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.config import SETTINGS
from app.data.critical_zones import zone_containing
from app.data.ports import port_area_at
from app.detectors.base import Detector, ScanContext
from app.models import DetectorType, NAV_STATUS_LABELS, Severity, Threat, Vessel, VesselType


_EXEMPT_TYPES = {VesselType.TUG, VesselType.SERVICE}
NAV_AT_ANCHOR = 1
NAV_MOORED = 5
NAV_FISHING = 7


@dataclass
class _Episode:
    zone_id: str
    started: datetime


class LoiteringDetector(Detector):
    detector_type = DetectorType.LOITERING

    def __init__(self) -> None:
        super().__init__()
        self._episodes: dict[str, _Episode] = {}
        self._evaluated: dict[str, datetime] = {}

    def scan(self, vessels: list[Vessel], ctx: Optional[ScanContext] = None) -> list[Threat]:
        threats: list[Threat] = []
        seen = set()
        for v in vessels:
            seen.add(v.mmsi)
            ts = v.last_position.timestamp
            if self._evaluated.get(v.mmsi) == ts:
                continue   # no new report, nothing to update
            self._evaluated[v.mmsi] = ts
            t = self._scan_one(v)
            if t:
                threats.append(t)

        # Vessels no longer broadcasting are the dark detector's business.
        for d in (self._episodes, self._evaluated):
            for mmsi in [m for m in d if m not in seen]:
                del d[mmsi]
        return threats

    def _scan_one(self, v: Vessel) -> Threat | None:
        pos = v.last_position
        zone = zone_containing(pos.lon, pos.lat)
        if zone is None or zone.category not in ("cable", "chokepoint"):
            self._episodes.pop(v.mmsi, None)
            return None
        if (v.vessel_type in _EXEMPT_TYPES or pos.nav_status == NAV_MOORED
                or port_area_at(pos.lon, pos.lat) is not None):
            self._episodes.pop(v.mmsi, None)
            return None
        if not pos.speed_available:
            return None   # unknown speed: neither extend nor reset

        if pos.speed_knots > SETTINGS.loiter_speed_knots:
            self._episodes.pop(v.mmsi, None)
            return None

        ep = self._episodes.get(v.mmsi)
        if ep is None or ep.zone_id != zone.id:
            ep = _Episode(zone_id=zone.id, started=pos.timestamp)
            self._episodes[v.mmsi] = ep
        minutes = (pos.timestamp - ep.started).total_seconds() / 60.0
        if minutes < SETTINGS.loiter_minutes_threshold:
            return None

        anchored = pos.nav_status == NAV_AT_ANCHOR
        fishing = v.vessel_type == VesselType.FISHING or pos.nav_status == NAV_FISHING
        if zone.category == "cable":
            if fishing:
                severity = Severity.LOW
            elif anchored:
                severity = Severity.HIGH     # anchors are what cut cables
            else:
                severity = Severity.MEDIUM
        else:  # chokepoint
            if fishing:
                return None                  # fishing fleets idle in straits constantly
            severity = Severity.LOW if anchored else Severity.MEDIUM

        # Small or unidentified craft (no type, no size) are usually local
        # boats on a mooring: still worth listing, but not above LOW.
        small = (0 < v.length_m < 30) or (v.vessel_type == VesselType.UNKNOWN and v.length_m == 0)
        if small and severity != Severity.LOW:
            severity = Severity.LOW

        status = NAV_STATUS_LABELS.get(pos.nav_status, "unknown") if pos.nav_status is not None else "not reported"
        what = "anchored" if anchored else "loitering"
        return Threat(
            id=self.make_id("loiter", v.mmsi, zone.id, ep.started.isoformat()),
            mmsi=v.mmsi,
            vessel_name=v.name,
            detector=DetectorType.LOITERING,
            severity=severity,
            title=f"Loitering inside {zone.name}",
            description=(
                f"{v.name} ({v.vessel_type.value}, flag {v.flag}) {what} at "
                f"{pos.speed_knots:.1f} knots inside {zone.name} for about "
                f"{minutes:.0f} minutes, outside any port area (status: {status})."
            ),
            evidence={
                "kind": f"loiter:{zone.id}",
                "zone": zone.name,
                "zone_category": zone.category,
                "minutes_loitering": round(minutes, 1),
                "since": ep.started.isoformat(),
                "speed_knots": pos.speed_knots,
                "nav_status": status,
            },
            lat=pos.lat,
            lon=pos.lon,
            detected_at=self.now_iso(),
        )
