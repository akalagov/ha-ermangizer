"""Per-pump Modbus operations: reads, writes and layout autodetection.

Sits between the coordinator and the shared gateway connection. Every request
is issued under the gateway lock, because RS-485 is half duplex and a second
request on the bus while one is in flight corrupts both.

The outer ``asyncio.wait_for`` is deliberate: a stalled socket does not always
trip tmodbus' own timeout, and without a hard deadline one hung read would
block every other pump on the same bus indefinitely. The deadline is well
above the tmodbus default timeout, so it only fires on a genuinely stuck
connection, and hitting it triggers a forced reconnect.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from .const import (
    LAYOUT_LEGACY,
    LAYOUT_MODERN,
)
from .layouts import LAYOUT_MAP, Layout, params_for_access
from .models import ParamDef
from .protocol import ReadBlock, build_read_blocks, decode_word32, to_raw

_LOGGER = logging.getLogger(__name__)

# Hard deadline for one request; comfortably above the tmodbus default of
# 10 s so it fires only on a stuck connection, not on a slow-but-live one.
REQUEST_DEADLINE = 30.0


class PumpUnavailable(Exception):
    """A request failed or the connection looks stuck."""


# Parameters further apart than this are read in separate requests: the wasted
# registers inside a merged block cost less than an extra round trip, until the
# gap grows past a few parameters' worth of dead registers.
PARAM_BLOCK_MAX_GAP = 12


def _param_block(params: list[ParamDef]) -> ReadBlock:
    start = params[0].address
    return ReadBlock(start, params[-1].address - start + 1, tuple(params))


@dataclass
class PumpData:
    """One pump on a shared gateway."""

    layout: Layout
    unit_id: int
    gateway: Any  # GatewayHandle
    params: list[ParamDef] = field(default_factory=list)
    _fast_blocks: list[ReadBlock] = field(default_factory=list, repr=False)
    _slow_blocks: list[ReadBlock] = field(default_factory=list, repr=False)
    _param_blocks: list[ReadBlock] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        fast = [reg for reg in self.layout.registers if reg.fast]
        slow = [reg for reg in self.layout.registers if not reg.fast]
        self._fast_blocks = build_read_blocks(fast, self.layout.max_read_input, 8, 1)
        self._slow_blocks = build_read_blocks(slow, self.layout.max_read_input, 8, 1)
        self._param_blocks = self._build_param_blocks()

    def _build_param_blocks(self) -> list[ReadBlock]:
        """Group writable parameters into function 0x03 reads.

        Parameters are sparse (P001..P238 maps to 1001..1238), so reading the
        whole span would fetch ~240 registers per cycle. Blocks split wherever
        the gap between consecutive parameters exceeds PARAM_BLOCK_MAX_GAP, and
        are capped at the device's function 0x03 limit.
        """
        if not self.params:
            return []
        ordered = sorted(self.params, key=lambda param: param.address)
        blocks: list[ReadBlock] = []
        current: list[ParamDef] = [ordered[0]]
        for param in ordered[1:]:
            start = current[0].address
            gap = param.address - current[-1].address
            span = param.address - start + 1
            if gap > PARAM_BLOCK_MAX_GAP or span > self.layout.max_read_holding:
                blocks.append(_param_block(current))
                current = [param]
            else:
                current.append(param)
        blocks.append(_param_block(current))
        return blocks

    async def _request(self, coro: Any, what: str) -> Any:
        async with self.gateway.lock:
            try:
                return await asyncio.wait_for(coro, REQUEST_DEADLINE)
            except asyncio.TimeoutError as exc:
                if self.gateway.should_recreate_now():
                    await self.gateway.recreate(f"{what} exceeded {REQUEST_DEADLINE}s")
                raise PumpUnavailable(
                    f"Timed out after {REQUEST_DEADLINE}s on {what}"
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise PumpUnavailable(f"{what} failed: {exc}") from exc

    async def _read_block(self, client: Any, block: ReadBlock, function: int) -> dict[int, int]:
        """Read one block and return {address: raw value}."""
        if function == 0x04:
            values = await self._request(
                client.read_input_registers(block.start_address, block.quantity),
                f"read_input_registers({block.start_address}+{block.quantity})",
            )
        else:
            values = await self._request(
                client.read_holding_registers(block.start_address, block.quantity),
                f"read_holding_registers({block.start_address}+{block.quantity})",
            )
        if values is None or len(values) < block.quantity:
            got = 0 if values is None else len(values)
            raise PumpUnavailable(
                f"Short read at {block.start_address}: {got} of {block.quantity} registers"
            )
        return {block.start_address + offset: int(raw) for offset, raw in enumerate(values)}

    async def read_inputs(self, fast: bool) -> dict[int, int]:
        """Read the telemetry block, returning raw values by address."""
        client = self.gateway.client_for(self.unit_id)
        blocks = self._fast_blocks if fast else self._slow_blocks
        out: dict[int, int] = {}
        for block in blocks:
            out.update(await self._read_block(client, block, 0x04))
        return out

    async def read_parameters(self) -> dict[str, int]:
        """Read the configured parameters, returning raw values by key."""
        if not self._param_blocks:
            return {}
        client = self.gateway.client_for(self.unit_id)
        raw_by_address: dict[int, int] = {}
        for block in self._param_blocks:
            raw_by_address.update(await self._read_block(client, block, 0x03))
        return {
            param.key: raw_by_address[param.address]
            for param in self.params
            if param.address in raw_by_address
        }

    async def read_parameter(self, param: ParamDef) -> int:
        """Read one parameter's raw value (for refresh after a write)."""
        client = self.gateway.client_for(self.unit_id)
        block = ReadBlock(param.address, 1, (param,))
        values = await self._read_block(client, block, 0x03)
        return values[param.address]

    async def write_parameter(self, param: ParamDef, value: float) -> int:
        """Write one parameter, returning the raw value sent."""
        raw = to_raw(value, param.scale, param.min_value, param.max_value)
        client = self.gateway.client_for(self.unit_id)
        await self._request(
            client.write_single_register(param.address, raw),
            f"write_single_register({param.address}={raw})",
        )
        return raw

    async def write_raw(self, param: ParamDef, raw: int) -> None:
        """Write a parameter's raw register value (enumerations, where the
        code is already what the register holds)."""
        client = self.gateway.client_for(self.unit_id)
        await self._request(
            client.write_single_register(param.address, raw),
            f"write_single_register({param.address}={raw})",
        )

    async def pulse_coil(self, address: int) -> None:
        """Energise a control coil; the device handles it as a command."""
        client = self.gateway.client_for(self.unit_id)
        await self._request(
            client.write_single_coil(address, True),
            f"write_single_coil({address}=on)",
        )

