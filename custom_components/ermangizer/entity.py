"""Entity base classes shared by all Ermangizer platforms."""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, GATEWAY_MODEL, MANUFACTURER, SUBENTRY_TYPE_PUMP
from .coordinator import ErmangizerCoordinator


def gateway_device_info(config_entry: ConfigEntry) -> DeviceInfo:
    """The bus itself as a device, so each pump can hang off it."""
    return DeviceInfo(
        identifiers={(DOMAIN, config_entry.entry_id)},
        name=config_entry.title,
        manufacturer=MANUFACTURER,
        model=GATEWAY_MODEL,
        entry_type=DeviceEntryType.SERVICE,
    )


@callback
def prune_stale(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    subentry: ConfigSubentry,
    domain: str,
    unique_ids: Iterable[str],
) -> None:
    """Remove this subentry's entities of ``domain`` that are no longer built.

    Which entities exist depends on the access level and on the detected
    register map, both of which can change while the entry stays loaded. HA
    only garbage-collects entities whose platform is gone, so without this the
    dropped ones linger forever as ``unavailable``.

    Takes the unique_ids about to be added rather than parameter keys, so the
    caller cannot drift from how entities actually name themselves. Matching is
    by unique_id rather than by device because the device registry is keyed per
    config entry, not per subentry: a device-level sweep would delete the other
    pumps' entities too.
    """
    registry = er.async_get(hass)
    keep = set(unique_ids)
    for entry in er.async_entries_for_config_entry(registry, config_entry.entry_id):
        if (
            entry.platform == DOMAIN
            and entry.domain == domain
            and entry.config_subentry_id == subentry.subentry_id
            and entry.unique_id not in keep
        ):
            registry.async_remove(entry.entity_id)


@dataclass(frozen=True)
class PumpIdentity:
    """Everything needed to name and place one pump's entities."""

    config_entry: ConfigEntry
    subentry: ConfigSubentry
    coordinator: ErmangizerCoordinator

    @property
    def unit_id(self) -> int:
        return self.coordinator.unit_id

    @property
    def title(self) -> str:
        return self.subentry.title

    def device_info(self, layout_title: str) -> DeviceInfo:
        """One device per pump subentry.

        The model names the detected register map rather than a claimed
        hardware model: the map is what was actually observed, and the
        manufacturer sells several models sharing one enclosure.
        """
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.config_entry.entry_id}:{self.subentry.subentry_id}")},
            name=self.title,
            manufacturer=MANUFACTURER,
            model=layout_title,
            via_device=(DOMAIN, self.config_entry.entry_id),
        )


class ErmangizerEntity(CoordinatorEntity[ErmangizerCoordinator]):
    """Base for entities bound to one pump subentry."""

    _attr_has_entity_name = True

    def __init__(self, identity: PumpIdentity, key: str) -> None:
        """``key`` identifies the register, parameter or coil; it becomes the
        entity's unique_id, so it must stay stable across releases even when
        the display name changes."""
        super().__init__(identity.coordinator)
        self._identity = identity
        self._attr_unique_id = f"{identity.subentry.subentry_id}-{key}"
        self._attr_device_info = identity.device_info(identity.coordinator.pump.layout.title)


def pump_identities(entry: ConfigEntry) -> list[PumpIdentity]:
    """Identities for every pump subentry that has a live coordinator."""
    runtime = entry.runtime_data
    return [
        PumpIdentity(
            config_entry=entry,
            subentry=subentry,
            coordinator=runtime.coordinators[subentry.subentry_id],
        )
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_PUMP
        and subentry.subentry_id in runtime.coordinators
    ]
