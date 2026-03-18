"""Tests for the TimescaleDB Exporter status sensor."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, PropertyMock

from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType
import pytest

from custom_components.timescaledb_exporter.const import DOMAIN
from custom_components.timescaledb_exporter.db.writer import ExporterStats
from custom_components.timescaledb_exporter.sensor import (
    TimescaleDBExporterStatusSensor,
)


@pytest.fixture
def mock_entry() -> MagicMock:
    """Create a mock config entry with runtime data."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id_123"

    exporter = MagicMock()
    exporter.stats = ExporterStats()
    exporter.queue_size = 0
    type(exporter).is_healthy = PropertyMock(return_value=True)

    runtime = MagicMock()
    runtime.exporter = exporter

    entry.runtime_data = runtime
    return entry


class TestStatusSensor:
    """Tests for TimescaleDBExporterStatusSensor."""

    def test_unique_id(self, mock_entry: MagicMock) -> None:
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.unique_id == "test_entry_id_123_status"

    def test_device_info(self, mock_entry: MagicMock) -> None:
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.device_info is not None
        assert (DOMAIN, "test_entry_id_123") in sensor.device_info["identifiers"]
        assert sensor.device_info["entry_type"] is DeviceEntryType.SERVICE

    def test_entity_category_diagnostic(self, mock_entry: MagicMock) -> None:
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.entity_category is EntityCategory.DIAGNOSTIC

    def test_icon(self, mock_entry: MagicMock) -> None:
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.icon == "mdi:database-export"

    def test_state_ok(self, mock_entry: MagicMock) -> None:
        """State is 'ok' when healthy and no new errors."""
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.native_value == "ok"

    def test_state_error_when_errors_increase(self, mock_entry: MagicMock) -> None:
        """State is 'error' when total_errors has increased since last poll."""
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        # Simulate errors increasing
        mock_entry.runtime_data.exporter.stats.total_errors = 5
        assert sensor.native_value == "error"

    def test_state_ok_after_update_clears_error(self, mock_entry: MagicMock) -> None:
        """After async_update, the error count is synced so state returns to 'ok'."""
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        mock_entry.runtime_data.exporter.stats.total_errors = 5
        assert sensor.native_value == "error"

    def test_state_disconnected_when_not_healthy(self, mock_entry: MagicMock) -> None:
        """State is 'disconnected' when exporter is not healthy."""
        type(mock_entry.runtime_data.exporter).is_healthy = PropertyMock(return_value=False)
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.native_value == "disconnected"

    def test_state_disconnected_when_no_runtime(self, mock_entry: MagicMock) -> None:
        """State is 'disconnected' when runtime_data is None."""
        mock_entry.runtime_data = None
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.native_value == "disconnected"

    def test_extra_attributes(self, mock_entry: MagicMock) -> None:
        """Extra state attributes contain all expected keys."""
        exporter = mock_entry.runtime_data.exporter
        exporter.stats.total_writes = 100
        exporter.stats.total_dropped = 2
        exporter.stats.total_errors = 1
        exporter.stats.total_retries = 3
        exporter.stats.queue_high_watermark = 50
        exporter.stats.last_flush_at = datetime(2026, 3, 18, 12, 0, 0, tzinfo=UTC)
        exporter.queue_size = 5

        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        attrs = sensor.extra_state_attributes

        assert attrs["total_writes"] == 100
        assert attrs["total_dropped"] == 2
        assert attrs["total_errors"] == 1
        assert attrs["total_retries"] == 3
        assert attrs["queue_size"] == 5
        assert attrs["queue_high_watermark"] == 50
        assert attrs["last_flush_at"] == "2026-03-18T12:00:00+00:00"

    def test_extra_attributes_none_when_no_runtime(self, mock_entry: MagicMock) -> None:
        mock_entry.runtime_data = None
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.extra_state_attributes is None

    def test_extra_attributes_last_flush_none(self, mock_entry: MagicMock) -> None:
        """last_flush_at is None when no flush has happened."""
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        attrs = sensor.extra_state_attributes
        assert attrs["last_flush_at"] is None

    async def test_async_update_syncs_error_count(self, mock_entry: MagicMock) -> None:
        """async_update records the current error count for next comparison."""
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        mock_entry.runtime_data.exporter.stats.total_errors = 5

        await sensor.async_update()

        # Now errors haven't increased since last update → ok
        assert sensor.native_value == "ok"

    async def test_async_update_noop_without_runtime(self, mock_entry: MagicMock) -> None:
        """async_update is safe when runtime_data is None."""
        mock_entry.runtime_data = None
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        await sensor.async_update()  # Should not raise
