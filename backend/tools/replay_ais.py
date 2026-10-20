"""Replay recorded AISStream messages through the full detector stack.

    python tools/replay_ais.py ../findings/raw.jsonl

Runs on a simulated clock driven by the messages' own timestamps, scanning
every 2 simulated seconds exactly like the live loop, so minutes of recorded
traffic replay in seconds. Prints the alerts, the ML status and the data
quality counters. Use it to check a detector change against real traffic
before deploying it. Findings go to findings/replay_findings.jsonl.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import time as _time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("PHANTOMSHIP_FINDINGS_PATH", "findings/replay_findings.jsonl")

from app import state as st  # noqa: E402
from app.data import ais_stream  # noqa: E402
from app.data.ais_stream import AISStreamFeed, parse_ais_time  # noqa: E402
from app.detectors import base, ml_anomaly  # noqa: E402

CLOCK: dict = {"now": None}


class _SimDatetime(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return CLOCK["now"]


class _SimTime:
    @staticmethod
    def monotonic() -> float:
        return CLOCK["now"].timestamp()


def main(path: str) -> None:
    for mod in (ais_stream, st, base):
        mod.datetime = _SimDatetime
    ml_anomaly.time = _SimTime

    feed = AISStreamFeed(api_key="replay")
    eng = st.StateEngine()
    eng.mode, eng.live = "live", feed
    last_scan, scans, slowest = None, 0, 0.0
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            t = parse_ais_time((msg.get("MetaData") or {}).get("time_utc"))
            if t is None:
                continue
            CLOCK["now"] = t
            feed._ingest(msg)
            if last_scan is None or (t - last_scan).total_seconds() >= 2.0:
                t0 = _time.perf_counter()
                feed.tick()
                eng._run_detectors()
                eng._expire_old_threats()
                eng._recompute_threat_scores()
                slowest = max(slowest, _time.perf_counter() - t0)
                last_scan, scans = t, scans + 1

    s = eng.stats()
    print(f"scans {scans}, vessels {s['vessels_tracked']}, slowest scan {slowest * 1000:.0f} ms")
    print(f"alerts {s['threats_active']} {s['threats_by_detector']} {s['threats_by_severity']}")
    print(f"ml {s['ml']}")
    print(f"data quality {s['data_quality']}")
    for t in eng.threats_list():
        print(f"  {t.severity.value:8} {t.detector.value:13} x{t.occurrences:<3} {t.mmsi}  {t.description[:160]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python tools/replay_ais.py RECORDING.jsonl")
    main(sys.argv[1])
