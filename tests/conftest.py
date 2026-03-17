"""Global fixtures for TimescaleDB Exporter tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir."""
    yield


@pytest.fixture
def mock_pool() -> MagicMock:
    """Return a mock asyncpg pool."""
    pool = MagicMock()
    pool.acquire = MagicMock()

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value={"installed": True})
    mock_conn.fetchval = AsyncMock()
    mock_conn.executemany = AsyncMock()
    mock_conn.copy_records_to_table = AsyncMock()
    mock_conn.close = AsyncMock()

    # Context manager for pool.acquire()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    pool.acquire.return_value = ctx

    pool.close = AsyncMock()
    pool.get_size = MagicMock(return_value=2)
    pool.get_idle_size = MagicMock(return_value=2)
    pool.get_min_size = MagicMock(return_value=2)
    pool.get_max_size = MagicMock(return_value=10)

    return pool


@pytest.fixture
def mock_conn(mock_pool: MagicMock) -> AsyncMock:
    """Return the mock connection from the mock pool."""
    ctx = mock_pool.acquire.return_value
    return ctx.__aenter__.return_value


@pytest.fixture
def mock_config_data() -> dict:
    """Return standard config entry data for tests."""
    return {
        "host": "localhost",
        "port": 5432,
        "database": "homeassistant",
        "username": "postgres",
        "password": "postgres",
        "ssl": False,
    }


@pytest.fixture
def mock_options() -> dict:
    """Return standard options for tests."""
    return {
        "batch_size": 50,
        "flush_interval": 1,
        "excluded_entity_globs": [],
        "excluded_domains": [],
        "compression_after_days": 7,
        "retention_raw_days": 365,
        "retention_hourly_days": 730,
        "retention_daily_days": 0,
    }
