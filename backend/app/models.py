"""Pydantic data models for vessels, positions, and threats."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class VesselType(str, Enum):
    CARGO = "cargo"
    TANKER = "tanker"
    FISHING = "fishing"
    PASSENGER = "passenger"
    MILITARY = "military"
    PLEASURE = "pleasure"
    # Live AIS carries many classes the simulator never produced. Each one
    # behaves differently, so lumping them into "unknown" made real tugs,
    # pilot boats and fast ferries look anomalous.
    HIGH_SPEED = "high_speed"     # AIS types 20-29 (WIG) and 40-49 (HSC)
    TUG = "tug"                   # AIS types 31, 32, 52
    SERVICE = "service"           # pilot, SAR, port tender, law enforcement, medical
    SPECIAL_OPS = "special_ops"   # dredging, diving, underwater operations (incl. cable work)
    UNKNOWN = "unknown"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_RANK = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2, Severity.CRITICAL: 3}


class DetectorType(str, Enum):
    KINEMATIC = "kinematic"           # Impossible speed / teleportation
    IDENTITY = "identity"             # MMSI collision (one ID, two ships)
    DARK_ACTIVITY = "dark_activity"   # AIS silence near sensitive zones
    LOITERING = "loitering"           # Lingering near critical infrastructure
    ML_ANOMALY = "ml_anomaly"         # Isolation-forest behavioral anomaly


class Position(BaseModel):
    """A single AIS-style position report."""
    timestamp: datetime
    lat: float
    lon: float
    speed_knots: float = Field(ge=0)
    course: float = Field(ge=0, lt=360)
    heading: float = Field(ge=0, lt=360)
    # AIS reserves sentinel values meaning "not available" (speed 102.3 kn,
    # course 360). When a report carries one, the field is stored as 0 and
    # flagged here so detectors never treat a missing value as a real one.
    speed_available: bool = True
    course_available: bool = True
    # AIS navigational status (0 underway, 1 at anchor, 5 moored, 7 fishing,
    # 15 not defined). None when the source does not provide it.
    nav_status: Optional[int] = None


NAV_STATUS_LABELS = {
    0: "under way using engine", 1: "at anchor", 2: "not under command",
    3: "restricted manoeuvrability", 4: "constrained by draught", 5: "moored",
    6: "aground", 7: "engaged in fishing", 8: "under way sailing",
    14: "AIS SART active", 15: "not defined",
}


class Vessel(BaseModel):
    """Vessel record + latest known position."""
    mmsi: str
    name: str
    vessel_type: VesselType
    flag: str                  # ISO-3166 country code, e.g. "US", "PA"; "--" if unknown
    length_m: int
    destination: str
    last_position: Position
    track: list[Position] = Field(default_factory=list)  # recent positions, capped
    is_dark: bool = False      # currently broadcasting?
    threat_score: float = 0.0  # 0..1 aggregate

    def to_public(self) -> dict[str, Any]:
        """Slim representation for the /vessels endpoint (no full track)."""
        p = self.last_position
        return {
            "mmsi": self.mmsi,
            "name": self.name,
            "type": self.vessel_type.value,
            "flag": self.flag,
            "length_m": self.length_m,
            "destination": self.destination,
            "lat": p.lat,
            "lon": p.lon,
            "speed": p.speed_knots,
            "course": p.course,
            "heading": p.heading,
            "speed_available": p.speed_available,
            "course_available": p.course_available,
            "nav_status": p.nav_status,
            "is_dark": self.is_dark,
            "threat_score": round(self.threat_score, 3),
            "timestamp": p.timestamp.isoformat(),
        }

    def snapshot(self) -> dict[str, Any]:
        """Identity facts kept with a threat so it stays explainable after
        the vessel itself has been evicted from memory."""
        return {
            "mmsi": self.mmsi,
            "name": self.name,
            "type": self.vessel_type.value,
            "flag": self.flag,
            "length_m": self.length_m,
            "destination": self.destination,
        }


class Threat(BaseModel):
    """A detection event flagged by one of the detectors.

    One Threat represents one *episode*: a vessel that keeps loitering, or
    keeps reporting an impossible speed, updates the same Threat (last_seen_at,
    occurrences) instead of raising a new alert every scan.
    """
    id: str
    mmsi: str
    vessel_name: str
    detector: DetectorType
    severity: Severity
    title: str
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    lat: float
    lon: float
    detected_at: datetime
    last_seen_at: Optional[datetime] = None
    occurrences: int = 1
    ai_assessment: Optional[str] = None
    ai_engine: Optional[str] = None
    vessel_snapshot: Optional[dict[str, Any]] = None

    def kind(self) -> str:
        """Stable label for the condition, used to merge repeat detections."""
        return str(self.evidence.get("kind") or self.title)

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mmsi": self.mmsi,
            "vessel_name": self.vessel_name,
            "detector": self.detector.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "evidence": self.evidence,
            "lat": self.lat,
            "lon": self.lon,
            "detected_at": self.detected_at.isoformat(),
            "last_seen_at": (self.last_seen_at or self.detected_at).isoformat(),
            "occurrences": self.occurrences,
            "ai_assessment": self.ai_assessment,
            "ai_engine": self.ai_engine,
        }


class CriticalZone(BaseModel):
    """A geographic area we care about: cable corridor, sanctioned port, choke point."""
    id: str
    name: str
    category: str   # 'cable', 'sanctioned_port', 'chokepoint', 'eez'
    description: str
    polygon: list[tuple[float, float]]  # [(lon, lat), ...] closed ring
    center: tuple[float, float]         # (lon, lat) for label placement
