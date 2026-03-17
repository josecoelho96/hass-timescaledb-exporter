"""Integration tests against a real TimescaleDB instance.

These tests verify the full write path, schema creation, compression,
continuous aggregates, and retention policies.

Run with: pytest tests/ -m integration
Requires a running TimescaleDB instance (see docker-compose.yml).
"""

from __future__ import annotations

from datetime import UTC, datetime

import asyncpg
import pytest

from custom_components.timescaledb_exporter.db.migrations.manager import MigrationManager
from custom_components.timescaledb_exporter.db.writer import (
    StateChange,
    TimescaleExporter,
)

pytestmark = pytest.mark.integration


async def test_migrations_create_schema(db_pool: asyncpg.Pool) -> None:
    """Test that all migrations run successfully and create expected objects."""
    manager = MigrationManager(db_pool)
    count = await manager.migrate()
    assert count == 7  # V001 through V007

    # Verify the hypertable exists
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'ha_states'"
        )
        assert row is not None
        assert row["hypertable_name"] == "ha_states"

        # Verify entity metadata table
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM information_schema.tables "
            "WHERE table_name = 'ha_entity_metadata'"
        )
        assert row["cnt"] == 1


async def test_migrations_idempotent(db_pool: asyncpg.Pool) -> None:
    """Test that running migrations twice is safe (idempotent)."""
    manager = MigrationManager(db_pool)
    count1 = await manager.migrate()
    count2 = await manager.migrate()

    assert count1 == 7
    assert count2 == 0  # All already applied


async def test_schema_version_tracking(db_pool: asyncpg.Pool) -> None:
    """Test that migration versions are tracked correctly."""
    manager = MigrationManager(db_pool)
    await manager.migrate()

    version = await manager.get_current_version()
    assert version == 7

    applied = await manager.get_applied_versions()
    assert set(applied.keys()) == {1, 2, 3, 4, 5, 6, 7}


async def test_write_single_state(db_pool: asyncpg.Pool) -> None:
    """Test writing a single state change to TimescaleDB."""
    manager = MigrationManager(db_pool)
    await manager.migrate()

    now = datetime.now(UTC)
    exporter = TimescaleExporter(pool=db_pool, batch_size=10, flush_interval=60)

    sc = StateChange(
        time=now,
        entity_id="sensor.temperature_living_room",
        state="22.5",
        state_numeric=22.5,
        attributes={"unit_of_measurement": "°C", "friendly_name": "Living Room Temperature"},
        context_id="test_ctx_001",
    )
    exporter.enqueue(sc)
    await exporter._flush_queue()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ha_states WHERE entity_id = $1",
            "sensor.temperature_living_room",
        )
        assert row is not None
        assert row["state"] == "22.5"
        assert row["state_numeric"] == 22.5
        assert row["context_id"] == "test_ctx_001"


async def test_write_batch_states(db_pool: asyncpg.Pool) -> None:
    """Test batch writing multiple state changes."""
    manager = MigrationManager(db_pool)
    await manager.migrate()

    now = datetime.now(UTC)
    exporter = TimescaleExporter(pool=db_pool, batch_size=100, flush_interval=60)

    for i in range(50):
        sc = StateChange(
            time=now,
            entity_id=f"sensor.test_{i}",
            state=str(float(i)),
            state_numeric=float(i),
            attributes={"index": i},
            context_id=f"ctx_{i}",
        )
        exporter.enqueue(sc)

    await exporter._flush_queue()
    assert exporter.stats.total_writes == 50

    async with db_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM ha_states")
        assert count == 50


async def test_write_non_numeric_state(db_pool: asyncpg.Pool) -> None:
    """Test writing non-numeric states (binary sensors, switches)."""
    manager = MigrationManager(db_pool)
    await manager.migrate()

    now = datetime.now(UTC)
    exporter = TimescaleExporter(pool=db_pool, batch_size=10, flush_interval=60)

    sc = StateChange(
        time=now,
        entity_id="binary_sensor.front_door",
        state="on",
        state_numeric=None,
        attributes={"device_class": "door", "friendly_name": "Front Door"},
        context_id="test_ctx",
    )
    exporter.enqueue(sc)
    await exporter._flush_queue()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ha_states WHERE entity_id = $1",
            "binary_sensor.front_door",
        )
        assert row["state"] == "on"
        assert row["state_numeric"] is None


