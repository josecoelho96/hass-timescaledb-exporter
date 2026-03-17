"""Tests for the TimescaleDB buffered writer."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.timescaledb_exporter.db.writer import (
    StateChange,
    TimescaleExporter,
    parse_state_numeric,
)

# --- parse_state_numeric tests ---


class TestParseStateNumeric:
    """Tests for the parse_state_numeric function."""

    def test_numeric_integer(self) -> None:
        assert parse_state_numeric("42") == 42.0

    def test_numeric_float(self) -> None:
        assert parse_state_numeric("22.5") == 22.5

    def test_negative_numeric(self) -> None:
        assert parse_state_numeric("-3.14") == -3.14

    def test_zero(self) -> None:
        assert parse_state_numeric("0") == 0.0

    def test_non_numeric_on(self) -> None:
        assert parse_state_numeric("on") is None

    def test_non_numeric_off(self) -> None:
        assert parse_state_numeric("off") is None

    def test_non_numeric_home(self) -> None:
        assert parse_state_numeric("home") is None

    def test_unavailable(self) -> None:
        assert parse_state_numeric("unavailable") is None

    def test_unknown(self) -> None:
        assert parse_state_numeric("unknown") is None

    def test_none_state(self) -> None:
        assert parse_state_numeric(None) is None

    def test_empty_string(self) -> None:
        assert parse_state_numeric("") is None

    def test_special_none_string(self) -> None:
        assert parse_state_numeric("none") is None


# --- TimescaleExporter tests ---


def _make_state_change(
    entity_id: str = "sensor.temperature",
    state: str = "22.5",
    **kwargs,
) -> StateChange:
    """Create a StateChange for testing."""
    now = datetime.now(UTC)
    return StateChange(
        time=kwargs.get("time", now),
        entity_id=entity_id,
        state=state,
        state_numeric=parse_state_numeric(state),
        attributes=kwargs.get("attributes", {"unit_of_measurement": "°C"}),
        context_id=kwargs.get("context_id", "test_context"),
    )


class TestExporterFiltering:
    """Tests for entity exclusion filtering."""

    def test_exclude_domain(self) -> None:
        exporter = TimescaleExporter(
            pool=MagicMock(),
            excluded_domains=["automation", "script"],
        )
        assert exporter.is_excluded("automation.morning_routine") is True
        assert exporter.is_excluded("script.turn_on_lights") is True
        assert exporter.is_excluded("sensor.temperature") is False

    def test_exclude_entity_glob(self) -> None:
        exporter = TimescaleExporter(
            pool=MagicMock(),
            excluded_entity_globs=["sensor.weather_*", "binary_sensor.test_*"],
        )
        assert exporter.is_excluded("sensor.weather_temperature") is True
        assert exporter.is_excluded("sensor.weather_humidity") is True
        assert exporter.is_excluded("binary_sensor.test_motion") is True
        assert exporter.is_excluded("sensor.indoor_temperature") is False

    def test_no_exclusions(self) -> None:
        exporter = TimescaleExporter(pool=MagicMock())
        assert exporter.is_excluded("sensor.anything") is False

    def test_update_filters(self) -> None:
        exporter = TimescaleExporter(pool=MagicMock())
        assert exporter.is_excluded("automation.test") is False

        exporter.update_filters(excluded_domains=["automation"])
        assert exporter.is_excluded("automation.test") is True


class TestExporterQueue:
    """Tests for the write queue."""

    def test_enqueue_success(self) -> None:
        exporter = TimescaleExporter(pool=MagicMock(), max_queue_size=100)
        sc = _make_state_change()
        assert exporter.enqueue(sc) is True
        assert exporter.queue_size == 1

    def test_enqueue_full_queue_drops(self) -> None:
        exporter = TimescaleExporter(pool=MagicMock(), max_queue_size=1)
        sc1 = _make_state_change(entity_id="sensor.a")
        sc2 = _make_state_change(entity_id="sensor.b")

        assert exporter.enqueue(sc1) is True
        assert exporter.enqueue(sc2) is False
        assert exporter.stats.total_dropped == 1

    def test_queue_high_watermark(self) -> None:
        exporter = TimescaleExporter(pool=MagicMock(), max_queue_size=100)
        for i in range(5):
            exporter.enqueue(_make_state_change(entity_id=f"sensor.s{i}"))
        assert exporter.stats.queue_high_watermark == 5


class TestExporterFlush:
    """Tests for the flush mechanism."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.executemany = AsyncMock()
        mock_conn.execute = AsyncMock()

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        pool.acquire.return_value = ctx
        pool.close = AsyncMock()

        return pool

    async def test_flush_writes_batch(self, mock_pool: MagicMock) -> None:
        exporter = TimescaleExporter(pool=mock_pool, batch_size=10)

        for i in range(3):
            exporter.enqueue(_make_state_change(entity_id=f"sensor.s{i}"))

        await exporter._flush_queue()

        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        mock_conn.executemany.assert_called_once()
        call_args = mock_conn.executemany.call_args
        assert len(call_args.args) == 2  # SQL string + records list
        assert exporter.stats.total_writes == 3

    async def test_flush_empty_queue_noop(self, mock_pool: MagicMock) -> None:
        exporter = TimescaleExporter(pool=mock_pool)
        await exporter._flush_queue()
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        mock_conn.executemany.assert_not_called()

    async def test_start_stop(self, mock_pool: MagicMock) -> None:
        exporter = TimescaleExporter(pool=mock_pool, batch_size=10, flush_interval=60)

        exporter.enqueue(_make_state_change())

        await exporter.start()
        assert exporter._running is True
        assert exporter._flush_task is not None

        await exporter.stop()
        assert exporter._running is False
        # Remaining items should be flushed on stop
        assert exporter.stats.total_writes == 1

    async def test_flush_error_increments_counter(self, mock_pool: MagicMock) -> None:
        mock_conn = mock_pool.acquire.return_value.__aenter__.return_value
        mock_conn.executemany.side_effect = Exception("DB error")

        exporter = TimescaleExporter(pool=mock_pool)
        exporter.enqueue(_make_state_change())

        await exporter._flush_queue()
        assert exporter.stats.total_errors == 1
        assert exporter.stats.total_writes == 0
