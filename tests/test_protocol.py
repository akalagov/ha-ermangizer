"""Tests for the pure Modbus core: CRC, frames, scaling and block grouping.

Frame fixtures are copied verbatim from the manufacturer's protocol documents,
so a CRC or byte-order regression fails against the vendor's own examples
rather than against a self-consistent guess.
"""
from __future__ import annotations

import pytest

from custom_components.ermangizer import protocol as p

# --- CRC-16 ----------------------------------------------------------------
# Frames copied verbatim from the "MODBUS communication protocol" doc for ER-G-220-01(02)
# (sections 6-7) and from the ER-G-220-03 protocol / node-red-ermangizer-modbus
# README. DOC_FRAMES are the ones that validate; VENDOR_TYPOS documents the two
# that do not, with the reason.
DOC_FRAMES = [
    # read coils 0..11 from unit 1
    bytes.fromhex("01010000000C3C0F"),
    # read holding 1..4 from unit 1
    bytes.fromhex("01030001000415C9"),
    # write coil "start"
    bytes.fromhex("01050000FF008C3A"),
    # write coil "stop" (value 0x0000)
    bytes.fromhex("010500000000CDCA"),
    # write 28.5 Hz (0x011D) to register 1
    bytes.fromhex("01060001011D1993"),
    # write coils: "reset alarm" + "start" in one function 0x0F request
    bytes.fromhex("010F00000009020101252C"),
    # write ramp times 20.0 s / 40.0 s to 0x000C..0x000D
    bytes.fromhex("0110000C00020400C8019073F8"),
    # diagnostics, function 0x08
    bytes.fromhex("01080000A537DA8D"),
    # exception response: bad address on read holding
    bytes.fromhex("0183030131"),
    # response to "read holding 1..4"
    bytes.fromhex("010308010001F401F4003225C4"),
    # response to "read input 1..5" (byte count 0x10 as printed in the doc)
    bytes.fromhex("01041001F4000000D6000002320A03"),
    # ER-G-220-03: read request for 22 registers from unit 63
    bytes.fromhex("3F0300010016911A"),
    # ER-G-220-03: setpoint 4.00 bar written to 0x1000
    bytes.fromhex("3F06100001908828"),
    # ER-G-220-03: exception response
    bytes.fromhex("3F8302A13D"),
]

# Two frames in the manufacturer's PDFs fail CRC, and in both cases the
# document - not this implementation - is wrong. Pinned here so a future
# "fix" that loosens CRC checking is visible as a deliberate choice.
def test_vendor_read_input_request_carries_wrong_crc() -> None:
    """Doc v1.4 copies the read-holding CRC onto the read-input example.

    Both examples end in 15C9 although the requests differ; only the holding
    one is correct, so the read-input example is a copy-paste error.
    """
    assert p.crc16(bytes.fromhex("010300010004")) == 0xC915  # doc: 15C9 (low/first) - correct
    assert p.crc16(bytes.fromhex("010400010005")) == 0xC961  # doc: 15C9 - wrong
    assert not p.check_crc(bytes.fromhex("01040001000515C9"))


def test_vendor_response_example_prints_its_header_twice() -> None:
    """The ER-G-220-03 response example repeats "3F 03 2C"; without the
    duplicate the frame validates and decodes to the 22 documented values."""
    duplicated = bytes.fromhex(
        "3F032C3F032C01F4000100EA0020000000000001000000000001001E000A001E004C0014000A00F00000000600550000003F38EE"
    )
    corrected = bytes.fromhex(
        "3F032C01F4000100EA0020000000000001000000000001001E000A001E004C0014000A00F00000000600550000003F38EE"
    )
    assert not p.check_crc(duplicated)
    assert p.check_crc(corrected)
    values = p.parse_read_response(corrected)
    # Documented decoding: 50.0 Hz, 0.1 A, 234 V, 32 °C, 0.00 bar, no error.
    assert values[:5] == [500, 1, 234, 32, 0]
    assert len(values) == 22


@pytest.mark.parametrize("frame", DOC_FRAMES)
def test_crc_accepts_vendor_frames(frame: bytes) -> None:
    assert p.check_crc(frame), frame.hex()


def test_crc_detects_corruption() -> None:
    frame = bytes.fromhex("01030001000415C9")
    corrupted = bytearray(frame)
    corrupted[-1] ^= 0x01
    assert not p.check_crc(bytes(corrupted))


def test_append_crc_round_trips() -> None:
    body = bytes.fromhex("0106 0001 011D".replace(" ", ""))
    assert p.append_crc(body) == bytes.fromhex("01060001011D1993")


# --- Frame builders --------------------------------------------------------
def test_read_request_matches_document_example() -> None:
    assert p.read_request(1, 0x03, 1, 4) == bytes.fromhex("01030001000415C9")


def test_write_coil_request_matches_document_example() -> None:
    assert p.write_coil_request(1, 0, True) == bytes.fromhex("01050000FF008C3A")
    assert p.write_coil_request(1, 0, False) == bytes.fromhex("010500000000CDCA")


def test_write_register_request_matches_document_example() -> None:
    assert p.write_register_request(1, 1, 0x011D) == bytes.fromhex("01060001011D1993")


