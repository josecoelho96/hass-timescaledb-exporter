"""Fixtures for integration tests requiring a real TimescaleDB instance."""

from __future__ import annotations

import json
import os

import asyncpg
import pytest
from pytest_socket import enable_socket


@pytest.fixture(autouse=True)
def socket_enabled():
    """Re-enable real sockets for integration tests.

    pytest-homeassistant-custom-component's pytest_runtest_setup hook calls
    disable_socket() on every test. This fixture runs after that hook and
    restores the real socket so integration tests can reach TimescaleDB.
    The fixture name 'socket_enabled' also tells pytest-socket's own hook
    to skip its restrictions.
    """
    enable_socket()
    yield


@pytest.fixture
def expected_lingering_timers() -> bool:
    """Allow lingering timers from asyncpg pool internals."""
    return True


@pytest.fixture(scope="session")
def timescaledb_dsn() -> str:
    """Build the DSN for the TimescaleDB test instance.

    Uses environment variables (set by CI or docker-compose) with sensible defaults
    for local development: localhost:5432/homeassistant.
    """
    host = os.environ.get("TIMESCALEDB_HOST", "127.0.0.1")
    port = os.environ.get("TIMESCALEDB_PORT", "5432")
    user = os.environ.get("TIMESCALEDB_USER", "postgres")
    password = os.environ.get("TIMESCALEDB_PASSWORD", "postgres")
    db = os.environ.get("TIMESCALEDB_DB", "homeassistant")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture
async def db_pool(timescaledb_dsn: str):
    """Create a real asyncpg pool connected to TimescaleDB.

    Cleans up test tables before and after each test.
    """

    async def init_conn(conn: asyncpg.Connection) -> None:
        await conn.set_type_codec(
            "jsonb",
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )

    pool = await asyncpg.create_pool(
        dsn=timescaledb_dsn,
        min_size=1,
        max_size=5,
        init=init_conn,
    )

    async def _clean_db(dsn: str) -> None:
        """Drop all test objects using a raw connection (no custom codecs)."""
        conn = await asyncpg.connect(dsn=dsn)
        try:
            # Disable scheduled background jobs to avoid deadlocks on DROP
            try:
                jobs = await conn.fetch(
                    "SELECT job_id FROM timescaledb_information.jobs "
                    "WHERE proc_schema = '_timescaledb_functions'"
                )
                for job in jobs:
                    await conn.execute(
                        "SELECT alter_job($1, scheduled => false)", job["job_id"]
                    )
            except (asyncpg.UndefinedTableError, asyncpg.UndefinedFunctionError):
                pass

            # Small delay to let any running job iteration finish
            await conn.execute("SELECT pg_sleep(0.2)")

            # Drop continuous aggregates top-down (CASCADE removes their policies)
            for view in (
                "ha_state_changes_daily",
                "ha_state_changes_hourly",
                "ha_states_daily",
                "ha_states_hourly",
                "ha_states_5min",
            ):
                await conn.execute(f"DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE")
            await conn.execute("DROP TABLE IF EXISTS ha_states CASCADE")
            await conn.execute("DROP TABLE IF EXISTS ha_entity_metadata CASCADE")
            await conn.execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
        finally:
            await conn.close()

    # Clean slate before test
    await _clean_db(timescaledb_dsn)

    yield pool

    # Cleanup after test
    await _clean_db(timescaledb_dsn)

    await pool.close()
    pool.terminate()
