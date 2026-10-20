<div align="center">

![PhantomShip dashboard with 69 vessels, 7 active threats across 3 detectors, and an AI analyst write-up of the top critical incident](docs/screenshots/dashboard.png)
# PhantomShip

**Real-time maritime cyber-intelligence console — detects AIS spoofing, identity hijacks, dark-activity events, and behavioral anomalies across a live global vessel feed.**

[![ci](https://github.com/whalewireceo/phantomship/actions/workflows/ci.yml/badge.svg)](https://github.com/whalewireceo/phantomship/actions/workflows/ci.yml)
[![python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![typescript](https://img.shields.io/badge/typescript-5.6-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![license](https://img.shields.io/badge/license-MIT-00e5c0)](LICENSE)

</div>

---

## Overview

**PhantomShip** is a defensive cybersecurity tool that treats the global AIS (Automatic Identification System) stream as an adversarial data source. The AIS protocol is unauthenticated and unencrypted, which makes it routinely targeted for **GPS spoofing**, **identity hijack**, **dark-activity sanctions evasion**, and **seabed-cable reconnaissance**. PhantomShip ingests live vessel telemetry, runs it through a stack of rule-based and ML detectors, and surfaces threats on an interactive 3D globe alongside Claude-generated analyst write-ups.

Built as a self-contained portfolio project: clone, `docker compose up`, open `localhost:5173`. No API keys required to demo — a deterministic simulator with planted anomalies runs out of the box.

## What it does

- **Tracks** the live AIS feed via [AISStream.io](https://aisstream.io), or runs a high-fidelity offline simulator (default) so it demos cleanly with zero setup.
- **Detects** five distinct threat classes using a rule-based + ML detector stack.
- **Visualizes** 180+ live vessels on an interactive WebGL globe with auto-rotation, threat-graded color coding, and animated arcs for impossible-jump events.
- **Explains** each detection in plain English via the Anthropic API, with a deterministic fallback when no key is configured.
- **Ships** as one `docker compose` command with full CI on every commit.

## Detectors

| Detector | Threat class | Signature |
|---|---|---|
| **Kinematic** | GPS spoofing, AIS replay | Sustained speed above the vessel class envelope that the positions confirm; a jump of more than 80 NM in 10 min or less that persists on the next report |
| **Identity** | MMSI hijack (shadow fleet) | One MMSI broadcast from two places more than 30 NM apart, either as two records or as one track alternating between two positions |
| **Dark activity** | Sanctions evasion, cable interference | Regular reporter goes silent for more than 30 min inside a critical zone while other ships nearby are still heard |
| **Loitering** | Seabed reconnaissance, illicit STS transfers | Under 1.5 kn for 25 min or more inside a chokepoint or cable corridor, outside port areas |
| **ML anomaly** | Novel / multivariate behavior | Isolation Forest that learns its baseline from the fleet under way in the current feed and flags persistent outliers |

Seven monitored zones ship with the project: **Baltic cable corridor · Bab-el-Mandeb · Strait of Malacca · Suez approaches · Strait of Hormuz · Taiwan Strait · UK–Ireland cable approaches**. All zones are point-in-polygon tested via ray casting; geofences are user-extensible in `backend/app/data/critical_zones.py`.

## Running against live AIS

Set `PHANTOMSHIP_DATA_SOURCE=live` and `AISSTREAM_API_KEY` in `.env`. Real AIS is far noisier than the simulator, and the first live runs of this project produced thousands of false alerts. The current version handles those cases explicitly, and counts what it filtered under `data_quality` in `/api/stats`:

- **Reserved values.** Speed 102.3, course 360, heading 511, latitude 91 and longitude 181 mean "not available" and are stored as missing, never as readings.
- **Broken positions.** Reports at exactly 0,0, fixes marked as manual input, dead reckoning or inoperative, and reports flagged invalid are dropped. A single corrupted fix that jumps out and straight back is counted as a glitch, not a teleport.
- **Broken speed sensors.** A ship reporting 70 knots while its positions barely move is a sensor fault. Speed alerts need the track to confirm the speed.
- **Shared and default MMSIs.** Numbers like 0 and 123456789 are used by many unrelated transmitters at once and are dropped at ingest. A valid MMSI heard from two places in alternation is reported as two transmitters on one identity.
- **Coverage gaps.** Ships sail out of receiver range constantly. Dark activity only counts when other ships near the last position are still being received.
- **Ports.** Ports and anchorages inside the watch zones (Singapore, Port Said, Stockholm and others) are excluded from loitering and dark activity, as are moored ships, tugs and harbour craft.
- **Repeat detections.** A persistent condition updates one alert (`occurrences`, `last_seen_at`) instead of raising a new one every scan. Alerts expire 30 minutes after the condition was last seen.
- **ML baseline.** The model learns from the ships it is watching, skips stationary ships and classes that move erratically by design (tugs, pilot boats, fishing and leisure craft, fast ferries), and only alerts when a vessel is more unusual than 99.8% of its own baseline in 3 of 5 checks. The dashboard shows `ML BASELINE: LEARNING` until it has enough samples, then `ACTIVE`.
- **Sparse reporting.** The free feed delivers roughly one report per ship every few minutes, so every time window is judged by implied speed and report count rather than fixed short intervals.

### Validating against real traffic

`backend/tools/record_ais.py` records raw AISStream messages to a file, and `backend/tools/replay_ais.py` replays a recording through the full detector stack on a simulated clock. An 11 minute recording of 17,000 live ships produced 9 low severity ML alerts and no rule based alerts after these changes; the first version produced over 3,000 alerts in 10 minutes on the same kind of traffic.

```bash
cd backend
AISSTREAM_API_KEY=... python tools/record_ais.py 600 ../findings/raw.jsonl
python tools/replay_ais.py ../findings/raw.jsonl
```

### Known limitations

- Watch zones are coarse illustrative boxes, and the port list is approximate.
- AIS status fields are self reported. A ship can claim to be moored or anchored when it is not.
- Coverage from free terrestrial AIS is uneven. Areas with few receivers will under report dark activity by design.
- Speed envelopes are per class, and AIS ship types are often missing or wrong, so an unknown fast craft gets a generous limit.
- Isolation Forest does not extrapolate: a vessel that is extreme on one feature alone (for example a steady 30 knots) can score as normal. The rule based detectors cover those cases.
- The findings log rotates at `PHANTOMSHIP_FINDINGS_MAX_MB` and keeps one previous file.

## Architecture

```
        ┌──────────────────────┐         ┌──────────────────────────────┐
        │  AISStream.io        │ ───────►│  Live ingest (WebSocket)     │
        │   ─ or ─             │         │                              │
        │  Offline simulator   │ ───────►│  Position normalization      │
        └──────────────────────┘         └────────────┬─────────────────┘
                                                      ▼
                                         ┌──────────────────────────────┐
                                         │  Detector stack              │
                                         │  · Kinematic                 │
                                         │  · Identity (MMSI collision) │
                                         │  · Dark activity             │
                                         │  · Loitering                 │
                                         │  · Isolation Forest          │
                                         └────────────┬─────────────────┘
                                                      ▼
                                         ┌──────────────────────────────┐
                                         │  State engine                │
                                         │  · Alert episodes (cap 500)  │
                                         │  · Per-vessel score grading  │
                                         └────────────┬─────────────────┘
                                                      ▼
                          ┌───────────────────────────┴───────────────────────────┐
                          ▼                                                       ▼
                ┌────────────────────┐                                  ┌────────────────────┐
                │ FastAPI REST       │                                  │ Anthropic API      │
                │ /vessels, /threats │                                  │ Claude analyst     │
                │ /zones, /stats     │                                  │ (cached per threat)│
                └─────────┬──────────┘                                  └─────────┬──────────┘
                          ▼                                                       ▼
                ┌────────────────────────────────────────────────────────────────────┐
                │  React + TypeScript + Vite                                         │
                │  · 3D globe (react-globe.gl, Three.js)                             │
                │  · Live alert feed, vessel intel panel, AI report                  │
                └────────────────────────────────────────────────────────────────────┘
```

## Tech stack

**Backend** — Python 3.12 · FastAPI · Pydantic v2 · scikit-learn (Isolation Forest) · NumPy · httpx · websockets · asyncio
**Frontend** — React 18 · TypeScript 5.6 · Vite · Tailwind CSS · react-globe.gl · Three.js
**Infra** — Docker · docker-compose · Nginx (SPA + API proxy) · GitHub Actions CI

## Quick start

### One command (recommended)

```bash
git clone https://github.com/whalewireceo/phantomship.git
cd phantomship
docker compose up --build
```

Open **[http://localhost:5173](http://localhost:5173)**. The simulator fleet boots immediately and the first threats fire within seconds. Ports are bound to `127.0.0.1`, so the dashboard and API are only reachable from your own machine.

### Manual / dev mode

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173`. API docs are auto-generated at `http://localhost:8000/docs`.

## Configuration

All settings are environment variables; defaults make the app run with zero setup.

| Variable | Default | Description |
|---|---|---|
| `PHANTOMSHIP_DATA_SOURCE` | `simulator` | `simulator` or `live` |
| `PHANTOMSHIP_SIM_VESSELS` | `180` | Vessel count in simulator mode |
| `PHANTOMSHIP_SIM_ANOMALY_RATE` | `0.08` | Fraction of fleet designated as bad actors |
| `PHANTOMSHIP_SIM_TICK` | `2.0` | Tick interval in seconds |
| `AISSTREAM_API_KEY` | _(none)_ | Free key from [aisstream.io](https://aisstream.io); enables `live` mode |
| `ANTHROPIC_API_KEY` | _(none)_ | Enables AI analyst; falls back to a deterministic assessment when absent |
| `ANTHROPIC_MODEL` | `claude-haiku-5-5` | Model used for the analyst write-ups |
| `PHANTOMSHIP_AI_MAX_CALLS_PER_MINUTE` | `10` | Cap on Claude calls, so a shared deployment cannot drain the key |
| `PHANTOMSHIP_LIVE_STALE_MINUTES` | `30` | Live vessels silent this long leave the active picture |
| `PHANTOMSHIP_LIVE_EVICT_HOURS` | `6` | Live vessels silent this long are dropped from memory |
| `PHANTOMSHIP_ML_MIN_SAMPLES` | `400` | Baseline samples needed before the ML detector starts alerting |
| `PHANTOMSHIP_FINDINGS_MAX_MB` | `100` | Size at which `findings/findings.jsonl` rotates |

Copy `.env.example` to `.env` and edit, or export inline.

## API reference

The backend exposes a small REST surface; all responses are JSON.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness probe |
| `GET` | `/api/stats` | Counts, mode, uptime, severity breakdown, ML status, data quality, live feed status |
| `GET` | `/api/vessels` | Current fleet snapshot (`?limit=N` keeps flagged vessels first) |
| `GET` | `/api/threats` | Active threats (filterable by `severity` and `detector`) |
| `GET` | `/api/threats/{id}` | Threat detail + vessel track |
| `POST` | `/api/threats/{id}/analysis` | Run the AI analyst (or rule based fallback); result cached on the threat, rate limited |
| `GET` | `/api/zones` | Critical-zone polygons for the globe overlay |

Full OpenAPI / Swagger UI at `/docs`.

## Testing

```bash
cd backend && pytest -v
```

The suite covers every detector, live ingest decoding, alert episodes, the ML baseline, the simulator and the API. Several tests replay real patterns recorded from the live feed (a cable ship with a broken speed sensor, a flipped latitude, one MMSI heard from two countries). CI runs them on every push.

## Roadmap

- WebSocket streaming on the client side for sub-second updates
- SAR / optical satellite imagery overlay on selected vessels
- OFAC / EU sanctions list cross-reference on threat detail
- Persistent threat log (SQLite) for historical analysis
- Geographic clustering for high-density port views

## Why I built this

AIS spoofing is having a real moment — Russian shadow-fleet tankers evading sanctions, undersea-cable incidents in the Baltic, GPS jamming in contested waters. Commercial maritime-cyber platforms (Windward, Spire, Pole Star) charge enterprise pricing for the kind of picture this project assembles in a few hundred lines of code. PhantomShip is a from-scratch demonstration that the core detection logic — and a polished operator-grade UI on top of it — is accessible to a single developer working with public AIS data and modern open-source ML.

## License

[MIT](LICENSE) — feel free to fork, adapt, or extend.
