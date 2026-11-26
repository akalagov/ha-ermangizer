"""Data models for register maps, shared by the two layout generations.

Units, device classes and state classes are kept as plain strings so this
module imports and tests cleanly without Home Assistant installed; the entity
platforms translate them to HA enums.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegisterDef:
    """One read-only input register (function 0x04)."""

    key: str
    address: int
    name: str
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None
    scale: float = 1.0
    # 32-bit values occupy two registers, big endian (high word first).
    count: int = 1
    icon: str | None = None
    # Raw values stay available for diagnostics even where a decoded sensor
    # exists, so an undocumented code is never hidden.
    diagnostic: bool = False
    entity_registry_enabled_default: bool = True
    # Polled on the fast interval (state) or the slow one (telemetry).
    fast: bool = False


@dataclass(frozen=True)
class ParamDef:
    """One read/write holding register (function 0x03 / 0x06)."""

    key: str
    address: int
    name: str
    access: str
    unit: str | None = None
    scale: float = 1.0
    min_value: float = 0.0
    max_value: float = 100.0
    step: float = 1.0
    # Enumeration options for select entities: {raw value: label}.
    options: dict[int, str] | None = None
    icon: str | None = None
    entity_registry_enabled_default: bool = True
    # Warning shown in the UI for parameters that change how the pump runs.
    warns: str | None = None

    @property
    def is_enum(self) -> bool:
        return self.options is not None


@dataclass(frozen=True)
class CoilDef:
    """One control coil (function 0x01 / 0x05)."""

    key: str
    address: int
    name: str
    icon: str | None = None


@dataclass(frozen=True)
class Layout:
    """Everything the coordinator and entity platforms need about one map."""

    id: str
    title: str
    registers: tuple[RegisterDef, ...]
    params: tuple[ParamDef, ...]
    coils: tuple[CoilDef, ...]
    # The device rejects function 0x04 reads longer than 0x11 registers and
    # 0x03 reads longer than 0x58 (doc v1.4, sections 6 and 7).
    max_read_input: int = 17
    max_read_holding: int = 88
    # Whether this generation exposes menu parameters as Pnnn aliases.
    has_param_aliases: bool = True
    status_register: RegisterDef = field(init=False)
    alarm_register: RegisterDef = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "status_register", self.register_by_key("status"))
        object.__setattr__(self, "alarm_register", self.register_by_key("alarm"))

    def register_by_key(self, key: str) -> RegisterDef:
        for reg in self.registers:
            if reg.key == key:
                return reg
        raise KeyError(key)

    def param_by_key(self, key: str) -> ParamDef:
        for param in self.params:
            if param.key == key:
                return param
        raise KeyError(key)

    def coil_by_key(self, key: str) -> CoilDef:
        for coil in self.coils:
            if coil.key == key:
                return coil
        raise KeyError(key)


def param_address(param: str) -> int:
    """Holding-register address of menu parameter ``Pnnn``: swap P for 1.

    Documented in the ER-G-220-02 manual and the ERG-220-05 protocol:
    P117 -> 1117 (0x045D), P005 -> 1005 (0x03ED), P206 -> 1206 (0x04B6).
    """
    if not param.upper().startswith("P") or not param[1:].isdigit():
        raise ValueError(f"Not a parameter name: {param!r}")
    return 1000 + int(param[1:])


# Which document each layout was transcribed from, and what was confirmed on
# hardware instead of read from paper.
PROVENANCE = {
    "legacy_220_01": {
        "source": "protocol_modbus_er-g-220-01.pdf (doc v1.4, FW 1.0.9.2)",
        "hardware_verified": ["pressure"],
    },
    "modern_220_02_05": {
        "source": "protocol_modbus_erg-220-05.pdf (doc 1.2, 17.01.2025)",
        "hardware_verified": [],
    },
}
