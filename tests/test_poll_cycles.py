"""Telemetry survives the fast poll cycles between slow ones.

With the shipped defaults (5 s status, 60 s telemetry) only the status words are
read on most cycles. The coordinator used to publish just what the current cycle
read, so every analogue sensor and every parameter went unknown one cycle after
being read, and stayed that way for the rest of the slow interval. On the device
card that looks like a pump with no telemetry at all, while the status and alarm
entities — read every cycle — stay green.

The slow interval is gated on ``time.monotonic()``, which the HA test helpers do
not advance, so the cycle type is driven by moving the coordinator's own
deadline rather than by simulating the clock.
"""
from __future__ import annotations

from time import monotonic

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_socket import enable_socket

from custom_components.ermangizer.coordinator import ErmangizerCoordinator
from tests.conftest import add_entry
from tests.fake_device import FakeModbusDevice

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

INPUTS = {
    1: 500, 3: 12, 5: 277, 6: 33, 12: 0, 26: 275,
    1024: 0, 1025: 0, 1026: 0, 1027: 0,
}
HOLDINGS = {2: 400}


def _device() -> FakeModbusDevice:
    enable_socket()
    return FakeModbusDevice(INPUTS, HOLDINGS)


async def _add(hass: HomeAssistant, port: int):
    return await add_entry(
        hass,
        {"connection_type": "tcp", "host": "127.0.0.1",
         "tcp_port": port, "wait_between_requests_ms": 0},
        [{"name": "Legacy pump", "unit_id": 1, "layout": "legacy_220_01",
          "poll_interval": 5, "slow_poll_interval": 60, "access_level": "general"}],
    )


def _state(hass: HomeAssistant, entry, suffix: str) -> str:
    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.unique_id and item.unique_id.endswith(suffix):
            state = hass.states.get(item.entity_id)
            return state.state if state else "<no state>"
    raise AssertionError(f"no entity ending with {suffix!r}")


def _coordinator(hass: HomeAssistant, entry) -> ErmangizerCoordinator:
    coordinators = entry.runtime_data.coordinators
    assert len(coordinators) == 1, coordinators
    return next(iter(coordinators.values()))


async def _refresh(hass: HomeAssistant, coordinator: ErmangizerCoordinator) -> None:
    await coordinator.async_refresh()
    await hass.async_block_till_done()


async def test_status_only_cycle_keeps_telemetry_and_parameters(
    hass: HomeAssistant,
) -> None:
    device = _device()
    await device.start()
    try:
        entry = await _add(hass, device.port)
        assert entry.state.name == "LOADED"
        coordinator = _coordinator(hass, entry)

        assert _state(hass, entry, "-frequency") == "50.0"
        assert _state(hass, entry, "-setpoint_frequency") == "40.0"

        # Force the next cycle to be a status-only one, which is what 55 of
        # every 60 seconds looks like in a default install.
        coordinator._slow_deadline = monotonic() + 3600
        before = len(device.requests)

        await _refresh(hass, coordinator)

        # Precondition: this cycle really read only the status block, so the
        # assertions below cannot be satisfied by a fresh telemetry read.
        assert [r for r in device.requests[before:]] == [("input", 1024, 4)], (
            device.requests[before:]
        )

        assert _state(hass, entry, "-frequency") == "50.0", (
            "telemetry dropped out on a status-only cycle"
        )
        assert _state(hass, entry, "-dc_voltage") == "277.0"
        assert _state(hass, entry, "-temperature") == "33.0"
        assert _state(hass, entry, "-setpoint_frequency") == "40.0", (
            "parameters dropped out on a status-only cycle"
        )
    finally:
        await device.stop()


async def test_slow_cycle_still_refreshes_after_a_status_only_one(
    hass: HomeAssistant,
) -> None:
    """Carrying values forward must not freeze them."""
    device = _device()
    await device.start()
    try:
        entry = await _add(hass, device.port)
        coordinator = _coordinator(hass, entry)

        coordinator._slow_deadline = monotonic() + 3600
        await _refresh(hass, coordinator)
        assert _state(hass, entry, "-frequency") == "50.0"

        device.tables["input"][1] = 512
        device.tables["holding"][2] = 450
        coordinator._slow_deadline = 0.0
        await _refresh(hass, coordinator)

        assert _state(hass, entry, "-frequency") == "51.2"
        assert _state(hass, entry, "-setpoint_frequency") == "45.0"
    finally:
        await device.stop()


async def test_register_that_stops_answering_does_not_linger(
    hass: HomeAssistant,
) -> None:
    """The carried-forward baseline must not outlive the device's word for it.

    A slow cycle reads every register, so it replaces the baseline wholesale: a
    register the firmware stopped answering disappears on the next slow cycle
    instead of repeating its last value forever.
    """
    device = _device()
    await device.start()
    try:
        entry = await _add(hass, device.port)
        assert _state(hass, entry, "-pressure") == "2.75"
        coordinator = _coordinator(hass, entry)

        device.reject.add(26)
        coordinator._slow_deadline = 0.0
        await _refresh(hass, coordinator)
        assert _state(hass, entry, "-pressure") == "unknown"

        # A following status-only cycle must not resurrect the stale value.
        coordinator._slow_deadline = monotonic() + 3600
        await _refresh(hass, coordinator)
        assert _state(hass, entry, "-pressure") == "unknown"
        assert _state(hass, entry, "-frequency") == "50.0"
    finally:
        await device.stop()
