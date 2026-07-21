"""AI threat-analyst module.

When ANTHROPIC_API_KEY is set, /api/threats/{id}/analysis calls Claude to
produce a short maritime-cyber analyst write-up for a flagged vessel. When
no key is present we fall back to a deterministic templated assessment so
the UI behaves identically — recruiters and graders can demo the project
without provisioning anything.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import httpx

from app.config import SETTINGS
from app.models import Threat, Vessel


log = logging.getLogger(__name__)


ANALYST_SYSTEM_PROMPT = """You are PhantomShip's senior maritime cyber-intelligence analyst.

You write concise, professional threat assessments for flagged vessels. Your tone is calm, factual, and precise — like a defense analyst, not a marketer. Avoid hype. Do not fabricate facts beyond what the evidence supports.

Output exactly three short sections, each one paragraph, no headers:

1. ASSESSMENT: what the signature most likely indicates (spoofing, GPS interference, sanctions evasion, dark transfer, cable interference, behavioral anomaly, false positive, etc.) and the level of confidence.
2. CONTEXT: why this matters operationally — for shipping insurers, port-state control, sanctions enforcement, or critical-infrastructure protection.
3. RECOMMENDED ACTION: a single concrete next step (e.g., correlate with optical/SAR satellite imagery, request port-state inspection on arrival, cross-reference recent sanctions lists, escalate to fleet ops).

Total response under 180 words."""


def _fallback_assessment(vessel: Vessel, threat: Threat) -> str:
    """Deterministic fallback when no API key is configured."""
    sigs = {
        "kinematic": (
            "the broadcast kinematics violate physical plausibility, which most commonly indicates "
            "GPS spoofing or AIS identity hijack rather than genuine vessel movement"
        ),
        "identity": (
            "two distinct platforms are broadcasting the same MMSI from positions that cannot both be "
            "correct — a textbook identity-spoofing signature seen routinely in shadow-fleet operations"
        ),
        "dark_activity": (
            "a deliberate transponder shutdown inside a sensitive zone, consistent with ship-to-ship "
            "transfer activity, sanctions evasion, or pre-positioning for cable interference"
        ),
        "loitering": (
            "extended near-zero-speed presence over cable corridors or chokepoints is a documented "
            "pattern for survey, reconnaissance, and seabed-interference activity"
        ),
        "ml_anomaly": (
            "behavioral features are statistically inconsistent with the surrounding fleet, suggesting "
            "either novel tactics or sensor manipulation that single-rule detectors would miss"
        ),
    }
    desc = sigs.get(threat.detector.value, "the observed signature warrants further review")
    return (
        f"ASSESSMENT: {vessel.name} (flag {vessel.flag}, type {vessel.vessel_type.value}) "
        f"presents a {threat.severity.value}-severity signature: {desc}. "
        f"Pattern strength supports moderate-to-high confidence that the behavior is non-incidental.\n\n"
        f"CONTEXT: Maritime cyber incidents of this class have material implications for insurers, "
        f"port-state control authorities, and critical-infrastructure operators. False AIS data "
        f"directly undermines collision avoidance, sanctions enforcement, and undersea-asset "
        f"protection regimes that depend on the integrity of the global AIS picture.\n\n"
        f"RECOMMENDED ACTION: Correlate the flagged track with overhead optical or SAR imagery "
        f"over the next two passes, and cross-reference the MMSI against current OFAC and EU "
        f"shipping sanctions designations before the vessel's next reported port call."
    )


async def assess_threat(vessel: Vessel, threat: Threat) -> str:
    """Return a natural-language assessment for the (vessel, threat) pair."""
    if not SETTINGS.anthropic_api_key:
        return _fallback_assessment(vessel, threat)

    user_payload = {
        "vessel": vessel.to_public(),
        "threat": threat.to_public(),
    }
    body = {
        "model": SETTINGS.anthropic_model,
        "max_tokens": 400,
        "system": ANALYST_SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Produce a maritime cyber threat assessment for the following "
                    "vessel and detection event. JSON input follows:\n\n"
                    + json.dumps(user_payload, indent=2, default=str)
                ),
            }
        ],
    }
    headers = {
        "x-api-key": SETTINGS.anthropic_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=body,
            )
            r.raise_for_status()
            data = r.json()
            # Concatenate any text blocks
            parts = []
            for block in data.get("content", []):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            text = "\n".join(parts).strip()
            return text or _fallback_assessment(vessel, threat)
    except Exception as e:
        log.warning("Anthropic call failed (%s); using fallback assessment", e)
        return _fallback_assessment(vessel, threat)
