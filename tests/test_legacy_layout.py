"""Legacy-generation devices, whose register map differs from the modern one.

A production ER-G-220-02 was found answering FC04 at 0 and 1024 but rejecting
26 with illegal data address, so the legacy pressure register cannot be
assumed present: doc v1.4 does not list it at all. These tests pin what the
integration does when it is missing — and that a device which is genuinely
unreachable still fails setup rather than loading empty.
"""
from __future__ import annotations

import socket

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_socket import enable_socket

from tests.conftest import add_entry
from tests.fake_device import FakeModbusDevice

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

# Frequency 50.0 Hz, current 1.2 A, DC bus 277 V, heatsink 33 C, output 0 V,
# pressure 2.75, status and alarm words zero.
INPUTS = {
    1: 500, 3: 12, 5: 277, 6: 33, 12: 0, 26: 275,
    1024: 0, 1025: 0, 1026: 0, 1027: 0,
}
HOLDINGS = {2: 400, 3: 100, 4: 200, 11: 50, 12: 10, 13: 20, 21: 350}


def _device(**kwargs) -> FakeModbusDevice:
    enable_socket()
    return FakeModbusDevice(INPUTS, HOLDINGS, **kwargs)


async def _add(hass: HomeAssistant, port: int):
    return await add_entry(
        hass,
        {"connection_type": "tcp", "host": "127.0.0.1",
         "tcp_port": port, "wait_between_requests_ms": 0},
        [{"name": "Legacy pump", "unit_id": 1, "layout": "legacy_220_01",
          "poll_interval": 1, "slow_poll_interval": 1, "access_level": "general"}],
    )


def _state(hass: HomeAssistant, entry, suffix: str) -> str:
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.unique_id and item.unique_id.endswith(suffix):
            state = hass.states.get(item.entity_id)
            return state.state if state else "<no state>"
    raise AssertionError(f"no entity ending with {suffix!r}")


async def test_legacy_device_sets_up(hass: HomeAssistant) -> None:
    device = _device()
    await device.start()
    try:
        entry = await _add(hass, device.port)
        assert entry.state.name == "LOADED"
        assert _state(hass, entry, "-pressure") == "2.75"
    finally:
        await device.stop()


async def test_missing_pressure_register_costs_only_pressure(
    hass: HomeAssistant,
) -> None:
    """One unsupported register must not take the device down with it.

    Pressure sits in its own slow-read block, and the exception on it used to
    propagate out of read_inputs() as PumpUnavailable -> UpdateFailed. The
    first refresh reads the slow block too, so the entry never finished setup:
    every sensor and parameter went unavailable although the telemetry block at
    1..12 had read fine.
    """
    device = _device(reject={26})
    await device.start()
    try:
        entry = await _add(hass, device.port)
        assert entry.state.name == "LOADED"

        # The refused reading is unknown, not stale or wrong.
        assert _state(hass, entry, "-pressure") == "unknown"
        # Everything the device does answer is still live.
        assert _state(hass, entry, "-frequency") == "50.0"
        assert _state(hass, entry, "-dc_voltage") == "277.0"
        assert _state(hass, entry, "-temperature") == "33.0"
        # And the traffic shows 26 was queried on its own, not merged into the
        # block that succeeded.
        assert ("input", 26, 1) in device.requests
    finally:
        await device.stop()


async def test_unreachable_device_still_fails_setup(hass: HomeAssistant) -> None:
    """Tolerance for absent registers must not hide a dead device.

    Nothing listens on this port, so requests fail with a connection error
    rather than a Modbus exception, and setup must back off for retry instead
    of loading a pump that reports nothing.
    """
    # Bind then release to claim a port nothing is listening on, rather than
    # guessing one that might have been taken over in between.
    enable_socket()
    reserve = socket.socket()
    reserve.bind(("127.0.0.1", 0))
    port = reserve.getsockname()[1]
    reserve.close()
    entry = await _add(hass, port)
    assert entry.state.name == "SETUP_RETRY"
