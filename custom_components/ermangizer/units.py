"""Unit and device-class translation between the register tables and Home
Assistant.

No value is ever rescaled here: what the register holds is what the device
shows, and Home Assistant must agree with the display on the pump.
"""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfFrequency,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)

# Documented unit -> the Home Assistant unit it is shown as. Every entry is
# an identity today; the map exists so a unit Home Assistant spells differently
# (or does not define at all) is fixed in one place.
DISPLAY_UNIT = {
    "Hz": UnitOfFrequency.HERTZ,
    "V": UnitOfElectricPotential.VOLT,
    "A": UnitOfElectricCurrent.AMPERE,
    "°C": UnitOfTemperature.CELSIUS,
    "%": PERCENTAGE,
    "s": UnitOfTime.SECONDS,
    "bar": UnitOfPressure.BAR,
}

DEVICE_CLASS_BY_DISPLAY_UNIT = {
    UnitOfFrequency.HERTZ: SensorDeviceClass.FREQUENCY,
    UnitOfElectricPotential.VOLT: SensorDeviceClass.VOLTAGE,
    UnitOfElectricCurrent.AMPERE: SensorDeviceClass.CURRENT,
    UnitOfTemperature.CELSIUS: SensorDeviceClass.TEMPERATURE,
    UnitOfPressure.BAR: SensorDeviceClass.PRESSURE,
}

NUMBER_DEVICE_CLASS_BY_DISPLAY_UNIT = {
    UnitOfFrequency.HERTZ: NumberDeviceClass.FREQUENCY,
    UnitOfElectricPotential.VOLT: NumberDeviceClass.VOLTAGE,
    UnitOfElectricCurrent.AMPERE: NumberDeviceClass.CURRENT,
    UnitOfPressure.BAR: NumberDeviceClass.PRESSURE,
}


def display_unit(documented: str | None) -> str | None:
    """The unit to show for a value documented in ``documented``."""
    if documented is None:
        return None
    return DISPLAY_UNIT.get(documented, documented)
