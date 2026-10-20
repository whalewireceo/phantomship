"""Detector unit tests.

Several cases replay patterns recorded from the live AISStream feed that
fooled the first version of each detector.
"""
from __future__ import annotations

from datetime import timedelta

from app.detectors.base import ScanContext
from app.detectors.dark_activity import DarkActivityDetector
from app.detectors.identity import IdentityDetector
from app.detectors.kinematic import KinematicDetector
from app.detectors.loitering import LoiteringDetector
from app.models import Severity, VesselType
from tests.conftest import pos, vessel_from


# --------------------------------------------------------------- kinematic #
def _moving_track(speed, n=5, step_s=10.0, lat=40.0, lon=-30.0, reported=None):
    """Track heading east whose positions really move at `speed` knots."""
    pts = []
    for i in range(n):
        dlon = (speed * (i * step_s) / 3600.0) / 60.0 / 0.766  # cos(40 deg)
        pts.append(pos(lat, lon + dlon, t=i * step_s, speed=reported if reported is not None else speed))
    return pts


def test_kinematic_flags_sustained_impossible_speed():
    v = vessel_from(_moving_track(80.0))
    threats = KinematicDetector().scan([v])
    assert len(threats) == 1
    t = threats[0]
    assert t.evidence["kind"] == "speed_envelope"
    assert t.evidence["speed_implied_by_positions"] > 60


def test_kinematic_waits_for_more_than_one_high_reading():
    pts = _moving_track(14.0, n=4)
    pts.append(pos(40.0, pts[-1].lon + 0.001, t=40, speed=85.0))
    assert KinematicDetector().scan([vessel_from(pts)]) == []


def test_kinematic_speed_sensor_fault_is_not_an_alert():
    # Replay of CS STRATOS: 67 to 72 knots reported while barely moving.
    reported = [67.4, 67.9, 72.5, 67.0, 67.6]
    coords = [(60.118, 31.379), (60.117, 31.401), (60.119, 31.372), (60.119, 31.373), (60.119, 31.386)]
    offsets = [0, 144, 214, 541, 787]
    pts = [pos(la, lo, t=dt, speed=s) for (la, lo), dt, s in zip(coords, offsets, reported)]
    det = KinematicDetector()
    assert det.scan([vessel_from(pts, vt=VesselType.UNKNOWN)]) == []
    assert det.quality.get("speed_sensor_fault") == 1


def test_kinematic_ignores_normal_speed():
    assert KinematicDetector().scan([vessel_from(_moving_track(14.0))]) == []


def test_fast_ferry_is_within_its_class_envelope():
    v = vessel_from(_moving_track(38.0), vt=VesselType.HIGH_SPEED)
    assert KinematicDetector().scan([v]) == []


def test_kinematic_flags_confirmed_teleportation():
    pts = [pos(0.0, -0.003, t=0), pos(0.0, 0.0, t=30), pos(0.0, 0.003, t=60),
           pos(0.0, 10.0, t=120),          # ~600 NM jump in one minute
           pos(0.0, 10.003, t=180)]        # ...and it keeps reporting from there
    threats = KinematicDetector().scan([vessel_from(pts)])
    assert len(threats) == 1
    assert threats[0].evidence["kind"] == "teleport"
    assert threats[0].severity == Severity.CRITICAL


def test_single_corrupted_fix_is_a_glitch_not_a_teleport():
    # Replay of TOON HERMANS: latitude sign flips for one report, then back.
    pts = [pos(52.379, 4.897, t=0, speed=0), pos(52.379, 4.897, t=300, speed=0),
           pos(-36.75, 4.897, t=359, speed=0), pos(52.379, 4.897, t=418, speed=0)]
    det = KinematicDetector()
    assert det.scan([vessel_from(pts, vt=VesselType.PASSENGER)]) == []
    assert det.quality.get("position_glitch") == 1
    # Judged once, not again on every scan.
    det.scan([vessel_from(pts, vt=VesselType.PASSENGER)])
    assert det.quality.get("position_glitch") == 1


