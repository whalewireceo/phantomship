"""Shared helpers for building vessels and tracks in tests."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from app.config import SETTINGS
from app.models import Position, Vessel, VesselType

T0 = datetime(2026, 10, 19, 23, 0, 0, tzinfo=timezone.utc)


def pos(lat, lon, t=0.0, speed=12.0, course=90.0, **kw) -> Position:
    """Position at T0 + t seconds."""
    return Position(timestamp=T0 + timedelta(seconds=t), lat=lat, lon=lon,
                    speed_knots=speed, course=course, heading=course, **kw)


def vessel_from(points: list[Position], mmsi="244123456", name="MV TEST",
                vt=VesselType.CARGO, flag="NL", length=200) -> Vessel:
    return Vessel(mmsi=mmsi, name=name, vessel_type=vt, flag=flag, length_m=length,
                  destination="TEST", last_position=points[-1], track=list(points[:-1]))


@pytest.fixture
def settings_override(monkeypatch):
    """Replace SETTINGS in the given modules with a modified copy."""
    def apply(modules, **changes):
        new = dataclasses.replace(SETTINGS, **changes)
        for m in modules:
            monkeypatch.setattr(m, "SETTINGS", new)
        return new
    return apply
