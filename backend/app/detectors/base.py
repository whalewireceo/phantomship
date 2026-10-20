"""Detector base class. Each detector inspects vessel state and emits Threats."""
from __future__ import annotations

import hashlib
import statistics
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app.data.geo import haversine_nm
from app.models import DetectorType, Position, Severity, Threat, Vessel


@dataclass
class ScanContext:
    """Facts about the whole picture that single-vessel rules cannot see."""
    mode: str = "simulator"
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # coverage(lon, lat, exclude_mmsi) -> number of *other* vessels heard
    # nearby in the last few minutes. Used to tell "this ship went quiet"
    # apart from "nobody is receiving signals out here".
    coverage: Optional[Callable[[float, float, str], int]] = None

    @property
    def live(self) -> bool:
        return self.mode == "live"


class Detector(ABC):
    """Base class for all anomaly detectors."""

    detector_type: DetectorType
    severity: Severity

    def __init__(self) -> None:
        # Things this detector saw and deliberately did *not* alert on, e.g.
        # a speed sensor fault. Surfaced in /api/stats as data quality.
        self.quality: dict[str, int] = {}

    def count(self, key: str, n: int = 1) -> None:
        self.quality[key] = self.quality.get(key, 0) + n

    @abstractmethod
    def scan(self, vessels: list[Vessel], ctx: Optional[ScanContext] = None) -> list[Threat]:
        """Return a list of threats found in this batch of vessel state."""
        raise NotImplementedError

    @staticmethod
    def make_id(*parts: str) -> str:
        """Deterministic threat ID so the same anomaly doesn't duplicate."""
        h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
        return f"t_{h[:16]}"

    @staticmethod
    def now_iso() -> datetime:
        return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Track helpers
# --------------------------------------------------------------------------- #
def full_track(v: Vessel) -> list[Position]:
    return v.track + [v.last_position]


def segment_speeds(points: list[Position], min_seconds: float = 1.0) -> list[float]:
    """Speed implied by each consecutive pair of positions, in knots."""
    out: list[float] = []
    for a, b in zip(points[:-1], points[1:]):
        dt = (b.timestamp - a.timestamp).total_seconds()
        if dt < min_seconds:
            continue
        out.append(haversine_nm(a.lon, a.lat, b.lon, b.lat) / (dt / 3600.0))
    return out


def recent(points: list[Position], now: datetime, minutes: float) -> list[Position]:
    """Points newer than now - minutes. Tracks are in time order, so walk
    back from the end and stop at the first older point."""
    cutoff = now - timedelta(minutes=minutes)
    i = len(points)
    while i > 0 and points[i - 1].timestamp >= cutoff:
        i -= 1
    return points[i:]


def median_or_none(xs: list[float]) -> Optional[float]:
    return statistics.median(xs) if xs else None
