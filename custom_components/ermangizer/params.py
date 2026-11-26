"""Menu parameters of the ER-G-220-02 / ERG-220-05 register generation.

Addresses are derived from the parameter name (see ``param_address``), so this
table only records what the manufacturer documents: name, unit, scale, range
and enumeration options. Ranges and factory defaults come from the ER-G-220-02
manual (table 6) and "Заводские настройки" (doc 1.6); scales come from the
ERG-220-05 protocol, which is the only document that states them.

Deliberately absent: parameters the manufacturer marks as read-only probes
(P202, P221-P226, P235, P237, P239, P240) and one-shot resets (P199, P220),
which would be dangerous as writable entities.
"""
from __future__ import annotations

from .const import ACCESS_ADVANCED, ACCESS_FACTORY, ACCESS_GENERAL
from .models import ParamDef, param_address

# The manual documents pressures in kgf/cm2 and scales the registers to
# match. They are labelled bar instead, one-to-one and without
# conversion: a setpoint of 3 shown in Home Assistant is 3 on the device
# display and 300 in the register. The unit is therefore ~2% off the
# physical one (1 kgf/cm2 = 0.980665 bar) - a deliberate trade of exactness
# for matching the hardware. See README.
PRESSURE = "bar"
FREQ = "Hz"


def _p(
    param: str,
    name: str,
    access: str,
    *,
    unit: str | None = None,
    scale: float = 1.0,
    min_value: float = 0.0,
    max_value: float = 100.0,
    step: float = 1.0,
    options: dict[int, str] | None = None,
    icon: str | None = None,
    enabled: bool = True,
    warns: str | None = None,
) -> ParamDef:
    return ParamDef(
        key=param.lower(),
        address=param_address(param),
        name=name,
        access=access,
        unit=unit,
        scale=scale,
        min_value=min_value,
        max_value=max_value,
        step=step,
        options=options,
        icon=icon,
        entity_registry_enabled_default=enabled,
        warns=warns,
    )


_RELAY_OPTIONS = {
    0: "Не используется",
    1: "Авария",
    2: "Работа",
    3: "Достигнута заданная частота",
    4: "Управление через Modbus",
    5: "Реле времени",
}

_DIGITAL_INPUT_OPTIONS = {
    0: "Не используется",
    1: "ПУСК/СТОП",
    4: "АВАРИЯ",
    5: "БЛОКИРОВКА ПУСКА",
}

# General settings (P001-P099)
GENERAL_PARAMS: tuple[ParamDef, ...] = (
    _p("P001", "Уставка давления", ACCESS_GENERAL, unit=PRESSURE, scale=0.01,
       max_value=16.0, step=0.01, icon="mdi:gauge"),
    _p("P002", "Коэффициент пропорциональности ПИ", ACCESS_GENERAL, scale=0.01,
       max_value=10.0, step=0.01),
    _p("P003", "Время интегрирования ПИ", ACCESS_GENERAL, unit="s", scale=0.01,
       min_value=0.1, max_value=10.0, step=0.01),
    _p("P004", "Длительность пуска", ACCESS_GENERAL, unit="s", max_value=30.0),
    _p("P005", "Аварийный порог давления", ACCESS_GENERAL, unit=PRESSURE, scale=0.01,
       max_value=16.0, step=0.01),
    _p("P006", "Предел датчика давления", ACCESS_GENERAL, unit=PRESSURE, scale=0.01,
       min_value=1.0, max_value=16.0, step=0.01),
    _p("P008", "Режим главного меню", ACCESS_GENERAL, max_value=1,
       options={0: "Текущее давление", 1: "Текущая частота"}, enabled=False),
    _p("P009", "Мягкий старт", ACCESS_GENERAL, max_value=1,
       options={0: "Выкл", 1: "Вкл"}, enabled=False),
    _p("P010", "Коррекция ошибки ПИ-регулятора", ACCESS_GENERAL, max_value=1,
       options={0: "Выкл", 1: "Вкл"}, enabled=False),
    _p("P011", "Погрешность поддержания давления", ACCESS_GENERAL, unit=PRESSURE,
       scale=0.01, max_value=1.0, step=0.01),
    _p("P099", "Уровень доступа", ACCESS_GENERAL, max_value=2,
       options={0: "Общие", 1: "Расширенные", 2: "Заводские"}, enabled=False),
)

