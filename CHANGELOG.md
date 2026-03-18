# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-03-18

### Added

- **Real-time state export** — listens to `EVENT_STATE_CHANGED` and writes to TimescaleDB
- **Buffered batch writer** — async queue with `executemany` for efficient throughput
- **Connection recovery** — automatic retry with exponential backoff (3 retries, 1s → 2s → 4s)
- **7 SQL migrations** — hypertables, indexes, compression, continuous aggregates, retention policies
- **Continuous aggregates** — hierarchical 5-min → hourly → daily pre-computed statistics, plus hourly/daily state change counts
- **Compression** — 90%+ storage reduction with `segmentby=entity_id, orderby=time DESC`
- **Retention policies** — configurable per tier (raw, hourly, daily)
- **8 diagnostic sensor entities**:
  - Status (ok/error/disconnected)
  - Total writes, errors, retries, dropped (TOTAL_INCREASING counters)
  - Queue size, queue high watermark (MEASUREMENT gauges)
  - Last flush (TIMESTAMP)
- **Config Flow + Options Flow** — full UI-based configuration, no YAML
- **Configurable exclusions** — by entity glob pattern or domain
- **Diagnostics** — connection status, queue depth, write stats, database size, compression ratios
- **Pre-built Grafana dashboard** — 7 panels for monitoring
- **CI pipeline** — lint, unit tests, integration tests, hassfest, HACS validation
- **GitHub release workflow** — auto-creates releases on version tags
