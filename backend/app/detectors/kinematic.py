"""Kinematic anomaly detection.

Flags two related behaviors:
  * Hypersonic vessels — broadcast speed exceeding realistic class limits.
  * Teleportation     — consecutive position reports separated by an
    implied speed far above any plausible vessel speed.

Both are textbook AIS spoofing signatures.
"""
from __future__ import annotations

from datetime import datetime

from app.config import SETTINGS
from app.data.simulator import haversine_nm
from app.detectors.base import Detector
from app.models import DetectorType, Severity, Threat, Vessel


class KinematicDetector(Detector):
    detector_type = DetectorType.KINEMATIC

    def scan(self, vessels: list[Vessel]) -> list[Threat]:
        threats: list[Threat] = []
        for v in vessels:
            t = self._scan_one(v)
            if t:
                threats.append(t)
        return threats

    def _scan_one(self, v: Vessel) -> Threat | None:
        pos = v.last_position

        # 1) Hypersonic check
        if pos.speed_knots > SETTINGS.max_realistic_speed_knots:
            return Threat(
                id=self.make_id("kinematic", v.mmsi, str(pos.timestamp)),
                mmsi=v.mmsi,
                vessel_name=v.name,
                detector=DetectorType.KINEMATIC,
                severity=Severity.HIGH if pos.speed_knots > 60 else Severity.MEDIUM,
                title="Hypersonic vessel signature",
                description=(
                    f"{v.name} ({v.vessel_type.value}) reporting "
                    f"{pos.speed_knots:.1f} knots — above realistic envelope of "
                    f"{SETTINGS.max_realistic_speed_knots:.0f} knots."
                ),
                evidence={
                    "speed_reported": pos.speed_knots,
                    "speed_limit": SETTINGS.max_realistic_speed_knots,
                    "vessel_type": v.vessel_type.value,
                    "vessel_length_m": v.length_m,
                },
                lat=pos.lat,
                lon=pos.lon,
                detected_at=self.now_iso(),
            )

        # 2) Teleportation check vs previous position
        if v.track:
            prev = v.track[-1]
            dt_min = self._minutes(prev.timestamp, pos.timestamp)
            if dt_min <= 0:
                return None
            dist_nm = haversine_nm(prev.lon, prev.lat, pos.lon, pos.lat)
            if dist_nm >= SETTINGS.teleport_nm_threshold and dt_min <= SETTINGS.teleport_minutes_threshold:
                implied_speed = dist_nm / (dt_min / 60.0)
                return Threat(
                    id=self.make_id("teleport", v.mmsi, str(pos.timestamp)),
                    mmsi=v.mmsi,
                    vessel_name=v.name,
                    detector=DetectorType.KINEMATIC,
                    severity=Severity.CRITICAL if dist_nm > 300 else Severity.HIGH,
                    title="Position teleportation",
                    description=(
                        f"{v.name} jumped {dist_nm:.0f} NM in {dt_min:.1f} minutes "
                        f"— implied speed {implied_speed:.0f} knots. Consistent "
                        f"with GPS spoofing or AIS identity hijack."
                    ),
                    evidence={
                        "distance_nm": round(dist_nm, 1),
                        "delta_minutes": round(dt_min, 2),
                        "implied_speed_knots": round(implied_speed, 1),
                        "from_lat": prev.lat,
                        "from_lon": prev.lon,
                        "to_lat": pos.lat,
                        "to_lon": pos.lon,
                    },
                    lat=pos.lat,
                    lon=pos.lon,
                    detected_at=self.now_iso(),
                )
        return None

    @staticmethod
    def _minutes(t1: datetime, t2: datetime) -> float:
        return abs((t2 - t1).total_seconds()) / 60.0
