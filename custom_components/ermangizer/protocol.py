"""Pure Modbus helpers: CRC-16, RTU frames and read-block grouping.

No Home Assistant and no tmodbus imports, so both the integration and the
standalone probe script can share it, and it is testable on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .models import RegisterDef

# --- CRC-16 ----------------------------------------------------------------
# Modbus CRC-16, polynomial 0xA001 (bit-reflected 0x8005), initial value
# 0xFFFF, transmitted low byte first. Doc v1.4 section 9 confirms the
# polynomial; the frame examples in that document pin the byte order.
def _build_crc_table() -> tuple[int, ...]:
    table = []
    for index in range(256):
        crc = index
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        table.append(crc)
    return tuple(table)


_CRC_TABLE = _build_crc_table()


def crc16(data: bytes) -> int:
    """Modbus CRC-16 of ``data`` as an integer (low byte goes first on wire)."""
    crc = 0xFFFF
    for byte in data:
        crc = _CRC_TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc


def append_crc(frame: bytes) -> bytes:
    """Append the CRC to a frame, low byte first."""
    return frame + bytes((crc16(frame) & 0xFF, crc16(frame) >> 8))


def check_crc(frame: bytes) -> bool:
    """Whether a received frame carries its own correct CRC."""
    if len(frame) < 4:
        return False
    body, received = frame[:-2], frame[-2] | (frame[-1] << 8)
    return crc16(body) == received


# --- RTU request/response helpers (used by the probe script) ---------------
def read_request(unit_id: int, function: int, address: int, quantity: int) -> bytes:
    """Build a read request frame (functions 0x01/0x03/0x04)."""
    return append_crc(bytes((unit_id, function)) + address.to_bytes(2, "big") + quantity.to_bytes(2, "big"))


def write_register_request(unit_id: int, address: int, value: int) -> bytes:
    """Build a function 0x06 write-single-register frame."""
    return append_crc(bytes((unit_id, 0x06)) + address.to_bytes(2, "big") + value.to_bytes(2, "big"))


def write_coil_request(unit_id: int, address: int, on: bool) -> bytes:
    """Build a function 0x05 write-single-coil frame (0xFF00 on, 0x0000 off)."""
    return append_crc(bytes((unit_id, 0x05)) + address.to_bytes(2, "big") + (0xFF00 if on else 0).to_bytes(2, "big"))


def parse_read_response(frame: bytes) -> list[int]:
    """Register values from a function 0x03/0x04 response.

    Raises ValueError on a malformed frame or an exception response, so a probe
    run reports a rejected address instead of silently returning nothing.
    """
    if not check_crc(frame):
        raise ValueError("bad CRC")
    function = frame[1]
    if function & 0x80:
        reasons = {0x01: "illegal function", 0x02: "illegal data address",
                   0x03: "illegal data address on read", 0x04: "illegal data address on write"}
        reason = reasons.get(frame[2], f"exception code {frame[2]}")
        raise ValueError(f"exception response: {reason}")
    byte_count = frame[2]
    payload = frame[3:3 + byte_count]
    if len(payload) != byte_count:
        raise ValueError(f"short payload: {len(payload)} of {byte_count} bytes")
    return [int.from_bytes(payload[i:i + 2], "big") for i in range(0, byte_count, 2)]


# --- Read block grouping ---------------------------------------------------
@dataclass(frozen=True)
class ReadBlock:
    """One read request covering several registers.

    ``registers`` holds the RegisterDefs for input-register blocks or the
    ParamDefs for parameter blocks; both are addressed identically.
    """

    start_address: int
    quantity: int
    registers: tuple[Any, ...]

    @property
    def end_address(self) -> int:
        return self.start_address + self.quantity


def build_read_blocks(
    registers: Sequence[RegisterDef],
    max_block_size: int,
    max_gap: int,
    min_quantity: int = 1,
) -> list[ReadBlock]:
    """Group registers into as few read requests as possible.

    Merging adjacent registers costs a few wasted registers but saves a round
    trip, which matters on a half duplex bus. ``max_block_size`` must respect
    the device limit (the ER-G rejects function 0x04 reads over 0x11
    registers); ``min_quantity`` pads a block so a single-register poll still
    fetches a useful slice.
    """
    ordered = sorted(registers, key=lambda reg: reg.address)
    blocks: list[ReadBlock] = []
    current: list[RegisterDef] = []

    def flush() -> None:
        if not current:
            return
        start = current[0].address
        end = max(reg.address + reg.count for reg in current)
        quantity = max(end - start, min_quantity)
        blocks.append(ReadBlock(start, quantity, tuple(current)))

    for reg in ordered:
        if current:
            start = current[0].address
            gap = reg.address - max(prev.address + prev.count for prev in current)
            span = reg.address + reg.count - start
            if gap > max_gap or span > max_block_size:
                flush()
                current = []
        current.append(reg)
    flush()
    return blocks


# --- Value conversion ------------------------------------------------------
def to_engineering(raw: int, scale: float) -> float:
    """Raw register value to engineering units, without float noise."""
    return round(raw * scale, 6)


def to_raw(value: float, scale: float, min_value: float, max_value: float) -> int:
    """Engineering value to a register value, clamped to the documented range.

    Rounding (not truncation) matters: a 4.00 kgsc setpoint at scale 0.01 must
    become 400, and floating point makes 4.00 * 100 equal 399.99999999999994.
    """
    if scale <= 0:
        raise ValueError(f"scale must be positive, got {scale}")
    raw = int(round(value / scale))
    return max(int(round(min_value / scale)), min(int(round(max_value / scale)), raw))


def decode_word32(high: int, low: int) -> int:
    """Combine two 16-bit registers, high word first (big endian)."""
    return (high << 16) | low
