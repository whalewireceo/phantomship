"""Kinematic anomaly detection.

Flags two related behaviors:
  * Impossible speed: a vessel reporting a speed far above what its class
    can do, *and* moving across the map at that speed.
  * Teleportation: a position jump no vessel could make, that *persists*
    (the vessel keeps reporting from the new location).

Both are textbook AIS spoofing signatures, but in live data both are far
more often caused by faulty equipment. The two corroboration rules below
are what separate them:

  * A speed sensor that is broken reports 70 knots while the positions
    barely move. We only alert when the positions agree with the speed.
  * A single corrupted position (a flipped latitude sign is common) jumps
    out and straight back on the next report. We only alert when the next
    report stays near the new location. Out and back jumps are counted as
    data quality, and a vessel that keeps alternating between two places is
    handled by the identity detector as two transmitters sharing one MMSI.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.config import SETTINGS
from app.data.geo import haversine_nm
from app.detectors.base import (
    Detector, ScanContext, full_track, median_or_none, recent, segment_speeds,
)
from app.models import DetectorType, Severity, Threat, Vessel, VesselType


# Realistic top speed per class, in knots. Container ships top out in the
# mid 20s, fast ferries and patrol craft can exceed 40, and small craft with
# no static data could be anything, so "unknown" stays generous.
SPEED_LIMITS: dict[VesselType, float] = {
    VesselType.CARGO: 32.0,
    VesselType.TANKER: 28.0,
    VesselType.FISHING: 30.0,
    VesselType.TUG: 25.0,
    VesselType.SPECIAL_OPS: 30.0,
    VesselType.PASSENGER: 45.0,
    VesselType.MILITARY: 50.0,
    VesselType.SERVICE: 50.0,
    VesselType.PLEASURE: 60.0,
    VesselType.HIGH_SPEED: 70.0,
    VesselType.UNKNOWN: 45.0,
}


# Jumps across longer reporting gaps than this are not judged: a ship can
# genuinely cover a lot of sea while out of receiver range.
MAX_JUMP_GAP_MINUTES = 120.0


def speed_limit(vt: VesselType) -> float:
    return SPEED_LIMITS.get(vt, 45.0)


def _duration(minutes: float) -> str:
    return f"{minutes * 60:.0f} seconds" if minutes < 1 else f"{minutes:.1f} minutes"


class KinematicDetector(Detector):
    detector_type = DetectorType.KINEMATIC

    def __init__(self) -> None:
        super().__init__()
        # mmsi -> timestamp of the jump already judged, so a jump is
        # classified once rather than on every scan.
        self._judged_jump: dict[str, datetime] = {}
        # mmsi -> timestamp of the last report evaluated; nothing changes
        # for a vessel until it sends a new one.
        self._evaluated: dict[str, datetime] = {}

    def scan(self, vessels: list[Vessel], ctx: Optional[ScanContext] = None) -> list[Threat]:
        threats: list[Threat] = []
        for v in vessels:
            ts = v.last_position.timestamp
            if self._evaluated.get(v.mmsi) == ts:
                continue
            self._evaluated[v.mmsi] = ts
            t = self._speed_check(v) or self._teleport_check(v)
            if t:
                threats.append(t)
        if len(self._judged_jump) > 50_000:
            self._judged_jump.clear()
        if len(self._evaluated) > 4 * max(len(vessels), 10_000):
            self._evaluated.clear()
        return threats

    # ------------------------------------------------------------- speed #
    def _speed_check(self, v: Vessel) -> Threat | None:
        pos = v.last_position
        limit = speed_limit(v.vessel_type)
        if not pos.speed_available or pos.speed_knots <= limit:
            return None

        # Free AIS feeds deliver a report every few minutes per ship, so the
        # window is generous; what matters is three consecutive reports.
        pts = recent(full_track(v), pos.timestamp, 30.0)[-4:]
        reported = [p.speed_knots for p in pts[-3:] if p.speed_available]
        if len(reported) < 3 or min(reported) <= limit:
            # One high reading is not a pattern yet. Wait for more reports.
            return None
        segs = segment_speeds(pts)
        if len(segs) < 2:
            return None
        implied = median_or_none(segs) or 0.0
        if implied < 0.6 * pos.speed_knots and implied <= limit:
            # Claims 70 knots, actually drifting: a sensor or data fault.
            self.count("speed_sensor_fault")
            return None

        return Threat(
            id=self.make_id("speed", v.mmsi, str(pos.timestamp)),
            mmsi=v.mmsi,
            vessel_name=v.name,
            detector=DetectorType.KINEMATIC,
            severity=Severity.HIGH if implied > limit * 1.5 else Severity.MEDIUM,
            title="Speed beyond vessel class envelope",
            description=(
                f"{v.name} ({v.vessel_type.value}) is reporting {pos.speed_knots:.1f} knots "
                f"and its positions confirm about {implied:.0f} knots, above the "
                f"{limit:.0f} knot envelope for its class."
            ),
            evidence={
                "kind": "speed_envelope",
                "speed_reported": pos.speed_knots,
                "speed_implied_by_positions": round(implied, 1),
                "speed_limit": limit,
                "vessel_type": v.vessel_type.value,
                "vessel_length_m": v.length_m,
            },
            lat=pos.lat,
            lon=pos.lon,
            detected_at=self.now_iso(),
        )

    # ---------------------------------------------------------- teleport #
    def _teleport_check(self, v: Vessel) -> Threat | None:
        pts = full_track(v)
        if len(pts) < 4:
            # Both ends of a jump must be confirmed: a report before it
            # (origin) and a report after it (destination).
            return None
        z, a, b, c = pts[-4], pts[-3], pts[-2], pts[-1]
        dt_ab_min = (b.timestamp - a.timestamp).total_seconds() / 60.0
        if dt_ab_min <= 0 or dt_ab_min > MAX_JUMP_GAP_MINUTES:
            return None
        d_ab = haversine_nm(a.lon, a.lat, b.lon, b.lat)
        if d_ab < SETTINGS.teleport_nm_threshold:
            return None
        # Judge the jump by the speed it implies, not by a fixed time window:
        # reports can be minutes apart on a free feed.
        if d_ab / (dt_ab_min / 60.0) < max(100.0, 3.0 * speed_limit(v.vessel_type)):
            return None
        if self._judged_jump.get(v.mmsi) == b.timestamp:
            return None
        self._judged_jump[v.mmsi] = b.timestamp

        d_ca = haversine_nm(c.lon, c.lat, a.lon, a.lat)
        if d_ca < d_ab * 0.25:
            # Out and straight back: one corrupted fix, not a relocation.
            self.count("position_glitch")
            return None
        # The jump *back* from a corrupted fix looks like a jump that
        # persists, so the origin must be confirmed too: the report before
        # it has to be near it, not near where the vessel "arrived". Live
        # data had Amsterdam canal boats flip latitude 52.4 to -64.7 for
        # one report; without this, the return trip was flagged CRITICAL.
        d_za = haversine_nm(z.lon, z.lat, a.lon, a.lat)
        d_zb = haversine_nm(z.lon, z.lat, b.lon, b.lat)
        if d_zb < d_ab * 0.25:
            return None   # already counted as a glitch on the way out
        dt_za_h = max((a.timestamp - z.timestamp).total_seconds(), 0.0) / 3600.0
        if d_za > 2.0 + speed_limit(v.vessel_type) * dt_za_h * 1.5:
            self.count("position_chaotic")
            return None
        d_bc = haversine_nm(b.lon, b.lat, c.lon, c.lat)
        dt_bc_h = max((c.timestamp - b.timestamp).total_seconds(), 0.0) / 3600.0
        plausible_nm = 2.0 + speed_limit(v.vessel_type) * dt_bc_h * 1.5
        if d_bc > plausible_nm:
            self.count("position_chaotic")
            return None

        implied_speed = d_ab / (dt_ab_min / 60.0)
        return Threat(
            id=self.make_id("teleport", v.mmsi, str(b.timestamp)),
            mmsi=v.mmsi,
            vessel_name=v.name,
            detector=DetectorType.KINEMATIC,
            severity=Severity.CRITICAL if d_ab > 300 else Severity.HIGH,
            title="Position teleportation",
            description=(
                f"{v.name} jumped {d_ab:.0f} NM in {_duration(dt_ab_min)} "
                f"(implied {implied_speed:.0f} knots) and kept reporting from the new "
                f"location. Consistent with GPS spoofing or AIS identity hijack."
            ),
            evidence={
                "kind": "teleport",
                "distance_nm": round(d_ab, 1),
                "delta_minutes": round(dt_ab_min, 2),
                "implied_speed_knots": round(implied_speed, 1),
                "from_lat": a.lat,
                "from_lon": a.lon,
                "to_lat": b.lat,
                "to_lon": b.lon,
                "confirmed_by_next_report": True,
            },
            lat=b.lat,
            lon=b.lon,
            detected_at=self.now_iso(),
        )
