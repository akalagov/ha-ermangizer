"""What the device card reports, and how many sensors one register gets.

Two regressions live here:

* The firmware register was published as a disabled-by-default sensor, while
  Home Assistant shows a component's version in the device's own fields.
* The status and alarm words each produced two sensors publishing the *same*
  number: a scaled TelemetrySensor (scale 1.0, so no scaling happens) and a
  RawRegisterSensor. Their names differed only by a suffix, which read as a
  naming bug rather than as a redundant entity.
"""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_socket import enable_socket

from tests.conftest import add_entry
from tests.fake_device import FakeModbusDevice

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

MODERN_INPUTS = {
    2000: 500, 2001: 12, 2002: 226, 2003: 44, 2004: 4, 2005: 0,
    2006: 275, 2007: 1092, 2008: 60, 2009: 0,
}
LEGACY_INPUTS = {
    1: 500, 3: 12, 5: 277, 6: 33, 12: 0, 26: 275,
    1024: 0, 1025: 0, 1026: 0, 1027: 0,
}


async def _setup(hass: HomeAssistant, inputs: dict, layout: str):
    enable_socket()
    device = FakeModbusDevice(inputs, {})
    await device.start()
    entry = await add_entry(
        hass,
        {"connection_type": "tcp", "host": "127.0.0.1",
         "tcp_port": device.port, "wait_between_requests_ms": 0},
        [{"name": "Pump", "unit_id": 3, "layout": layout,
          "poll_interval": 1, "slow_poll_interval": 1, "access_level": "general"}],
    )
    return device, entry


def _pump_device(hass: HomeAssistant, entry) -> dr.DeviceEntry:
    registry = dr.async_get(hass)
    devices = [
        item for item in dr.async_entries_for_config_entry(registry, entry.entry_id)
        if item.name == "Pump"
    ]
    assert len(devices) == 1, [item.name for item in devices]
    return devices[0]


def _unique_ids(hass: HomeAssistant, entry) -> set[str]:
    registry = er.async_get(hass)
    return {
        item.unique_id
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.domain == "sensor"
    }


async def test_firmware_version_is_reported_on_the_device(hass: HomeAssistant) -> None:
    device = None
    try:
        device, entry = await _setup(hass, MODERN_INPUTS, "modern_220_02_05")
        assert _pump_device(hass, entry).sw_version == "1092"
        # ...and not also as a sensor competing with that field.
        assert not [uid for uid in _unique_ids(hass, entry) if uid.endswith("-firmware")]
    finally:
        if device:
            await device.stop()


async def test_legacy_device_reports_no_version(hass: HomeAssistant) -> None:
    """The legacy map has no firmware register; the field stays empty."""
    device = None
    try:
        device, entry = await _setup(hass, LEGACY_INPUTS, "legacy_220_01")
        assert _pump_device(hass, entry).sw_version is None
    finally:
        if device:
            await device.stop()


async def test_status_and_alarm_have_one_sensor_each(hass: HomeAssistant) -> None:
    device = None
    try:
        device, entry = await _setup(hass, LEGACY_INPUTS, "legacy_220_01")
        ids = _unique_ids(hass, entry)
        subentry_id = entry.subentries[next(iter(entry.subentries))].subentry_id
        prefix = f"{subentry_id}-"

        # The undecoded word is published once, under the *_raw id...
        assert f"{prefix}status_raw" in ids
        assert f"{prefix}alarm_raw" in ids
        # ...and not a second time as a scaled sensor showing the same number.
        assert f"{prefix}status" not in ids
        assert f"{prefix}alarm" not in ids
        # The decoded readings are unaffected.
        assert f"{prefix}state" in ids
        assert f"{prefix}alarms" in ids
    finally:
        if device:
            await device.stop()


async def test_obsolete_sensors_from_an_earlier_release_are_pruned(
    hass: HomeAssistant,
) -> None:
    """Upgrading removes the entities this integration stopped publishing.

    Registers are dropped from the entity list rather than disabled, so the
    registry is swept against what the platform actually adds (see
    ``prune_stale``). This seeds the ids that 0.3.0 created and checks a reload
    clears them, so an upgraded install does not keep dead rows.
    """
    device = None
    try:
        device, entry = await _setup(hass, LEGACY_INPUTS, "legacy_220_01")
        registry = er.async_get(hass)
        subentry_id = entry.subentries[next(iter(entry.subentries))].subentry_id
        prefix = f"{subentry_id}-"
        stale = (f"{prefix}status", f"{prefix}alarm", f"{prefix}firmware")
        for uid in stale:
            registry.async_get_or_create(
                "sensor",
                "ermangizer",
                uid,
                config_entry=entry,
                config_subentry_id=subentry_id,
            )
        assert set(stale) <= _unique_ids(hass, entry)

        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

        remaining = _unique_ids(hass, entry)
        assert not (remaining & set(stale)), remaining & set(stale)
        # The surviving readings are still there.
        assert f"{prefix}frequency" in remaining
        assert f"{prefix}status_raw" in remaining
    finally:
        if device:
            await device.stop()