def test_unconfirmed_jump_waits_for_next_report():
    pts = [pos(0.0, -0.003, t=0), pos(0.0, 0.0, t=30), pos(0.0, 0.003, t=60), pos(0.0, 10.0, t=120)]
    assert KinematicDetector().scan([vessel_from(pts)]) == []


# ---------------------------------------------------------------- identity #
def test_identity_flags_mmsi_collision_between_records():
    a = vessel_from([pos(10.0, 10.0)], mmsi="244111111", name="MV Real")
    b = vessel_from([pos(20.0, 40.0)], mmsi="244111111", name="MV Spoof")
    threats = IdentityDetector().scan([a, b])
    assert len(threats) == 1
    assert "collision" in threats[0].title.lower()


def test_identity_ignores_distinct_mmsis():
    a = vessel_from([pos(10.0, 10.0)], mmsi="244111111")
    b = vessel_from([pos(20.0, 40.0)], mmsi="244222222")
    assert IdentityDetector().scan([a, b]) == []


def test_identity_flags_one_mmsi_alternating_between_two_places():
    # Replay of MARFAAM: one Dutch MMSI heard off Copenhagen and off Scotland.
    cph, scot = (55.687, 12.633), (58.158, -5.688)
    seq = [cph, scot, cph, scot, cph, scot]
    pts = [pos(la, lo, t=i * 120, speed=0.0) for i, (la, lo) in enumerate(seq)]
    threats = IdentityDetector().scan([vessel_from(pts, mmsi="246843000", vt=VesselType.UNKNOWN)])
    assert len(threats) == 1
    assert threats[0].evidence["kind"] == "mmsi_alternating"
    assert threats[0].evidence["switches"] >= 3


def test_identity_ignores_a_vessel_simply_travelling():
    pts = [pos(40.0, -30.0 + i * 0.1, t=i * 600, speed=30.0) for i in range(8)]
    assert IdentityDetector().scan([vessel_from(pts)]) == []


# --------------------------------------------------------------- loitering #
BALTIC_OPEN_SEA = (57.5, 19.5)   # inside the cable box, away from ports
SINGAPORE = (1.24, 103.84)


def _slow_reports(lat, lon, minutes=30, every_s=180, **kw):
    return [pos(lat, lon, t=i * every_s, speed=0.4, **kw) for i in range(int(minutes * 60 / every_s) + 1)]


def _run_loiter(points, det=None, **vkw):
    det = det or LoiteringDetector()
    out = []
    for i in range(1, len(points) + 1):
        out = det.scan([vessel_from(points[:i], **vkw)])
    return out


def test_loitering_requires_critical_zone():
    assert _run_loiter(_slow_reports(0.0, 0.0)) == []


def test_loitering_in_cable_corridor_is_flagged():
    threats = _run_loiter(_slow_reports(*BALTIC_OPEN_SEA))
    assert len(threats) == 1
    assert threats[0].severity == Severity.MEDIUM
    assert threats[0].evidence["minutes_loitering"] >= 25


def test_anchoring_in_cable_corridor_is_high():
    threats = _run_loiter(_slow_reports(*BALTIC_OPEN_SEA, nav_status=1))
    assert threats and threats[0].severity == Severity.HIGH


def test_port_anchorage_inside_zone_is_ignored():
    assert _run_loiter(_slow_reports(*SINGAPORE)) == []


def test_moored_and_harbour_craft_are_ignored():
    assert _run_loiter(_slow_reports(*BALTIC_OPEN_SEA, nav_status=5)) == []
    assert _run_loiter(_slow_reports(*BALTIC_OPEN_SEA), vt=VesselType.TUG) == []


def test_loitering_duration_comes_from_reports_not_scan_count():
    # One report, scanned 1000 times: the ship has not been seen loitering
    # for 25 minutes, it has just not said anything new.
    det = LoiteringDetector()
    v = vessel_from([pos(*BALTIC_OPEN_SEA, speed=0.4)])
    for _ in range(1000):
        out = det.scan([v])
    assert out == []


