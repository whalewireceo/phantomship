"""AIS data simulator with deliberately injected anomalies.

The simulator is the default data source so the demo runs offline with no
API keys. It spawns a fleet of vessels that follow realistic shipping routes
at appropriate speeds, then periodically introduces known suspicious
behaviors:

  * Hypersonic speeds (40+ knots on cargo class)
  * Position teleportation (jumping 100+ NM in a single tick)
  * MMSI identity collisions (two vessels broadcasting the same MMSI)
  * Loitering in critical infrastructure zones
  * Dark activity (vessels disappearing then reappearing far away)

Detectors operate against the resulting position stream exactly as they
would against a real AIS feed.
"""
from __future__ import annotations

import math
import random
import string
from collections import deque
from datetime import datetime, timezone

from app.config import SETTINGS
from app.data.critical_zones import CRITICAL_ZONES
from app.data.ship_routes import ROUTES
from app.models import Position, Vessel, VesselType


EARTH_RADIUS_NM = 3440.065  # nautical miles


# --------------------------------------------------------------------------- #
# Geo helpers
# --------------------------------------------------------------------------- #
def _to_rad(d: float) -> float:
    return d * math.pi / 180.0


def haversine_nm(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance between two points in nautical miles."""
    phi1, phi2 = _to_rad(lat1), _to_rad(lat2)
    dphi = _to_rad(lat2 - lat1)
    dl = _to_rad(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
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


# --------------------------------------------------------------------------- #
# Vessel-name generation (cheesy but believable)
# --------------------------------------------------------------------------- #
_PREFIXES = ["MV", "MT", "SS", "FV"]
_NAMES_A = [
    "Northern", "Pacific", "Atlantic", "Eastern", "Western", "Imperial",
    "Sovereign", "Royal", "Crystal", "Silver", "Iron", "Golden", "Polar",
    "Coral", "Aurora", "Stellar", "Marine", "Oceanic", "Hanseatic", "Liberty",
]
_NAMES_B = [
    "Voyager", "Trader", "Wave", "Star", "Pioneer", "Spirit", "Endeavor",
    "Mariner", "Glory", "Princess", "Falcon", "Horizon", "Crown", "Frontier",
    "Eagle", "Sentinel", "Argonaut", "Tempest", "Aegir", "Cetus",
]


def _make_name() -> str:
    return f"{random.choice(_PREFIXES)} {random.choice(_NAMES_A)} {random.choice(_NAMES_B)}"


_FLAGS = ["PA", "LR", "MH", "SG", "MT", "CY", "GR", "CN", "JP", "US", "DE", "GB", "NL", "NO", "DK", "IT"]


def _make_mmsi() -> str:
    return "".join(random.choices(string.digits, k=9))


# --------------------------------------------------------------------------- #
# Vessel construction
# --------------------------------------------------------------------------- #
_TYPE_PROFILES = {
    VesselType.CARGO:     {"cruise": (12.0, 18.0), "length": (180, 320), "weight": 0.40},
    VesselType.TANKER:    {"cruise": (11.0, 16.0), "length": (220, 360), "weight": 0.22},
    VesselType.FISHING:   {"cruise": (6.0, 11.0),  "length": (25, 75),   "weight": 0.18},
    VesselType.PASSENGER: {"cruise": (16.0, 22.0), "length": (200, 340), "weight": 0.06},
    VesselType.MILITARY:  {"cruise": (15.0, 24.0), "length": (130, 250), "weight": 0.04},
    VesselType.PLEASURE:  {"cruise": (8.0, 14.0),  "length": (15, 50),   "weight": 0.10},
}


def _sample_type() -> VesselType:
    types, weights = zip(*[(t, p["weight"]) for t, p in _TYPE_PROFILES.items()])
    return random.choices(types, weights=weights, k=1)[0]


def _spawn_vessel(route_name: str, route_index: int) -> tuple[Vessel, dict]:
    """Spawn a vessel placed on a route waypoint. Returns vessel + sim state."""
    route = ROUTES[route_name]
    start = route[route_index % len(route)]
    next_wp = route[(route_index + 1) % len(route)]
    vt = _sample_type()
    prof = _TYPE_PROFILES[vt]
    cruise = random.uniform(*prof["cruise"])
    course = bearing_deg(start[0], start[1], next_wp[0], next_wp[1])
    now = datetime.now(timezone.utc)

    vessel = Vessel(
        mmsi=_make_mmsi(),
        name=_make_name(),
        vessel_type=vt,
        flag=random.choice(_FLAGS),
        length_m=int(random.uniform(*prof["length"])),
        destination=random.choice(
            ["ROTTERDAM", "SINGAPORE", "SHANGHAI", "LOS ANGELES", "HAMBURG",
             "DUBAI", "TOKYO", "HOUSTON", "PIRAEUS", "BUSAN", "ANTWERP"]
        ),
        last_position=Position(
            timestamp=now,
            lat=start[1],
            lon=start[0],
            speed_knots=cruise,
            course=course,
            heading=course,
        ),
        track=[],
    )
    sim_state = {
        "route": route_name,
        "wp_index": (route_index + 1) % len(route),
        "cruise": cruise,
        "anomaly_role": None,        # set if this vessel is a planted bad actor
        "dark_until_tick": -1,       # tick number until which it stays dark
        "twin_mmsi_of": None,        # if this vessel is the spoofed twin of another
    }
    return vessel, sim_state


# --------------------------------------------------------------------------- #
# Simulator
# --------------------------------------------------------------------------- #
class Simulator:
    """Stateful AIS fleet simulator."""

    def __init__(self, vessel_count: int | None = None) -> None:
        self.vessels: dict[str, Vessel] = {}
        self.state: dict[str, dict] = {}  # mmsi -> sim_state
        self.tick_count: int = 0
        self.recent_anomaly_events: deque[dict] = deque(maxlen=200)
        self._build_fleet(vessel_count or SETTINGS.sim_vessel_count)
        self._designate_anomalies()

    # -- fleet construction -------------------------------------------------- #
    def _build_fleet(self, n: int) -> None:
        route_names = list(ROUTES.keys())
        for _ in range(n):
            route = random.choice(route_names)
            wp_idx = random.randint(0, len(ROUTES[route]) - 1)
            vessel, sim = _spawn_vessel(route, wp_idx)
            self.vessels[vessel.mmsi] = vessel
            self.state[vessel.mmsi] = sim

    def _designate_anomalies(self) -> None:
        """Mark a fraction of vessels as bad actors with assigned roles."""
        roles = ["teleporter", "hypersonic", "ghost", "loiterer", "spoof_twin"]
        n_anomalous = max(8, int(SETTINGS.sim_anomaly_rate * len(self.vessels)))
        targets = random.sample(list(self.vessels.keys()), k=n_anomalous)
        for i, mmsi in enumerate(targets):
            role = roles[i % len(roles)]
            self.state[mmsi]["anomaly_role"] = role

            # Spawn a twin for spoofing role
            if role == "spoof_twin":
                victim = self.vessels[mmsi]
                # Place the twin on a far-away route
                far_routes = [r for r in ROUTES if r != self.state[mmsi]["route"]]
                twin_route = random.choice(far_routes)
                twin_vessel, twin_sim = _spawn_vessel(twin_route, 0)
                # Make the twin broadcast the same MMSI as the victim
                twin_synthetic_id = f"{victim.mmsi}#twin"
                twin_vessel.mmsi = victim.mmsi  # same broadcast identity, key collision
                twin_sim["twin_mmsi_of"] = victim.mmsi
                # Store under a synthetic internal key so we don't overwrite
                self.vessels[twin_synthetic_id] = twin_vessel
                self.state[twin_synthetic_id] = twin_sim

    # -- per-tick advancement ----------------------------------------------- #
    def tick(self) -> None:
        self.tick_count += 1
        dt_hours = SETTINGS.sim_tick_seconds / 3600.0
        for key, vessel in list(self.vessels.items()):
            sim = self.state[key]

            # Dark handling
            if vessel.is_dark and self.tick_count < sim["dark_until_tick"]:
                continue
            if vessel.is_dark and self.tick_count >= sim["dark_until_tick"]:
                vessel.is_dark = False
                # Reappear at a teleported location for ghost role
                if sim.get("anomaly_role") == "ghost":
                    new_lat = vessel.last_position.lat + random.uniform(-3.0, 3.0)
                    new_lon = vessel.last_position.lon + random.uniform(-3.0, 3.0)
                    new_pos = Position(
                        timestamp=datetime.now(timezone.utc),
                        lat=new_lat,
                        lon=new_lon,
                        speed_knots=sim["cruise"],
                        course=vessel.last_position.course,
                        heading=vessel.last_position.heading,
                    )
                    self._append_position(vessel, new_pos)
                    self.recent_anomaly_events.append({
                        "mmsi": vessel.mmsi, "role": "ghost", "tick": self.tick_count
                    })
                    continue

            # Normal movement toward next waypoint
            route_name = sim["route"]
            route = ROUTES[route_name]
            wp = route[sim["wp_index"]]
            cur_lon = vessel.last_position.lon
            cur_lat = vessel.last_position.lat
            to_wp_nm = haversine_nm(cur_lon, cur_lat, wp[0], wp[1])
            speed = sim["cruise"]

            # ---- inject anomaly behavior ---- #
            role = sim.get("anomaly_role")
            if role == "hypersonic" and random.random() < 0.25:
                speed = random.uniform(55.0, 95.0)
                self.recent_anomaly_events.append({
                    "mmsi": vessel.mmsi, "role": "hypersonic", "tick": self.tick_count
                })
            elif role == "teleporter" and random.random() < 0.10:
                # Jump 150-400 NM in a random direction
                jump_nm = random.uniform(150.0, 400.0)
                bearing = random.uniform(0, 360)
                new_lon, new_lat = destination(cur_lon, cur_lat, bearing, jump_nm)
                new_pos = Position(
                    timestamp=datetime.now(timezone.utc),
                    lat=new_lat, lon=new_lon,
                    speed_knots=sim["cruise"],
                    course=bearing,
                    heading=bearing,
                )
                self._append_position(vessel, new_pos)
                self.recent_anomaly_events.append({
                    "mmsi": vessel.mmsi, "role": "teleporter", "tick": self.tick_count
                })
                continue
            elif role == "ghost" and not vessel.is_dark and random.random() < 0.06:
                # Go dark for the equivalent of ~30 minutes
                ticks_dark = int(30 * 60 / SETTINGS.sim_tick_seconds)
                vessel.is_dark = True
                sim["dark_until_tick"] = self.tick_count + ticks_dark
                self.recent_anomaly_events.append({
                    "mmsi": vessel.mmsi, "role": "ghost_start", "tick": self.tick_count
                })
                continue
            elif role == "loiterer":
                # If inside a critical zone, slow to a near-stop
                for zone in CRITICAL_ZONES:
                    from app.data.critical_zones import point_in_zone
                    if point_in_zone(cur_lon, cur_lat, zone) and zone.category in ("cable", "chokepoint"):
                        speed = random.uniform(0.2, 1.2)
                        break

            step_nm = speed * dt_hours
            if step_nm >= to_wp_nm:
                # Reached waypoint
                new_lon, new_lat = wp[0], wp[1]
                sim["wp_index"] = (sim["wp_index"] + 1) % len(route)
                next_wp = route[sim["wp_index"]]
                new_course = bearing_deg(new_lon, new_lat, next_wp[0], next_wp[1])
            else:
                course = bearing_deg(cur_lon, cur_lat, wp[0], wp[1])
                new_lon, new_lat = destination(cur_lon, cur_lat, course, step_nm)
                new_course = course

            # Tiny jitter for realism
            new_course = (new_course + random.uniform(-1.5, 1.5)) % 360.0

            new_pos = Position(
                timestamp=datetime.now(timezone.utc),
                lat=new_lat,
                lon=new_lon,
                speed_knots=round(speed, 2),
                course=round(new_course, 2),
                heading=round(new_course, 2),
            )
            self._append_position(vessel, new_pos)

    def _append_position(self, vessel: Vessel, pos: Position) -> None:
        vessel.track.append(vessel.last_position)
        if len(vessel.track) > SETTINGS.track_length:
            vessel.track = vessel.track[-SETTINGS.track_length:]
        vessel.last_position = pos

    # -- API ---------------------------------------------------------------- #
    def all_vessels(self) -> list[Vessel]:
        """Return all vessels currently broadcasting (skip dark ones)."""
        return [v for v in self.vessels.values() if not v.is_dark]

    def all_vessels_including_dark(self) -> list[Vessel]:
        return list(self.vessels.values())
