"""Optional live AISStream.io connector.

Enabled only when PHANTOMSHIP_DATA_SOURCE=live and AISSTREAM_API_KEY is set.
Get a free key at https://aisstream.io.

This consumer subscribes to global AIS PositionReport and ShipStaticData
messages and writes them into the same Vessel/Position structures the
simulator uses, so the detectors don't care which source they're scanning.

Real AIS is messy in ways the simulator never was, and every rule below
exists because the live feed produced a false alert without it:

* Reserved "not available" values (speed 102.3, course 360, heading 511,
  latitude 91, longitude 181) are decoded as missing, never as readings.
* Positions at exactly 0,0 ("null island"), positions the transponder marks
  as manual input, dead reckoning or inoperative, and reports flagged
  invalid are dropped.
* Invalid and shared MMSIs (0, 123456789, unknown country codes, beacons)
  are dropped. Many unrelated devices broadcast them, so they look like one
  ship teleporting around the planet.
* The message timestamp from AISStream is used instead of the time we
  happened to read it; out of order and duplicate reports are discarded.
* Static data that arrives before a ship's first position is kept and
  applied when the position shows up, and the flag comes from the MMSI
  country code when static data is missing.
* Vessels that stop reporting leave the active picture after a while and
  are evicted from memory later, so the process does not grow forever.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import websockets

from app.config import SETTINGS
from app.data.mmsi import MmsiClass, classify_mmsi, flag_for_mmsi, normalize_mmsi
from app.models import Position, Vessel, VesselType


log = logging.getLogger(__name__)

AISSTREAM_WS_URL = "wss://stream.aisstream.io/v0/stream"

_PRINTABLE = re.compile(r"[^A-Za-z0-9 .,'/&()\-+#:]")
_TIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.(\d+))?")


def _coerce_vessel_type(ship_type: int | None) -> VesselType:
    """Map AIS ship-type codes (ITU-R M.1371) to our coarse VesselType enum."""
    if ship_type is None:
        return VesselType.UNKNOWN
    try:
        t = int(ship_type)
    except (TypeError, ValueError):
        return VesselType.UNKNOWN
    if 20 <= t <= 29 or 40 <= t <= 49:
        return VesselType.HIGH_SPEED
    if t == 30:
        return VesselType.FISHING
    if t in (31, 32, 52):
        return VesselType.TUG
    if t in (33, 34):
        return VesselType.SPECIAL_OPS
    if t == 35:
        return VesselType.MILITARY
    if t in (36, 37):
        return VesselType.PLEASURE
    if t in (50, 51, 53, 54, 55, 58, 59):
        return VesselType.SERVICE
    if 60 <= t <= 69:
        return VesselType.PASSENGER
    if 70 <= t <= 79:
        return VesselType.CARGO
    if 80 <= t <= 89:
        return VesselType.TANKER
    return VesselType.UNKNOWN


def clean_text(value: Any, max_len: int = 40) -> str:
    """AIS text fields are padded with '@' and can contain anything a
    transmitter chooses to send. Keep them short and printable."""
    if not isinstance(value, str):
        return ""
    s = value.replace("@", " ")
    s = _PRINTABLE.sub("", s)
    s = " ".join(s.split())
    return s[:max_len]


def parse_ais_time(value: Any) -> Optional[datetime]:
    """Parse AISStream's 'time_utc' (e.g. '2026-10-19 23:50:30.752066789 +0000 UTC')."""
    if not isinstance(value, str):
        return None
    m = _TIME_RE.match(value.strip())
    if not m:
        return None
    frac = (m.group(3) or "0")[:6].ljust(6, "0")
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}.{frac}", "%Y-%m-%d %H:%M:%S.%f").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