async def test_entity_metadata_upsert(db_pool: asyncpg.Pool) -> None:
    """Test that entity metadata is created and updated."""
    manager = MigrationManager(db_pool)
    await manager.migrate()

    now = datetime.now(UTC)
    exporter = TimescaleExporter(pool=db_pool, batch_size=10, flush_interval=60)

    sc = StateChange(
        time=now,
        entity_id="sensor.outdoor_temp",
        state="15.3",
        state_numeric=15.3,
        attributes={
            "unit_of_measurement": "°C",
            "device_class": "temperature",
            "friendly_name": "Outdoor Temperature",
        },
        context_id="ctx",
    )
    exporter.enqueue(sc)
    await exporter._flush_queue()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ha_entity_metadata WHERE entity_id = $1",
            "sensor.outdoor_temp",
        )
        assert row is not None
        assert row["domain"] == "sensor"
        assert row["friendly_name"] == "Outdoor Temperature"
        assert row["unit_of_measurement"] == "°C"
        assert row["device_class"] == "temperature"
        assert row["is_numeric"] is True


async def test_compression_policy_exists(db_pool: asyncpg.Pool) -> None:
    """Test that compression policy was created by migrations."""
    manager = MigrationManager(db_pool)
    await manager.migrate()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_compression'"
        )
        # Should have compression policies for ha_states + 5 aggregates
        assert len(rows) >= 6


async def test_continuous_aggregates_exist(db_pool: asyncpg.Pool) -> None:
    """Test that continuous aggregates were created."""
    manager = MigrationManager(db_pool)
    await manager.migrate()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT view_name FROM timescaledb_information.continuous_aggregates ORDER BY view_name"
        )
        names = {r["view_name"] for r in rows}
        assert "ha_states_5min" in names
        assert "ha_states_hourly" in names
        assert "ha_states_daily" in names
        assert "ha_state_changes_hourly" in names
        assert "ha_state_changes_daily" in names


async def test_retention_policy_exists(db_pool: asyncpg.Pool) -> None:
    """Test that retention policies were created."""
    manager = MigrationManager(db_pool)
    await manager.migrate()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention'"
        )
        # Should have retention policies for ha_states, ha_states_5min and ha_states_hourly
        assert len(rows) >= 3


async def test_indexes_exist(db_pool: asyncpg.Pool) -> None:
    """Test that custom indexes were created."""
    manager = MigrationManager(db_pool)
    await manager.migrate()

    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT indexname FROM pg_indexes WHERE tablename = 'ha_states'")
        index_names = {r["indexname"] for r in rows}
        assert "ix_ha_states_entity_time" in index_names
        assert "ix_ha_states_numeric" in index_names


async def test_exporter_start_stop_lifecycle(db_pool: asyncpg.Pool) -> None:
    """Test full exporter lifecycle: start, write, stop, verify."""
    manager = MigrationManager(db_pool)
    await manager.migrate()

    now = datetime.now(UTC)
    exporter = TimescaleExporter(pool=db_pool, batch_size=10, flush_interval=60)

    await exporter.start()

    for i in range(5):
        sc = StateChange(
            time=now,
            entity_id=f"sensor.lifecycle_{i}",
            state=str(float(i * 10)),
            state_numeric=float(i * 10),
            attributes={},
            context_id=f"lc_{i}",
        )
        exporter.enqueue(sc)

    await exporter.stop()

    # All 5 should have been flushed on stop
    assert exporter.stats.total_writes == 5

    async with db_pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM ha_states WHERE entity_id LIKE 'sensor.lifecycle_%'"
        )
        assert count == 5
