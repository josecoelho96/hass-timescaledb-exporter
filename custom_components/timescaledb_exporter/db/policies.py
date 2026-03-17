"""Manage TimescaleDB compression and retention policies at runtime."""

from __future__ import annotations

from datetime import timedelta
import logging

import asyncpg

_LOGGER = logging.getLogger(__name__)

# Tables/views that support retention policies.
# Hourly and daily settings each apply to both numeric and state-change views.
_RETENTION_TARGETS: dict[str, list[str]] = {
    "raw": ["ha_states"],
    "5min": ["ha_states_5min"],
    "hourly": ["ha_states_hourly", "ha_state_changes_hourly"],
    "daily": ["ha_states_daily", "ha_state_changes_daily"],
}


async def apply_retention_policies(
    pool: asyncpg.Pool,
    *,
    retention_raw_days: int,
    retention_hourly_days: int,
    retention_daily_days: int,
) -> None:
    """Apply or remove retention policies based on the configured day values.

    A value of 0 means "keep forever" — the policy is removed if it exists.
    A value > 0 sets or updates the retention interval.
    The 5-minute aggregate follows the raw retention setting.
    Hourly/daily settings apply to both numeric and state-change views.
    """
    settings = {
        "raw": retention_raw_days,
        "5min": retention_raw_days,
        "hourly": retention_hourly_days,
        "daily": retention_daily_days,
    }

    async with pool.acquire() as conn:
        for key, days in settings.items():
            for table in _RETENTION_TARGETS[key]:
                if days > 0:
                    await _upsert_retention(conn, table, days)
                else:
                    await _remove_retention(conn, table)


async def apply_compression_policy(
    pool: asyncpg.Pool,
    *,
    compression_after_days: int,
) -> None:
    """Apply or update the compression policy on ha_states."""
    async with pool.acquire() as conn:
        # Remove existing policy first, then re-add with new interval
        await conn.execute("SELECT remove_compression_policy('ha_states', if_exists => TRUE)")
        await conn.execute(
            "SELECT add_compression_policy('ha_states', $1::interval, if_not_exists => TRUE)",
            timedelta(days=compression_after_days),
        )
        _LOGGER.info(
            "Compression policy updated: compress after %d days",
            compression_after_days,
        )


async def _upsert_retention(
    conn: asyncpg.Connection,
    table: str,
    days: int,
) -> None:
    """Set or update a retention policy on the given table."""
    # Remove first, then add — simplest way to "update" the interval
    await conn.execute(f"SELECT remove_retention_policy('{table}', if_exists => TRUE)")
    await conn.execute(
        f"SELECT add_retention_policy('{table}', $1::interval, if_not_exists => TRUE)",
        timedelta(days=days),
    )
    _LOGGER.info("Retention policy on %s: drop after %d days", table, days)


async def _remove_retention(
    conn: asyncpg.Connection,
    table: str,
) -> None:
    """Remove a retention policy (keep data forever)."""
    await conn.execute(f"SELECT remove_retention_policy('{table}', if_exists => TRUE)")
    _LOGGER.info("Retention policy on %s removed (keep forever)", table)
