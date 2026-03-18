"""Sensor platform for TimescaleDB Exporter integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .db.writer import TimescaleExporter

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


@dataclass(frozen=True, kw_only=True)
class TimescaleDBSensorEntityDescription(SensorEntityDescription):
    """Describes a TimescaleDB Exporter sensor entity."""

    value_fn: Callable[[TimescaleExporter], Any]


SENSOR_DESCRIPTIONS: tuple[TimescaleDBSensorEntityDescription, ...] = (
    TimescaleDBSensorEntityDescription(
        key="total_writes",
        translation_key="total_writes",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:database-arrow-up",
        value_fn=lambda e: e.stats.total_writes,
    ),
    TimescaleDBSensorEntityDescription(
        key="total_errors",
        translation_key="total_errors",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:alert-circle",
        value_fn=lambda e: e.stats.total_errors,
    ),
    TimescaleDBSensorEntityDescription(
        key="total_retries",
        translation_key="total_retries",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:refresh",
        value_fn=lambda e: e.stats.total_retries,
    ),
    TimescaleDBSensorEntityDescription(
        key="total_dropped",
        translation_key="total_dropped",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:package-down",
        value_fn=lambda e: e.stats.total_dropped,
    ),
    TimescaleDBSensorEntityDescription(
        key="queue_size",
        translation_key="queue_size",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:tray-full",
        value_fn=lambda e: e.queue_size,
    ),
    TimescaleDBSensorEntityDescription(
        key="queue_high_watermark",
        translation_key="queue_high_watermark",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:waves-arrow-up",
        value_fn=lambda e: e.stats.queue_high_watermark,
    ),
    TimescaleDBSensorEntityDescription(
        key="last_flush_at",
        translation_key="last_flush_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda e: e.stats.last_flush_at,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up TimescaleDB Exporter sensors from a config entry."""
    entities: list[SensorEntity] = [TimescaleDBExporterStatusSensor(entry)]
    entities.extend(
        TimescaleDBStatsSensor(entry, description) for description in SENSOR_DESCRIPTIONS
    )
    async_add_entities(entities)


class _TimescaleDBSensorBase(SensorEntity):
    """Shared base for all TimescaleDB Exporter sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize common attributes."""
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="TimescaleDB Exporter",
            entry_type=DeviceEntryType.SERVICE,
        )


class TimescaleDBExporterStatusSensor(_TimescaleDBSensorBase):
    """Sensor showing the health status of the TimescaleDB exporter."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:database-export"

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the status sensor."""
        super().__init__(entry)
        self._attr_unique_id = f"{entry.entry_id}_status"
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

    async def async_update(self) -> None:
        """Update the last known error count for next poll comparison."""
        runtime = self._entry.runtime_data
        if runtime is not None:
            self._last_error_count = runtime.exporter.stats.total_errors


class TimescaleDBStatsSensor(_TimescaleDBSensorBase):
    """Sensor exposing a single exporter statistic."""

    entity_description: TimescaleDBSensorEntityDescription

    def __init__(
        self,
        entry: ConfigEntry,
        description: TimescaleDBSensorEntityDescription,
    ) -> None:
        """Initialize a stats sensor."""
        super().__init__(entry)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> int | float | datetime | None:
        """Return the current value of this statistic."""
        runtime = self._entry.runtime_data
        if runtime is None:
            return None
        return self.entity_description.value_fn(runtime.exporter)
