"""Live AIS ingest: reserved values, broken identities, timing and housekeeping.

Every case here is something the live feed actually sent.
"""
from datetime import datetime, timedelta, timezone

from app.data import ais_stream
from app.data.ais_stream import AISStreamFeed, clean_text, parse_ais_time
from app.data.mmsi import MmsiClass, classify_mmsi, flag_for_mmsi
from app.detectors.kinematic import KinematicDetector
from app.models import Position, Vessel, VesselType


def _report(mmsi=366000001, lat=27.9, lon=-82.7, sog=12.0, cog=90.0, heading=90,
            time_utc=None, name="TEST VESSEL", **extra):
    pr = {"Latitude": lat, "Longitude": lon, "Sog": sog, "Cog": cog, "TrueHeading": heading}
    pr.update(extra)
    meta = {"MMSI": mmsi, "ShipName": name}
    if time_utc:
        meta["time_utc"] = time_utc
    return {"MessageType": "PositionReport", "MetaData": meta, "Message": {"PositionReport": pr}}


def _static(mmsi=366000001, **ssd):
    return {"MessageType": "ShipStaticData", "MetaData": {"MMSI": mmsi},
            "Message": {"ShipStaticData": ssd}}


def _feed():
    return AISStreamFeed(api_key="test")


# ------------------------------------------------------------ sentinels #
def test_speed_not_available_is_flagged_not_stored_as_102_knots():
    feed = _feed()
    feed._ingest(_report(sog=102.3))
    pos = feed.vessels["366000001"].last_position
    assert pos.speed_available is False
    assert pos.speed_knots == 0.0


def test_speed_102_2_is_treated_as_unavailable():
    feed = _feed()
    feed._ingest(_report(sog=102.2))
    assert feed.vessels["366000001"].last_position.speed_available is False


def test_course_360_is_flagged_unavailable():
    feed = _feed()
    feed._ingest(_report(cog=360.0))
    pos = feed.vessels["366000001"].last_position
    assert pos.course_available is False
    assert pos.course == 0.0


def test_position_not_available_is_dropped():
    feed = _feed()
    feed._ingest(_report(lat=91.0, lon=181.0))
    assert "366000001" not in feed.vessels


def test_null_island_is_dropped():
    feed = _feed()
    feed._ingest(_report(lat=0.0, lon=0.0))
    assert "366000001" not in feed.vessels
    assert feed.quality["dropped_null_island"] == 1


def test_manual_or_dead_reckoning_fix_is_dropped():
    feed = _feed()
    feed._ingest(_report(Timestamp=62))
    assert "366000001" not in feed.vessels


def test_valid_report_is_kept():
    feed = _feed()
    feed._ingest(_report(sog=14.5, cog=270.0, NavigationalStatus=0))
    pos = feed.vessels["366000001"].last_position
    assert pos.speed_available and pos.course_available
    assert pos.speed_knots == 14.5
    assert pos.nav_status == 0


def test_kinematic_ignores_unavailable_speed():
    pos = Position(timestamp=datetime.now(timezone.utc), lat=27.9, lon=-82.7,
                   speed_knots=0.0, course=0.0, heading=0.0, speed_available=False)
    v = Vessel(mmsi="1", name="X", vessel_type=VesselType.UNKNOWN, flag="--",
               length_m=0, destination="--", last_position=pos)
    assert KinematicDetector().scan([v]) == []


# --------------------------------------------------------------- MMSIs #
def test_shared_default_mmsis_are_dropped():
    # MMSI 0 was heard from Perth and from the Danube in the same minute.
    feed = _feed()
    for m in (0, 123456789, 111111111, 1193046):
        feed._ingest(_report(mmsi=m))
    assert feed.vessels == {}
    assert feed.quality["dropped_invalid_mmsi"] == 4


def test_beacons_and_aids_to_navigation_are_not_ships():
    assert classify_mmsi("970123456") == MmsiClass.SPECIAL
    assert classify_mmsi("992351234") == MmsiClass.SPECIAL
    assert classify_mmsi("003669999") == MmsiClass.SPECIAL
    assert classify_mmsi("366000001") == MmsiClass.SHIP