def test_fishing_in_chokepoint_is_ignored():
    malacca_open = (3.6, 100.6)
    assert _run_loiter(_slow_reports(*malacca_open), vt=VesselType.FISHING) == []


# ------------------------------------------------------------ dark activity #
def _regular_reporter(lat, lon, mmsi="244123456"):
    pts = [pos(lat, lon, t=i * 60, speed=8.0) for i in range(20)]
    return vessel_from(pts, mmsi=mmsi)


def test_dark_in_zone_is_flagged_in_simulator_mode():
    det = DarkActivityDetector()
    v = _regular_reporter(*BALTIC_OPEN_SEA)
    last = v.last_position.timestamp
    det.scan([v], ScanContext(mode="simulator", now=last))
    threats = det.scan([], ScanContext(mode="simulator", now=last + timedelta(minutes=31)))
    assert len(threats) == 1
    assert threats[0].vessel_name == "MV TEST"


def test_dark_live_needs_receiver_coverage():
    det = DarkActivityDetector()
    v = _regular_reporter(*BALTIC_OPEN_SEA)
    last = v.last_position.timestamp
    det.scan([v], ScanContext(mode="live", now=last))
    later = last + timedelta(minutes=31)
    nobody_heard = ScanContext(mode="live", now=later, coverage=lambda lon, lat, m: 0)
    assert det.scan([], nobody_heard) == []
    assert det.quality.get("dark_no_receiver_coverage") == 1
    others_heard = ScanContext(mode="live", now=later, coverage=lambda lon, lat, m: 5)
    assert len(det.scan([], others_heard)) == 1


def test_dark_live_outside_zones_is_ignored():
    det = DarkActivityDetector()
    v = _regular_reporter(40.0, -30.0)
    last = v.last_position.timestamp
    det.scan([v], ScanContext(mode="live", now=last))
    ctx = ScanContext(mode="live", now=last + timedelta(hours=3), coverage=lambda *a: 9)
    assert det.scan([], ctx) == []


def test_dark_in_port_is_ignored():
    det = DarkActivityDetector()
    v = _regular_reporter(*SINGAPORE)
    last = v.last_position.timestamp
    det.scan([v], ScanContext(mode="live", now=last))
    ctx = ScanContext(mode="live", now=last + timedelta(minutes=45), coverage=lambda *a: 9)
    assert det.scan([], ctx) == []



def test_return_from_corrupted_fix_is_not_a_teleport():
    # Live: canal boat DE GEEST VAN HELENA, latitude 52.398 -> -64.693 for
    # one report and back. The jump back used to be flagged CRITICAL.
    coords = [(52.398, 4.884), (52.398, 4.884), (52.398, 4.884), (-64.693, 4.883),
              (52.398, 4.884), (52.398, 4.884)]
    pts = [pos(la, lo, t=i * 70, speed=0.0) for i, (la, lo) in enumerate(coords)]
    det = KinematicDetector()
    for i in range(4, len(pts) + 1):
        assert det.scan([vessel_from(pts[:i], vt=VesselType.PASSENGER)]) == []
    assert det.quality.get("position_glitch") == 1


def test_jump_from_first_ever_report_is_not_judged():
    # Live: TAURUS first heard at latitude 44.406, then 54.406 from then on
    # (a 10 degree bit error in the very first report).
    pts = [pos(44.406, 18.666, t=0, speed=0), pos(54.406, 18.666, t=60, speed=0),
           pos(54.406, 18.666, t=180, speed=0)]
    assert KinematicDetector().scan([vessel_from(pts)]) == []


def test_small_unidentified_craft_loitering_is_low():
    threats = _run_loiter(_slow_reports(*BALTIC_OPEN_SEA), vt=VesselType.UNKNOWN, length=0)
    assert threats and threats[0].severity == Severity.LOW
