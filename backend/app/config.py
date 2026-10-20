"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _f(name: str, default: str) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: str) -> int:
    return int(os.getenv(name, default))


@dataclass(frozen=True)
class Settings:
    # Data source mode: 'simulator' (default, no keys needed) or 'live' (AISStream.io).
    data_source: str = os.getenv("PHANTOMSHIP_DATA_SOURCE", "simulator").strip().lower()

    # AISStream.io API key, only used when data_source == 'live'.
    # Get a free key at https://aisstream.io
    aisstream_api_key: str = os.getenv("AISSTREAM_API_KEY", "").strip()

    # Anthropic API key for the AI Analyst feature. Optional; if blank we fall
    # back to a deterministic, rule-based assessment so the UI never breaks.
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "").strip()
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5").strip()
    # Cap on Claude calls per minute, so a public or shared deployment cannot
    # burn through the API key.
    ai_max_calls_per_minute: int = _i("PHANTOMSHIP_AI_MAX_CALLS_PER_MINUTE", "10")

    # Simulator parameters
    sim_vessel_count: int = _i("PHANTOMSHIP_SIM_VESSELS", "180")
    sim_anomaly_rate: float = _f("PHANTOMSHIP_SIM_ANOMALY_RATE", "0.08")
    sim_tick_seconds: float = _f("PHANTOMSHIP_SIM_TICK", "2.0")

    # Detector thresholds
    teleport_nm_threshold: float = 80.0       # minimum jump between consecutive reports (NM)
    loiter_speed_knots: float = 1.5
    loiter_minutes_threshold: float = 25.0
    dark_minutes_threshold: float = 30.0
    # Dark activity in live mode only counts when the area still has receiver
    # coverage: at least this many other vessels were heard nearby recently.
    dark_coverage_min_neighbors: int = 3
    dark_coverage_radius_nm: float = 25.0

    # Live feed housekeeping
    # A vessel that has not reported for this long is treated as silent and
    # leaves the active picture (this is what lets dark activity work live).
    live_stale_minutes: float = _f("PHANTOMSHIP_LIVE_STALE_MINUTES", "30")
    # Vessels silent for longer than this are dropped from memory entirely.
    live_evict_hours: float = _f("PHANTOMSHIP_LIVE_EVICT_HOURS", "6")

    # ML baseline: the model learns "normal" from the fleet it is watching
    # and stays quiet until it has seen enough of it.
    ml_min_samples: int = _i("PHANTOMSHIP_ML_MIN_SAMPLES", "400")
    ml_min_vessels: int = _i("PHANTOMSHIP_ML_MIN_VESSELS", "100")
    ml_sample_interval_s: float = _f("PHANTOMSHIP_ML_SAMPLE_INTERVAL", "60")
    ml_refit_seconds: float = _f("PHANTOMSHIP_ML_REFIT_SECONDS", "600")
    ml_contamination: float = _f("PHANTOMSHIP_ML_CONTAMINATION", "0.005")

    # Alert lifecycle: repeat detections of the same condition on the same
    # vessel merge into one alert while it stays active.
    threat_expire_minutes: float = 30.0
    threat_cap: int = 500

    # Findings recorder: every new alert (and every severity escalation) is
    # appended here as one JSON line, so detections survive restarts.
    findings_path: str = os.getenv("PHANTOMSHIP_FINDINGS_PATH", "findings/findings.jsonl")
    findings_max_mb: float = _f("PHANTOMSHIP_FINDINGS_MAX_MB", "100")

    # API
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000")

    # Track length: how many recent positions to keep per vessel
    track_length: int = 30


SETTINGS = Settings()
