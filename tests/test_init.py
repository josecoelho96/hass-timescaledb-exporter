"""Tests for integration setup and teardown."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.timescaledb_exporter.const import DOMAIN


@pytest.fixture
def config_entry(mock_config_data: dict) -> MockConfigEntry:
    """Create a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=mock_config_data,
        options={
            "batch_size": 50,
            "flush_interval": 1,
            "excluded_entity_globs": [],
            "excluded_domains": [],
            "retention_raw_days": 365,
            "retention_hourly_days": 730,
            "retention_daily_days": 0,
            "compression_after_days": 7,
        },
    )


async def test_setup_entry_success(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_pool: MagicMock,
) -> None:
    """Test successful setup of a config entry."""
    config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.timescaledb_exporter._create_pool",
            return_value=mock_pool,
        ),
        patch("custom_components.timescaledb_exporter.MigrationManager") as mock_migration_cls,
        patch("custom_components.timescaledb_exporter.apply_retention_policies") as mock_ret,
        patch("custom_components.timescaledb_exporter.apply_compression_policy") as mock_comp,
    ):
        mock_migration = AsyncMock()
        mock_migration.migrate = AsyncMock(return_value=0)
        mock_migration_cls.return_value = mock_migration
        mock_ret.return_value = None
        mock_comp.return_value = None

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data is not None
    mock_ret.assert_called_once()
    mock_comp.assert_called_once()


async def test_setup_entry_connection_failure(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Test setup fails gracefully when database is unreachable."""
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.timescaledb_exporter._create_pool",
        side_effect=OSError("Connection refused"),
    ):
        assert not await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_entry_migration_failure(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_pool: MagicMock,
) -> None:
    """Test setup fails gracefully when migration fails."""
    config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.timescaledb_exporter._create_pool",
            return_value=mock_pool,
        ),
        patch("custom_components.timescaledb_exporter.MigrationManager") as mock_migration_cls,
        patch("custom_components.timescaledb_exporter.apply_retention_policies"),
        patch("custom_components.timescaledb_exporter.apply_compression_policy"),
    ):
        mock_migration = AsyncMock()
        mock_migration.migrate = AsyncMock(side_effect=Exception("Migration failed"))
        mock_migration_cls.return_value = mock_migration

        assert not await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    # Pool should be closed on migration failure
    mock_pool.close.assert_called_once()


async def test_unload_entry(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_pool: MagicMock,
) -> None:
    """Test unloading a config entry cleans up resources."""
    config_entry.add_to_hass(hass)

    with (
        patch(
            "custom_components.timescaledb_exporter._create_pool",
            return_value=mock_pool,
        ),
        patch("custom_components.timescaledb_exporter.MigrationManager") as mock_migration_cls,
        patch("custom_components.timescaledb_exporter.apply_retention_policies"),
        patch("custom_components.timescaledb_exporter.apply_compression_policy"),
    ):
        mock_migration = AsyncMock()
        mock_migration.migrate = AsyncMock(return_value=0)
        mock_migration_cls.return_value = mock_migration

        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED

    # Unload
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.NOT_LOADED
    # Pool should be closed via async_on_unload callback
    mock_pool.close.assert_called()
