"""Small geodesy helpers shared by the simulator, ingest and detectors."""
from __future__ import annotations

import math

EARTH_RADIUS_NM = 3440.065  # nautical miles


def _to_rad(d: float) -> float:
    return d * math.pi / 180.0


def haversine_nm(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two points in nautical miles."""
    phi1, phi2 = _to_rad(lat1), _to_rad(lat2)
    dphi = _to_rad(lat2 - lat1)
    dl = _to_rad(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    a = min(1.0, max(0.0, a))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_NM * c


def bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial bearing from point 1 to point 2, in degrees [0, 360)."""
    phi1, phi2 = _to_rad(lat1), _to_rad(lat2)
    dl = _to_rad(lon2 - lon1)
    y = math.sin(dl) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dl)
    theta = math.atan2(y, x)
    return (theta * 180.0 / math.pi + 360.0) % 360.0


def destination(lon: float, lat: float, bearing: float, distance_nm: float) -> tuple[float, float]:
    """Compute destination given start, bearing (deg), and distance (NM)."""
    d_r = distance_nm / EARTH_RADIUS_NM
    br = _to_rad(bearing)
    phi1, lam1 = _to_rad(lat), _to_rad(lon)
    phi2 = math.asin(math.sin(phi1) * math.cos(d_r) + math.cos(phi1) * math.sin(d_r) * math.cos(br))
    lam2 = lam1 + math.atan2(
        math.sin(br) * math.sin(d_r) * math.cos(phi1),
        math.cos(d_r) - math.sin(phi1) * math.sin(phi2),
    )
    return ((lam2 * 180.0 / math.pi + 540.0) % 360.0 - 180.0, phi2 * 180.0 / math.pi)


def norm_deg(x: float) -> float:
    """Wrap an angle into [0, 360). Guards against 359.999 rounding to 360."""
    y = x % 360.0
    return 0.0 if y >= 360.0 else y
