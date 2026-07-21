"""Anomaly detectors. All inherit from Detector and emit Threat objects."""
from app.detectors.base import Detector
from app.detectors.dark_activity import DarkActivityDetector
from app.detectors.identity import IdentityDetector
from app.detectors.kinematic import KinematicDetector
from app.detectors.loitering import LoiteringDetector
from app.detectors.ml_anomaly import MLAnomalyDetector

__all__ = [
    "Detector",
    "KinematicDetector",
    "IdentityDetector",
    "DarkActivityDetector",
    "LoiteringDetector",
    "MLAnomalyDetector",
]


def default_detectors() -> list[Detector]:
    return [
        KinematicDetector(),
        IdentityDetector(),
        DarkActivityDetector(),
        LoiteringDetector(),
        MLAnomalyDetector(),
    ]
