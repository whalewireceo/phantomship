"""Detector unit tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.detectors.identity import IdentityDetector
from app.detectors.kinematic import KinematicDetector
from app.detectors.loitering import LoiteringDetector
from app.models import Position, Vessel, VesselType


def _vessel(mmsi="123456789", name="MV Test", lat=0.0, lon=0.0, speed=12.0, vt=VesselType.CARGO, flag="US") -> Vessel:
    now = datetime.now(timezone.utc)
    return Vessel(
        mmsi=mmsi, name=name, vessel_type=vt, flag=flag, length_m=200,
        destination="TEST",
        last_position=Position(timestamp=now, lat=lat, lon=lon, speed_knots=speed, course=0.0, heading=0.0),
    )


def test_kinematic_flags_hypersonic():
    v = _vessel(speed=85.0)
    threats = KinematicDetector().scan([v])
    assert len(threats) == 1
    assert threats[0].detector.value == "kinematic"
    assert "Hypersonic" in threats[0].title


def test_kinematic_ignores_normal_speed():
    v = _vessel(speed=14.0)
    threats = KinematicDetector().scan([v])
    assert threats == []


def test_kinematic_flags_teleportation():
    v = _vessel(speed=14.0, lat=0.0, lon=0.0)
    prev = Position(
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=2),
        lat=0.0, lon=0.0, speed_knots=14.0, course=90.0, heading=90.0,
    )
    v.track.append(prev)
    # Move ~600 NM east in 2 minutes -> implied speed ~18000 knots
    v.last_position = Position(
        timestamp=datetime.now(timezone.utc),
        lat=0.0, lon=10.0, speed_knots=14.0, course=90.0, heading=90.0,
    )
    threats = KinematicDetector().scan([v])
    assert any("teleport" in t.title.lower() for t in threats)


def test_identity_flags_mmsi_collision():
    a = _vessel(mmsi="111111111", name="MV Real", lat=10.0, lon=10.0)
    b = _vessel(mmsi="111111111", name="MV Spoof", lat=20.0, lon=40.0)
    threats = IdentityDetector().scan([a, b])
    assert len(threats) == 1
    assert "spoof" in threats[0].title.lower() or "collision" in threats[0].title.lower()


def test_identity_ignores_distinct_mmsis():
    a = _vessel(mmsi="111111111", lat=10.0, lon=10.0)
    b = _vessel(mmsi="222222222", lat=20.0, lon=40.0)
    assert IdentityDetector().scan([a, b]) == []


def test_loitering_requires_critical_zone():
    # Loitering somewhere uninteresting -> no flag
    v = _vessel(lat=0.0, lon=0.0, speed=0.5)
    det = LoiteringDetector()
    for _ in range(20):
        det.scan([v])
    assert det.scan([v]) == []
