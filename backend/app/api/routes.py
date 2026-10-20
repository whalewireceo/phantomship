"""HTTP routes for the PhantomShip dashboard."""
from __future__ import annotations

import asyncio
import time
from collections import deque

from fastapi import APIRouter, HTTPException, Query

from app.ai import assess_threat
from app.config import SETTINGS
from app.data.critical_zones import CRITICAL_ZONES
from app.state import state_engine


router = APIRouter()

# Claude calls cost money, and the analysis endpoint needs no login, so cap
# how often it can reach the API. Cached results are always served.
_ai_calls: deque[float] = deque()
_analysis_locks: dict[str, asyncio.Lock] = {}


def _ai_budget_available() -> bool:
    now = time.monotonic()
    while _ai_calls and now - _ai_calls[0] > 60.0:
        _ai_calls.popleft()
    return len(_ai_calls) < SETTINGS.ai_max_calls_per_minute


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "mode": state_engine.mode}


@router.get("/stats")
async def stats() -> dict:
    return state_engine.stats()


@router.get("/vessels")
async def vessels(limit: int | None = Query(default=None, ge=1, le=50_000)) -> dict:
    vs = state_engine.vessels()
    total = len(vs)
    if limit and total > limit:
        # Flagged vessels first so a display cap never hides one.
        vs = sorted(vs, key=lambda v: v.threat_score, reverse=True)[:limit]
    items = [v.to_public() for v in vs]
    return {"vessels": items, "count": len(items), "total": total}


@router.get("/threats")
async def threats(severity: str | None = None, detector: str | None = None) -> dict:
    items = state_engine.threats_list()
    if severity:
        items = [t for t in items if t.severity.value == severity.lower()]
    if detector:
        items = [t for t in items if t.detector.value == detector.lower()]
    return {"threats": [t.to_public() for t in items], "count": len(items)}


@router.get("/threats/{threat_id}")
async def threat_detail(threat_id: str) -> dict:
    t = state_engine.find_threat(threat_id)
    if not t:
        raise HTTPException(404, "threat not found")
    vessel = state_engine.find_vessel(t.mmsi)
    return {
        "threat": t.to_public(),
        "vessel": vessel.to_public() if vessel else None,
        "vessel_snapshot": t.vessel_snapshot,
        "track": [
            {"lat": p.lat, "lon": p.lon, "speed": p.speed_knots,
             "speed_available": p.speed_available,
             "course": p.course, "timestamp": p.timestamp.isoformat()}
            for p in (vessel.track + [vessel.last_position] if vessel else [])
        ],
    }


@router.post("/threats/{threat_id}/analysis")
async def threat_analysis(threat_id: str) -> dict:
    """Run AI analyst on a threat. Cached on the threat object."""
    t = state_engine.find_threat(threat_id)
    if not t:
        raise HTTPException(404, "threat not found")
    if t.ai_assessment:
        return {"assessment": t.ai_assessment, "engine": t.ai_engine, "cached": True}

    lock = _analysis_locks.setdefault(threat_id, asyncio.Lock())
    async with lock:
        # A second click while the first request was running gets its result.
        if t.ai_assessment:
            return {"assessment": t.ai_assessment, "engine": t.ai_engine, "cached": True}
        if SETTINGS.anthropic_api_key:
            if not _ai_budget_available():
                raise HTTPException(429, "AI analysis limit reached; try again in a minute.")
            _ai_calls.append(time.monotonic())
        vessel = state_engine.find_vessel(t.mmsi)
        text, engine = await assess_threat(vessel, t, data_source=state_engine.mode)
        # Cache it, unless Claude was configured but the call failed: then a
        # later click should get a real AI review rather than the fallback.
        if engine == "claude" or not SETTINGS.anthropic_api_key:
            t.ai_assessment = text
            t.ai_engine = engine
    if len(_analysis_locks) > 2000:
        _analysis_locks.clear()
    return {"assessment": text, "engine": engine, "cached": False}


@router.get("/zones")
async def zones() -> dict:
    return {
        "zones": [
            {
                "id": z.id,
                "name": z.name,
                "category": z.category,
                "description": z.description,
                "polygon": [[lon, lat] for lon, lat in z.polygon],
                "center": [z.center[0], z.center[1]],
            }
            for z in CRITICAL_ZONES
        ]
    }
