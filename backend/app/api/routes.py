"""HTTP routes for the PhantomShip dashboard."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.ai import assess_threat
from app.data.critical_zones import CRITICAL_ZONES
from app.state import state_engine


router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"ok": True, "mode": state_engine.mode}


@router.get("/stats")
async def stats() -> dict:
    return state_engine.stats()


@router.get("/vessels")
async def vessels(limit: int | None = None) -> dict:
    items = [v.to_public() for v in state_engine.vessels()]
    if limit:
        items = items[:limit]
    return {"vessels": items, "count": len(items)}


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
        "track": [
            {"lat": p.lat, "lon": p.lon, "speed": p.speed_knots,
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
        return {"assessment": t.ai_assessment, "cached": True}
    vessel = state_engine.find_vessel(t.mmsi)
    if not vessel:
        raise HTTPException(404, "vessel not found")
    text = await assess_threat(vessel, t)
    t.ai_assessment = text
    return {"assessment": text, "cached": False}


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
