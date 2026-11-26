"""Sensors for an Ermangizer pump: telemetry, operating state, alarms."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .entity import ErmangizerEntity, prune_stale, pump_identities
from .models import RegisterDef

from .units import DEVICE_CLASS_BY_DISPLAY_UNIT, display_unit


def _device_class(unit: str | None):
    return DEVICE_CLASS_BY_DISPLAY_UNIT.get(display_unit(unit))


class TelemetrySensor(ErmangizerEntity, SensorEntity):
    """One input register, scaled to engineering units."""

    def __init__(self, identity, register: RegisterDef) -> None:
        super().__init__(identity, register.key)
        self._register = register
        self._attr_name = register.name
        self._attr_native_unit_of_measurement = display_unit(register.unit)
        self._attr_device_class = _device_class(register.unit)
        if register.state_class == "measurement":
            self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_registry_enabled_default = register.entity_registry_enabled_default
        if register.icon:
            self._attr_icon = register.icon
        if register.diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> float | None:
        entry = self._identity.coordinator.data.get(self._register.key)
        # A 32-bit register is only present once both words were read, so a
        # half-read value never reaches the state machine.
        return None if entry is None else entry["value"]


class StateSensor(ErmangizerEntity, SensorEntity):
    """Operating state, translated from the status word."""

    _attr_translation_key = "state"
    _attr_icon = "mdi:pump"

    def __init__(self, identity) -> None:
        super().__init__(identity, "state")

    @property
    def native_value(self) -> str | None:
        return self._identity.coordinator.data.get("state")

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"state_label": self._identity.coordinator.data.get("state_label", "")}


class AlarmSensor(ErmangizerEntity, SensorEntity):
    """Alarms reported by the alarm word."""

    _attr_translation_key = "alarms"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:alert"

    def __init__(self, identity) -> None:
        super().__init__(identity, "alarms")

    @property
    def native_value(self) -> str | None:
        alarms = self._identity.coordinator.data.get("alarms")
        if alarms is None:
            return None
        return ", ".join(entry["label"] for entry in alarms) or "none"

    @property
    def extra_state_attributes(self) -> dict[str, list[str]]:
        alarms = self._identity.coordinator.data.get("alarms") or ()
        return {"alarm_keys": [entry["key"] for entry in alarms]}


class RawRegisterSensor(ErmangizerEntity, SensorEntity):
    """Undecoded register value, so an undocumented code stays visible."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, identity, register: RegisterDef) -> None:
        super().__init__(identity, f"{register.key}_raw")
        self._register = register
        self._attr_name = f"{register.name} (сырое значение)"

    @property
    def native_value(self) -> int | None:
        entry = self._identity.coordinator.data.get(self._register.key)
        return None if entry is None else entry["raw"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    for identity in pump_identities(entry):
        entities: list[SensorEntity] = []
        for register in identity.coordinator.pump.layout.registers:
            entities.append(TelemetrySensor(identity, register))
            # Status and alarm words are bit fields or enumerations; keep the
            # raw number alongside the decoded one.
            if register.key in ("status", "alarm"):
                entities.append(RawRegisterSensor(identity, register))
        entities.append(StateSensor(identity))
        entities.append(AlarmSensor(identity))
        prune_stale(
            hass,
            entry,
            identity.subentry,
            "sensor",
            {entity.unique_id for entity in entities},
        )
        async_add_entities(entities, config_subentry_id=identity.subentry.subentry_id)
