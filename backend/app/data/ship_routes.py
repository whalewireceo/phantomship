"""Stylized shipping routes used by the simulator to make vessel motion realistic.

Each route is a list of (lon, lat) waypoints. Vessels follow the route by
heading toward the next waypoint at their cruise speed, looping at the end.
"""
from __future__ import annotations

# (lon, lat) waypoints
ROUTES: dict[str, list[tuple[float, float]]] = {
    "transatlantic_north": [
        (-74.0, 40.6),    # New York
        (-50.0, 43.5),
        (-20.0, 49.0),
        (-5.0, 50.0),
        (4.5, 51.9),      # Rotterdam
    ],
    "transatlantic_south": [
        (-95.0, 29.5),    # Houston
        (-70.0, 24.0),
        (-30.0, 15.0),
        (-5.0, 6.0),
        (3.4, 6.5),       # Lagos
    ],
    "asia_eu_via_suez": [
        (114.0, 22.3),    # Hong Kong
        (103.8, 1.3),     # Singapore
        (80.0, 6.0),
        (55.0, 12.0),
        (43.3, 12.6),     # Bab-el-Mandeb
        (38.0, 22.0),
        (32.5, 30.5),     # Suez
        (24.0, 35.0),
        (12.5, 36.0),
        (-5.5, 36.0),     # Gibraltar
        (4.5, 51.9),      # Rotterdam
    ],
    "transpacific_north": [
        (139.7, 35.6),    # Tokyo Bay
        (160.0, 40.0),
        (180.0, 45.0),
        (-160.0, 47.0),
        (-130.0, 40.0),
        (-118.3, 33.7),   # Los Angeles
    ],
    "transpacific_south": [
        (121.5, 31.2),    # Shanghai
        (140.0, 25.0),
        (170.0, 15.0),
        (-160.0, 5.0),
        (-110.0, 0.0),
        (-79.5, 8.9),     # Panama
    ],
    "indian_ocean": [
        (72.8, 18.9),     # Mumbai
        (60.0, 14.0),
        (50.0, 8.0),
        (40.0, -5.0),
        (39.2, -6.8),     # Dar es Salaam
    ],
    "med_circuit": [
        (12.5, 36.0),
        (24.0, 35.0),
        (28.0, 36.5),
        (34.5, 31.3),
        (28.0, 36.5),
        (12.5, 36.0),
    ],
    "baltic_circuit": [
        (12.5, 55.7),     # Copenhagen approaches
        (18.0, 56.0),
        (24.0, 59.5),
        (24.0, 65.0),
        (18.0, 60.0),
        (12.5, 55.7),
    ],
    "north_sea_fishing": [
        (2.0, 56.0),
        (5.0, 57.5),
        (3.0, 58.5),
        (0.0, 57.0),
        (2.0, 56.0),
    ],
    "caribbean": [
        (-80.0, 25.0),
        (-75.0, 20.0),
        (-66.0, 18.5),
        (-61.0, 13.0),
        (-75.0, 20.0),
        (-80.0, 25.0),
    ],
}
