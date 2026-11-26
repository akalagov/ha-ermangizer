#!/usr/bin/env python3
"""Probe an Ermangizer pump controller over Modbus and report what it speaks.

Read-only: sends function 0x03/0x04 reads only, never a write. Run it before
adding the integration to Home Assistant, or when a device reports the wrong
values, to establish which register layout the firmware uses.

Usage (from a machine that can reach the device or gateway):

    # native Modbus TCP, e.g. a multi-port serial-to-Ethernet gateway
    ./probe_ermangizer.py --tcp 203.0.113.10:502 --unit 1

    # transparent RTU-over-TCP bridge
    ./probe_ermangizer.py --rtu-tcp 203.0.113.11:5020 --unit 8

    # USB-RS485 adapter on this machine
    ./probe_ermangizer.py --serial /dev/ttyUSB0 --unit 8 --baudrate 9600

Requires Python 3.11+. The serial transport needs pyserial (bundled with
Home Assistant). No other third-party dependency.
"""
from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from pathlib import Path

# Import the shared protocol module from the integration: works from a repo
# checkout, and inside Home Assistant, whose /config is already on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
try:
    from custom_components.ermangizer import protocol as proto
    from custom_components.ermangizer.const import LAYOUT_LEGACY, LAYOUT_MODERN
    from custom_components.ermangizer.layouts import LAYOUT_MAP
except ImportError as exc:  # pragma: no cover - operator-facing message
    sys.exit(f"Cannot import the integration ({exc}).\nRun this script from the repository root.")


# Addresses worth probing. Kept independent of the layout tables on purpose:
# the point is to discover the layout, so probing must not presuppose it.
PROBE_RANGES: list[tuple[str, int, int]] = [
    ("legacy telemetry", 0x04, 0, 16),
    # Probed alone: a read spanning 24..27 fails as a whole, which cannot say
    # which address the firmware refuses, and 26 is firmware-dependent.
    ("legacy pressure 26", 0x04, 26, 1),
    ("legacy status", 0x04, 1024, 4),
    ("modern telemetry", 0x04, 2000, 12),
    ("legacy control", 0x03, 0, 16),
    ("parameter P001-P012", 0x03, 1001, 12),
    ("parameter P100-P126", 0x03, 1100, 27),
    ("parameter P200-P215", 0x03, 1200, 16),
]


class Transport:
    """Minimal request/response plumbing for one Modbus peer."""

    def __init__(self, unit_id: int, timeout: float) -> None:
        self.unit_id = unit_id
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._serial = None
        self._rtu = True

    async def open(self, host: str | None, port: int | None, device: str | None,
                   baudrate: int, rtu_over_tcp: bool) -> None:
        self._rtu = rtu_over_tcp
        if device:
            try:
                import serial
            except ImportError:
                sys.exit("Serial transport needs pyserial: pip install pyserial")
            self._serial = serial.serial_for_url(
                device, baudrate=baudrate, timeout=self.timeout,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
            )
            return
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(str(host), int(port)), self.timeout
        )

    def close(self) -> None:
        if self._serial is not None:
            self._serial.close()
        if self._writer is not None:
            self._writer.close()

    def _drain(self) -> None:
        if self._serial is not None:
            self._serial.reset_input_buffer()
            return
        while self._reader is not None and not self._reader.at_eof():
            try:
                self._reader.read_nowait()
            except Exception:
                break

    async def exchange(self, request: bytes) -> bytes:
        """Send one request and return the complete response frame."""
        self._drain()
        if self._serial is not None:
            self._serial.write(request)
            self._serial.flush()
            return await asyncio.to_thread(self._serial.read, 256)
        assert self._writer is not None and self._reader is not None
        self._writer.write(request)
        await self._writer.drain()
        return await asyncio.wait_for(self._read_response(), self.timeout)

    async def _read_response(self) -> bytes:
        assert self._reader is not None
        if not self._rtu:
            # Modbus TCP: the MBAP header carries the length.
            header = await self._reader.readexactly(7)
            length = int.from_bytes(header[4:6], "big")
            return header + await self._reader.readexactly(length - 1)
        # RTU has no length field in the header, so read until the expected
        # frame size is reached, then let the inter-frame gap end the read.
        buffer = bytearray()
        needed = 0
        while True:
            try:
                chunk = await asyncio.wait_for(self._reader.read(256), 0.35)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) >= 3:
                needed = expected_rtu_frame_length(buffer)
                if len(buffer) >= needed:
                    break
        return bytes(buffer[:needed]) if needed and len(buffer) >= needed else bytes(buffer)


