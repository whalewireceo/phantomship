"""Dark-activity detection.

When a vessel disables its AIS transponder near sensitive infrastructure or
in a chokepoint, then reappears far away, that is a hallmark of sanctions
evasion, illicit ship-to-ship transfers, and cable interference operations.

This detector tracks gaps in broadcast and flags vessels whose silence
overlapped a critical zone.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.config import SETTINGS
from app.data.critical_zones import zone_containing
from app.detectors.base import Detector
from app.models import DetectorType, Severity, Threat, Vessel


class DarkActivityDetector(Detector):
    detector_type = DetectorType.DARK_ACTIVITY

    def __init__(self) -> None:
        # Maps mmsi -> (last_seen_timestamp, last_lat, last_lon)
        self._last_seen: dict[str, tuple[datetime, float, float]] = {}

    def scan(self, vessels: list[Vessel]) -> list[Threat]:
        threats: list[Threat] = []
        now = datetime.now(timezone.utc)
        current_mmsis = {v.mmsi for v in vessels}

        # Update last-seen for all visible vessels
        for v in vessels:
            self._last_seen[v.mmsi] = (
                v.last_position.timestamp, v.last_position.lat, v.last_position.lon
            )

        # Look for vessels we previously saw inside a critical zone that have
        # now gone silent
        for mmsi, (last_ts, lat, lon) in list(self._last_seen.items()):
            if mmsi in current_mmsis:
                continue  # Still broadcasting
            silent_for = (now - last_ts).total_seconds() / 60.0
            if silent_for < SETTINGS.dark_minutes_threshold:
                continue
            zone = zone_containing(lon, lat)
            if zone is None:
                # If silent for a very long time anywhere, lower-severity flag
                if silent_for > 120.0:
                    threats.append(self._make_threat(
                        mmsi=mmsi, name="(last known)", lat=lat, lon=lon,
                        silent_min=silent_for, zone_name=None, zone_category=None,
                        severity=Severity.LOW,
                    ))
                continue
            severity = Severity.HIGH if zone.category == "cable" else Severity.MEDIUM
            threats.append(self._make_threat(
                mmsi=mmsi, name="(last known)", lat=lat, lon=lon,
                silent_min=silent_for, zone_name=zone.name, zone_category=zone.category,
                severity=severity,
            ))
        return threats

    def _make_threat(
        self,
        *,
        mmsi: str, name: str, lat: float, lon: float,
        silent_min: float,
        zone_name: str | None, zone_category: str | None,
        severity: Severity,
    ) -> Threat:
        if zone_name:
            description = (
                f"MMSI {mmsi} last seen inside {zone_name} ({zone_category}); "
                f"AIS dark for {silent_min:.0f} minutes. Consistent with "
                f"deliberate transponder shutdown."
            )
            title = f"Dark activity in {zone_name}"
        else:
            description = (
                f"MMSI {mmsi} AIS dark for {silent_min:.0f} minutes. "
                f"Not currently inside a critical zone."
            )
            title = "Prolonged AIS silence"
        return Threat(
            id=self.make_id("dark", mmsi, str(int(silent_min))),
            mmsi=mmsi,
            vessel_name=name,
            detector=DetectorType.DARK_ACTIVITY,
            severity=severity,
            title=title,
            description=description,
            evidence={
                "silent_minutes": round(silent_min, 1),
                "last_lat": lat,
                "last_lon": lon,
                "zone": zone_name,
                "zone_category": zone_category,
            },
            lat=lat,
            lon=lon,
            detected_at=self.now_iso(),
        )
