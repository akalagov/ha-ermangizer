"""Tests for the register maps: derived addresses, provenance and coherence.

The parameter-address rule (Pnnn -> 1000+nnn) is the load-bearing assumption of
every writable entity, so it is pinned against every worked example the
manufacturer gives, not just one.
"""
from __future__ import annotations

import pytest

from custom_components.ermangizer import layouts
from custom_components.ermangizer.const import (
    ACCESS_ADVANCED,
    ACCESS_FACTORY,
    ACCESS_GENERAL,
    LAYOUT_LEGACY,
    LAYOUT_MODERN,
)
from custom_components.ermangizer.models import param_address

# Worked examples transcribed from the ER-G-220-02 manual (section 10) and the
# ERG-220-05 protocol register table.
DOCUMENTED_ADDRESSES = [
    ("P001", 1001, 0x03E9),
    ("P005", 1005, 0x03ED),
    ("P100", 1100, 0x044C),
    ("P117", 1117, 0x045D),
    ("P122", 1122, 0x0462),
    ("P206", 1206, 0x04B6),
]


@pytest.mark.parametrize(("param", "decimal", "hexadecimal"), DOCUMENTED_ADDRESSES)
def test_param_address_matches_documented_examples(
    param: str, decimal: int, hexadecimal: int
) -> None:
    assert param_address(param) == decimal == hexadecimal


def test_param_address_accepts_lowercase() -> None:
    assert param_address("p117") == 1117


@pytest.mark.parametrize("bad", ["117", "PP1", "P1a", "", "X001"])
def test_param_address_rejects_non_parameters(bad: str) -> None:
    with pytest.raises(ValueError):
        param_address(bad)


def test_every_modern_param_uses_the_derived_address() -> None:
    """Guard against a hand-typed address drifting from the rule."""
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    for param in layout.params:
        assert param.address == param_address(param.key.upper()), param.key


def test_both_layouts_expose_the_core_telemetry() -> None:
    for layout_id in (LAYOUT_LEGACY, LAYOUT_MODERN):
        layout = layouts.layout_by_id(layout_id)
        for key in ("frequency", "current", "temperature", "pressure", "status", "alarm"):
            assert layout.register_by_key(key).key == key


def test_legacy_addresses_match_the_production_config() -> None:
    """The addresses a working YAML configuration reads today.

    These came from a live ER-G-220-02 on firmware older than the 2025
    protocol, so they are the strongest evidence available for this layout.
    """
    layout = layouts.layout_by_id(LAYOUT_LEGACY)
    expected = {
        "frequency": 1,
        "current": 3,
        "dc_voltage": 5,
        "temperature": 6,
        "output_voltage": 12,
        "pressure": 26,
        "status": 1024,
        "alarm": 1026,
    }
    assert {reg.key: reg.address for reg in layout.registers} == expected


def test_legacy_status_and_alarm_are_32_bit() -> None:
    """The production config reads both words as uint32; keep that."""
    layout = layouts.layout_by_id(LAYOUT_LEGACY)
    assert layout.status_register.count == 2
    assert layout.alarm_register.count == 2


def test_modern_status_and_alarm_are_16_bit() -> None:
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    assert layout.status_register.count == 1
    assert layout.alarm_register.count == 1


def test_modern_telemetry_is_one_contiguous_block() -> None:
    """2000..2009 reads in a single function 0x04 request."""
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    addresses = sorted(reg.address for reg in layout.registers)
    assert addresses == list(range(2000, 2000 + len(addresses)))
    assert len(addresses) <= layout.max_read_input


def test_pressure_scale_is_documented_in_both_layouts() -> None:
    for layout_id in (LAYOUT_LEGACY, LAYOUT_MODERN):
        layout = layouts.layout_by_id(layout_id)
        assert layout.register_by_key("pressure").scale == 0.01


def test_common_coils_exist_in_both_layouts() -> None:
    layout_legacy = layouts.layout_by_id(LAYOUT_LEGACY)
    layout_modern = layouts.layout_by_id(LAYOUT_MODERN)
    legacy_keys = {coil.key for coil in layout_legacy.coils}
    modern_keys = {coil.key for coil in layout_modern.coils}
    assert {"start", "stop", "emergency_stop", "reset_alarm"} <= legacy_keys
    # EEPROM save/load and the relay outputs are only documented for the
    # modern generation, so they must not be offered on the legacy one.
    assert {"save_eeprom", "load_eeprom", "output_y1", "output_y2"} <= modern_keys
    assert not {"save_eeprom", "load_eeprom"} & legacy_keys


def test_start_and_stop_are_the_documented_coil_addresses() -> None:
    for layout_id in (LAYOUT_LEGACY, LAYOUT_MODERN):
        layout = layouts.layout_by_id(layout_id)
        assert layout.coil_by_key("start").address == 0
        assert layout.coil_by_key("stop").address == 1
        assert layout.coil_by_key("emergency_stop").address == 2
        assert layout.coil_by_key("reset_alarm").address == 9


