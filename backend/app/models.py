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
    UNKNOWN = "unknown"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


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


class Vessel(BaseModel):
    """Vessel record + latest known position."""
    mmsi: str
    name: str
    vessel_type: VesselType
    flag: str                  # ISO-3166 country code, e.g. "US", "PA"
    length_m: int
    destination: str
    last_position: Position
    track: list[Position] = Field(default_factory=list)  # recent positions, capped
    is_dark: bool = False      # currently broadcasting?
    threat_score: float = 0.0  # 0..1 aggregate

    def to_public(self) -> dict[str, Any]:
        """Slim representation for the /vessels endpoint (no full track)."""
        return {
            "mmsi": self.mmsi,
            "name": self.name,
            "type": self.vessel_type.value,
            "flag": self.flag,
            "length_m": self.length_m,
            "destination": self.destination,
            "lat": self.last_position.lat,
            "lon": self.last_position.lon,
            "speed": self.last_position.speed_knots,
            "course": self.last_position.course,
            "heading": self.last_position.heading,
            "is_dark": self.is_dark,
            "threat_score": round(self.threat_score, 3),
            "timestamp": self.last_position.timestamp.isoformat(),
        }


class Threat(BaseModel):
    """A detection event flagged by one of the detectors."""
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
    ai_assessment: Optional[str] = None

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
            "ai_assessment": self.ai_assessment,
        }


class CriticalZone(BaseModel):
    """A geographic area we care about: cable corridor, sanctioned port, choke point."""
    id: str
    name: str
    category: str   # 'cable', 'sanctioned_port', 'chokepoint', 'eez'
    description: str
    polygon: list[tuple[float, float]]  # [(lon, lat), ...] closed ring
    center: tuple[float, float]         # (lon, lat) for label placement
