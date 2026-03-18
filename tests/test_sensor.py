"""Tests for the TimescaleDB Exporter sensor platform."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, PropertyMock

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceEntryType
import pytest

from custom_components.timescaledb_exporter.const import DOMAIN
from custom_components.timescaledb_exporter.db.writer import ExporterStats
from custom_components.timescaledb_exporter.sensor import (
    SENSOR_DESCRIPTIONS,
    TimescaleDBExporterStatusSensor,
    TimescaleDBStatsSensor,
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


# ---------------------------------------------------------------------------
# Status sensor
# ---------------------------------------------------------------------------


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
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.native_value == "ok"

    def test_state_error_when_errors_increase(self, mock_entry: MagicMock) -> None:
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        mock_entry.runtime_data.exporter.stats.total_errors = 5
        assert sensor.native_value == "error"

    def test_state_ok_after_update_clears_error(self, mock_entry: MagicMock) -> None:
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        mock_entry.runtime_data.exporter.stats.total_errors = 5
        assert sensor.native_value == "error"

    def test_state_disconnected_when_not_healthy(self, mock_entry: MagicMock) -> None:
        type(mock_entry.runtime_data.exporter).is_healthy = PropertyMock(return_value=False)
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.native_value == "disconnected"

    def test_state_disconnected_when_no_runtime(self, mock_entry: MagicMock) -> None:
        mock_entry.runtime_data = None
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        assert sensor.native_value == "disconnected"

    async def test_async_update_syncs_error_count(self, mock_entry: MagicMock) -> None:
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        mock_entry.runtime_data.exporter.stats.total_errors = 5
        await sensor.async_update()
        assert sensor.native_value == "ok"

    async def test_async_update_noop_without_runtime(self, mock_entry: MagicMock) -> None:
        mock_entry.runtime_data = None
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        await sensor.async_update()  # Should not raise

    def test_no_extra_state_attributes(self, mock_entry: MagicMock) -> None:
        """Status sensor should no longer expose extra_state_attributes."""
        sensor = TimescaleDBExporterStatusSensor(mock_entry)
        attrs = getattr(sensor, "extra_state_attributes", None)
        assert attrs is None


# ---------------------------------------------------------------------------
# Stats sensors (description-driven)
# ---------------------------------------------------------------------------


class TestStatsSensors:
    """Tests for TimescaleDBStatsSensor entities."""

    def test_all_descriptions_create_sensors(self, mock_entry: MagicMock) -> None:
        """Every description produces a valid sensor."""
        for desc in SENSOR_DESCRIPTIONS:
            sensor = TimescaleDBStatsSensor(mock_entry, desc)
            assert sensor.unique_id == f"test_entry_id_123_{desc.key}"
            assert sensor.entity_category is EntityCategory.DIAGNOSTIC
            assert sensor.has_entity_name is True

    def test_device_info_shared(self, mock_entry: MagicMock) -> None:
        """All stats sensors share the same device."""
        sensors = [TimescaleDBStatsSensor(mock_entry, d) for d in SENSOR_DESCRIPTIONS]
        device_ids = {tuple(sorted(s.device_info["identifiers"])) for s in sensors}
        assert len(device_ids) == 1

    # -- Counter sensors (TOTAL_INCREASING) --

    @pytest.mark.parametrize(
        "key", ["total_writes", "total_errors", "total_retries", "total_dropped"]
    )
    def test_counter_state_class(self, mock_entry: MagicMock, key: str) -> None:
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == key)
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.state_class is SensorStateClass.TOTAL_INCREASING

    def test_total_writes_value(self, mock_entry: MagicMock) -> None:
        mock_entry.runtime_data.exporter.stats.total_writes = 42
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "total_writes")
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.native_value == 42

    def test_total_errors_value(self, mock_entry: MagicMock) -> None:
        mock_entry.runtime_data.exporter.stats.total_errors = 7
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "total_errors")
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.native_value == 7

    def test_total_retries_value(self, mock_entry: MagicMock) -> None:
        mock_entry.runtime_data.exporter.stats.total_retries = 3
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "total_retries")
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.native_value == 3

    def test_total_dropped_value(self, mock_entry: MagicMock) -> None:
        mock_entry.runtime_data.exporter.stats.total_dropped = 10
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "total_dropped")
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.native_value == 10

    # -- Gauge sensors (MEASUREMENT) --

    @pytest.mark.parametrize("key", ["queue_size", "queue_high_watermark"])
    def test_gauge_state_class(self, mock_entry: MagicMock, key: str) -> None:
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == key)
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.state_class is SensorStateClass.MEASUREMENT

    def test_queue_size_value(self, mock_entry: MagicMock) -> None:
        mock_entry.runtime_data.exporter.queue_size = 15
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "queue_size")
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.native_value == 15

    def test_queue_high_watermark_value(self, mock_entry: MagicMock) -> None:
        mock_entry.runtime_data.exporter.stats.queue_high_watermark = 200
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "queue_high_watermark")
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.native_value == 200

    # -- Timestamp sensor --

    def test_last_flush_at_device_class(self, mock_entry: MagicMock) -> None:
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "last_flush_at")
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.device_class is SensorDeviceClass.TIMESTAMP

    def test_last_flush_at_value(self, mock_entry: MagicMock) -> None:
        ts = datetime(2026, 3, 18, 12, 0, 0, tzinfo=UTC)
        mock_entry.runtime_data.exporter.stats.last_flush_at = ts
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "last_flush_at")
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.native_value == ts

    def test_last_flush_at_none_before_first_flush(self, mock_entry: MagicMock) -> None:
        desc = next(d for d in SENSOR_DESCRIPTIONS if d.key == "last_flush_at")
        sensor = TimescaleDBStatsSensor(mock_entry, desc)
        assert sensor.native_value is None

    # -- No runtime --

    def test_value_none_when_no_runtime(self, mock_entry: MagicMock) -> None:
        mock_entry.runtime_data = None
        for desc in SENSOR_DESCRIPTIONS:
            sensor = TimescaleDBStatsSensor(mock_entry, desc)
            assert sensor.native_value is None, f"{desc.key} should be None without runtime"
