"""Optional live AISStream.io connector.

Enabled only when PHANTOMSHIP_DATA_SOURCE=live and AISSTREAM_API_KEY is set.
Get a free key at https://aisstream.io.

When enabled, this consumer subscribes to global AIS PositionReport messages
and writes them into the same Vessel/Position structures the simulator uses,
so the detectors don't care which source they're scanning.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import websockets

from app.config import SETTINGS
from app.models import Position, Vessel, VesselType


log = logging.getLogger(__name__)

AISSTREAM_WS_URL = "wss://stream.aisstream.io/v0/stream"


def _coerce_vessel_type(ship_type: int | None) -> VesselType:
    """Map AIS ship-type codes to our coarse VesselType enum."""
    if ship_type is None:
        return VesselType.UNKNOWN
    if 70 <= ship_type <= 79:
        return VesselType.CARGO
    if 80 <= ship_type <= 89:
        return VesselType.TANKER
    if ship_type == 30:
        return VesselType.FISHING
    if 60 <= ship_type <= 69:
        return VesselType.PASSENGER
    if ship_type == 35 or ship_type == 55:
        return VesselType.MILITARY
    if ship_type == 37 or 30 <= ship_type <= 39:
        return VesselType.PLEASURE
    return VesselType.UNKNOWN


class AISStreamFeed:
    """Connects to AISStream and maintains an in-memory vessel state map."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or SETTINGS.aisstream_api_key
        self.vessels: dict[str, Vessel] = {}
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

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

    def all_vessels(self) -> list[Vessel]:
        return list(self.vessels.values())

    def all_vessels_including_dark(self) -> list[Vessel]:
        return list(self.vessels.values())

    def tick(self) -> None:
        """No-op: state is updated asynchronously by the WS task."""
        return

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
                    await ws.send(json.dumps(subscribe_msg))
                    backoff = 1.0
                    log.info("AISStream connected")
                    async for raw in ws:
                        if self._stop.is_set():
                            break
                        try:
                            msg = json.loads(raw)
                            self._ingest(msg)
                        except Exception:
                            log.exception("ingest failed")
            except Exception as e:
                log.warning("AISStream disconnect: %s; retrying in %.1fs", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)

    def _ingest(self, msg: dict) -> None:
        meta = msg.get("MetaData", {}) or {}
        mmsi_raw = meta.get("MMSI") or meta.get("MMSI_String")
        if mmsi_raw is None:
            return
        mmsi = str(mmsi_raw)
        msg_type = msg.get("MessageType", "")
        pr = msg.get("Message", {}).get("PositionReport") or {}
        ssd = msg.get("Message", {}).get("ShipStaticData") or {}

        vessel = self.vessels.get(mmsi)
        if msg_type == "PositionReport" and pr:
            lat = pr.get("Latitude"); lon = pr.get("Longitude")
            sog = pr.get("Sog", 0.0); cog = pr.get("Cog", 0.0)
            heading = pr.get("TrueHeading")
            if lat is None or lon is None:
                return
            if heading is None or heading == 511:
                heading = cog or 0.0
            now = datetime.now(timezone.utc)
            pos = Position(
                timestamp=now,
                lat=float(lat),
                lon=float(lon),
                speed_knots=max(0.0, float(sog or 0.0)),
                course=float(cog or 0.0) % 360.0,
                heading=float(heading or 0.0) % 360.0,
            )
            if vessel is None:
                vessel = Vessel(
                    mmsi=mmsi,
                    name=meta.get("ShipName", f"VESSEL {mmsi[-4:]}").strip() or f"VESSEL {mmsi[-4:]}",
                    vessel_type=VesselType.UNKNOWN,
                    flag="--",
                    length_m=0,
                    destination="--",
                    last_position=pos,
                )
                self.vessels[mmsi] = vessel
            else:
                vessel.track.append(vessel.last_position)
                if len(vessel.track) > SETTINGS.track_length:
                    vessel.track = vessel.track[-SETTINGS.track_length:]
                vessel.last_position = pos
        elif msg_type == "ShipStaticData" and ssd and vessel is not None:
            name = ssd.get("Name") or vessel.name
            ship_type = ssd.get("Type")
            vessel.name = name.strip() if isinstance(name, str) else vessel.name
            vessel.vessel_type = _coerce_vessel_type(ship_type)
            dim = ssd.get("Dimension") or {}
            length = int((dim.get("A", 0) or 0) + (dim.get("B", 0) or 0))
            if length > 0:
                vessel.length_m = length
