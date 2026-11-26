"""End-to-end setup against a fake device: entry, coordinator, entities."""
from __future__ import annotations

import pytest
from pytest_socket import enable_socket
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN, SERVICE_TURN_OFF
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.ermangizer.const import DOMAIN, SUBENTRY_TYPE_PUMP
from tests.conftest import add_entry
from tests.fake_device import FakeModbusDevice

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

# Modern map. Status word 2004 = 4 (holding_setpoint), pressure raw 275,
# frequency raw 500 (scale 0.1 -> 50.0 Hz), alarms 0.
INPUTS = {
    2000: 500, 2001: 12, 2002: 226, 2003: 44, 2004: 4, 2005: 0,
    2006: 275, 2007: 1092, 2008: 60, 2009: 0,
}
HOLDINGS = {1001: 400, 1002: 100, 1003: 200, 1004: 10, 1005: 500, 1006: 1000}


@pytest.fixture
async def device() -> FakeModbusDevice:
    # The fake device listens on a real loopback socket; the HA test harness
    # guards sockets by default and its marker does not reach async fixtures.
    enable_socket()
    dev = FakeModbusDevice(INPUTS, HOLDINGS)
    await dev.start()
    yield dev
    await dev.stop()


@pytest.fixture
async def entry(hass: HomeAssistant, device: FakeModbusDevice):
    return await add_entry(
        hass,
        {"connection_type": "tcp", "host": "127.0.0.1",
         "tcp_port": device.port, "wait_between_requests_ms": 0},
        [{"name": "Well pump", "unit_id": 8, "layout": "modern_220_02_05",
          "poll_interval": 1, "slow_poll_interval": 1, "access_level": "advanced"}],
    )


def _states(hass: HomeAssistant, entry) -> list:
    return [
        state
        for entity in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if (state := hass.states.get(entity.entity_id)) is not None
    ]


def _by_name(hass: HomeAssistant, entry, kind: str, fragment: str):
    """First entity of one platform whose name contains ``fragment``."""
    return next(
        (
            state
            for state in _states(hass, entry)
            if state.entity_id.startswith(f"{kind}.") and fragment in state.attributes["friendly_name"]
        ),
        None,
    )


def _by_kind(hass: HomeAssistant, entry, kind: str, index: int = 0):
    matches = [
        s for s in _states(hass, entry) if s.entity_id.startswith(f"{kind}.")
    ]
    return matches[index] if len(matches) > index else None


async def test_setup_creates_entities(hass: HomeAssistant, entry) -> None:
    assert entry.state.name == "LOADED"
    kinds = {s.entity_id.split(".")[0] for s in _states(hass, entry)}
    assert {"sensor", "binary_sensor", "switch", "button", "number", "select"} <= kinds


async def test_telemetry_values(hass: HomeAssistant, entry) -> None:
    freq = _by_name(hass, entry, "sensor", "Частота")
    assert float(freq.state) == pytest.approx(50.0)
    assert freq.attributes["unit_of_measurement"] == "Hz"

    pressure = _by_name(hass, entry, "sensor", "Давление")
    assert float(pressure.state) == pytest.approx(2.75)
    assert pressure.attributes["unit_of_measurement"] == "bar"
    assert pressure.attributes["device_class"] == "pressure"


async def test_state_and_running(hass: HomeAssistant, entry) -> None:
    running = _by_kind(hass, entry, "binary_sensor")
    assert running.state == STATE_ON


async def test_switch_turn_off_writes_coil(hass: HomeAssistant, entry, device) -> None:
    switch = _by_kind(hass, entry, "switch")
    assert switch.state == STATE_ON  # status word said holding_setpoint
    device.writes.clear()
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: switch.entity_id}, blocking=True
    )
    assert [w for w in device.writes if w[0] == "coil"]


async def test_number_writes_a_parameter(hass: HomeAssistant, entry, device) -> None:
    # P001 (pressure setpoint) holds 400 -> 4.0, inside its documented range.
    number = _by_name(hass, entry, "number", "Уставка давления")
    assert float(number.state) == pytest.approx(4.0)
    await hass.services.async_call(
        NUMBER_DOMAIN, SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: number.entity_id, ATTR_VALUE: 3.5}, blocking=True,
    )
    writes = [w for w in device.writes if w[0] == "register"]
    assert writes, "setting a number must write a register"
    assert (number.attributes["min"] <= 3.5 <= number.attributes["max"])


async def test_select_writes_the_code(hass: HomeAssistant, entry, device) -> None:
    select = _by_kind(hass, entry, "select")
    device.writes.clear()
    await hass.services.async_call(
        SELECT_DOMAIN, SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: select.entity_id, ATTR_OPTION: select.attributes["options"][0]},
        blocking=True,
    )
    assert [w for w in device.writes if w[0] == "register"]


async def test_unloading_releases_the_bus(hass: HomeAssistant, entry) -> None:
    # The bus handle lives in hass.data under the domain; unloading the only
    # entry on it must close the socket, not just drop the coordinators.
    assert hass.data.get(DOMAIN)
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    # The gateway dict is emptied; the domain key itself may linger empty.
    gateways = hass.data.get(DOMAIN, {}).get("gateways", {})
    assert not gateways


async def _reconfigure_access(hass: HomeAssistant, entry, level: str) -> None:
    sub = next(
        s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_PUMP
    )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_PUMP),
        context={
            "source": SOURCE_RECONFIGURE,
            "subentry_id": sub.subentry_id,
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input={**sub.data, "access_level": level}
    )
    await hass.async_block_till_done()
    assert result["type"] == "abort"


def _registered(hass: HomeAssistant, entry, domain: str) -> set[str]:
    return {
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == domain
    }


async def test_lowering_access_prunes_dropped_entities(
    hass: HomeAssistant, entry
) -> None:
    """A parameter the level no longer exposes must vanish, not linger.

    HA only garbage-collects entities whose platform is gone, so a parameter
    dropped by an access-level change would otherwise sit in the registry as
    ``unavailable`` forever, and automations pointing at it would silently stop
    working instead of seeing the entity disappear.
    """
    before = _registered(hass, entry, NUMBER_DOMAIN)
    assert before

    await _reconfigure_access(hass, entry, "general")

    after = _registered(hass, entry, NUMBER_DOMAIN)
    assert after < before, "numbers removed by the level must be unregistered"
    assert entry.state.name == "LOADED"
    # What survives is exactly what the general level still exposes, and it is
    # live rather than orphaned.
    for entity_id in after:
        state = hass.states.get(entity_id)
        assert state is not None and state.state != STATE_UNAVAILABLE


async def test_raising_access_adds_entities(hass: HomeAssistant, entry) -> None:
    await _reconfigure_access(hass, entry, "general")
    general = _registered(hass, entry, NUMBER_DOMAIN)
    await _reconfigure_access(hass, entry, "factory")
    assert general < _registered(hass, entry, "number")


async def test_pumps_hang_off_a_gateway_device(hass: HomeAssistant, entry) -> None:
    """The pump devices name the bus as their via_device, so it must exist.

    A dangling via_device is a warning in 2026.2 and an error in 2025.12+.
    """
    devices = dr.async_get(hass)
    entries = list(dr.async_entries_for_config_entry(devices, entry.entry_id))
    assert len(entries) == 2, "one bus device plus one pump device"
    pump = next(d for d in entries if d.via_device_id is not None)
    bus = next(d for d in entries if d.id == pump.via_device_id)
    assert bus.entry_type is dr.DeviceEntryType.SERVICE
