"""Switch entities: Modbus run/stop control for a pump.

The start and stop coils are command pulses, not latched state, so the switch
reads its state from the status register and writes a pulse on change. This is
only meaningful when the controller takes its run command from RS-485
(P117 = 2 on the modern layout); with panel-only control the pulse is accepted
by the bus and ignored by the pump.
"""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .codes import RUNNING_STATES
from .entity import ErmangizerEntity, pump_identities
from .pump import PumpUnavailable

_LOGGER = logging.getLogger(__name__)


class PumpRunSwitch(ErmangizerEntity, SwitchEntity):
    """Start/stop the pump over Modbus."""

    _attr_translation_key = "pump_running"
    _attr_icon = "mdi:pump"

    def __init__(self, identity) -> None:
        super().__init__(identity, "pump_running")

    @property
    def is_on(self) -> bool | None:
        state = self._identity.coordinator.data.get("state")
        if state is None:
            return None
        return state in RUNNING_STATES

    @property
    def available(self) -> bool:
        return super().available and self._coils_available()

    def _coils_available(self) -> bool:
        coils = {coil.key for coil in self._identity.coordinator.pump.layout.coils}
        return "start" in coils and "stop" in coils

    async def async_turn_on(self, **kwargs) -> None:
        await self._pulse("start")

    async def async_turn_off(self, **kwargs) -> None:
        await self._pulse("stop")

    async def _pulse(self, coil_key: str) -> None:
        pump = self._identity.coordinator.pump
        coil = next((c for c in pump.layout.coils if c.key == coil_key), None)
        if coil is None:
            raise HomeAssistantError(f"Layout has no {coil_key} coil")
        try:
            await pump.pulse_coil(coil.address)
        except PumpUnavailable as exc:
            raise HomeAssistantError(f"Modbus {coil_key} failed: {exc}") from exc
        # Ask for an immediate refresh so the switch reflects the command as
        # soon as the pump reacts, rather than waiting a poll cycle.
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    for identity in pump_identities(entry):
        async_add_entities(
            [PumpRunSwitch(identity)], config_subentry_id=identity.subentry.subentry_id
        )
