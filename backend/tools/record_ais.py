"""Record raw AISStream messages to a JSON lines file for offline replay.

    AISSTREAM_API_KEY=... python tools/record_ais.py 600 ../findings/raw.jsonl

Records for the given number of seconds (appending to the file).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import websockets

URL = "wss://stream.aisstream.io/v0/stream"


async def record(seconds: float, out_path: str) -> int:
    key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set AISSTREAM_API_KEY first.")
    sub = {
        "APIKey": key,
        "BoundingBoxes": [[[-90, -180], [90, 180]]],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }
    n, t0 = 0, time.time()
    with open(out_path, "a", encoding="utf-8") as f:
        async with websockets.connect(URL, max_size=2**22) as ws:
            await ws.send(json.dumps(sub))
            async for raw in ws:
                f.write(raw.decode() if isinstance(raw, bytes) else raw)
                f.write("\n")
                n += 1
                if time.time() - t0 > seconds:
                    break
    return n


if __name__ == "__main__":
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 300
    out = sys.argv[2] if len(sys.argv) > 2 else "raw_ais.jsonl"
    print(f"recorded {asyncio.run(record(seconds, out))} messages to {out}")