def expected_rtu_frame_length(frame: bytes) -> int:
    """Total frame length implied by a partial RTU response."""
    function = frame[1]
    if function & 0x80:
        return 5  # unit + function + exception code + CRC
    if function in (0x01, 0x02, 0x03, 0x04):
        return 3 + frame[2] + 2  # unit + function + byte count + data + CRC
    if function in (0x05, 0x06):
        return 8  # echo of the request
    if function == 0x0F:
        return 8
    if function == 0x10:
        return 8
    return 6


async def read_block(transport: Transport, function: int, start: int, quantity: int) -> list[int] | str:
    """Read registers, returning values or a short error string."""
    request = proto.read_request(transport.unit_id, function, start, quantity)
    if transport._rtu:
        response = await transport.exchange(request)
        if not response:
            return "no response"
        try:
            return proto.parse_read_response(response)
        except ValueError as exc:
            return str(exc)
    # Modbus TCP: no CRC on the wire. The MBAP length counts unit id + PDU, and
    # ``pdu`` here already starts with the unit id.
    pdu = request[:-2]
    frame = (1).to_bytes(2, "big") + (0).to_bytes(2, "big") + len(pdu).to_bytes(2, "big") + pdu
    response = await transport.exchange(frame)
    body = response[6:]  # drop the MBAP header, keep unit + PDU
    if len(body) < 3:
        return "no response"
    if body[1] & 0x80:
        return f"exception {body[2]}"
    byte_count = body[2]
    payload = body[3:3 + byte_count]
    return [int.from_bytes(payload[i:i + 2], "big") for i in range(0, byte_count, 2)]


def render(label: str, start: int, values: list[int] | str) -> str:
    if isinstance(values, str):
        return f"  {label:24s} @{start:<5d} {values}"
    lines = [f"  {label:24s} @{start:<5d} " + " ".join(f"{v:#06x}" for v in values[:12])]
    if len(values) > 12:
        lines.append(" " * 34 + "...")
    return "\n".join(lines)


def interpret(layout_id: str, inputs: dict[int, int]) -> list[str]:
    """Decode a layout's telemetry out of the function 0x04 readings."""
    from custom_components.ermangizer import codes

    layout = LAYOUT_MAP[layout_id]
    if layout.id == LAYOUT_LEGACY:
        decode_status, decode_alarm = codes.decode_legacy_status, codes.decode_legacy_alarm
    else:
        decode_status, decode_alarm = codes.decode_modern_status, codes.decode_modern_alarm
    out = []
    for reg in layout.registers:
        if reg.address not in inputs:
            continue
        raw = inputs[reg.address]
        if reg.count == 2:
            if reg.address + 1 not in inputs:
                continue
            high, low = raw, inputs[reg.address + 1]
            # Doc v1.4 says 1024-1025 form one 32-bit value but does not fix
            # the word order, so show both and let the live values decide.
            if reg.key in ("status", "alarm"):
                decoder = decode_status if reg.key == "status" else decode_alarm
                for order, combined in (("hi/lo", proto.decode_word32(high, low)),
                                        ("lo/hi", proto.decode_word32(low, high))):
                    if reg.key == "status":
                        detail = decoder(combined)["state_label"]
                    else:
                        active = decoder(combined)
                        detail = ", ".join(e["label"] for e in active) if active else "none"
                    out.append(f"    {reg.name:26s} {high:#06x} {low:#06x} ({order}) -> {detail}")
                continue
            raw = proto.decode_word32(high, low)
        if reg.key == "status":
            out.append(f"    {reg.name:26s} {raw} -> {decode_status(raw)['state_label']}")
        elif reg.key == "alarm":
            active = decode_alarm(raw)
            detail = ", ".join(e["label"] for e in active) if active else "none"
            out.append(f"    {reg.name:26s} {raw} -> {detail}")
        else:
            value = proto.to_engineering(raw, reg.scale)
            out.append(f"    {reg.name:26s} {value!r} {reg.unit or ''}".rstrip())
    return out


