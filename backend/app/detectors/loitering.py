"""Loitering detection.

Vessels moving at near-zero speed inside critical zones (cable corridors,
chokepoints) for extended periods are a notable signature. State-linked
research and survey vessels associated with the Russian 'GUGI' fleet, for
example, have repeatedly been observed loitering on top of subsea cables.
"""
from __future__ import annotations

from app.config import SETTINGS
from app.data.critical_zones import zone_containing
from app.detectors.base import Detector
from app.models import DetectorType, Severity, Threat, Vessel


class LoiteringDetector(Detector):
    detector_type = DetectorType.LOITERING

    def __init__(self) -> None:
        # mmsi -> consecutive low-speed-in-zone ticks
        self._loiter_ticks: dict[str, int] = {}

    def scan(self, vessels: list[Vessel]) -> list[Threat]:
        threats: list[Threat] = []
        tick_minutes = SETTINGS.sim_tick_seconds / 60.0
        threshold_ticks = max(2, int(SETTINGS.loiter_minutes_threshold / tick_minutes))

        seen = set()
        for v in vessels:
            seen.add(v.mmsi)
            pos = v.last_position
            zone = zone_containing(pos.lon, pos.lat)
            if zone is None or zone.category not in ("cable", "chokepoint"):
                self._loiter_ticks[v.mmsi] = 0
                continue
            if pos.speed_knots <= SETTINGS.loiter_speed_knots:
                self._loiter_ticks[v.mmsi] = self._loiter_ticks.get(v.mmsi, 0) + 1
            else:
                self._loiter_ticks[v.mmsi] = 0

            if self._loiter_ticks[v.mmsi] >= threshold_ticks:
                minutes_loitering = self._loiter_ticks[v.mmsi] * tick_minutes
                severity = Severity.HIGH if zone.category == "cable" else Severity.MEDIUM
                threats.append(Threat(
                    id=self.make_id("loiter", v.mmsi, zone.id, str(int(minutes_loitering))),
                    mmsi=v.mmsi,
                    vessel_name=v.name,
                    detector=DetectorType.LOITERING,
                    severity=severity,
                    title=f"Loitering inside {zone.name}",
                    description=(
                        f"{v.name} ({v.vessel_type.value}, flag {v.flag}) "
                        f"loitering at {pos.speed_knots:.1f} knots inside "
                        f"{zone.name} for ~{minutes_loitering:.0f} minutes."
                    ),
                    evidence={
                        "zone": zone.name,
                        "zone_category": zone.category,
                        "minutes_loitering": round(minutes_loitering, 1),
                        "speed_knots": pos.speed_knots,
                    },
                    lat=pos.lat,
                    lon=pos.lon,
                    detected_at=self.now_iso(),
                ))

        # Clear counters for vessels no longer broadcasting (handled by dark detector)
        for mmsi in list(self._loiter_ticks):
            if mmsi not in seen:
                self._loiter_ticks.pop(mmsi, None)

        return threats