# --- Response parsing ------------------------------------------------------
def test_parse_read_response_returns_big_endian_words() -> None:
    # Response to "read holding 1..4": 0x0100 0x01F4 0x01F4 0x0032
    frame = bytes.fromhex("010308010001F401F4003225C4")
    assert p.check_crc(frame)
    assert p.parse_read_response(frame) == [0x0100, 0x01F4, 0x01F4, 0x0032]


def test_parse_read_response_decodes_document_voltage_block() -> None:
    """Values from the doc v1.4 "read input 1..5" example.

    The printed frame is internally inconsistent (byte count 0x10 with five
    registers, and a CRC copied from the read-holding example), so this fixture
    keeps the documented values with the byte count and CRC corrected.
    """
    frame = bytes.fromhex("01040A01F4000000D6000002327F1B")
    assert p.check_crc(frame)
    assert p.parse_read_response(frame) == [500, 0, 214, 0, 562]


@pytest.mark.parametrize(
    ("frame", "expected"),
    [
        (bytes.fromhex("01830180F0"), "illegal function"),
        (bytes.fromhex("018302C0F1"), "illegal data address"),
        # The frame printed in doc v1.4 section 6.
        (bytes.fromhex("0183030131"), "illegal data address on read"),
        (bytes.fromhex("01830440F3"), "illegal data address on write"),
    ],
)
def test_parse_read_response_raises_on_exception(frame: bytes, expected: str) -> None:
    with pytest.raises(ValueError, match=expected):
        p.parse_read_response(frame)


def test_parse_read_response_reports_unknown_exception_code() -> None:
    with pytest.raises(ValueError, match="exception code 9"):
        p.parse_read_response(p.append_crc(bytes.fromhex("018309")))


def test_parse_read_response_rejects_bad_crc() -> None:
    with pytest.raises(ValueError, match="bad CRC"):
        p.parse_read_response(bytes.fromhex("01030201F40000"))


def test_parse_read_response_rejects_short_payload() -> None:
    frame = p.append_crc(bytes.fromhex("0103080100"))
    with pytest.raises(ValueError, match="short payload"):
        p.parse_read_response(frame)


# --- Scaling ---------------------------------------------------------------
def test_to_raw_rounds_instead_of_truncating() -> None:
    # 4.00 / 0.01 is 399.99999999999994 in binary floating point.
    assert p.to_raw(4.00, 0.01, 0.0, 16.0) == 400
    assert p.to_raw(2.5, 0.01, 0.0, 16.0) == 250
    assert p.to_raw(50.0, 0.1, 0.0, 100.0) == 500


def test_to_raw_clamps_to_documented_range() -> None:
    assert p.to_raw(99.0, 0.01, 0.0, 16.0) == 1600
    assert p.to_raw(-5.0, 0.01, 0.0, 16.0) == 0
    # Negative ranges are documented (P201 lower calibration is negative).
    assert p.to_raw(-600.0, 1.0, -500.0, 2000.0) == -500


def test_to_engineering_is_exact() -> None:
    assert p.to_engineering(400, 0.01) == 4.0
    assert p.to_engineering(500, 0.1) == 50.0
    assert p.to_engineering(214, 1.0) == 214.0


def test_to_raw_rejects_zero_scale() -> None:
    with pytest.raises(ValueError, match="scale"):
        p.to_raw(1.0, 0.0, 0.0, 10.0)


def test_decode_word32_is_big_endian() -> None:
    assert p.decode_word32(0x0000, 0x0400) == 1024
    assert p.decode_word32(0x0001, 0x0000) == 65536


# --- Block grouping --------------------------------------------------------
def _regs(*addresses: int) -> list[p.RegisterDef]:
    return [p.RegisterDef(key=f"r{addr}", address=addr, name=str(addr)) for addr in addresses]


def test_contiguous_registers_merge_into_one_block() -> None:
    blocks = p.build_read_blocks(_regs(2000, 2001, 2002, 2003), 17, 8)
    assert len(blocks) == 1
    assert (blocks[0].start_address, blocks[0].quantity) == (2000, 4)


def test_large_gap_starts_a_new_block() -> None:
    blocks = p.build_read_blocks(_regs(1, 3, 1024), 17, 8)
    assert [(b.start_address, b.quantity) for b in blocks] == [(1, 3), (1024, 1)]


def test_block_never_exceeds_device_limit() -> None:
    blocks = p.build_read_blocks(_regs(*range(2000, 2020)), 17, 8)
    assert all(block.quantity <= 17 for block in blocks)
    assert sum(len(block.registers) for block in blocks) == 20


def test_min_quantity_pads_small_blocks() -> None:
    blocks = p.build_read_blocks(_regs(1024), 17, 8, min_quantity=16)
    assert (blocks[0].start_address, blocks[0].quantity) == (1024, 16)


def test_multiword_register_extends_block_span() -> None:
    regs = [
        p.RegisterDef(key="a", address=1024, name="a"),
        p.RegisterDef(key="b", address=1026, name="b", count=2),
    ]
    blocks = p.build_read_blocks(regs, 17, 8)
    assert (blocks[0].start_address, blocks[0].quantity) == (1024, 4)