def detect_layout(inputs: dict[int, int]) -> list[str]:
    """Report which layout the observed input registers fit, and why."""
    verdicts = []
    for layout_id in (LAYOUT_LEGACY, LAYOUT_MODERN):
        layout = LAYOUT_MAP[layout_id]
        present = [reg.key for reg in layout.registers if reg.address in inputs]
        missing = [reg.key for reg in layout.registers if reg.address not in inputs]
        verdicts.append(f"  {layout.title}: read {len(present)}/{len(layout.registers)} "
                        f"(missing: {', '.join(missing) if missing else 'none'})")
    return verdicts


async def probe(args: argparse.Namespace) -> int:
    host, port, device = None, None, args.serial
    rtu_over_tcp = True
    if args.tcp:
        host, _, port = args.tcp.partition(":")
        rtu_over_tcp = False
    elif args.rtu_tcp:
        host, _, port = args.rtu_tcp.partition(":")
    elif not device:
        print("Give one of --tcp HOST:PORT, --rtu-tcp HOST:PORT or --serial DEVICE")
        return 2

    transport = Transport(args.unit, args.timeout)
    try:
        await transport.open(host, port or 502, device, args.baudrate, rtu_over_tcp)
    except (OSError, socket.timeout, asyncio.TimeoutError) as exc:
        print(f"Connection failed: {exc}")
        return 1
    except SystemExit:
        raise

    print(f"Connected: {'serial ' + device if device else f'{host}:{port} ' + ('RTU-over-TCP' if rtu_over_tcp else 'Modbus TCP')}, unit id {args.unit}")
    # Input (FC04) and holding (FC03) registers are separate address
    # spaces in Modbus; keeping them apart prevents one poll from
    # masquerading as the other.
    inputs: dict[int, int] = {}
    holdings: dict[int, int] = {}
    for label, function, start, quantity in PROBE_RANGES:
        if quantity > 17 and function == 0x04:
            quantity = 17  # the device rejects longer function 0x04 reads
        try:
            values = await read_block(transport, function, start, quantity)
        except (asyncio.TimeoutError, socket.timeout):
            values = "timeout"
        except asyncio.IncompleteReadError:
            values = "connection closed"
        print(render(f"FC{function:02d} {label}", start, values))
        if isinstance(values, list):
            target = inputs if function == 0x04 else holdings
            for offset, value in enumerate(values):
                target[start + offset] = value
        await asyncio.sleep(args.delay / 1000)

    print("\n=== Layout detection ===")
    for line in detect_layout(inputs):
        print(line)

    print("\n=== Decoding ===")
    for layout_id in (LAYOUT_LEGACY, LAYOUT_MODERN):
        decoded = interpret(layout_id, inputs)
        if decoded:
            print(f"  {LAYOUT_MAP[layout_id].title}:")
            print("\n".join(decoded))

    transport.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--tcp", metavar="HOST:PORT", help="native Modbus TCP gateway")
    target.add_argument("--rtu-tcp", metavar="HOST:PORT", help="transparent RTU-over-TCP bridge")
    target.add_argument("--serial", metavar="DEVICE", help="serial device, e.g. /dev/ttyUSB0")
    parser.add_argument("--unit", type=int, default=1, help="Modbus unit id (default 1)")
    parser.add_argument("--baudrate", type=int, default=9600, help="serial baud rate (default 9600)")
    parser.add_argument("--timeout", type=float, default=5.0, help="seconds per request (default 5)")
    parser.add_argument("--delay", type=float, default=50.0, help="ms between requests (default 50)")
    args = parser.parse_args()
    try:
        return asyncio.run(probe(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
