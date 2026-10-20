"""Identity spoofing detection.

One MMSI should belong to one ship. Two signatures say otherwise:

1. Two vessel records broadcast the same MMSI from positions that cannot
   both be correct (the simulator plants these as separate records).
2. In a live feed both transmitters arrive under the same MMSI, so they show
   up as one "vessel" whose reports alternate between two places far apart
   (A, B, A, B...). That alternation is the live form of the same collision.

Not every collision is malicious. Ships sometimes copy an MMSI from a
sister vessel or keep a previous owner's number, so severity reflects that
this needs checking, not that spoofing is proven. Shared *default* numbers
(0, 123456789) never reach this detector because ingest drops them.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Optional

from app.data.geo import haversine_nm
from app.detectors.base import Detector, ScanContext, full_track, recent
from app.detectors.kinematic import speed_limit
from app.models import DetectorType, Position, Severity, Threat, Vessel


# Threshold (NM): two reports under one MMSI further apart than this within
# a short window cannot come from one ship.
COLLISION_DISTANCE_NM = 30.0
MIN_SWITCHES = 3


class IdentityDetector(Detector):
    detector_type = DetectorType.IDENTITY

    def __init__(self) -> None:
        super().__init__()
        self._checked: dict[str, datetime] = {}

    def scan(self, vessels: list[Vessel], ctx: Optional[ScanContext] = None) -> list[Threat]:
        threats = self._duplicate_records(vessels)
        for v in vessels:
            last_ts = v.last_position.timestamp
            if self._checked.get(v.mmsi) == last_ts:
                continue
            self._checked[v.mmsi] = last_ts
            t = self._alternating_track(v)
            if t:
                threats.append(t)
        if len(self._checked) > 100_000:
            self._checked.clear()
        return threats

    # ---------------------------------------------- separate records #
    def _duplicate_records(self, vessels: list[Vessel]) -> list[Threat]:
        by_mmsi: dict[str, list[Vessel]] = defaultdict(list)
        for v in vessels:
            by_mmsi[v.mmsi].append(v)

        threats: list[Threat] = []
        for mmsi, group in by_mmsi.items():
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    dist = haversine_nm(
                        a.last_position.lon, a.last_position.lat,
                        b.last_position.lon, b.last_position.lat,
                    )
                    if dist < COLLISION_DISTANCE_NM:
                        continue
                    threats.append(Threat(
                        id=self.make_id("identity", mmsi, "records"),
                        mmsi=mmsi,
                        vessel_name=f"{a.name} / {b.name}",
                        detector=DetectorType.IDENTITY,
                        severity=Severity.CRITICAL,
                        title="MMSI collision: identity spoofing",
                        description=(
                            f"Two vessels are broadcasting MMSI {mmsi} "
                            f"simultaneously {dist:.0f} NM apart. One is "
                            f"impersonating the other. Both reported names: "
                            f"'{a.name}' and '{b.name}'."
                        ),
                        evidence={
                            "kind": "mmsi_collision",
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

    # ---------------------------------------------- alternating track #
    def _alternating_track(self, v: Vessel) -> Threat | None:
        pts = recent(full_track(v), v.last_position.timestamp, 60.0)
        if len(pts) < 4:
            return None
        # Cheap reject: a track that fits in a small box cannot alternate
        # between two places 30 NM apart.
        lat0 = lat1 = pts[0].lat
        lon0 = lon1 = pts[0].lon
        for p in pts:
            if p.lat < lat0: lat0 = p.lat
            elif p.lat > lat1: lat1 = p.lat
            if p.lon < lon0: lon0 = p.lon
            elif p.lon > lon1: lon1 = p.lon
        lat_span_nm = (lat1 - lat0) * 60.0
        lon_range = lon1 - lon0
        nearest_equator = 0.0 if lat0 <= 0.0 <= lat1 else min(abs(lat0), abs(lat1))
        coslat = math.cos(math.radians(nearest_equator))
        if (lon_range <= 180.0  # a wider range means the track crosses the antimeridian
                and lat_span_nm < COLLISION_DISTANCE_NM
                and lon_range * 60.0 * coslat < COLLISION_DISTANCE_NM):
            return None

        anchor_a = pts[0]
        anchor_b: Optional[Position] = None
        for p in pts[1:]:
            if haversine_nm(p.lon, p.lat, anchor_a.lon, anchor_a.lat) >= COLLISION_DISTANCE_NM:
                anchor_b = p
                break
        if anchor_b is None:
            return None

        labels: list[tuple[str, Position]] = []
        for p in pts:
            da = haversine_nm(p.lon, p.lat, anchor_a.lon, anchor_a.lat)
            db = haversine_nm(p.lon, p.lat, anchor_b.lon, anchor_b.lat)
            if min(da, db) > COLLISION_DISTANCE_NM:
                continue
            labels.append(("A" if da <= db else "B", p))
        n_a = sum(1 for l, _ in labels if l == "A")
        n_b = len(labels) - n_a
        switches = 0
        fastest_switch = 0.0
        for (la, pa), (lb, pb) in zip(labels[:-1], labels[1:]):
            if la == lb:
                continue
            switches += 1
            dt_h = max((pb.timestamp - pa.timestamp).total_seconds(), 1.0) / 3600.0
            fastest_switch = max(fastest_switch, haversine_nm(pa.lon, pa.lat, pb.lon, pb.lat) / dt_h)
        if switches < MIN_SWITCHES or n_a < 2 or n_b < 2:
            return None
        if fastest_switch < 2.0 * speed_limit(v.vessel_type):
            return None

        dist = haversine_nm(anchor_a.lon, anchor_a.lat, anchor_b.lon, anchor_b.lat)
        return Threat(
            id=self.make_id("identity", v.mmsi, "alternating"),
            mmsi=v.mmsi,
            vessel_name=v.name,
            detector=DetectorType.IDENTITY,
            severity=Severity.HIGH,
            title="One MMSI, two transmitters",
            description=(
                f"Reports for MMSI {v.mmsi} ({v.name}) alternate between two positions "
                f"{dist:.0f} NM apart ({switches} switches in the last hour). Two "
                f"transmitters are using one identity: spoofing, or a copied or "
                f"misconfigured MMSI."
            ),
            evidence={
                "kind": "mmsi_alternating",
                "distance_between_nm": round(dist, 1),
                "switches": switches,
                "reports_at_a": n_a,
                "reports_at_b": n_b,
                "position_a": {"lat": anchor_a.lat, "lon": anchor_a.lon},
                "position_b": {"lat": anchor_b.lat, "lon": anchor_b.lon},
            },
            lat=v.last_position.lat,
            lon=v.last_position.lon,
            detected_at=self.now_iso(),
        )
