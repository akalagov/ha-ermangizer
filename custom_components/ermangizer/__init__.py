"""The Ermangizer integration.

One config entry is one physical bus; pumps on it are subentries, so the
connection and its lock are configured once and shared by every pump on the
line.

Home Assistant is imported inside the setup functions rather than at module
level. The register maps, decoders and framing in this package are pure Python
and are used outside Home Assistant - notably scripts/probe_ermangizer.py,
which runs on any machine that can reach the device - and importing this
package must not require the Home Assistant wheel to be installed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .const import SUBENTRY_TYPE_PUMP

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .coordinator import ErmangizerCoordinator
    from .modbus_client import GatewayHandle

_LOGGER = logging.getLogger(__name__)

def platforms() -> list:
    """Platforms to forward to, resolved lazily so importing this package
    does not require Home Assistant."""
    from homeassistant.const import Platform

    return [
        Platform.BINARY_SENSOR,
        Platform.BUTTON,
        Platform.NUMBER,
        Platform.SELECT,
        Platform.SENSOR,
        Platform.SWITCH,
    ]


@dataclass
class ErmangizerRuntimeData:
    """Runtime data attached to a config entry."""

    gateway: "GatewayHandle"
    coordinators: dict[str, "ErmangizerCoordinator"] = field(default_factory=dict)


async def async_setup_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    from .coordinator import async_create_coordinator
    from .modbus_client import async_get_gateway, async_release_gateway

    gateway = await async_get_gateway(hass, entry.data)

    coordinators: dict[str, ErmangizerCoordinator] = {}
    try:
        for subentry in entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_PUMP:
                continue
            coordinator = await async_create_coordinator(
                hass, gateway, subentry.data, subentry.title
            )
            await coordinator.async_config_entry_first_refresh()
            coordinators[subentry.subentry_id] = coordinator
    except Exception:
        await async_release_gateway(hass, entry.data)
        raise

    entry.runtime_data = ErmangizerRuntimeData(gateway=gateway, coordinators=coordinators)
    # Pump devices name this as their via_device, so it must exist before the
    # platforms register them.
    from homeassistant.helpers import device_registry as dr

    from .entity import gateway_device_info

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, **gateway_device_info(entry)
    )
    await hass.config_entries.async_forward_entry_setups(entry, platforms())
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    from .modbus_client import async_release_gateway

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms())
    if unload_ok:
        await async_release_gateway(hass, entry.data)
    return unload_ok


async def _async_update_listener(hass: "HomeAssistant", entry: "ConfigEntry") -> None:
    """Reload on entry changes; HA already reloads on subentry edits."""
    await hass.config_entries.async_reload(entry.entry_id)
