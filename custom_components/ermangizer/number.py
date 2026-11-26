"""Number entities for writable scalar parameters.

One entity per parameter exposed at the configured access level. Values are
written straight to the holding register; the device applies them immediately,
which is why parameters that alter how the pump runs carry a warning in the UI
rather than being hidden behind a confirmation step.
"""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ErmangizerEntity, pump_identities
from .models import ParamDef
from .pump import PumpUnavailable
from .units import NUMBER_DEVICE_CLASS_BY_DISPLAY_UNIT, display_unit


class ParameterNumber(ErmangizerEntity, NumberEntity):
    """One writable scalar parameter."""

    def __init__(self, identity, param: ParamDef) -> None:
        super().__init__(identity, param.key)
        self._param = param
        self._attr_name = param.name
        self._attr_native_min_value = param.min_value
        self._attr_native_max_value = param.max_value
        self._attr_native_step = param.step
        self._attr_native_unit_of_measurement = display_unit(param.unit)
        self._attr_device_class = NUMBER_DEVICE_CLASS_BY_DISPLAY_UNIT.get(display_unit(param.unit))
        # A box, not a slider: parameter ranges are wide and precision matters
        # more than glanceability.
        self._attr_mode = NumberMode.BOX
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_entity_registry_enabled_default = param.entity_registry_enabled_default
        if param.icon:
            self._attr_icon = param.icon

    @property
    def native_value(self) -> float | None:
        raw = self._identity.coordinator.data.get("parameters", {}).get(self._param.key)
        if raw is None:
            return None
        return round(raw * self._param.scale, 6)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        # Surfaced so an operator sees "this changes how the pump runs" before
        # editing the value, not after.
        return {"warning": self._param.warns} if self._param.warns else {}

    @property
    def available(self) -> bool:
        # A parameter the pump never answered for is not writable: the read
        # would fail too, and offering it invites a confusing error.
        return super().available and self._param.key in self._identity.coordinator.data.get("parameters", {})

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self._identity.coordinator.pump.write_parameter(self._param, value)
        except PumpUnavailable as exc:
            raise HomeAssistantError(f"Failed to write {self._param.name}: {exc}") from exc
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    for identity in pump_identities(entry):
        async_add_entities(
            [
                ParameterNumber(identity, param)
                for param in identity.coordinator.pump.params
                if not param.is_enum
            ],
            config_subentry_id=identity.subentry.subentry_id,
        )
