"""Identity spoofing detection.

When two vessels broadcast the same MMSI from positions that cannot both be
correct (separated by a large distance at the same wall-clock time), one of
them is spoofing the other's identity. This is one of the cleanest signatures
of deliberate AIS manipulation.

Note: the simulator deliberately injects identity collisions; in the live
data path the same logic applies to incoming AISStream messages.
"""
from __future__ import annotations

from collections import defaultdict

from app.data.simulator import haversine_nm
from app.detectors.base import Detector
from app.models import DetectorType, Severity, Threat, Vessel


# Threshold (NM): two reports under one MMSI further apart than this within the
# same scan window are definitively impossible — no legitimate vessel
# instantaneously occupies two locations.
COLLISION_DISTANCE_NM = 30.0


class IdentityDetector(Detector):
    detector_type = DetectorType.IDENTITY

    def scan(self, vessels: list[Vessel]) -> list[Threat]:
        # Group by broadcast MMSI
        by_mmsi: dict[str, list[Vessel]] = defaultdict(list)
        for v in vessels:
            by_mmsi[v.mmsi].append(v)

        threats: list[Threat] = []
        for mmsi, group in by_mmsi.items():
            if len(group) < 2:
                continue
            # Compare every pair; in practice the simulator never makes >2 per MMSI
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    dist = haversine_nm(
                        a.last_position.lon, a.last_position.lat,
                        b.last_position.lon, b.last_position.lat,
                    )
                    if dist >= COLLISION_DISTANCE_NM:
                        threats.append(Threat(
                            id=self.make_id("identity", mmsi, str(min(a.last_position.timestamp, b.last_position.timestamp))),
                            mmsi=mmsi,
                            vessel_name=f"{a.name} / {b.name}",
                            detector=DetectorType.IDENTITY,
                            severity=Severity.CRITICAL,
                            title="MMSI collision — identity spoofing",
                            description=(
                                f"Two vessels are broadcasting MMSI {mmsi} "
                                f"simultaneously {dist:.0f} NM apart. One is "
                                f"impersonating the other. Both reported names: "
                                f"'{a.name}' and '{b.name}'."
                            ),
                            evidence={
                                "distance_between_nm": round(dist, 1),
                                "vessel_a": {
                                    "name": a.name, "type": a.vessel_type.value, "flag": a.flag,
                                    "lat": a.last_position.lat, "lon": a.last_position.lon,
                                },
                                "vessel_b": {
                                    "name": b.name, "type": b.vessel_type.value, "flag": b.flag,
                                    "lat": b.last_position.lat, "lon": b.last_position.lon,
                                },
                            },
                            lat=(a.last_position.lat + b.last_position.lat) / 2,
                            lon=(a.last_position.lon + b.last_position.lon) / 2,
                            detected_at=self.now_iso(),
                        ))
        return threats
