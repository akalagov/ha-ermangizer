"""The two Modbus register generations Ermangizer pump controllers ship with.

The maps are mutually exclusive and the firmware decides which one answers -
the same ER-G-220-02 has been seen running either, so the layout is a per
device setting with an autodetection helper rather than a model constant.

``legacy_220_01``
    "Протокол связи MODBUS" for ER-G-220-01(02), doc v1.4 (FW 1.0.9.2).
    Telemetry in the low input-register block (1, 3, 5, 6, 12), a 32-bit status
    word at 1024 and a latched alarm word at 1026. Control registers use raw
    addresses (2 = frequency setpoint, 12/13 = ramp times); there are no Pnnn
    aliases.

``modern_220_02_05``
    "Протокол связи MODBUS" for ERG-220-05, doc 1.2 (17.01.2025), which the
    manufacturer extends to ER-G-220-02. Telemetry is a contiguous block at
    2000+ and menu parameters live at holding register ``1000 + nnn``.

Pressure at legacy input register 26 is not in doc v1.4, which predates the
pressure-based pump controller and marks 0x000D-0x03FF as reserved. It is
listed because it reads on some production ER-G-220-02 units, but others refuse
it with illegal data address — it is firmware-dependent, so PROVENANCE in
models.py records it as such and the integration tolerates it being absent.
"""
from __future__ import annotations

from .const import (
    ACCESS_ADVANCED,
    ACCESS_FACTORY,
    ACCESS_GENERAL,
    ACCESS_MONITOR,
    LAYOUT_LEGACY,
    LAYOUT_MODERN,
)
from .models import CoilDef, Layout, ParamDef, RegisterDef
from .params import MODERN_PARAMS

# --- Coils -----------------------------------------------------------------
# 0, 1, 2 and 9 are documented in both generations. EEPROM save/load (5, 7)
# and the Y1/Y2 outputs (13, 14) are documented for the modern generation
# only; the legacy layout omits them so the UI does not offer coils that may
# not exist there.
COILS_LEGACY = (
    CoilDef("start", 0, "Пуск", icon="mdi:play"),
    CoilDef("stop", 1, "Стоп", icon="mdi:stop"),
    CoilDef("emergency_stop", 2, "Аварийная остановка", icon="mdi:alert-octagon"),
    CoilDef("reset_alarm", 9, "Сброс аварии", icon="mdi:alert-circle"),
)

COILS_MODERN = COILS_LEGACY + (
    CoilDef("save_eeprom", 5, "Сохранить параметры в ПЗУ", icon="mdi:content-save"),
    CoilDef("load_eeprom", 7, "Загрузить параметры из ПЗУ", icon="mdi:content-save-alert"),
    CoilDef("output_y1", 13, "Дискретный выход Y1", icon="mdi:relay"),
    CoilDef("output_y2", 14, "Дискретный выход Y2", icon="mdi:relay"),
)

# --- Legacy telemetry ------------------------------------------------------
LEGACY_REGISTERS = (
    RegisterDef("frequency", 1, "Частота на выходе", "Hz", "frequency", "measurement", 0.1),
    RegisterDef("current", 3, "Ток двигателя", "A", "current", "measurement", 0.1),
    RegisterDef("dc_voltage", 5, "Выпрямленное напряжение", "V", "voltage", "measurement"),
    RegisterDef("temperature", 6, "Температура радиатора", "°C", "temperature", "measurement"),
    RegisterDef("output_voltage", 12, "Напряжение на выходе", "V", "voltage", "measurement"),
    RegisterDef("pressure", 26, "Давление", "bar", "pressure", "measurement", 0.01),
    RegisterDef("status", 1024, "Состояние (сырое)", None, None, None, 1.0, 2,
                diagnostic=True, entity_registry_enabled_default=False, fast=True),
    RegisterDef("alarm", 1026, "Код аварии (сырой)", None, None, None, 1.0, 2,
                diagnostic=True, entity_registry_enabled_default=False, fast=True),
)