# Advanced settings (P100-P145)
ADVANCED_PARAMS: tuple[ParamDef, ...] = (
    _p("P100", "Режим работы", ACCESS_ADVANCED, max_value=3,
       options={0: "Регулирование давления", 1: "Ручное задание частоты",
                2: "Частота по RS-485", 3: "Частота от аналогового входа"},
       icon="mdi:cog-sync"),
    _p("P101", "Частота при ручном задании", ACCESS_ADVANCED, unit=FREQ, scale=0.1,
       max_value=50.0, step=0.1),
    _p("P102", "Верхний предел частоты", ACCESS_ADVANCED, unit=FREQ, scale=0.1,
       max_value=50.0, step=0.1),
    _p("P103", "Нижний предел частоты", ACCESS_ADVANCED, unit=FREQ, scale=0.1,
       max_value=50.0, step=0.1),
    _p("P104", "Пусковая частота", ACCESS_ADVANCED, unit=FREQ, scale=0.1,
       max_value=60.0, step=0.1, enabled=False),
    _p("P105", "Начальное напряжение пусковой частоты", ACCESS_ADVANCED, unit="%",
       max_value=100.0, enabled=False),
    _p("P106", "Частота проверки пуска двигателя", ACCESS_ADVANCED, unit=FREQ, scale=0.1,
       max_value=50.0, step=0.1, enabled=False),
    _p("P107", "Время ожидания пуска двигателя", ACCESS_ADVANCED, unit="s",
       max_value=120.0, enabled=False),
    _p("P108", "Период тестирования на протечку", ACCESS_ADVANCED, unit="s",
       max_value=600.0, enabled=False),
    _p("P109", "Разность давлений определения протечки", ACCESS_ADVANCED, unit=PRESSURE,
       scale=0.01, max_value=16.0, step=0.01, enabled=False),
    _p("P110", "Период тестирования расхода", ACCESS_ADVANCED, unit="s",
       min_value=1.0, max_value=600.0, enabled=False),
    _p("P111", "Разность давлений определения расхода", ACCESS_ADVANCED, unit=PRESSURE,
       scale=0.01, max_value=16.0, step=0.01, enabled=False),
    _p("P112", "Длительность тестирования", ACCESS_ADVANCED, unit="s", min_value=10.0,
       max_value=60.0, enabled=False),
    _p("P113", "Порог срабатывания сухого хода", ACCESS_ADVANCED, unit=PRESSURE,
       scale=0.01, max_value=16.0, step=0.01),
    _p("P114", "Время срабатывания сухого хода", ACCESS_ADVANCED, unit="s",
       max_value=600.0),
    _p("P115", "Разница давления для запуска", ACCESS_ADVANCED, unit=PRESSURE,
       scale=0.01, max_value=16.0, step=0.01),
    _p("P116", "Разница давления для определения пуска", ACCESS_ADVANCED, unit=PRESSURE,
       scale=0.01, max_value=16.0, step=0.01, enabled=False),
    _p("P117", "Способ запуска", ACCESS_ADVANCED, max_value=2,
       options={0: "Панель управления", 1: "Дискретный вход", 2: "RS-485"},
       icon="mdi:play-network",
       warns="При способе «RS-485» запуск с панели управления не работает."),
    _p("P118", "Функция дискретного выхода Y1", ACCESS_ADVANCED, max_value=5,
       options=_RELAY_OPTIONS, enabled=False),
    _p("P119", "Состояние выхода Y1", ACCESS_ADVANCED, max_value=1,
       options={0: "Нормально разомкнут", 1: "Нормально замкнут"}, enabled=False),
    _p("P120", "Функция дискретного выхода Y2", ACCESS_ADVANCED, max_value=5,
       options=_RELAY_OPTIONS, enabled=False),
    _p("P121", "Состояние выхода Y2", ACCESS_ADVANCED, max_value=1,
       options={0: "Нормально разомкнут", 1: "Нормально замкнут"}, enabled=False),
    _p("P122", "Адрес устройства MODBUS", ACCESS_ADVANCED, min_value=1, max_value=31,
       icon="mdi:numeric",
       warns="После смены адреса устройство будет недоступно, пока не измените "
             "адрес в настройках интеграции."),
    _p("P123", "Скорость RS-485", ACCESS_ADVANCED, max_value=6,
       options={0: "1,2 кбит/с", 1: "2,4 кбит/с", 2: "4,8 кбит/с", 3: "9,6 кбит/с",
                4: "19,2 кбит/с", 5: "38,4 кбит/с", 6: "57,6 кбит/с"},
       enabled=False, warns="Смена скорости разорвёт связь до перенастройки шлюза."),
    _p("P124", "Токовый вход датчика давления", ACCESS_ADVANCED, max_value=3,
       options={0: "Автоопределение", 1: "AI1", 2: "AI2", 3: "AI1+AI2"}, enabled=False),
    _p("P125", "Состояние при подаче питания", ACCESS_ADVANCED, max_value=2,
       options={0: "Остановлен", 1: "Восстановить последнее", 2: "Запустить насос"},
       enabled=False),
    _p("P126", "Режим сна", ACCESS_ADVANCED, max_value=1,
       options={0: "Включён", 1: "Выключен"}),
    _p("P144", "Лимит непрерывной работы", ACCESS_ADVANCED, unit="h", max_value=24.0,
       enabled=False),
    _p("P145", "Лимит включений в час", ACCESS_ADVANCED, max_value=90, enabled=False),
)

