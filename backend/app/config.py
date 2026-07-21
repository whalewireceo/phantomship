"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Data source mode: 'simulator' (default, no keys needed) or 'live' (AISStream.io).
    data_source: str = os.getenv("PHANTOMSHIP_DATA_SOURCE", "simulator")

    # AISStream.io API key — only used when data_source == 'live'.
    # Get a free key at https://aisstream.io
    aisstream_api_key: str = os.getenv("AISSTREAM_API_KEY", "")

    # Anthropic API key for the AI Analyst feature. Optional; if blank we fall
    # back to a deterministic, rule-based assessment so the UI never breaks.
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")

    # Simulator parameters
    sim_vessel_count: int = int(os.getenv("PHANTOMSHIP_SIM_VESSELS", "180"))
    sim_anomaly_rate: float = float(os.getenv("PHANTOMSHIP_SIM_ANOMALY_RATE", "0.08"))
    sim_tick_seconds: float = float(os.getenv("PHANTOMSHIP_SIM_TICK", "2.0"))

    # Detector thresholds
    max_realistic_speed_knots: float = 45.0   # cargo/tanker upper bound; small craft can exceed
    teleport_nm_threshold: float = 80.0       # nautical miles between consecutive reports
    teleport_minutes_threshold: float = 10.0  # time window for teleport detection
    loiter_speed_knots: float = 1.5
    loiter_minutes_threshold: float = 25.0
    dark_minutes_threshold: float = 30.0

    # API
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://localhost:3000")

    # Track length: how many recent positions to keep per vessel
    track_length: int = 30


SETTINGS = Settings()
