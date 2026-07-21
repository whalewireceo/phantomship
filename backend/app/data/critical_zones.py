"""Critical maritime zones we monitor for loitering, dark activity, and threat overlap.

These are stylized polygons covering well-known strategic areas. They are
intentionally illustrative rather than survey-grade — the goal is to give the
detectors meaningful geofences and the globe meaningful overlays.
"""
from __future__ import annotations

from app.models import CriticalZone


CRITICAL_ZONES: list[CriticalZone] = [
    CriticalZone(
        id="cz_baltic",
        name="Baltic Sea Cable Corridor",
        category="cable",
        description=(
            "Dense undersea power and data cable infrastructure including "
            "Nord Stream, Estlink, and Baltic Connector segments."
        ),
        polygon=[
            (17.0, 59.5), (24.0, 59.5), (24.0, 54.5),
            (17.0, 54.5), (17.0, 59.5),
        ],
        center=(20.5, 57.0),
    ),
    CriticalZone(
        id="cz_red_sea",
        name="Bab-el-Mandeb Strait",
        category="chokepoint",
        description=(
            "Strategic maritime chokepoint linking the Red Sea and the Gulf "
            "of Aden. Carries ~12% of global seaborne trade."
        ),
        polygon=[
            (42.5, 13.5), (44.0, 13.5), (44.0, 11.5),
            (42.5, 11.5), (42.5, 13.5),
        ],
        center=(43.25, 12.5),
    ),
    CriticalZone(
        id="cz_malacca",
        name="Strait of Malacca",
        category="chokepoint",
        description=(
            "World's busiest shipping lane connecting the Indian and Pacific "
            "Oceans. ~25% of global trade transits annually."
        ),
        polygon=[
            (99.5, 5.5), (103.5, 5.5), (104.0, 1.0),
            (100.0, 1.0), (99.5, 5.5),
        ],
        center=(101.5, 3.0),
    ),
    CriticalZone(
        id="cz_suez",
        name="Suez Approaches",
        category="chokepoint",
        description=(
            "Northern approach to the Suez Canal. High-density transit and "
            "regular target of regional disruption."
        ),
        polygon=[
            (31.5, 32.5), (33.0, 32.5), (33.0, 30.0),
            (31.5, 30.0), (31.5, 32.5),
        ],
        center=(32.25, 31.25),
    ),
    CriticalZone(
        id="cz_hormuz",
        name="Strait of Hormuz",
        category="chokepoint",
        description=(
            "Only sea route between the Persian Gulf and the open ocean. "
            "Carries roughly 20% of global oil consumption."
        ),
        polygon=[
            (55.5, 27.5), (57.5, 27.5), (57.5, 25.5),
            (55.5, 25.5), (55.5, 27.5),
        ],
        center=(56.5, 26.5),
    ),
    CriticalZone(
        id="cz_taiwan",
        name="Taiwan Strait",
        category="chokepoint",
        description=(
            "Contested waterway between the PRC mainland and Taiwan. Hosts "
            "major submarine cable landings."
        ),
        polygon=[
            (118.0, 26.0), (122.0, 26.0), (122.0, 22.0),
            (118.0, 22.0), (118.0, 26.0),
        ],
        center=(120.0, 24.0),
    ),
    CriticalZone(
        id="cz_uk_atlantic",
        name="UK–Ireland Cable Approaches",
        category="cable",
        description=(
            "Transatlantic cable landings serving Western Europe. Frequent "
            "Russian survey-vessel loitering reported."
        ),
        polygon=[
            (-12.0, 53.5), (-7.0, 53.5), (-7.0, 49.5),
            (-12.0, 49.5), (-12.0, 53.5),
        ],
        center=(-9.5, 51.5),
    ),
]


def point_in_zone(lon: float, lat: float, zone: CriticalZone) -> bool:
    """Ray-casting point-in-polygon test."""
    poly = zone.polygon
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        intersect = ((yi > lat) != (yj > lat)) and (
            lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi
        )
        if intersect:
            inside = not inside
        j = i
    return inside


def zone_containing(lon: float, lat: float) -> CriticalZone | None:
    for zone in CRITICAL_ZONES:
        if point_in_zone(lon, lat, zone):
            return zone
    return None