def decode_registers(layout: Layout, raw: dict[int, int]) -> dict[str, Any]:
    """Turn raw input-register values into engineering values plus decoded
    state and alarm fields."""
    from . import codes

    out: dict[str, Any] = {}
    for reg in layout.registers:
        if reg.address not in raw:
            continue
        value = raw[reg.address]
        if reg.count == 2:
            low = raw.get(reg.address + 1)
            if low is None:
                continue
            value = decode_word32(value, low)
        out[reg.key] = {"raw": value, "value": round(value * reg.scale, 6)}

    status_raw = raw.get(layout.status_register.address)
    alarm_raw = raw.get(layout.alarm_register.address)
    if layout.id == LAYOUT_LEGACY:
        decode_status, decode_alarm = codes.decode_legacy_status, codes.decode_legacy_alarm
    else:
        decode_status, decode_alarm = codes.decode_modern_status, codes.decode_modern_alarm
    if status_raw is not None:
        decoded = decode_status(status_raw)
        out["state"] = decoded["state"]
        out["state_label"] = decoded["state_label"]
        out["motor_overload"] = decoded["motor_overload"]
    if alarm_raw is not None:
        out["alarms"] = decode_alarm(alarm_raw)
    return out


async def detect_layout(pump: PumpData) -> str:
    """Probe which register map the device answers on.

    The two generations disagree on where telemetry lives and on whether
    status is a bit field or an enumeration, so guessing is not an option.
    Reads one status register from each map and reports which one answered.
    """
    client = pump.gateway.client_for(pump.unit_id)
    answers: dict[str, bool] = {}
    for layout_id in (LAYOUT_MODERN, LAYOUT_LEGACY):
        candidate = LAYOUT_MAP[layout_id]
        address = candidate.status_register.address
        try:
            values = await pump._read_block(  # noqa: SLF001 - same module family
                client, ReadBlock(address, 1, (candidate.status_register,)), 0x04
            )
            answers[layout_id] = address in values
        except PumpUnavailable:
            answers[layout_id] = False
    if answers.get(LAYOUT_MODERN) and not answers.get(LAYOUT_LEGACY):
        return LAYOUT_MODERN
    if answers.get(LAYOUT_LEGACY) and not answers.get(LAYOUT_MODERN):
        return LAYOUT_LEGACY
    # Both answered (a legacy device may answer a read at 2004 with zeros) or
    # neither did. Prefer legacy: it is the map the older firmware responds on,
    # and a wrong modern guess yields plausible-looking zeros rather than an
    # obvious failure.
    _LOGGER.info(
        "Ermangizer layout autodetection inconclusive (modern=%s legacy=%s), using %s",
        answers.get(LAYOUT_MODERN), answers.get(LAYOUT_LEGACY), LAYOUT_LEGACY,
    )
    return LAYOUT_LEGACY


def build_pump(layout: Layout, unit_id: int, gateway: Any, access_level: str) -> PumpData:
    return PumpData(
        layout=layout,
        unit_id=unit_id,
        gateway=gateway,
        params=params_for_access(layout, access_level),
    )
