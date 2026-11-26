"""Select entities for enumerable parameters (Pnnn with documented options)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ErmangizerEntity, pump_identities
from .models import ParamDef
from .pump import PumpUnavailable


class ParameterSelect(ErmangizerEntity, SelectEntity):
    """One parameter whose values are a documented enumeration."""

    def __init__(self, identity, param: ParamDef) -> None:
        super().__init__(identity, param.key)
        self._param = param
        self._attr_name = param.name
        # Option order follows the raw code, so the list reads like the manual.
        self._attr_options = [param.options[code] for code in sorted(param.options)]
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_entity_registry_enabled_default = param.entity_registry_enabled_default
        if param.icon:
            self._attr_icon = param.icon

    @property
    def current_option(self) -> str | None:
        raw = self._identity.coordinator.data.get("parameters", {}).get(self._param.key)
        if raw is None:
            return None
        return self._param.options.get(raw)

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        # Surfaced so an operator sees "this changes how the pump runs" before
        # editing the value, not after.
        return {"warning": self._param.warns} if self._param.warns else {}

    @property
    def available(self) -> bool:
        return super().available and self._param.key in self._identity.coordinator.data.get("parameters", {})

    async def async_select_option(self, option: str) -> None:
        raw = next(
            (code for code, label in self._param.options.items() if label == option), None
        )
        if raw is None:
            raise HomeAssistantError(f"Unknown option {option!r} for {self._param.name}")
        try:
            await self._identity.coordinator.pump.write_raw(self._param, raw)
        except PumpUnavailable as exc:
            raise HomeAssistantError(f"Failed to write {self._param.name}: {exc}") from exc
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    for identity in pump_identities(entry):
        async_add_entities(
            [
                ParameterSelect(identity, param)
                for param in identity.coordinator.pump.params
                if param.is_enum
            ],
            config_subentry_id=identity.subentry.subentry_id,
        )
