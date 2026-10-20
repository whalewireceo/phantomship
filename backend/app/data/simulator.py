"""AIS data simulator with deliberately injected anomalies.

The simulator is the default data source so the demo runs offline with no
API keys. It spawns a fleet of vessels that follow realistic shipping routes
at appropriate speeds, then periodically introduces known suspicious
behaviors:

  * Sustained impossible speeds (55+ knots, with the track moving to match)
  * Position teleportation (jumping 100+ NM in a single tick)
  * MMSI identity collisions (two vessels broadcasting the same MMSI)
  * Loitering in critical infrastructure zones
  * Dark activity (vessels disappearing then reappearing far away)

Detectors operate against the resulting position stream exactly as they
would against a real AIS feed.
"""
from __future__ import annotations

import random
from collections import deque
from datetime import datetime, timezone

from app.config import SETTINGS
from app.data.critical_zones import CRITICAL_ZONES, point_in_zone, zone_containing
from app.data.geo import bearing_deg, destination, haversine_nm, norm_deg
from app.data.mmsi import MID_TO_FLAG
from app.data.ports import port_area_at
from app.data.ship_routes import ROUTES
from app.models import Position, Vessel, VesselType


# Geo helpers live in app.data.geo; re-exported here for older imports.
__all__ = ["Simulator", "haversine_nm", "bearing_deg", "destination"]


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


_FLAG_TO_MIDS: dict[str, list[str]] = {}
for _mid, _flag in MID_TO_FLAG.items():
    _FLAG_TO_MIDS.setdefault(_flag, []).append(_mid)


def _make_mmsi(flag: str) -> str:
    """A well formed ship MMSI whose country code matches the flag, the way
    real ones do (live mode derives the flag from these digits)."""
    mid = random.choice(_FLAG_TO_MIDS.get(flag, ["351"]))
    return mid + "".join(random.choices("0123456789", k=6))


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

    flag = random.choice(_FLAGS)
    vessel = Vessel(
        mmsi=_make_mmsi(flag),
        name=_make_name(),
        vessel_type=vt,
        flag=flag,
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
        "burst_left": 0,             # remaining ticks of an impossible-speed burst
    }
    return vessel, sim_state


def _zone_waypoints() -> list[tuple[str, int]]:
    """Route waypoints inside a cable corridor or chokepoint, outside ports.
    Loiterers and ghosts start here so the demo actually exercises the
    loitering and dark activity detectors (most routes never enter a zone)."""
    out = []
    for name, pts in ROUTES.items():
        for i, (lon, lat) in enumerate(pts):
            z = zone_containing(lon, lat)
            if z and z.category in ("cable", "chokepoint") and port_area_at(lon, lat) is None:
                out.append((name, i))
    return out


_ZONE_WAYPOINTS = _zone_waypoints()


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
            if role in ("loiterer", "ghost") and _ZONE_WAYPOINTS:
                route, idx = random.choice(_ZONE_WAYPOINTS)
                placed, placed_sim = _spawn_vessel(route, idx)
                v = self.vessels[mmsi]
                v.last_position = placed.last_position
                self.state[mmsi].update(route=route, wp_index=placed_sim["wp_index"])
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
            if role == "hypersonic" and (sim["burst_left"] > 0 or random.random() < 0.05):
                # Sustained burst of impossible speed. The track moves at the
                # reported speed too, which is what separates a real (or
                # spoofed) speed claim from a broken speed sensor.
                if sim["burst_left"] <= 0:
                    sim["burst_left"] = random.randint(6, 12)
                    sim["burst_speed"] = random.uniform(55.0, 95.0)
                sim["burst_left"] -= 1
                speed = sim["burst_speed"]
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
                    course=norm_deg(bearing),
                    heading=norm_deg(bearing),
                )
                self._append_position(vessel, new_pos)
                self.recent_anomaly_events.append({
                    "mmsi": vessel.mmsi, "role": "teleporter", "tick": self.tick_count
                })
                continue
            elif (role == "ghost" and not vessel.is_dark and random.random() < 0.03
                  and zone_containing(cur_lon, cur_lat) is not None):
                # Go dark for ~45 minutes. (It used to be exactly 30, the same
                # as the detector threshold, so the alert only ever fired
                # when the scan loop happened to run slow.)
                ticks_dark = int(45 * 60 / SETTINGS.sim_tick_seconds)
                vessel.is_dark = True
                sim["dark_until_tick"] = self.tick_count + ticks_dark
                self.recent_anomaly_events.append({
                    "mmsi": vessel.mmsi, "role": "ghost_start", "tick": self.tick_count
                })
                continue
            elif role == "loiterer":
                # If inside a critical zone, slow to a near-stop
                for zone in CRITICAL_ZONES:
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

            # Tiny jitter for realism. Round first, then wrap: 359.996 rounds
            # to 360.0, which Position rejects, and used to crash the tick.
            new_course = norm_deg(round(new_course + random.uniform(-1.5, 1.5), 2))

            new_pos = Position(
                timestamp=datetime.now(timezone.utc),
                lat=new_lat,
                lon=new_lon,
                speed_knots=round(speed, 2),
                course=new_course,
                heading=new_course,
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

    def get(self, mmsi: str) -> Vessel | None:
        return self.vessels.get(mmsi)
