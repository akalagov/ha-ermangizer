"""Binary sensors derived from the status word."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .codes import RUNNING_STATES
from .entity import ErmangizerEntity, pump_identities


class ErmangizerBinarySensor(ErmangizerEntity, BinarySensorEntity):
    """Base that names the binary sensor by its translation key."""

    def __init__(self, identity) -> None:
        super().__init__(identity, self._attr_translation_key)


class RunningBinarySensor(ErmangizerBinarySensor):
    """Whether the pump is driving the motor."""

    _attr_translation_key = "pump_running"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:pump"

    @property
    def is_on(self) -> bool | None:
        state = self._identity.coordinator.data.get("state")
        return None if state is None else state in RUNNING_STATES


class AlarmBinarySensor(ErmangizerBinarySensor):
    """Whether the alarm word reports anything."""

    _attr_translation_key = "alarm_active"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self) -> bool | None:
        alarms = self._identity.coordinator.data.get("alarms")
        return None if alarms is None else bool(alarms)


class MotorOverloadBinarySensor(ErmangizerBinarySensor):
    """Motor overload flag, present only on the legacy status word."""

    _attr_translation_key = "motor_overload"
    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self) -> bool | None:
        return self._identity.coordinator.data.get("motor_overload")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    for identity in pump_identities(entry):
        entities: list[BinarySensorEntity] = [
            RunningBinarySensor(identity),
            AlarmBinarySensor(identity),
        ]
        # The modern status word has no overload bit; offering the entity there
        # would leave it permanently unknown.
        if identity.coordinator.pump.layout.id.endswith("220_01"):
            entities.append(MotorOverloadBinarySensor(identity))
        async_add_entities(entities, config_subentry_id=identity.subentry.subentry_id)
