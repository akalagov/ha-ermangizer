"""Buttons for one-shot control coils.

Coils here are commands the device consumes on the rising edge, so a momentary
button fits them better than a toggle that would imply retained state.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ErmangizerEntity, prune_stale, pump_identities
from .models import CoilDef
from .pump import PumpUnavailable

# start/stop are presented as a switch; the rest are momentary commands.
_SWITCH_COILS = frozenset({"start", "stop"})


class CoilButton(ErmangizerEntity, ButtonEntity):
    """One control coil pressed as a command."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, identity, coil: CoilDef) -> None:
        super().__init__(identity, f"coil_{coil.key}")
        self._coil = coil
        self._attr_name = coil.name
        if coil.icon:
            self._attr_icon = coil.icon

    async def async_press(self) -> None:
        try:
            await self._identity.coordinator.pump.pulse_coil(self._coil.address)
        except PumpUnavailable as exc:
            raise HomeAssistantError(f"{self._coil.name} failed: {exc}") from exc
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    for identity in pump_identities(entry):
        entities = [
            CoilButton(identity, coil)
            for coil in identity.coordinator.pump.layout.coils
            if coil.key not in _SWITCH_COILS
        ]
        prune_stale(
            hass,
            entry,
            identity.subentry,
            "button",
            {entity.unique_id for entity in entities},
        )
        async_add_entities(entities, config_subentry_id=identity.subentry.subentry_id)
