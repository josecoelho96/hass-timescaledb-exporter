"""The TimescaleDB Exporter integration."""

from __future__ import annotations

import json
import logging

import asyncpg
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_BATCH_SIZE,
    CONF_COMPRESSION_AFTER_DAYS,
    CONF_DATABASE,
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITY_GLOBS,
    CONF_FLUSH_INTERVAL,
    CONF_RETENTION_DAILY_DAYS,
    CONF_RETENTION_HOURLY_DAYS,
    CONF_RETENTION_RAW_DAYS,
    CONF_SSL,
    DEFAULT_BATCH_SIZE,
    DEFAULT_COMPRESSION_AFTER_DAYS,
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_RETENTION_DAILY_DAYS,
    DEFAULT_RETENTION_HOURLY_DAYS,
    DEFAULT_RETENTION_RAW_DAYS,
    DOMAIN,  # noqa: F401 - used by HA integration loader
)
from .db import (
    MigrationManager,
    TimescaleExporter,
    apply_compression_policy,
    apply_retention_policies,
)
from .listener import async_setup_listener

_LOGGER = logging.getLogger(__name__)

type TimescaleDBExporterConfigEntry = ConfigEntry[TimescaleExporterRuntimeData]


class TimescaleExporterRuntimeData:
    """Runtime data stored on the config entry."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        exporter: TimescaleExporter,
    ) -> None:
        """Initialize runtime data."""
        self.pool = pool
        self.exporter = exporter


async def _create_pool(data: dict) -> asyncpg.Pool:
    """Create an asyncpg connection pool with JSONB codec support."""
    ssl_context: bool | str = "require" if data.get(CONF_SSL) else False

    async def init_connection(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            "jsonb",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )
        await conn.execute("SET timezone = 'UTC'")

    return await asyncpg.create_pool(
        host=data[CONF_HOST],
        port=int(data[CONF_PORT]),
        user=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        database=data[CONF_DATABASE],
        ssl=ssl_context,
        min_size=2,
        max_size=10,
        command_timeout=60,
        init=init_connection,
    )


async def async_setup_entry(hass: HomeAssistant, entry: TimescaleDBExporterConfigEntry) -> bool:
    """Set up TimescaleDB Exporter from a config entry."""
    # 1. Create connection pool
    try:
        pool = await _create_pool(entry.data)
    except (OSError, asyncpg.PostgresError, TimeoutError) as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to TimescaleDB at {entry.data[CONF_HOST]}: {err}"
        ) from err

    # 2. Run database migrations
    try:
        migration_manager = MigrationManager(pool)
        applied = await migration_manager.migrate()
        if applied:
            _LOGGER.info("Applied %d database migration(s)", applied)
    except Exception as err:
        await pool.close()
        raise ConfigEntryNotReady(f"Database migration failed: {err}") from err

    # 3. Apply retention and compression policies from options
    options = entry.options
    try:
        await apply_retention_policies(
            pool,
            retention_raw_days=options.get(CONF_RETENTION_RAW_DAYS, DEFAULT_RETENTION_RAW_DAYS),
            retention_hourly_days=options.get(
                CONF_RETENTION_HOURLY_DAYS, DEFAULT_RETENTION_HOURLY_DAYS
            ),
            retention_daily_days=options.get(
                CONF_RETENTION_DAILY_DAYS, DEFAULT_RETENTION_DAILY_DAYS
            ),
        )
        await apply_compression_policy(
            pool,
            compression_after_days=options.get(
                CONF_COMPRESSION_AFTER_DAYS, DEFAULT_COMPRESSION_AFTER_DAYS
            ),
        )
    except Exception:
        _LOGGER.warning("Failed to apply policies, using migration defaults", exc_info=True)

    # 4. Create the exporter
    exporter = TimescaleExporter(
        pool=pool,
        batch_size=options.get(CONF_BATCH_SIZE, DEFAULT_BATCH_SIZE),
        flush_interval=options.get(CONF_FLUSH_INTERVAL, DEFAULT_FLUSH_INTERVAL),
        excluded_entity_globs=options.get(CONF_EXCLUDED_ENTITY_GLOBS, []),
        excluded_domains=options.get(CONF_EXCLUDED_DOMAINS, []),
    )

    # 5. Start the exporter flush loop
    await exporter.start()

    # 6. Register the state change listener
    unsub_listener = async_setup_listener(hass, exporter)

    # 7. Store runtime data
    entry.runtime_data = TimescaleExporterRuntimeData(
        pool=pool,
        exporter=exporter,
    )

    # 8. Register cleanup
    async def _async_close_pool() -> None:
        await exporter.stop()
        await pool.close()

    entry.async_on_unload(unsub_listener)
    entry.async_on_unload(_async_close_pool)

    # 9. Listen for options updates
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    _LOGGER.info("TimescaleDB Exporter started successfully")
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: TimescaleDBExporterConfigEntry
) -> None:
    """Handle options update — update exporter filters and DB policies."""
    runtime: TimescaleExporterRuntimeData = entry.runtime_data
    options = entry.options

    # Update in-memory filters
    runtime.exporter.update_filters(
        excluded_entity_globs=options.get(CONF_EXCLUDED_ENTITY_GLOBS, []),
        excluded_domains=options.get(CONF_EXCLUDED_DOMAINS, []),
    )

    # Apply retention and compression policy changes to the database
    try:
        await apply_retention_policies(
            runtime.pool,
            retention_raw_days=options.get(CONF_RETENTION_RAW_DAYS, DEFAULT_RETENTION_RAW_DAYS),
            retention_hourly_days=options.get(
                CONF_RETENTION_HOURLY_DAYS, DEFAULT_RETENTION_HOURLY_DAYS
            ),
            retention_daily_days=options.get(
                CONF_RETENTION_DAILY_DAYS, DEFAULT_RETENTION_DAILY_DAYS
            ),
        )
        await apply_compression_policy(
            runtime.pool,
            compression_after_days=options.get(
                CONF_COMPRESSION_AFTER_DAYS, DEFAULT_COMPRESSION_AFTER_DAYS
            ),
        )
    except Exception:
        _LOGGER.exception("Failed to apply updated policies to TimescaleDB")

    _LOGGER.debug("Exporter options updated (filters + policies)")


async def async_unload_entry(hass: HomeAssistant, entry: TimescaleDBExporterConfigEntry) -> bool:
    """Unload a config entry."""
    # Cleanup callbacks registered via entry.async_on_unload() are called automatically
    _LOGGER.info("TimescaleDB Exporter unloaded")
    return True
