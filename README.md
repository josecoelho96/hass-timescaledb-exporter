# Home Assistant TimescaleDB Exporter

[![CI](https://github.com/jcoelho/hass-timescaledb-exporter/actions/workflows/ci.yml/badge.svg)](https://github.com/jcoelho/hass-timescaledb-exporter/actions/workflows/ci.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

A Home Assistant custom integration that exports **all state changes** to [TimescaleDB](https://www.timescale.com/) for long-term storage, analytics, and visualization.

## Features

- **Real-time export** — Listens to all `EVENT_STATE_CHANGED` events and writes to TimescaleDB
- **Buffered batch writes** — Uses an async queue with `executemany` for efficient throughput
- **Connection recovery** — Automatic retry with exponential backoff on transient database errors
- **Automatic schema management** — 7 versioned SQL migrations create hypertables, indexes, compression, continuous aggregates, and retention policies
- **TimescaleDB-native features**:
  - **Hypertables** with configurable chunk intervals
  - **Compression** (90%+ storage reduction) with `segmentby=entity_id, orderby=time DESC`
  - **Continuous aggregates** — hierarchical 5-min → hourly → daily pre-computed statistics (avg, min, max, count, first, last) plus hourly/daily state change counts
  - **Retention policies** — automatically drop old raw data while preserving aggregated summaries
- **Dual-column state storage** — `state` (TEXT) + `state_numeric` (FLOAT) for efficient aggregation without query-time casting
- **Entity metadata tracking** — domain, friendly name, unit, device class
- **Configurable exclusions** — exclude entities by glob pattern or entire domains
- **Diagnostic sensors** — 8 individual entities (status, total writes/errors/retries/dropped, queue size, queue high watermark, last flush) with proper `state_class` for HA long-term statistics
- **UI-based configuration** — full Config Flow + Options Flow, no YAML needed
- **Diagnostics** — connection status, queue depth, write stats, database size, compression ratios

## Requirements

- Home Assistant 2024.1.0 or later
- TimescaleDB 2.13+ (PostgreSQL 16 or 17 recommended)

## Installation

### HACS (Recommended)

1. Open HACS → Integrations → ⋮ (top right) → **Custom repositories**
2. Add `https://github.com/jcoelho/hass-timescaledb-exporter` with category **Integration**
3. Click **Install**
4. Restart Home Assistant

### Manual

1. Copy the `custom_components/timescaledb_exporter` directory to your `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **TimescaleDB Exporter**
3. Enter your database connection details:
   - **Host**: TimescaleDB server hostname
   - **Port**: PostgreSQL port (default: 5432)
   - **Database**: Database name (default: `homeassistant`)
   - **Username**: Database user
   - **Password**: Database password
   - **SSL**: Enable SSL connection

The integration will automatically run all database migrations on first setup.

### Options

After setup, click **Configure** on the integration to adjust:

| Option | Default | Description |
|--------|---------|-------------|
| Batch size | 50 | Number of records per write batch |
| Flush interval | 1s | How often to flush the write buffer |
| Excluded entity patterns | _(empty)_ | Glob patterns to exclude (one per line, e.g. `sensor.weather_*`) |
| Excluded domains | _(empty)_ | Domains to exclude (comma-separated, e.g. `automation,script`) |
| Compress after (days) | 7 | Compress data chunks older than N days |
| Keep raw data (days) | 365 | Drop raw data older than N days (0 = forever) |
| Keep hourly aggregates (days) | 730 | Retention for hourly summaries |
| Keep daily aggregates (days) | 0 | Retention for daily summaries (0 = forever) |

## Database Schema

### `ha_states` (Hypertable)

| Column | Type | Description |
|--------|------|-------------|
| `time` | TIMESTAMPTZ | Event timestamp |
| `entity_id` | TEXT | Entity ID (e.g., `sensor.temperature`) |
| `state` | TEXT | Raw state string |
| `state_numeric` | DOUBLE PRECISION | Parsed numeric value (NULL for non-numeric) |
| `attributes` | JSONB | Full attributes dict |
| `context_id` | TEXT | HA context ID |

### Continuous Aggregates

- **`ha_states_5min`** — 5-minute avg/min/max/count/first/last for numeric entities
- **`ha_states_hourly`** — Hourly rollup (hierarchical, built on 5-minute)
- **`ha_states_daily`** — Daily rollup (hierarchical, built on hourly)
- **`ha_state_changes_hourly`** — State change counts per entity per state per hour
- **`ha_state_changes_daily`** — Daily state change rollup (hierarchical, built on hourly)

### Example Queries

```sql
-- Last 24h of a sensor
SELECT time, state_numeric FROM ha_states
WHERE entity_id = 'sensor.temperature_living_room'
  AND time > NOW() - INTERVAL '24 hours'
ORDER BY time;

-- Daily averages for the last month
SELECT bucket, avg_value, min_value, max_value
FROM ha_states_daily
WHERE entity_id = 'sensor.outdoor_temperature'
  AND bucket > NOW() - INTERVAL '30 days'
ORDER BY bucket;

-- How long was a door open today?
SELECT state, COUNT(*) as transitions
FROM ha_state_changes_hourly
WHERE entity_id = 'binary_sensor.front_door'
  AND bucket >= CURRENT_DATE
GROUP BY state;

-- Gap-filled hourly data
SELECT
    time_bucket_gapfill('1 hour', bucket) AS hour,
    locf(avg(avg_value)) AS temperature
FROM ha_states_hourly
WHERE entity_id = 'sensor.temperature_living_room'
  AND bucket >= NOW() - INTERVAL '24 hours'
  AND bucket < NOW()
GROUP BY hour
ORDER BY hour;
```

## Grafana Dashboard

A pre-built Grafana dashboard is included in `grafana/dashboard.json`.

### Panels

- **Database Size** — total database size on disk
- **Tracked Entities** — count of unique entities seen
- **Compression Ratio** — storage savings from compression
- **Total State Changes (24h)** — event count over the last day
- **Entity State History** — raw numeric state values for a selected entity
- **Hourly Aggregates** — avg/min/max from continuous aggregates
- **State Change Rate** — events per hour bar chart
- **Top 20 Entities by Activity** — busiest entities in the last 24h
- **Chunk Overview** — TimescaleDB chunk status and compression

### Setup

1. Add a **PostgreSQL** data source in Grafana pointing to your TimescaleDB instance
2. Go to **Dashboards → Import → Upload JSON file**
3. Select `grafana/dashboard.json`
4. Choose your PostgreSQL data source when prompted

## Development

### Prerequisites

- Python 3.12+
- Docker & Docker Compose
- VS Code with Dev Containers extension (optional)

### Quick Start

```bash
# Clone the repository
git clone https://github.com/jcoelho/hass-timescaledb-exporter.git
cd hass-timescaledb-exporter

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install

# Start TimescaleDB for local development
docker compose up timescaledb -d

# Run unit tests
pytest tests/ -m "not integration" -vv

# Run integration tests (requires TimescaleDB running)
pytest tests/ -m integration -vv

# Run all tests
pytest tests/ -vv

# Lint
pre-commit run --all-files
```

### DevContainer

Open the repo in VS Code and select **Reopen in Container** when prompted. The devcontainer:
- Installs Python 3.12 with all dev dependencies in a virtual environment
- Has Docker-in-Docker for running TimescaleDB
- Forwards ports 8123 (HA) and 5432 (TimescaleDB)

### Manual Testing with Home Assistant

```bash
# Start the full stack (HA + TimescaleDB)
docker compose up -d

# Browse to http://localhost:8123
# Complete onboarding, then:
# Settings → Devices & Services → Add Integration → TimescaleDB Exporter
# Use host: timescaledb, port: 5432, database: homeassistant, user: postgres, password: postgres

# Connect to TimescaleDB directly to verify writes
docker exec -it timescaledb psql -U postgres -d homeassistant
# \dt                         -- list tables
# SELECT COUNT(*) FROM ha_states;
# SELECT * FROM ha_states ORDER BY time DESC LIMIT 10;
```

### Project Structure

```
hass-timescaledb-exporter/
├── custom_components/
│   └── timescaledb_exporter/
│       ├── __init__.py              # Integration setup/teardown
│       ├── config_flow.py           # UI config + options flow
│       ├── const.py                 # Constants and defaults
│       ├── diagnostics.py           # Debug diagnostics
│       ├── listener.py              # EVENT_STATE_CHANGED handler
│       ├── sensor.py                # Diagnostic sensor entities (8 sensors)
│       ├── manifest.json            # Integration metadata
│       ├── strings.json             # Translation strings
│       ├── translations/en.json     # English translations
│       └── db/
│           ├── __init__.py          # Package exports
│           ├── policies.py          # Runtime retention/compression policies
│           ├── writer.py            # Buffered batch writer
│           └── migrations/
│               ├── manager.py       # SQL migration runner
│               └── versions/        # V001-V007 SQL files
├── tests/
│   ├── conftest.py                  # Test fixtures
│   ├── test_config_flow.py          # Config flow tests
│   ├── test_writer.py               # Writer unit tests
│   ├── test_sensor.py               # Sensor entity tests
│   ├── test_listener.py             # Listener unit tests
│   ├── test_init.py                 # Setup/teardown tests
│   ├── test_migrations.py           # Migration manager tests
│   ├── test_policies.py             # Retention/compression policy tests
│   └── integration/                 # Real DB integration tests
├── .devcontainer/                   # VS Code devcontainer
├── .github/workflows/ci.yml        # CI: lint, test, validate
├── grafana/dashboard.json           # Pre-built Grafana dashboard
├── docker-compose.yml               # HA + TimescaleDB stack
├── pyproject.toml                   # Project config
├── hacs.json                        # HACS metadata
└── README.md
```

## License

MIT
