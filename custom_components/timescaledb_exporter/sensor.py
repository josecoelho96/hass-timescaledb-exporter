"""Sensor platform for TimescaleDB Exporter integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up TimescaleDB Exporter sensors from a config entry."""
    async_add_entities([TimescaleDBExporterStatusSensor(entry)])


class TimescaleDBExporterStatusSensor(SensorEntity):
    """Sensor showing the health status of the TimescaleDB exporter."""

    _attr_has_entity_name = True
    _attr_translation_key = "status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:database-export"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_status"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="TimescaleDB Exporter",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._last_error_count = 0

    @property
    def native_value(self) -> str:
        """Return the current status."""
        runtime = self._entry.runtime_data
        if runtime is None:
            return "disconnected"

        exporter = runtime.exporter
        if not exporter.is_healthy:
            return "disconnected"

        current_errors = exporter.stats.total_errors
        if current_errors > self._last_error_count:
            return "error"

        return "ok"

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Return detailed exporter statistics."""
        runtime = self._entry.runtime_data
        if runtime is None:
            return None

        exporter = runtime.exporter
        stats = exporter.stats
        return {
            "total_writes": stats.total_writes,
            "total_dropped": stats.total_dropped,
            "total_errors": stats.total_errors,
            "total_retries": stats.total_retries,
            "queue_size": exporter.queue_size,
            "queue_high_watermark": stats.queue_high_watermark,
            "last_flush_at": (stats.last_flush_at.isoformat() if stats.last_flush_at else None),
        }

    async def async_update(self) -> None:
        """Update the last known error count for next poll comparison."""
        runtime = self._entry.runtime_data
        if runtime is not None:
            self._last_error_count = runtime.exporter.stats.total_errors
