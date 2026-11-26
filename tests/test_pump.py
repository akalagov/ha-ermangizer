"""Tests for the pump-level Modbus operations.

A fake tmodbus client records requests and serves register tables, so these
exercise the real block grouping, scaling and layout detection rather than a
mock of our own logic.
"""
from __future__ import annotations

import asyncio

import pytest

from custom_components.ermangizer import pump as pump_mod
from custom_components.ermangizer.const import (
    ACCESS_ADVANCED,
    ACCESS_FACTORY,
    ACCESS_GENERAL,
    LAYOUT_LEGACY,
    LAYOUT_MODERN,
)
from custom_components.ermangizer.layouts import LAYOUT_MAP, layout_by_id
from custom_components.ermangizer.pump import PumpUnavailable, build_pump, decode_registers, detect_layout


class FakeClient:
    """Serves two register tables and records every request."""

    def __init__(self, inputs: dict[int, int], holdings: dict[int, int]) -> None:
        self.inputs = inputs
        self.holdings = holdings
        self.requests: list[tuple] = []
        self.writes: list[tuple] = []

    async def read_input_registers(self, address: int, quantity: int) -> list[int]:
        self.requests.append(("input", address, quantity))
        return [self.inputs.get(address + i, 0) for i in range(quantity)]

    async def read_holding_registers(self, address: int, quantity: int) -> list[int]:
        self.requests.append(("holding", address, quantity))
        return [self.holdings.get(address + i, 0) for i in range(quantity)]

    async def write_single_register(self, address: int, value: int) -> None:
        self.writes.append(("register", address, value))
        self.holdings[address] = value

    async def write_single_coil(self, address: int, value: bool) -> None:
        self.writes.append(("coil", address, value))


class FakeGateway:
    """Stands in for GatewayHandle: one client, one lock."""

    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.lock = asyncio.Lock()
        self.recreates = 0

    def client_for(self, unit_id: int) -> FakeClient:
        return self.client

    def should_recreate_now(self) -> bool:
        return True

    async def recreate(self, reason: str | None = None) -> None:
        self.recreates += 1


def make_pump(layout_id: str = LAYOUT_MODERN, access: str = ACCESS_GENERAL):
    client = FakeClient(
        inputs={2000: 500, 2001: 12, 2002: 226, 2003: 44, 2004: 4, 2005: 0,
                2006: 275, 2007: 1092, 2008: 60, 2009: 0},
        holdings={1001: 400, 1002: 100, 1003: 200, 1004: 10, 1005: 500, 1006: 1000},
    )
    gateway = FakeGateway(client)
    return build_pump(layout_by_id(layout_id), 8, gateway, access), client


async def test_fast_read_only_touches_fast_registers():
    pump, client = make_pump()
    await pump.read_inputs(fast=True)
    fast_addresses = {r.address for r in pump.layout.registers if r.fast}
    read = {addr + i for kind, addr, qty in client.requests for i in range(qty)}
    assert read == fast_addresses


async def test_scaled_decoding_and_state_labels():
    pump, _ = make_pump()
    raw = await pump.read_inputs(fast=False)
    data = decode_registers(pump.layout, raw)
    assert data["frequency"]["value"] == 50.0
    # Raw 275 -> 2.75, labelled bar: what the display shows, what the register
    # holds, what Home Assistant reports. No rescaling.
    assert data["pressure"]["value"] == 2.75
    assert data["state"] == "holding_setpoint"
    assert data["alarms"] == []


async def test_parameter_reads_are_grouped_into_few_requests():
    pump, client = make_pump(access=ACCESS_FACTORY)
    values = await pump.read_parameters()
    # General + advanced + factory spans P001..P238; one request per register
    # would be dozens, a single merged read would be 238 registers.
    assert len(client.requests) == len(pump._param_blocks)
    assert all(qty <= pump.layout.max_read_holding for _, _, qty in client.requests)
    assert values, "expected at least one parameter decoded"


async def test_wasted_registers_in_parameter_blocks_stay_bounded():
    pump, _ = make_pump(access=ACCESS_FACTORY)
    wasted = sum(block.quantity - len(block.registers) for block in pump._param_blocks)
    assert wasted < 60, f"parameter blocks read {wasted} registers nobody asked for"


async def test_write_parameter_scales_and_clamps():
    pump, client = make_pump(access=ACCESS_ADVANCED)
    param = next(p for p in pump.params if p.key == "p101")
    raw = await pump.write_parameter(param, 42.5)
    assert raw == 425
    assert client.writes == [("register", param.address, 425)]

    # Out of range is clamped to the documented bound, not rejected by us.
    raw = await pump.write_parameter(param, 999.0)
    assert raw == int(param.max_value / param.scale)


async def test_write_raw_sends_the_code_unchanged():
    pump, client = make_pump(access=ACCESS_ADVANCED)
    param = next(p for p in pump.params if p.key == "p117")
    await pump.write_raw(param, 2)
    assert client.writes == [("register", param.address, 2)]


async def test_coil_pulse_targets_the_documented_address():
    pump, client = make_pump()
    start = next(c for c in pump.layout.coils if c.key == "start")
    await pump.pulse_coil(start.address)
    assert client.writes == [("coil", start.address, True)]


async def test_short_read_raises_pump_unavailable():
    pump, client = make_pump()

    async def short(address, quantity):
        return [1]

    client.read_input_registers = short
    with pytest.raises(PumpUnavailable, match="Short read"):
        await pump.read_inputs(fast=True)


async def test_request_timeout_forces_reconnect(monkeypatch):
    pump, client = make_pump()
    monkeypatch.setattr(pump_mod, "REQUEST_DEADLINE", 0.01)

    async def slow(address, quantity):
        await asyncio.sleep(1)
        return []

    client.read_input_registers = slow
    with pytest.raises(PumpUnavailable, match="Timed out"):
        await pump.read_inputs(fast=True)
    assert pump.gateway.recreates == 1


async def test_detect_layout_picks_the_map_that_answers():
    # A modern device answers 2004 and refuses 1024 (exception -> our fake
    # returns nothing for an unmapped table, so emulate refusal with a raise).
    client = FakeClient(inputs={2004: 4}, holdings={})

    async def unknown_unit(address, quantity):
        raise RuntimeError("bad gateway target")

    client.read_input_registers = lambda a, q: (
        asyncio.sleep(0, result=[4]) if a == 2004 else unknown_unit(a, q)
    )
    gateway = FakeGateway(client)
    probe = build_pump(layout_by_id(LAYOUT_LEGACY), 8, gateway, ACCESS_GENERAL)
    assert await detect_layout(probe) == LAYOUT_MODERN


async def test_detect_layout_falls_back_to_legacy_when_both_answer():
    client = FakeClient(inputs={1024: 0, 2004: 0}, holdings={})
    gateway = FakeGateway(client)
    probe = build_pump(layout_by_id(LAYOUT_LEGACY), 8, gateway, ACCESS_GENERAL)
    assert await detect_layout(probe) == LAYOUT_LEGACY


async def test_every_layout_register_is_readable():
    """Guard against a register beyond the device's read limit."""
    for layout in LAYOUT_MAP.values():
        pump = build_pump(layout, 1, FakeGateway(FakeClient({}, {})), ACCESS_FACTORY)
        for block in pump._fast_blocks + pump._slow_blocks:
            assert block.quantity <= layout.max_read_input
