"""State change event listener for Home Assistant."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback

from .db.writer import StateChange, TimescaleExporter, parse_state_numeric

if TYPE_CHECKING:
    from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)


def async_setup_listener(
    hass: HomeAssistant,
    exporter: TimescaleExporter,
) -> Callable[[], None]:
    """Register a listener for all state change events.

    Returns an unsubscribe callback.
    """

    @callback
    def _state_changed_listener(event: Event) -> None:
        """Handle a state change event."""
        new_state = event.data.get("new_state")
        if new_state is None:
            # Entity was removed
            return

        entity_id: str = event.data["entity_id"]

        # Apply exclusion filters
        if exporter.is_excluded(entity_id):
            return

        state_str = new_state.state
        attributes = dict(new_state.attributes) if new_state.attributes else {}

        state_change = StateChange(
            time=new_state.last_updated,
            entity_id=entity_id,
            state=state_str,
            state_numeric=parse_state_numeric(state_str),
            attributes=attributes,
            context_id=new_state.context.id if new_state.context else None,
        )

        exporter.enqueue(state_change)

    unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, _state_changed_listener)
    _LOGGER.debug("State change listener registered")
    return unsub