# Factory settings (P200-P250)
FACTORY_PARAMS: tuple[ParamDef, ...] = (
    _p("P200", "Верхняя калибровка датчика A1", ACCESS_FACTORY, max_value=2000.0,
       enabled=False),
    _p("P201", "Нижняя калибровка датчика A1", ACCESS_FACTORY, min_value=-500.0,
       max_value=2000.0, enabled=False),
    _p("P203", "Режим обработки ошибок", ACCESS_FACTORY, max_value=2,
       options={0: "Перезапуск: E tH, E P1",
                1: "Перезапуск: + E FA, E C1, E Ul, E UH",
                2: "Перезапуск: + E SH"}, enabled=False),
    _p("P204", "Нижний аварийный порог напряжения", ACCESS_FACTORY, unit="V",
       min_value=150.0, max_value=300.0, enabled=False),
    _p("P205", "Частота модуляции", ACCESS_FACTORY, unit="kHz", scale=0.1,
       min_value=1.5, max_value=8.0, step=0.1, enabled=False),
    _p("P206", "Температура ограничения частоты", ACCESS_FACTORY, unit="°C",
       min_value=50.0, max_value=90.0, enabled=False),
    _p("P207", "Время разгона", ACCESS_FACTORY, unit="s", scale=0.1, min_value=1.0,
       max_value=60.0, step=0.1),
    _p("P208", "Время торможения", ACCESS_FACTORY, unit="s", scale=0.1, min_value=1.0,
       max_value=60.0, step=0.1),
    _p("P209", "Номинальный ток двигателя", ACCESS_FACTORY, unit="A", scale=0.1,
       max_value=30.0, step=0.1, enabled=False),
    _p("P210", "Номинальное напряжение двигателя", ACCESS_FACTORY, unit="V",
       min_value=110.0, max_value=260.0, enabled=False),
    _p("P214", "Тип двигателя", ACCESS_FACTORY, min_value=1, max_value=3,
       options={1: "Однофазный 220 В", 2: "Двухфазный 160 В", 3: "Трёхфазный 220 В"},
       enabled=False, warns="Неверное значение выводит насос из строя."),
    _p("P215", "Направление вращения", ACCESS_FACTORY, max_value=1,
       options={0: "Прямое", 1: "Обратное"}, enabled=False,
       warns="Менять только на остановленном насосе."),
    _p("P216", "Ограничение тока при разгоне", ACCESS_FACTORY, unit="%",
       min_value=20.0, max_value=150.0, enabled=False),
    _p("P228", "Порог включения вентилятора", ACCESS_FACTORY, unit="°C",
       max_value=90.0, enabled=False),
    _p("P229", "Порог отключения вентилятора", ACCESS_FACTORY, unit="°C",
       max_value=90.0, enabled=False),
    _p("P230", "Функция входа X1", ACCESS_FACTORY, max_value=5,
       options=_DIGITAL_INPUT_OPTIONS, enabled=False),
    _p("P231", "Функция входа X2", ACCESS_FACTORY, max_value=5,
       options=_DIGITAL_INPUT_OPTIONS, enabled=False),
    _p("P232", "Функция входа X3", ACCESS_FACTORY, max_value=5,
       options=_DIGITAL_INPUT_OPTIONS, enabled=False),
    _p("P236", "Период ШИМ вентилятора", ACCESS_FACTORY, unit="%", max_value=100.0,
       enabled=False),
    _p("P238", "Яркость индикатора", ACCESS_FACTORY, min_value=2, max_value=9,
       enabled=False),
)

MODERN_PARAMS: tuple[ParamDef, ...] = GENERAL_PARAMS + ADVANCED_PARAMS + FACTORY_PARAMS