# --- Modern telemetry ------------------------------------------------------
MODERN_REGISTERS = (
    RegisterDef("frequency", 2000, "Частота на выходе", "Hz", "frequency", "measurement", 0.1),
    RegisterDef("current", 2001, "Ток двигателя", "A", "current", "measurement", 0.1),
    RegisterDef("input_voltage", 2002, "Входное напряжение", "V", "voltage", "measurement"),
    RegisterDef("temperature", 2003, "Температура ПЧ", "°C", "temperature", "measurement"),
    RegisterDef("status", 2004, "Состояние (сырое)", None, None, None, 1.0, 1,
                diagnostic=True, entity_registry_enabled_default=False, fast=True),
    RegisterDef("alarm", 2005, "Код ошибки (сырой)", None, None, None, 1.0, 1,
                diagnostic=True, entity_registry_enabled_default=False, fast=True),
    RegisterDef("pressure", 2006, "Давление", "bar", "pressure", "measurement", 0.01),
    RegisterDef("firmware", 2007, "Версия ПО", None, None, None, 1.0, 1,
                icon="mdi:chip", device_info=True),
    RegisterDef("ai_a1", 2008, "Сигнал входа А1", "%", None, "measurement", 1.0, 1,
                entity_registry_enabled_default=False),
    RegisterDef("ai_a2", 2009, "Сигнал входа А2", "%", None, "measurement", 1.0, 1,
                entity_registry_enabled_default=False),
)

# --- Legacy control registers ----------------------------------------------
# No Pnnn aliases in this generation; the addresses come from doc v1.4 and the
# scales from its "weight per digit" column.
LEGACY_PARAMS = (
    ParamDef(
        key="setpoint_frequency", address=2, name="Задание частоты",
        access=ACCESS_GENERAL, unit="Hz", scale=0.1, min_value=0.0, max_value=100.0,
        step=0.1, icon="mdi:speedometer"),
    ParamDef(
        key="max_frequency", address=3, name="Максимальная частота",
        access=ACCESS_ADVANCED, unit="Hz", scale=0.1, min_value=0.0, max_value=100.0,
        step=0.1, entity_registry_enabled_default=False),
    ParamDef(
        key="min_frequency", address=4, name="Минимальная частота",
        access=ACCESS_ADVANCED, unit="Hz", scale=0.1, min_value=0.0, max_value=100.0,
        step=0.1, entity_registry_enabled_default=False),
    ParamDef(
        key="carrier_frequency", address=11, name="Несущая частота",
        access=ACCESS_FACTORY, unit="kHz", scale=0.1, min_value=0.0, max_value=16.0,
        step=0.1, entity_registry_enabled_default=False),
    ParamDef(
        key="ramp_up", address=12, name="Время разгона", access=ACCESS_ADVANCED,
        unit="s", scale=0.1, min_value=0.0, max_value=600.0, step=0.1,
        icon="mdi:speedometer-slow"),
    ParamDef(
        key="ramp_down", address=13, name="Время торможения", access=ACCESS_ADVANCED,
        unit="s", scale=0.1, min_value=0.0, max_value=600.0, step=0.1,
        icon="mdi:speedometer-slow"),
    ParamDef(
        key="brake_threshold", address=21, name="Порог динамического торможения",
        access=ACCESS_FACTORY, unit="V", min_value=0.0, max_value=400.0,
        entity_registry_enabled_default=False),
)

LAYOUT_MAP: dict[str, Layout] = {
    LAYOUT_LEGACY: Layout(
        id=LAYOUT_LEGACY,
        title="ER-G-220-01(02) — классическая карта",
        registers=LEGACY_REGISTERS,
        params=LEGACY_PARAMS,
        coils=COILS_LEGACY,
        has_param_aliases=False,
    ),
    LAYOUT_MODERN: Layout(
        id=LAYOUT_MODERN,
        title="ER-G-220-02 / ERG-220-05 — карта 2025 года",
        registers=MODERN_REGISTERS,
        params=MODERN_PARAMS,
        coils=COILS_MODERN,
    ),
}

_ACCESS_RANK = {ACCESS_GENERAL: 0, ACCESS_ADVANCED: 1, ACCESS_FACTORY: 2}


def layout_by_id(layout_id: str) -> Layout:
    try:
        return LAYOUT_MAP[layout_id]
    except KeyError:
        raise KeyError(f"Unknown layout: {layout_id!r}") from None


def params_for_access(layout: Layout, access_level: str) -> list[ParamDef]:
    """Parameters visible at or below the configured access level.

    Monitoring mode returns nothing: a read-only deployment gets no writable
    entity at all, rather than a set that merely happens to be harmless.
    """
    if access_level == ACCESS_MONITOR:
        return []
    limit = _ACCESS_RANK.get(access_level, 0)
    return [param for param in layout.params if _ACCESS_RANK[param.access] <= limit]
