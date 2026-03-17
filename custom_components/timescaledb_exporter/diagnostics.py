"""Diagnostics support for TimescaleDB Exporter."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import TimescaleDBExporterConfigEntry

REDACT_KEYS = {CONF_PASSWORD, CONF_USERNAME}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: TimescaleDBExporterConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    exporter = runtime.exporter
    pool = runtime.pool

    # Gather database stats (best-effort)
    db_info: dict[str, Any] = {}
    try:
        async with pool.acquire() as conn:
            # Schema version
            row = await conn.fetchrow(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            )
            db_info["schema_version"] = row["version"] if row else 0

            # Database size
            row = await conn.fetchrow("SELECT pg_database_size(current_database()) AS size")
            db_info["database_size_bytes"] = row["size"] if row else None

            # Hypertable info
            rows = await conn.fetch("""
                SELECT hypertable_name, num_chunks, compression_enabled
                FROM timescaledb_information.hypertables
                WHERE hypertable_schema = 'public'
            """)
            db_info["hypertables"] = [dict(r) for r in rows]

            # Compression stats
            rows = await conn.fetch("""
                SELECT
                    hypertable_name,
                    COUNT(*) AS compressed_chunks,
                    SUM(before_compression_total_bytes) AS before_bytes,
                    SUM(after_compression_total_bytes) AS after_bytes
                FROM timescaledb_information.compressed_chunk_stats
                GROUP BY hypertable_name
            """)
            db_info["compression_stats"] = [dict(r) for r in rows]

            # Entity count
            row = await conn.fetchrow("SELECT COUNT(*) AS count FROM ha_entity_metadata")
            db_info["tracked_entities"] = row["count"] if row else 0

    except Exception as err:
        db_info["error"] = str(err)

    return {
        "config_entry": async_redact_data(dict(entry.data), REDACT_KEYS),
        "options": dict(entry.options),
        "exporter": {
            "queue_size": exporter.queue_size,
            "total_writes": exporter.stats.total_writes,
            "total_dropped": exporter.stats.total_dropped,
            "total_errors": exporter.stats.total_errors,
            "queue_high_watermark": exporter.stats.queue_high_watermark,
            "last_flush_at": (
                exporter.stats.last_flush_at.isoformat() if exporter.stats.last_flush_at else None
            ),
        },
        "database": db_info,
        "pool": {
            "size": pool.get_size(),
            "free_size": pool.get_idle_size(),
            "min_size": pool.get_min_size(),
            "max_size": pool.get_max_size(),
        },
    }
