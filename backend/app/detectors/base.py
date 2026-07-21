"""Detector base class. Each detector inspects vessel state and emits Threats."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.models import DetectorType, Severity, Threat, Vessel


class Detector(ABC):
    """Base class for all anomaly detectors."""

    detector_type: DetectorType
    severity: Severity

    @abstractmethod
    def scan(self, vessels: list[Vessel]) -> list[Threat]:
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
