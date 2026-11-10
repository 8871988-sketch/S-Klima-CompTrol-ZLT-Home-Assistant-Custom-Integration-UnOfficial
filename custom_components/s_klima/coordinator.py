"""Data update coordinator for the S-Klima CompTrol ZLT integration."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CompTrolAuthError,
    CompTrolClient,
    CompTrolConnectionError,
    CompTrolError,
    CompTrolState,
    IndoorUnit,
)
from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN
from .stabilize import StateStabilizer

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

# The CompTrol web server sometimes stalls for a moment: retry a failed poll once.
RETRY_DELAY = 3
# Failed polls in a row that keep the last good state before entities go unavailable.
MAX_FAILED_POLLS = 3


class SKlimaCoordinator(DataUpdateCoordinator[CompTrolState]):
    """Polls all indoor units with a single request."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: CompTrolClient
    ) -> None:
        """Initialize."""
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self._stabilizer = StateStabilizer()
        self._failed_polls = 0

    async def _async_update_data(self) -> CompTrolState:
        try:
            try:
                state = await self.client.async_get_state()
            except CompTrolConnectionError as err:
                _LOGGER.debug("Poll failed (%s), retrying once", err)
                await asyncio.sleep(RETRY_DELAY)
                state = await self.client.async_get_state()
        except CompTrolAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except CompTrolError as err:
            if self.data is not None and self._failed_polls < MAX_FAILED_POLLS:
                self._failed_polls += 1
                _LOGGER.debug(
                    "Poll failed (%s), keeping last state (%d/%d)",
                    err, self._failed_polls, MAX_FAILED_POLLS,
                )
                return self.data
            raise UpdateFailed(str(err)) from err
        self._failed_polls = 0
        return self._stabilizer.apply(state)

    async def async_write_unit(
        self, unit_id: int, values: dict[str, int], optimistic: dict[str, Any]
    ) -> None:
        """Write values to a unit, update the local state and refresh."""
        try:
            await self.client.async_write_unit(unit_id, values)
        except CompTrolAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(f"CompTrol ZLT login failed: {err}") from err
        except CompTrolError as err:
            raise HomeAssistantError(f"Writing to CompTrol ZLT failed: {err}") from err

        unit: IndoorUnit | None = self.data.units.get(unit_id) if self.data else None
        if unit is not None and optimistic:
            self.data.units[unit_id] = replace(unit, **optimistic)
            self.async_update_listeners()
        await self.async_request_refresh()