class AISStreamFeed:
    """Connects to AISStream and maintains an in-memory vessel state map."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or SETTINGS.aisstream_api_key
        self.vessels: dict[str, Vessel] = {}
        self._pending_static: dict[str, dict[str, Any]] = {}
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self.quality: dict[str, int] = {}
        self.status: dict[str, Any] = {
            "connected": False,
            "messages": 0,
            "last_message_at": None,
            "last_error": None,
            "connects": 0,
        }
        self._ingest_errors_logged = 0

    # ------------------------------------------------------------ lifecycle #
    async def start(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "AISSTREAM_API_KEY not set. Either set it in your environment or "
                "switch PHANTOMSHIP_DATA_SOURCE=simulator."
            )
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------------ API #
    def _stale_cutoff(self, now: Optional[datetime] = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        return now - timedelta(minutes=SETTINGS.live_stale_minutes)

    def all_vessels(self) -> list[Vessel]:
        """Vessels heard recently. Silent ones drop out, which is what lets
        the dark activity detector notice that they went quiet."""
        cutoff = self._stale_cutoff()
        out = []
        for v in self.vessels.values():
            dark = v.last_position.timestamp < cutoff
            if v.is_dark != dark:
                v.is_dark = dark
            if not dark:
                out.append(v)
        return out

    def all_vessels_including_dark(self) -> list[Vessel]:
        return list(self.vessels.values())

    def get(self, mmsi: str) -> Optional[Vessel]:
        return self.vessels.get(mmsi)

    def tick(self) -> None:
        """Housekeeping: evict vessels silent for hours, bound the static cache."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=SETTINGS.live_evict_hours)
        stale = [m for m, v in self.vessels.items() if v.last_position.timestamp < cutoff]
        for m in stale:
            del self.vessels[m]
        if stale:
            self._count("evicted_silent_vessels", len(stale))
        if len(self._pending_static) > 50_000:
            self._pending_static.clear()

    # ------------------------------------------------------------- internal #
    def _count(self, key: str, n: int = 1) -> None:
        self.quality[key] = self.quality.get(key, 0) + n

    async def _run(self) -> None:
        subscribe_msg = {
            "APIKey": self.api_key,
            # Global bounding box
            "BoundingBoxes": [[[-90, -180], [90, 180]]],
            "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
        }
        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(AISSTREAM_WS_URL, max_size=2**22) as ws:
                    # AISStream closes the socket if the subscription is not
                    # sent within a few seconds of connecting.
                    await ws.send(json.dumps(subscribe_msg))
                    self.status["connected"] = True
                    self.status["connects"] += 1
                    log.info("AISStream connected")
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        backoff = 1.0
                        self.status["messages"] += 1
                        self.status["last_message_at"] = datetime.now(timezone.utc).isoformat()
                        try:
                            msg = json.loads(raw)
                            if isinstance(msg, dict) and "error" in msg:
                                # e.g. {"error": "Api Key Is Not Valid"}
                                self.status["last_error"] = str(msg["error"])[:200]
                                log.error("AISStream rejected the subscription: %s", self.status["last_error"])
                                continue
                            self._ingest(msg)
                        except Exception:
                            self._count("ingest_errors")
                            if self._ingest_errors_logged < 5:
                                self._ingest_errors_logged += 1
                                log.exception("ingest failed")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.status["last_error"] = f"{type(e).__name__}: {e}"[:200]
                log.warning("AISStream disconnect: %s; retrying in %.1fs", e, backoff)
            finally:
                self.status["connected"] = False
            if not self._stop.is_set():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 60.0)

    def _ingest(self, msg: dict) -> None:
        meta = msg.get("MetaData", {}) or {}
        mmsi_raw = meta.get("MMSI") if meta.get("MMSI") is not None else meta.get("MMSI_String")
        if mmsi_raw is None:
            return
        mmsi = normalize_mmsi(mmsi_raw)
        msg_type = msg.get("MessageType", "")
        body = msg.get("Message", {}) or {}

        cls = classify_mmsi(mmsi)
        if cls != MmsiClass.SHIP:
            self._count("dropped_invalid_mmsi" if cls == MmsiClass.INVALID else "dropped_non_ship_mmsi")
            return

        if msg_type == "PositionReport":
            self._ingest_position(mmsi, meta, body.get("PositionReport") or {})
        elif msg_type == "ShipStaticData":
            self._ingest_static(mmsi, body.get("ShipStaticData") or {})

    def _ingest_position(self, mmsi: str, meta: dict, pr: dict) -> None:
        if not pr:
            return
        self._count("position_reports")
        if pr.get("Valid") is False:
            self._count("dropped_invalid_report")
            return
        lat = pr.get("Latitude")
        lon = pr.get("Longitude")
        if lat is None or lon is None:
            self._count("dropped_no_position")
            return
        lat = float(lat)
        lon = float(lon)
        # Latitude 91 / longitude 181 mean "position not available".
        if abs(lat) > 90 or abs(lon) > 180:
            self._count("dropped_no_position")
            return
        if abs(lat) < 1e-6 and abs(lon) < 1e-6:
            self._count("dropped_null_island")
            return
        # The 'Timestamp' field is the UTC second of the fix. 61, 62 and 63
        # mean manual input, dead reckoning and positioning system
        # inoperative; those positions are not real fixes.
        ts_field = pr.get("Timestamp")
        if isinstance(ts_field, (int, float)) and int(ts_field) in (61, 62, 63):
            self._count("dropped_unreliable_fix")
            return

        sog = pr.get("Sog")
        cog = pr.get("Cog")
        heading = pr.get("TrueHeading")
        # Speed over ground is sent in tenths of a knot: 1023 (102.3 kn)
        # means "not available" and 1022 (102.2 kn) means "102.2 kn or
        # more", which no real ship reaches, so both are treated as unknown.
        speed_available = sog is not None and 0.0 <= float(sog) < 102.2
        # Course 360 means "not available".
        course_available = cog is not None and 0.0 <= float(cog) < 360.0
        if not speed_available:
            self._count("speed_unavailable")
        if not course_available:
            self._count("course_unavailable")
        speed = float(sog) if speed_available else 0.0
        course = float(cog) if course_available else 0.0
        if heading is None or not (0 <= float(heading) < 360):  # 511 = not available
            heading = course
        nav = pr.get("NavigationalStatus")
        nav_status = int(nav) if isinstance(nav, (int, float)) and 0 <= int(nav) <= 15 else None

        now = datetime.now(timezone.utc)
        ts = parse_ais_time(meta.get("time_utc")) or now
        if ts > now + timedelta(seconds=30):
            ts = now   # clock skew upstream; never let a report live in the future

        pos = Position(
            timestamp=ts,
            lat=lat,
            lon=lon,
            speed_knots=speed,
            course=course,
            heading=float(heading) % 360.0,
            speed_available=speed_available,
            course_available=course_available,
            nav_status=nav_status,
        )

        vessel = self.vessels.get(mmsi)
        if vessel is None:
            name = clean_text(meta.get("ShipName")) or f"MMSI {mmsi}"
            vessel = Vessel(
                mmsi=mmsi,
                name=name,
                vessel_type=VesselType.UNKNOWN,
                flag=flag_for_mmsi(mmsi),
                length_m=0,
                destination="--",
                last_position=pos,
            )
            pending = self._pending_static.pop(mmsi, None)
            if pending:
                self._apply_static(vessel, pending)
            self.vessels[mmsi] = vessel
            return

        last = vessel.last_position
        if ts < last.timestamp:
            self._count("dropped_out_of_order")
            return
        if ts == last.timestamp or (
            (ts - last.timestamp).total_seconds() < 1.0 and last.lat == lat and last.lon == lon
        ):
            # Same report heard by several receivers.
            self._count("dropped_duplicate")
            return
        vessel.track.append(last)
        if len(vessel.track) > SETTINGS.track_length:
            del vessel.track[: len(vessel.track) - SETTINGS.track_length]
        vessel.last_position = pos
        vessel.is_dark = False

    def _ingest_static(self, mmsi: str, ssd: dict) -> None:
        if not ssd:
            return
        self._count("static_reports")
        vessel = self.vessels.get(mmsi)
        if vessel is None:
            # Static data often arrives before the first position report.
            self._pending_static[mmsi] = ssd
            return
        self._apply_static(vessel, ssd)

    @staticmethod
    def _apply_static(vessel: Vessel, ssd: dict) -> None:
        name = clean_text(ssd.get("Name"))
        if name:
            vessel.name = name
        vt = _coerce_vessel_type(ssd.get("Type"))
        if vt != VesselType.UNKNOWN:
            vessel.vessel_type = vt
        dest = clean_text(ssd.get("Destination"), max_len=30)
        if dest:
            vessel.destination = dest
        dim = ssd.get("Dimension") or {}
        try:
            length = int((dim.get("A", 0) or 0) + (dim.get("B", 0) or 0))
        except (TypeError, ValueError):
            length = 0
        if 0 < length < 500:   # 511 per side means "not available"
            vessel.length_m = length
