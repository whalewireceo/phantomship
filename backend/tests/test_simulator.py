"""Smoke tests for the simulator."""
from app.data.simulator import Simulator


def test_simulator_builds_fleet():
    sim = Simulator(vessel_count=20)
    # Allow extra entries for spoofing twins
    assert len(sim.vessels) >= 20
    for v in sim.vessels.values():
        assert -90 <= v.last_position.lat <= 90
        assert -180 <= v.last_position.lon <= 180


def test_simulator_ticks_advance_positions():
    sim = Simulator(vessel_count=10)
    snapshot = {k: (v.last_position.lat, v.last_position.lon) for k, v in sim.vessels.items()}
    for _ in range(3):
        sim.tick()
    moved = 0
    for k, v in sim.vessels.items():
        before = snapshot[k]
        after = (v.last_position.lat, v.last_position.lon)
        if before != after:
            moved += 1
    assert moved > 0


def test_simulator_emits_some_anomalies():
    sim = Simulator(vessel_count=80)
    # Many ticks raise the chance of emitting anomalies
    for _ in range(40):
        sim.tick()
    roles = {sim.state[mmsi].get("anomaly_role") for mmsi in sim.vessels}
    roles.discard(None)
    assert len(roles) > 0
