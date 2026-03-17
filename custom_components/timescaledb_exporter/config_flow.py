"""Config flow for TimescaleDB Exporter integration."""

from __future__ import annotations

import logging
from typing import Any

import asyncpg
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol

from .const import (
    CONF_BATCH_SIZE,
    CONF_CHUNK_INTERVAL_HOURS,
    CONF_COMPRESSION_AFTER_DAYS,
    CONF_DATABASE,
    CONF_EXCLUDED_DOMAINS,
    CONF_EXCLUDED_ENTITY_GLOBS,
    CONF_FLUSH_INTERVAL,
    CONF_RETENTION_DAILY_DAYS,
    CONF_RETENTION_HOURLY_DAYS,
    CONF_RETENTION_RAW_DAYS,
    CONF_SSL,
    DEFAULT_BATCH_SIZE,
    DEFAULT_COMPRESSION_AFTER_DAYS,
    DEFAULT_DATABASE,
    DEFAULT_FLUSH_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_RETENTION_DAILY_DAYS,
    DEFAULT_RETENTION_HOURLY_DAYS,
    DEFAULT_RETENTION_RAW_DAYS,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        vol.Required(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Required(CONF_DATABASE, default=DEFAULT_DATABASE): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_USERNAME): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_SSL, default=False): BooleanSelector(),
    }
)


async def validate_connection(data: dict[str, Any]) -> None:
    """Validate the user input allows us to connect and TimescaleDB is installed."""
    ssl_context: bool | str = "require" if data.get(CONF_SSL) else False
    conn = await asyncpg.connect(
        host=data[CONF_HOST],
        port=int(data[CONF_PORT]),
        user=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        database=data[CONF_DATABASE],
        ssl=ssl_context,
        timeout=10,
    )
    try:
        row = await conn.fetchrow(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') AS installed"
        )
        if not row or not row["installed"]:
            raise TimescaleDBNotInstalled
    finally:
        await conn.close()


class TimescaleDBNotInstalled(Exception):
    """Error raised when TimescaleDB extension is not found."""


class TimescaleDBExporterConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for TimescaleDB Exporter."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_PORT] = int(user_input[CONF_PORT])
            try:
                await validate_connection(user_input)
            except (OSError, asyncpg.PostgresError, TimeoutError):
                errors["base"] = "cannot_connect"
            except asyncpg.InvalidPasswordError:
                errors["base"] = "invalid_auth"
            except TimescaleDBNotInstalled:
                errors["base"] = "timescaledb_not_installed"
            except Exception:
                _LOGGER.exception("Unexpected exception during connection validation")
                errors["base"] = "unknown"
            else:
                unique_id = (
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}/{user_input[CONF_DATABASE]}"
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"TimescaleDB ({user_input[CONF_HOST]})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow."""
        return TimescaleDBExporterOptionsFlow(config_entry)


class TimescaleDBExporterOptionsFlow(OptionsFlow):
    """Handle options flow for TimescaleDB Exporter."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # Parse the multiline globs into a list
            raw_globs = user_input.get(CONF_EXCLUDED_ENTITY_GLOBS, "")
            user_input[CONF_EXCLUDED_ENTITY_GLOBS] = [
                g.strip() for g in raw_globs.splitlines() if g.strip()
            ]
            # Parse the comma-separated domains into a list
            raw_domains = user_input.get(CONF_EXCLUDED_DOMAINS, "")
            user_input[CONF_EXCLUDED_DOMAINS] = [
                d.strip() for d in raw_domains.split(",") if d.strip()
            ]
            # Cast numeric fields
            for key in (
                CONF_BATCH_SIZE,
                CONF_FLUSH_INTERVAL,
                CONF_COMPRESSION_AFTER_DAYS,
                CONF_RETENTION_RAW_DAYS,
                CONF_RETENTION_HOURLY_DAYS,
                CONF_RETENTION_DAILY_DAYS,
                CONF_CHUNK_INTERVAL_HOURS,
            ):
                if key in user_input:
                    user_input[key] = int(user_input[key])
            return self.async_create_entry(data=user_input)

        current = self._config_entry.options

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_BATCH_SIZE,
                    default=current.get(CONF_BATCH_SIZE, DEFAULT_BATCH_SIZE),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=1000, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_FLUSH_INTERVAL,
                    default=current.get(CONF_FLUSH_INTERVAL, DEFAULT_FLUSH_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=60, step=1, mode=NumberSelectorMode.SLIDER)
                ),
                vol.Optional(
                    CONF_EXCLUDED_ENTITY_GLOBS,
                    default="\n".join(current.get(CONF_EXCLUDED_ENTITY_GLOBS, [])),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT, multiline=True)),
                vol.Optional(
                    CONF_EXCLUDED_DOMAINS,
                    default=",".join(current.get(CONF_EXCLUDED_DOMAINS, [])),
                ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                vol.Optional(
                    CONF_COMPRESSION_AFTER_DAYS,
                    default=current.get(
                        CONF_COMPRESSION_AFTER_DAYS, DEFAULT_COMPRESSION_AFTER_DAYS
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=365, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_RETENTION_RAW_DAYS,
                    default=current.get(CONF_RETENTION_RAW_DAYS, DEFAULT_RETENTION_RAW_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=3650, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_RETENTION_HOURLY_DAYS,
                    default=current.get(CONF_RETENTION_HOURLY_DAYS, DEFAULT_RETENTION_HOURLY_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=3650, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(
                    CONF_RETENTION_DAILY_DAYS,
                    default=current.get(CONF_RETENTION_DAILY_DAYS, DEFAULT_RETENTION_DAILY_DAYS),
                ): NumberSelector(
                    NumberSelectorConfig(min=0, max=3650, step=1, mode=NumberSelectorMode.BOX)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)
