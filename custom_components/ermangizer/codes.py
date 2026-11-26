"""Decoding tables for the status and alarm words of both register layouts.

Sources:
- "Протокол связи MODBUS" for ER-G-220-01(02), doc v1.4 - status word at input
  register 1024 and alarm word at 1026, both documented as bit fields.
- "Протокол связи MODBUS" for ERG-220-05 (doc 1.2, 17.01.2025) - status and
  error codes at input registers 2004/2005 as enumerated values, and the note
  that ER-G-220-02 shares this protocol generation.

Bit fields and enumerations are transcribed verbatim; where the manufacturer
marks a bit or code as reserved it is left out rather than guessed at.
"""
from __future__ import annotations

# --- Legacy layout: status word is a bit field -----------------------------
# Bits 0-1 carry a state code, bit 5 a motor overload flag.
LEGACY_STATUS_STATES = {
    0x00: "stopped",
    0x01: "running_constant",
    0x02: "accelerating",
    0x03: "decelerating",
}

LEGACY_ALARM_BITS = {
    0: "emergency_stop",
    1: "undervoltage_dc",
    2: "overvoltage_dc",
    3: "motor_undercurrent",
    4: "motor_overcurrent",
    5: "inverter_short_circuit",
    6: "overheating",
    7: "pwm_fault",
    10: "system_error",
    11: "system_reset",
}

# Human readable labels for the decoded state keys above.
STATE_LABELS = {
    "stopped": "Остановлен",
    "running_constant": "Работает, частота постоянна",
    "accelerating": "Разгон",
    "decelerating": "Торможение",
    "initializing": "Инициализация",
    "off": "Выключен",
    "starting_motor": "Запуск двигателя",
    "moving_to_setpoint": "Движение к уставке",
    "holding_setpoint": "Поддержание уставки",
    "measuring_flow": "Определение расхода",
    "sleep": "Сон",
    "stopping": "Остановка",
    "running_at_target": "Работа на заданной частоте",
    "alarm": "Авария",
    "start_delay": "Задержка перед пуском",
    "relay_test": "Тест реле перед пуском",
    "unknown": "Неизвестное состояние",
}

ALARM_LABELS = {
    "emergency_stop": "Аварийная остановка",
    "undervoltage_dc": "Низкое напряжение VDC",
    "overvoltage_dc": "Высокое напряжение VDC",
    "motor_undercurrent": "Низкий ток двигателя",
    "motor_overcurrent": "Ток двигателя превысил порог",
    "inverter_short_circuit": "Авария инвертора (КЗ)",
    "overheating": "Перегрев",
    "pwm_fault": "Авария ШИМ-модулятора",
    "system_error": "Системная ошибка",
    "system_reset": "Системный сброс",
}


def decode_legacy_status(raw: int) -> dict[str, object]:
    """Split the legacy status word into its documented fields."""
    state = LEGACY_STATUS_STATES.get(raw & 0x03, "unknown")
    return {
        "state": state,
        "state_label": STATE_LABELS[state],
        "motor_overload": bool(raw & (1 << 5)),
    }


def decode_legacy_alarm(raw: int) -> list[dict[str, str]]:
    """Active alarm flags in the legacy alarm word.

    The word documents "код последней аварии", so it is a latch: it keeps the
    last fault until it is cleared. Callers should treat a nonzero result as
    "these faults were reported", not necessarily "happening right now".
    """
    return [
        {"key": name, "label": ALARM_LABELS.get(name, name), "bit": bit}
        for bit, name in sorted(LEGACY_ALARM_BITS.items())
        if raw & (1 << bit)
    ]


# --- Modern layout: status and error are enumerations ----------------------
MODERN_STATUS_STATES = {
    0: "initializing",
    1: "off",
    2: "starting_motor",
    3: "moving_to_setpoint",
    4: "holding_setpoint",
    5: "measuring_flow",
    6: "sleep",
    7: "stopping",
    8: "running_at_target",
    9: "alarm",
    10: "start_delay",
    11: "relay_test",
}

# States in which the pump motor is driven. Sleep and relay test are excluded:
# in sleep the controller has stopped the pump by design, the relay test only
# energises the output relays.
RUNNING_STATES = frozenset(
    {"running_constant", "accelerating", "decelerating", "starting_motor",
     "moving_to_setpoint", "holding_setpoint", "running_at_target"}
)

# Codes 22 and 23 are not listed by the manufacturer; they are left unmapped
# rather than invented.
MODERN_ERROR_CODES = {
    0: ("no_error", "Нет ошибки"),
    4: ("err1", "Ошибка 1 (Err1)"),
    5: ("overpressure", "Высокое давление (E P1)"),
    6: ("failed_start", "Неудачный пуск (E FA)"),
    7: ("overheating", "Перегрев (E tH)"),
    8: ("overcurrent", "Ток насоса выше допустимого (E C1)"),
    9: ("fault_current", "Аварийный ток нагрузки (E C2)"),
    10: ("undervoltage", "Низкое напряжение (E UL)"),
    11: ("external_fault", "Внешняя авария (E Er)"),
    12: ("overvoltage", "Высокое напряжение (E UH)"),
    13: ("undervoltage_u3", "Пониженное напряжение U3 (E U3)"),
    14: ("undervoltage_u4", "Пониженное напряжение U4 (E U4)"),
    15: ("undervoltage_u5", "Пониженное напряжение U5 (E U5)"),
    16: ("undervoltage_u6", "Пониженное напряжение U6 (E U6)"),
    17: ("undervoltage_u7", "Пониженное напряжение U7 (E U7)"),
    18: ("undervoltage_u8", "Пониженное напряжение U8 (E U8)"),
    19: ("undervoltage_u9", "Пониженное напряжение U9 (E U9)"),
    20: ("pressure_sensor_open", "Обрыв датчика давления (E S1)"),
    21: ("dry_run", "Сухой ход (E SH)"),
    24: ("pressure_sensor_overload", "Перегрузка входа датчика давления (E S2)"),
    25: ("charge_relay_failure", "Отказ зарядного реле (E rF)"),
    26: ("impulse_overcurrent", "Импульсная перегрузка по току (E C3)"),
    27: ("memory_failure", "Сбой памяти (E rr)"),
    28: ("config_fault", "Ошибка конфигурации (E CF)"),
}


def decode_modern_status(raw: int) -> dict[str, object]:
    state = MODERN_STATUS_STATES.get(raw, "unknown")
    return {
        "state": state,
        "state_label": STATE_LABELS[state],
        "motor_overload": False,
    }


def decode_modern_alarm(raw: int) -> list[dict[str, str]]:
    """Decode the modern error code into a single-entry list.

    Unlike the legacy layout the modern one reports one code, not a bitmask,
    so the result is empty for code 0 and for codes the manufacturer does not
    document (those keep the raw number so they stay visible).
    """
    if raw == 0:
        return []
    entry = MODERN_ERROR_CODES.get(raw)
    if entry is None:
        return [{"key": f"code_{raw}", "label": f"Код {raw} (не описан)", "bit": raw}]
    key, label = entry
    return [{"key": key, "label": label, "bit": raw}]