def test_control_coils_do_not_collide() -> None:
    for layout_id in (LAYOUT_LEGACY, LAYOUT_MODERN):
        layout = layouts.layout_by_id(layout_id)
        addresses = [coil.address for coil in layout.coils]
        assert len(addresses) == len(set(addresses))


def test_control_registers_do_not_collide_with_telemetry_semantics() -> None:
    """Legacy control registers are raw addresses in the same 16-bit space as
    the holding-register telemetry; duplicates would write the wrong thing."""
    layout = layouts.layout_by_id(LAYOUT_LEGACY)
    addresses = [param.address for param in layout.params]
    assert len(addresses) == len(set(addresses))


def test_access_levels_are_ordered_subsets() -> None:
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    general = {p.key for p in layouts.params_for_access(layout, ACCESS_GENERAL)}
    advanced = {p.key for p in layouts.params_for_access(layout, ACCESS_ADVANCED)}
    factory = {p.key for p in layouts.params_for_access(layout, ACCESS_FACTORY)}
    assert general < advanced < factory
    assert "p001" in general
    assert "p117" in advanced and "p117" not in general
    assert "p214" in factory and "p214" not in advanced


def test_monitor_level_exposes_no_parameters() -> None:
    """Monitoring-only mode must not create a single writable entity."""
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    assert layouts.params_for_access(layout, "monitor") == []


def test_unknown_access_level_falls_back_to_general() -> None:
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    assert {p.key for p in layouts.params_for_access(layout, "nonsense")} == {
        p.key for p in layouts.params_for_access(layout, ACCESS_GENERAL)
    }


def test_enumerated_parameters_have_options_inside_their_range() -> None:
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    for param in layout.params:
        if param.options:
            for option in param.options:
                assert param.min_value <= option <= param.max_value, param.key


def test_ranges_are_sane() -> None:
    for layout in layouts.LAYOUT_MAP.values():
        for param in layout.params:
            assert param.min_value < param.max_value, param.key
            assert param.scale > 0, param.key


def test_documented_scales_match_the_protocol_table() -> None:
    """Scales from the ERG-220-05 register table (the only document that
    states them for parameters)."""
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    expected = {
        "p001": 0.01,  # pressure setpoint
        "p002": 0.01,  # proportionality coefficient
        "p003": 0.01,  # integration time
        "p004": 1.0,   # start duration, s
        "p101": 0.1,   # manual setpoint frequency
        "p113": 0.01,  # dry-run threshold
        "p114": 1.0,   # dry-run time
        "p117": 1.0,   # start method (enum)
    }
    for key, scale in expected.items():
        assert layout.param_by_key(key).scale == scale, key


def test_dangerous_parameters_carry_a_warning() -> None:
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    for key in ("p117", "p122", "p123", "p214", "p215"):
        assert layout.param_by_key(key).warns, key


def test_motor_hardware_parameters_are_disabled_by_default() -> None:
    """Wrong values here damage the pump, so they stay hidden until the user
    opts in via the entity registry."""
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    for key in ("p214", "p215", "p200", "p201", "p209", "p210"):
        assert not layout.param_by_key(key).entity_registry_enabled_default, key


def test_read_limits_match_the_protocol() -> None:
    """Doc v1.4: function 0x04 accepts up to 0x11 registers, 0x03 up to 0x58."""
    for layout in layouts.LAYOUT_MAP.values():
        assert layout.max_read_input == 0x11
        assert layout.max_read_holding == 0x58


def test_param_aliases_only_exist_in_the_modern_generation() -> None:
    assert layouts.layout_by_id(LAYOUT_LEGACY).has_param_aliases is False
    assert layouts.layout_by_id(LAYOUT_MODERN).has_param_aliases is True


def test_layout_ids_are_the_constants() -> None:
    assert set(layouts.LAYOUT_MAP) == {LAYOUT_LEGACY, LAYOUT_MODERN}


def test_layout_by_id_rejects_unknown() -> None:
    with pytest.raises(KeyError, match="Unknown layout"):
        layouts.layout_by_id("nope")


def test_provenance_names_the_source_document_for_each_layout() -> None:
    from custom_components.ermangizer.models import PROVENANCE

    for layout_id in layouts.LAYOUT_MAP:
        entry = PROVENANCE[layout_id]
        assert ".pdf" in entry["source"]
    # Pressure in the legacy layout is the one entry known only from hardware.
    assert "pressure" in PROVENANCE[LAYOUT_LEGACY]["hardware_verified"]


def test_no_readonly_probe_parameter_is_exposed_as_writable() -> None:
    """P202/P221-P226/P235/P237/P239/P240 are display-only probes and P199/P220
    are one-shot resets; offering them as number/select entities is a trap."""
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    keys = {param.key for param in layout.params}
    for forbidden in ("p199", "p202", "p220", "p221", "p226", "p235", "p237", "p239", "p240"):
        assert forbidden not in keys


def test_access_constants_used_by_params_are_valid() -> None:
    layout = layouts.layout_by_id(LAYOUT_MODERN)
    valid = {ACCESS_GENERAL, ACCESS_ADVANCED, ACCESS_FACTORY}
    for param in layout.params:
        assert param.access in valid, param.key
