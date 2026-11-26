"""Config flow for the Ermangizer integration.

One config entry describes one physical bus (a gateway host/port or a serial
port); pumps on that bus are subentries, so several pumps on one RS-485 line
share a connection and its lock.
"""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigSubentryFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    ACCESS_GENERAL,
    ACCESS_LEVELS,
    CONF_ACCESS_LEVEL,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CONNECTION_TYPE,
    CONF_LAYOUT,
    CONF_PARITY,
    CONF_POLL_INTERVAL,
    CONF_SLOW_POLL_INTERVAL,
    CONF_STOPBITS,
    CONF_UNIT_ID,
    CONF_WAIT_BETWEEN_REQUESTS,
    CONNECTION_RTU_OVER_TCP,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    DEFAULT_BAUDRATE,
    DEFAULT_BYTESIZE,
    DEFAULT_PARITY,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_SLOW_POLL_INTERVAL,
    DEFAULT_STOPBITS,
    DEFAULT_TCP_PORT,
    DEFAULT_WAIT_BETWEEN_REQUESTS_NETWORK,
    DEFAULT_WAIT_BETWEEN_REQUESTS_SERIAL,
    DOMAIN,
    LAYOUT_AUTO,
    LAYOUT_LEGACY,
    LAYOUT_MODERN,
    PARITY_OPTIONS,
    SUBENTRY_TYPE_PUMP,
)
from .modbus_client import gateway_key

# Native Modbus TCP first: it is what a multi-port serial-to-Ethernet gateway
# presents, and the most common way these controllers reach Home Assistant.
CONNECTION_TYPE_OPTIONS = [CONNECTION_TCP, CONNECTION_RTU_OVER_TCP, CONNECTION_SERIAL]

LAYOUT_OPTIONS = [LAYOUT_AUTO, LAYOUT_LEGACY, LAYOUT_MODERN]

ACCESS_OPTIONS = list(ACCESS_LEVELS)


def _unit_id_selector() -> NumberSelector:
    # Box rather than slider: a precise Modbus address is hard to land on a
    # slider, especially on a phone.
    return NumberSelector(
        NumberSelectorConfig(min=1, max=247, step=1, mode=NumberSelectorMode.BOX)
    )


def _interval_selector(maximum: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(min=1, max=maximum, step=1, mode=NumberSelectorMode.BOX)
    )


def _translation_selector(options: list[str], key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST, translation_key=key)
    )


def _pump_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("name", default=defaults.get("name", "Ermangizer")): str,
            # NumberSelector returns a float even with step=1; coerce so the
            # stored unit_id is a plain int before it reaches struct.pack.
            vol.Required(
                CONF_UNIT_ID, default=defaults.get(CONF_UNIT_ID, 1)
            ): vol.All(_unit_id_selector(), vol.Coerce(int)),
            vol.Required(
                CONF_LAYOUT, default=defaults.get(CONF_LAYOUT, LAYOUT_AUTO)
            ): _translation_selector(LAYOUT_OPTIONS, "layout"),
            vol.Optional(
                CONF_POLL_INTERVAL,
                default=defaults.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            ): vol.All(_interval_selector(3600), vol.Coerce(int)),
            vol.Optional(
                CONF_SLOW_POLL_INTERVAL,
                default=defaults.get(CONF_SLOW_POLL_INTERVAL, DEFAULT_SLOW_POLL_INTERVAL),
            ): vol.All(_interval_selector(3600), vol.Coerce(int)),
            vol.Optional(
                CONF_ACCESS_LEVEL, default=defaults.get(CONF_ACCESS_LEVEL, ACCESS_GENERAL)
            ): _translation_selector(ACCESS_OPTIONS, "access_level"),
        }
    )


def _duplicate_unit_id(unit_id: int, others: list[dict[str, Any]]) -> bool:
    return any(pump.get(CONF_UNIT_ID) == unit_id for pump in others)


class ErmangizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow: bus first, then pumps on it."""

    def __init__(self) -> None:
        self._gateway_data: dict[str, Any] = {}
        self._pumps: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._gateway_data = {CONF_CONNECTION_TYPE: user_input[CONF_CONNECTION_TYPE]}
            if user_input[CONF_CONNECTION_TYPE] == CONNECTION_SERIAL:
                return await self.async_step_serial()
            return await self.async_step_network()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CONNECTION_TYPE, default=CONNECTION_TCP
                    ): _translation_selector(CONNECTION_TYPE_OPTIONS, "connection_type"),
                }
            ),
        )

    async def async_step_network(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._gateway_data["host"] = user_input["host"]
            self._gateway_data["tcp_port"] = user_input["tcp_port"]
            self._gateway_data[CONF_WAIT_BETWEEN_REQUESTS] = user_input[
                CONF_WAIT_BETWEEN_REQUESTS
            ]
            if self.source == config_entries.SOURCE_RECONFIGURE:
                return self._async_finish_reconfigure()
            return await self.async_step_pump()

        # A transparent RTU-over-TCP bridge is a serial bus underneath and
        # tends to need the same slack; a native Modbus TCP gateway queues
        # requests itself and usually tolerates a shorter pause.
        default_wait = self._gateway_data.get(
            CONF_WAIT_BETWEEN_REQUESTS,
            DEFAULT_WAIT_BETWEEN_REQUESTS_SERIAL
            if self._gateway_data.get(CONF_CONNECTION_TYPE) == CONNECTION_RTU_OVER_TCP
            else DEFAULT_WAIT_BETWEEN_REQUESTS_NETWORK,
        )
        return self.async_show_form(
            step_id="network",
            data_schema=vol.Schema(
                {
                    vol.Required("host", default=self._gateway_data.get("host", "")): str,
                    vol.Required(
                        "tcp_port", default=self._gateway_data.get("tcp_port", DEFAULT_TCP_PORT)
                    ): int,
                    vol.Required(
                        CONF_WAIT_BETWEEN_REQUESTS, default=default_wait
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1000)),
                }
            ),
        )

    async def async_step_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            self._gateway_data.update(
                {
                    "port": user_input["port"],
                    CONF_BAUDRATE: user_input[CONF_BAUDRATE],
                    CONF_PARITY: user_input[CONF_PARITY],
                    CONF_STOPBITS: user_input[CONF_STOPBITS],
                    CONF_BYTESIZE: user_input[CONF_BYTESIZE],
                    CONF_WAIT_BETWEEN_REQUESTS: user_input[CONF_WAIT_BETWEEN_REQUESTS],
                }
            )
            if self.source == config_entries.SOURCE_RECONFIGURE:
                return self._async_finish_reconfigure()
            return await self.async_step_pump()

        return self.async_show_form(
            step_id="serial",
            data_schema=vol.Schema(
                {
                    vol.Required("port", default=self._gateway_data.get("port", "/dev/ttyUSB0")): str,
                    vol.Required(
                        CONF_BAUDRATE, default=self._gateway_data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)
                    ): vol.In([1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]),
                    vol.Required(
                        CONF_PARITY, default=self._gateway_data.get(CONF_PARITY, DEFAULT_PARITY)
                    ): vol.In(PARITY_OPTIONS),
                    vol.Required(
                        CONF_STOPBITS, default=self._gateway_data.get(CONF_STOPBITS, DEFAULT_STOPBITS)
                    ): vol.In([1, 2]),
                    vol.Required(
                        CONF_BYTESIZE, default=self._gateway_data.get(CONF_BYTESIZE, DEFAULT_BYTESIZE)
                    ): vol.In([7, 8]),
                    vol.Required(
                        CONF_WAIT_BETWEEN_REQUESTS,
                        default=self._gateway_data.get(
                            CONF_WAIT_BETWEEN_REQUESTS, DEFAULT_WAIT_BETWEEN_REQUESTS_SERIAL
                        ),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=1000)),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Change the bus settings without touching configured pumps.

        The connection type itself is not offered: switching between TCP and
        serial is a different enough setup that removing and re-adding is
        clearer than migrating in place.
        """
        entry = self._get_reconfigure_entry()
        self._gateway_data = dict(entry.data)
        if self._gateway_data[CONF_CONNECTION_TYPE] == CONNECTION_SERIAL:
            return await self.async_step_serial()
        return await self.async_step_network()

    @callback
    def _async_finish_reconfigure(self) -> config_entries.ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        unique_id = "|".join(str(part) for part in gateway_key(self._gateway_data))
        return self.async_update_reload_and_abort(
            entry, unique_id=unique_id, data=self._gateway_data
        )

    async def async_step_pump(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if _duplicate_unit_id(user_input[CONF_UNIT_ID], self._pumps):
                errors["unit_id"] = "duplicate_unit_id"
            else:
                self._pumps.append(dict(user_input))
                return await self.async_step_add_another()

        next_unit_id = max((pump[CONF_UNIT_ID] for pump in self._pumps), default=0) + 1
        defaults = {"name": f"Ermangizer {next_unit_id}", CONF_UNIT_ID: next_unit_id}
        return self.async_show_form(
            step_id="pump", data_schema=_pump_schema(defaults), errors=errors
        )

    async def async_step_add_another(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_show_menu(
            step_id="add_another",
            menu_options=["pump", "finish"],
            description_placeholders={"count": str(len(self._pumps))},
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        await self.async_set_unique_id(
            "|".join(str(part) for part in gateway_key(self._gateway_data))
        )
        self._abort_if_unique_id_configured()

        label = self._gateway_data.get("host") or self._gateway_data.get("port") or "gateway"
        subentries = [
            {
                "subentry_type": SUBENTRY_TYPE_PUMP,
                "data": pump,
                "title": pump["name"],
                "unique_id": str(pump[CONF_UNIT_ID]),
            }
            for pump in self._pumps
        ]
        return self.async_create_entry(
            title=f"Ermangizer ({label})", data=self._gateway_data, subentries=subentries
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_TYPE_PUMP: PumpSubentryFlowHandler}


class PumpSubentryFlowHandler(ConfigSubentryFlow):
    """Add or reconfigure one pump on an already configured bus."""

    def _other_pumps(self, current_id: str | None) -> list[dict[str, Any]]:
        entry = self._get_entry()
        return [
            subentry.data
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_PUMP
            and (current_id is None or subentry.subentry_id != current_id)
        ]

    def _next_unit_id(self) -> int:
        """Suggest the address above the highest one already on this bus."""
        used = [int(data.get(CONF_UNIT_ID, 0)) for data in self._other_pumps(None)]
        return max(used, default=0) + 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.SubentryFlowResult:
        return await self._async_step_form(user_input, is_new=True)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.SubentryFlowResult:
        return await self._async_step_form(user_input, is_new=False)

    async def _async_step_form(
        self, user_input: dict[str, Any] | None, *, is_new: bool
    ) -> config_entries.SubentryFlowResult:
        step_id = "user" if is_new else "reconfigure"
        existing = None if is_new else self._get_reconfigure_subentry()
        entry = self._get_entry()

        if user_input is not None:
            if _duplicate_unit_id(user_input[CONF_UNIT_ID], self._other_pumps(
                None if existing is None else existing.subentry_id
            )):
                return self.async_show_form(
                    step_id=step_id,
                    data_schema=_pump_schema({**(existing.data if existing else {}), **user_input}),
                    errors={"unit_id": "duplicate_unit_id"},
                )
            if is_new:
                return self.async_create_entry(
                    title=user_input["name"],
                    data=user_input,
                    unique_id=str(user_input[CONF_UNIT_ID]),
                )
            return self.async_update_and_abort(
                entry, existing, title=user_input["name"], data=user_input
            )

        defaults = existing.data if existing else {
            "name": f"Ermangizer {self._next_unit_id()}",
            CONF_UNIT_ID: self._next_unit_id(),
        }
        return self.async_show_form(step_id=step_id, data_schema=_pump_schema(defaults))
