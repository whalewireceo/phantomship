"""Ports and anchorages that sit inside the critical zones.

The watch zones are deliberately broad boxes, and several of them contain
busy ports: Singapore and Port Klang inside the Malacca box, Port Said
inside the Suez box, Stockholm and Klaipeda inside the Baltic box. Hundreds
of ships sit still in those places every day for ordinary reasons (moored,
waiting for a berth, waiting to transit), which made "slow vessel inside a
critical zone" fire on normal port traffic.

Positions within ``radius_nm`` of one of these points are excluded from
loitering and dark activity alerts. Coordinates and radii are approximate
and cover the port plus its usual anchorage. Extend this list when a new
zone is added.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.data.geo import haversine_nm


@dataclass(frozen=True)
class PortArea:
    name: str
    lon: float
    lat: float
    radius_nm: float


PORT_AREAS: list[PortArea] = [
    # Baltic Sea Cable Corridor
    PortArea("Stockholm", 18.07, 59.33, 12.0),
    PortArea("Nynashamn", 17.95, 58.90, 5.0),
    PortArea("Oxelosund", 17.10, 58.67, 5.0),
    PortArea("Visby", 18.29, 57.64, 4.0),
    PortArea("Klaipeda", 21.13, 55.71, 8.0),
    PortArea("Liepaja", 21.00, 56.52, 6.0),
    PortArea("Ventspils", 21.55, 57.40, 6.0),
    PortArea("Riga approaches", 23.95, 57.05, 10.0),
    PortArea("Baltiysk / Kaliningrad", 19.90, 54.65, 10.0),
    PortArea("Gdansk / Gdynia anchorage", 18.70, 54.55, 12.0),
    PortArea("Kuressaare", 22.48, 58.25, 4.0),
    # Bab el Mandeb
    PortArea("Djibouti", 43.14, 11.60, 10.0),
    PortArea("Assab", 42.74, 13.00, 6.0),
    PortArea("Mocha", 43.25, 13.32, 4.0),
    # Strait of Malacca
    PortArea("Singapore", 103.82, 1.25, 16.0),
    PortArea("Tanjung Pelepas", 103.55, 1.36, 8.0),
    PortArea("Batam", 104.00, 1.12, 8.0),
    PortArea("Port Klang", 101.30, 3.00, 12.0),
    PortArea("Port Dickson", 101.80, 2.52, 6.0),
    PortArea("Malacca", 102.25, 2.19, 5.0),
    PortArea("Dumai", 101.45, 1.68, 8.0),
    PortArea("Penang", 100.35, 5.41, 8.0),
    # Suez approaches
    PortArea("Port Said anchorage", 32.30, 31.30, 16.0),
    PortArea("Damietta", 31.80, 31.47, 8.0),
    PortArea("Ismailia", 32.27, 30.60, 5.0),
    PortArea("Great Bitter Lake", 32.40, 30.35, 10.0),
    # Strait of Hormuz
    PortArea("Bandar Abbas", 56.28, 27.15, 12.0),
    PortArea("Qeshm", 55.90, 26.90, 6.0),
    PortArea("Khasab", 56.25, 26.20, 5.0),
    PortArea("Ras Al Khaimah", 55.94, 25.79, 6.0),
    # Taiwan Strait
    PortArea("Kaohsiung", 120.28, 22.60, 10.0),
    PortArea("Anping / Tainan", 120.16, 22.98, 5.0),
    PortArea("Mailiao", 120.20, 23.79, 5.0),
    PortArea("Taichung", 120.50, 24.27, 8.0),
    PortArea("Taipei Port", 121.37, 25.16, 6.0),
    PortArea("Keelung", 121.74, 25.15, 6.0),
    PortArea("Hualien", 121.62, 23.98, 5.0),
    PortArea("Magong", 119.56, 23.56, 5.0),
    PortArea("Xiamen", 118.07, 24.47, 12.0),
    PortArea("Kinmen", 118.40, 24.43, 5.0),
    PortArea("Quanzhou", 118.68, 24.85, 8.0),
    PortArea("Matsu", 119.95, 26.15, 5.0),
    # UK and Ireland cable approaches
    PortArea("Cork Harbour", -8.30, 51.83, 10.0),
    PortArea("Bantry Bay", -9.55, 51.65, 8.0),
    PortArea("Castletownbere", -9.90, 51.65, 4.0),
    PortArea("Shannon Estuary", -9.20, 52.60, 12.0),
    PortArea("Galway", -9.05, 53.27, 6.0),
]


def port_area_at(lon: float, lat: float) -> PortArea | None:
    for p in PORT_AREAS:
        # Cheap bounding check first; 1 degree of latitude is 60 NM.
        if abs(lat - p.lat) * 60.0 > p.radius_nm + 1:
            continue
        if haversine_nm(lon, lat, p.lon, p.lat) <= p.radius_nm:
            return p
    return None