def test_flag_comes_from_mmsi_country_code():
    assert flag_for_mmsi("566029000") == "SG"
    assert flag_for_mmsi("636011247") == "LR"
    assert flag_for_mmsi("244710626") == "NL"
    feed = _feed()
    feed._ingest(_report(mmsi=566029000))
    assert feed.vessels["566029000"].flag == "SG"


# ------------------------------------------------------------- timing #
def test_message_time_is_used_and_out_of_order_reports_dropped():
    feed = _feed()
    feed._ingest(_report(time_utc="2026-10-19 23:50:30.752066789 +0000 UTC", lon=-82.70))
    feed._ingest(_report(time_utc="2026-10-19 23:50:40.000000 +0000 UTC", lon=-82.69))
    feed._ingest(_report(time_utc="2026-10-19 23:50:35.000000 +0000 UTC", lon=-82.68))
    v = feed.vessels["366000001"]
    assert v.last_position.timestamp == datetime(2026, 10, 19, 23, 50, 40, tzinfo=timezone.utc)
    assert len(v.track) == 1
    assert feed.quality["dropped_out_of_order"] == 1


def test_parse_ais_time_handles_nanoseconds_and_garbage():
    t = parse_ais_time("2026-10-19 23:50:30.123456789 +0000 UTC")
    assert t.microsecond == 123456
    assert parse_ais_time("not a time") is None
    assert parse_ais_time(None) is None


def test_duplicate_report_is_dropped():
    feed = _feed()
    r = _report(time_utc="2026-10-19 23:50:30.0 +0000 UTC")
    feed._ingest(r)
    feed._ingest(r)
    assert len(feed.vessels["366000001"].track) == 0


# -------------------------------------------------------- static data #
def test_static_data_before_first_position_is_kept():
    feed = _feed()
    feed._ingest(_static(Name="CS STRATOS@@@@", Type=33, Destination="ST PETERSBURG@@",
                         Dimension={"A": 90, "B": 25}))
    feed._ingest(_report())
    v = feed.vessels["366000001"]
    assert v.name == "CS STRATOS"
    assert v.vessel_type == VesselType.SPECIAL_OPS
    assert v.length_m == 115
    assert v.destination == "ST PETERSBURG"


def test_ais_type_codes_map_to_real_classes():
    m = ais_stream._coerce_vessel_type
    assert m(52) == VesselType.TUG
    assert m(41) == VesselType.HIGH_SPEED
    assert m(50) == VesselType.SERVICE
    assert m(31) == VesselType.TUG          # towing used to be mapped to "pleasure"
    assert m(37) == VesselType.PLEASURE
    assert m(0) == VesselType.UNKNOWN


def test_clean_text_strips_padding_and_control_characters():
    assert clean_text("BENCKES@@@@@@") == "BENCKES"
    assert clean_text("A\x00B<script>") == "ABscript"
    assert clean_text(None) == ""
    assert len(clean_text("X" * 200)) == 40


# --------------------------------------------------- stale and eviction #
def test_silent_vessels_leave_the_active_picture_and_are_evicted():
    feed = _feed()
    feed._ingest(_report())
    v = feed.vessels["366000001"]
    v.last_position = v.last_position.model_copy(
        update={"timestamp": datetime.now(timezone.utc) - timedelta(minutes=45)})
    assert feed.all_vessels() == []
    assert v.is_dark is True
    assert len(feed.all_vessels_including_dark()) == 1
    v.last_position = v.last_position.model_copy(
        update={"timestamp": datetime.now(timezone.utc) - timedelta(hours=7)})
    feed.tick()
    assert feed.vessels == {}


def test_server_error_message_does_not_crash_ingest():
    feed = _feed()
    feed._ingest({"error": "Api Key Is Not Valid"})
    assert feed.vessels == {}


def test_country_code_placeholder_mmsi_is_invalid():
    # 227000000 ("FRENCH WARSHIP") was heard from places 800 NM apart.
    assert classify_mmsi("227000000") == MmsiClass.INVALID
    assert classify_mmsi("246843000") == MmsiClass.SHIP   # trailing 000 is normal
