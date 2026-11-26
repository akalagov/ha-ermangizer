"""Config flow tests: transport steps, pump subentries, duplicate addresses."""
from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.ermangizer.const import (
    CONF_ACCESS_LEVEL,
    CONF_CONNECTION_TYPE,
    CONF_LAYOUT,
    CONF_POLL_INTERVAL,
    CONF_SLOW_POLL_INTERVAL,
    CONF_UNIT_ID,
    CONF_WAIT_BETWEEN_REQUESTS,
    CONNECTION_RTU_OVER_TCP,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    DEFAULT_WAIT_BETWEEN_REQUESTS_NETWORK,
    DEFAULT_WAIT_BETWEEN_REQUESTS_SERIAL,
    DOMAIN,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def _advance(hass: HomeAssistant, result, **overrides):
    """Submit one flow step. A menu step (the "add another?" prompt) is closed
    out by picking the given option, so tests read as the user's choices."""
    if result["type"] == "menu":
        overrides = overrides or {"next_step_id": "finish"}
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=overrides
    )


async def test_tcp_flow_creates_entry_with_pump_subentry(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] == "form" and result["step_id"] == "user"

    result = await _advance(hass, result, connection_type=CONNECTION_TCP)
    assert result["step_id"] == "network"
    # A native Modbus TCP gateway queues requests, so it starts with the
    # shorter pause a serial bus does not tolerate.
    assert result["data_schema"] is not None

    result = await _advance(
        hass, result, host="203.0.113.10", tcp_port=502,
        wait_between_requests_ms=DEFAULT_WAIT_BETWEEN_REQUESTS_NETWORK,
    )
    assert result["step_id"] == "pump"

    result = await _advance(
        hass, result, name="Well pump", **{CONF_UNIT_ID: 8},
        **{CONF_LAYOUT: "auto"}, **{CONF_POLL_INTERVAL: 5},
        **{CONF_SLOW_POLL_INTERVAL: 60}, **{CONF_ACCESS_LEVEL: "general"},
    )
    assert result["step_id"] == "add_another"

    result = await _advance(hass, result)  # menu -> finish
    assert result["type"] == "create_entry"
    entry = result["result"]
    assert entry.data[CONF_CONNECTION_TYPE] == CONNECTION_TCP
    assert entry.data["host"] == "203.0.113.10"
    assert entry.data["tcp_port"] == 502
    assert entry.unique_id == f"{CONNECTION_TCP}|203.0.113.10|502"
    assert len(entry.subentries) == 1
    subentry = next(iter(entry.subentries.values()))
    assert subentry.data[CONF_UNIT_ID] == 8
    assert subentry.unique_id == "8"


async def test_rtu_over_tcp_defaults_to_the_serial_pause(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _advance(hass, result, connection_type=CONNECTION_RTU_OVER_TCP)
    # The step's default must be the serial value: a transparent bridge is a
    # serial bus underneath.
    schema = {str(k): k.default() for k in result["data_schema"].schema}
    assert schema[CONF_WAIT_BETWEEN_REQUESTS] == DEFAULT_WAIT_BETWEEN_REQUESTS_SERIAL


async def test_duplicate_unit_id_is_rejected(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await _advance(hass, result, connection_type=CONNECTION_TCP)
    result = await _advance(hass, result, host="203.0.113.20", tcp_port=502, wait_between_requests_ms=20)
    pump = {CONF_LAYOUT: "auto", CONF_POLL_INTERVAL: 5,
            CONF_SLOW_POLL_INTERVAL: 60, CONF_ACCESS_LEVEL: "general"}
    result = await _advance(hass, result, name="A", **{CONF_UNIT_ID: 3}, **pump)
    result = await _advance(hass, result, next_step_id="pump")
    result = await _advance(hass, result, name="B", **{CONF_UNIT_ID: 3}, **pump)
    assert result["type"] == "form" and result["step_id"] == "pump"
    assert result["errors"] == {"unit_id": "duplicate_unit_id"}

    result = await _advance(hass, result, name="B", **{CONF_UNIT_ID: 4}, **pump)
    result = await _advance(hass, result)
    assert result["type"] == "create_entry"
    entry = result["result"]
    assert {s.data[CONF_UNIT_ID] for s in entry.subentries.values()} == {3, 4}


async def test_second_bus_is_a_separate_entry(hass: HomeAssistant) -> None:
    """Two TCP ports on one gateway host are two buses, not one."""
    for port in (502, 5002):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await _advance(hass, result, connection_type=CONNECTION_TCP)
        result = await _advance(hass, result, host="203.0.113.10", tcp_port=port,
                                wait_between_requests_ms=20)
        result = await _advance(hass, result, name=f"P{port}", **{CONF_UNIT_ID: 8},
                                **{CONF_LAYOUT: "auto"}, **{CONF_POLL_INTERVAL: 5},
                                **{CONF_SLOW_POLL_INTERVAL: 60}, **{CONF_ACCESS_LEVEL: "general"})
        result = await _advance(hass, result)
        assert result["type"] == "create_entry"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


async def test_same_bus_twice_aborts(hass: HomeAssistant) -> None:
    for _ in range(2):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await _advance(hass, result, connection_type=CONNECTION_SERIAL)
        result = await _advance(
            hass, result, port="/dev/ttyUSB0", baudrate=9600, parity="N",
            stopbits=1, bytesize=8, wait_between_requests_ms=30,
        )
        result = await _advance(hass, result, name="P", **{CONF_UNIT_ID: 1},
                                **{CONF_LAYOUT: "auto"}, **{CONF_POLL_INTERVAL: 5},
                                **{CONF_SLOW_POLL_INTERVAL: 60}, **{CONF_ACCESS_LEVEL: "general"})
        if result["type"] == "menu":
            result = await _advance(hass, result)
    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
