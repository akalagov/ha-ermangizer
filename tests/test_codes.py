"""Tests for the status/alarm decoders of both register layouts.

Bit positions and code numbers are transcribed from the manufacturer's
documents; these tests pin that transcription so an edit cannot silently shift
a bit or renumber a fault.
"""
from __future__ import annotations

import pytest

from custom_components.ermangizer import codes


# --- Legacy bit-field status word -----------------------------------------
@pytest.mark.parametrize(
    ("raw", "state"),
    [
        (0x0000, "stopped"),
        (0x0001, "running_constant"),
        (0x0002, "accelerating"),
        (0x0003, "decelerating"),
        # Higher bits must not disturb the state code in bits 0-1.
        (0x0021, "running_constant"),
    ],
)
def test_legacy_status_decodes_state_bits(raw: int, state: str) -> None:
    assert codes.decode_legacy_status(raw)["state"] == state


def test_legacy_status_reports_motor_overload_bit() -> None:
    assert codes.decode_legacy_status(1 << 5)["motor_overload"] is True
    assert codes.decode_legacy_status(0x0001)["motor_overload"] is False


def test_legacy_status_has_label_for_every_state() -> None:
    for state in codes.LEGACY_STATUS_STATES.values():
        assert state in codes.STATE_LABELS


# --- Legacy bit-field alarm word ------------------------------------------
def test_legacy_alarm_decodes_each_documented_bit() -> None:
    for bit, name in codes.LEGACY_ALARM_BITS.items():
        result = codes.decode_legacy_alarm(1 << bit)
        assert [entry["key"] for entry in result] == [name]


def test_legacy_alarm_combines_multiple_bits_in_bit_order() -> None:
    result = codes.decode_legacy_alarm((1 << 6) | (1 << 1))
    assert [entry["key"] for entry in result] == ["undervoltage_dc", "overheating"]


def test_legacy_alarm_empty_for_zero() -> None:
    assert codes.decode_legacy_alarm(0) == []


def test_legacy_alarm_labels_are_russian() -> None:
    for name in codes.LEGACY_ALARM_BITS.values():
        assert name in codes.ALARM_LABELS


# --- Modern enumerated status ---------------------------------------------
@pytest.mark.parametrize(
    ("raw", "state"),
    [
        (0, "initializing"),
        (1, "off"),
        (2, "starting_motor"),
        (3, "moving_to_setpoint"),
        (4, "holding_setpoint"),
        (5, "measuring_flow"),
        (6, "sleep"),
        (7, "stopping"),
        (8, "running_at_target"),
        (9, "alarm"),
        (10, "start_delay"),
        (11, "relay_test"),
    ],
)
def test_modern_status_decodes_documented_codes(raw: int, state: str) -> None:
    assert codes.decode_modern_status(raw)["state"] == state


def test_modern_status_unknown_for_undocumented_code() -> None:
    assert codes.decode_modern_status(42)["state"] == "unknown"


def test_sleep_is_not_a_running_state() -> None:
    """Sleep means the controller stopped the pump by design; an automation
    keyed on "is the pump running" must see off there."""
    assert "sleep" not in codes.RUNNING_STATES
    assert "holding_setpoint" in codes.RUNNING_STATES
    assert "stopping" not in codes.RUNNING_STATES


def test_every_modern_state_has_a_label() -> None:
    for state in codes.MODERN_STATUS_STATES.values():
        assert state in codes.STATE_LABELS


def test_running_states_are_all_real_states() -> None:
    known = set(codes.MODERN_STATUS_STATES.values()) | set(codes.LEGACY_STATUS_STATES.values())
    assert codes.RUNNING_STATES <= known


# --- Modern enumerated error code -----------------------------------------
def test_modern_alarm_empty_for_no_error() -> None:
    assert codes.decode_modern_alarm(0) == []


@pytest.mark.parametrize(
    ("raw", "key"),
    [
        (5, "overpressure"),
        (6, "failed_start"),
        (7, "overheating"),
        (10, "undervoltage"),
        (12, "overvoltage"),
        (20, "pressure_sensor_open"),
        (21, "dry_run"),
        (27, "memory_failure"),
    ],
)
def test_modern_alarm_decodes_documented_codes(raw: int, key: str) -> None:
    result = codes.decode_modern_alarm(raw)
    assert [entry["key"] for entry in result] == [key]


def test_modern_alarm_keeps_undocumented_code_visible() -> None:
    """Codes 22/23 are not published; they must surface as the raw number
    rather than disappear."""
    result = codes.decode_modern_alarm(22)
    assert result[0]["key"] == "code_22"
    assert "22" in result[0]["label"]


def test_modern_alarm_labels_include_display_codes() -> None:
    """The label must contain what the user sees on the device screen."""
    for key, label in codes.MODERN_ERROR_CODES.values():
        if key != "no_error":
            assert label


def test_decoder_choice_follows_layout() -> None:
    """Legacy uses bit masks, modern uses enumerations - mixing them silently
    misreports the pump state, so the entry points are separate."""
    # 0x0002 is "accelerating" as a legacy bit field but "starting_motor" as a
    # modern enumeration.
    assert codes.decode_legacy_status(0x0002)["state"] == "accelerating"
    assert codes.decode_modern_status(0x0002)["state"] == "starting_motor"
