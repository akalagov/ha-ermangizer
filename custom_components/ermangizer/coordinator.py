"""Data update coordinator for one Ermangizer pump.

Two poll rates share one coordinator. The status word is read every cycle
because automations act on run/stop transitions; the analogue telemetry is read
only once its own interval has elapsed, because on a half duplex bus every
extra request displaces traffic from other devices on the same line.

The fast cycle therefore reads a fraction of what is published, and carries the
rest of the last slow reading forward. Without that, every telemetry sensor and
every parameter would go unknown for all but one cycle in
`slow_poll_interval` — with the defaults, one second in sixty.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_ACCESS_LEVEL,
    CONF_LAYOUT,
    CONF_POLL_INTERVAL,
    CONF_SLOW_POLL_INTERVAL,
    CONF_UNIT_ID,
    ACCESS_GENERAL,
    LAYOUT_LEGACY,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SLOW_POLL_INTERVAL,
    LAYOUT_AUTO,
)
from .layouts import layout_by_id
from .pump import (
    PumpData,
    PumpUnavailable,
    build_pump,
    decode_registers,
    detect_layout,
)

_LOGGER = logging.getLogger(__name__)


class ErmangizerCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll one pump and expose its decoded state."""

    def __init__(
        self,
        hass: HomeAssistant,
        gateway,
        *,
        name: str,
        unit_id: int,
        layout_id: str,
        access_level: str,
        poll_interval: int,
        slow_poll_interval: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=name,
            update_interval=timedelta(seconds=poll_interval),
        )
        self.unit_id = unit_id
        self.gateway = gateway
        self._requested_layout_id = layout_id
        self._access_level = access_level
        self._slow_poll_interval = slow_poll_interval
        self._pump: PumpData | None = None
        self._slow_deadline = 0.0
        # Telemetry and parameters are read on the slow interval; the fast
        # cycle reads only the status words, so it republishes the last slow
        # reading instead of dropping it.
        self._last_raw: dict[int, int] = {}
        self._last_parameters: dict[str, int] = {}

    @property
    def pump(self) -> PumpData:
        if self._pump is None:
            raise UpdateFailed("Pump not yet resolved")
        return self._pump

    @property
    def layout_id(self) -> str:
        return self._pump.layout.id if self._pump else self._requested_layout_id

    async def _async_setup(self) -> None:
        """Resolve the register layout before the first poll.

        Autodetection needs the connection, which is why it happens here rather
        than in the constructor.
        """
        if self._requested_layout_id == LAYOUT_AUTO:
            probe = build_pump(
                layout_by_id(LAYOUT_LEGACY), self.unit_id, self.gateway, ACCESS_GENERAL
            )
            resolved = await detect_layout(probe)
            _LOGGER.debug("Ermangizer unit %s: detected layout %s", self.unit_id, resolved)
        else:
            resolved = self._requested_layout_id
        self._pump = build_pump(
            layout_by_id(resolved), self.unit_id, self.gateway, self._access_level
        )

    async def _async_update_data(self) -> dict[str, Any]:
        pump = self.pump
        now = monotonic()
        read_slow = now >= self._slow_deadline
        try:
            raw = await pump.read_inputs(fast=True)
            if read_slow:
                raw.update(await pump.read_inputs(fast=False))
                if pump.params:
                    self._last_parameters = await pump.read_parameters()
            else:
                raw = {**self._last_raw, **raw}
        except PumpUnavailable as exc:
            raise UpdateFailed(str(exc)) from exc

        if read_slow:
            # Floor at the fast interval so a slow interval of zero still
            # reads telemetry once per cycle rather than thrashing the bus.
            self._slow_deadline = now + max(self._slow_poll_interval, self.update_interval.total_seconds())
            # A slow cycle read every register, so it is the new baseline. A
            # register the device stopped answering drops out here rather than
            # lingering forever.
            self._last_raw = raw

        data = decode_registers(pump.layout, raw)
        data["parameters"] = self._last_parameters
        data["slow_poll"] = read_slow
        data["layout"] = pump.layout.id
        return data


async def async_create_coordinator(
    hass: HomeAssistant, gateway, subentry_data: dict[str, Any], name: str
) -> ErmangizerCoordinator:
    """Build a coordinator for one pump subentry."""
    return ErmangizerCoordinator(
        hass,
        gateway,
        name=name,
        unit_id=int(subentry_data[CONF_UNIT_ID]),
        layout_id=subentry_data.get(CONF_LAYOUT, LAYOUT_AUTO),
        access_level=subentry_data.get(CONF_ACCESS_LEVEL, ACCESS_GENERAL),
        poll_interval=int(subentry_data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)),
        slow_poll_interval=int(
            subentry_data.get(CONF_SLOW_POLL_INTERVAL, DEFAULT_SLOW_POLL_INTERVAL)
        ),
    )
