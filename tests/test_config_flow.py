"""Tests for TimescaleDB Exporter config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.timescaledb_exporter.config_flow import TimescaleDBNotInstalled
from custom_components.timescaledb_exporter.const import DOMAIN


async def test_flow_user_shows_form(hass: HomeAssistant) -> None:
    """Test that the user step shows the connection form."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_flow_user_creates_entry(hass: HomeAssistant, mock_config_data: dict) -> None:
    """Test a successful user flow creates a config entry."""
    with (
        patch(
            "custom_components.timescaledb_exporter.config_flow.validate_connection",
            return_value=None,
        ),
        patch(
            "custom_components.timescaledb_exporter.async_setup_entry",
            return_value=True,
        ) as mock_setup,
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=mock_config_data,
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "TimescaleDB (localhost)"
    assert result["data"]["host"] == "localhost"
    assert result["data"]["port"] == 5432
    assert result["data"]["database"] == "homeassistant"
    assert mock_setup.called


async def test_flow_user_connection_error(hass: HomeAssistant, mock_config_data: dict) -> None:
    """Test we show an error when connection fails."""
    with patch(
        "custom_components.timescaledb_exporter.config_flow.validate_connection",
        side_effect=OSError("Connection refused"),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=mock_config_data,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_flow_user_timescaledb_not_installed(
    hass: HomeAssistant, mock_config_data: dict
) -> None:
    """Test we show an error when TimescaleDB extension is missing."""
    with patch(
        "custom_components.timescaledb_exporter.config_flow.validate_connection",
        side_effect=TimescaleDBNotInstalled(),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=mock_config_data,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "timescaledb_not_installed"}


async def test_flow_user_unknown_error(hass: HomeAssistant, mock_config_data: dict) -> None:
    """Test we show a generic error on unexpected exceptions."""
    with patch(
        "custom_components.timescaledb_exporter.config_flow.validate_connection",
        side_effect=RuntimeError("Something went wrong"),
    ):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input=mock_config_data,
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_flow_user_duplicate_aborts(hass: HomeAssistant, mock_config_data: dict) -> None:
    """Test that configuring a second instance aborts (single_config_entry)."""
    existing_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="localhost:5432/homeassistant",
        data=mock_config_data,
    )
    existing_entry.add_to_hass(hass)

    with patch(
        "custom_components.timescaledb_exporter.async_setup_entry",
        return_value=True,
    ):
        await hass.config_entries.async_setup(existing_entry.entry_id)
        await hass.async_block_till_done()

    # With single_config_entry=true, HA aborts at flow init
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow_shows_form(hass: HomeAssistant, mock_config_data: dict) -> None:
    """Test the options flow shows the form with current values."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=mock_config_data,
        options={
            "batch_size": 100,
            "flush_interval": 5,
            "excluded_entity_globs": ["sensor.weather_*"],
            "excluded_domains": ["automation", "script"],
        },
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.timescaledb_exporter.async_setup_entry",
        return_value=True,
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_saves_data(hass: HomeAssistant, mock_config_data: dict) -> None:
    """Test the options flow saves updated values."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data=mock_config_data,
        options={},
    )
    config_entry.add_to_hass(hass)

    with patch(
        "custom_components.timescaledb_exporter.async_setup_entry",
        return_value=True,
    ):
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "batch_size": 200,
            "flush_interval": 10,
            "excluded_entity_globs": "sensor.weather_*\nbinary_sensor.test_*",
            "excluded_domains": "automation,script",
            "compression_after_days": 14,
            "retention_raw_days": 180,
            "retention_hourly_days": 365,
            "retention_daily_days": 0,
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["batch_size"] == 200
    assert result["data"]["flush_interval"] == 10
    assert result["data"]["excluded_entity_globs"] == [
        "sensor.weather_*",
        "binary_sensor.test_*",
    ]
    assert result["data"]["excluded_domains"] == ["automation", "script"]
    assert result["data"]["compression_after_days"] == 14
    assert result["data"]["retention_raw_days"] == 180
