"""Shared Modbus connection handling for the Ermangizer integration.

One physical gateway (a TCP host/port pair or a serial port) is opened once
and shared by every pump configured against it, guarded by one asyncio.Lock:
RS-485 is half duplex, so two concurrent requests on the same bus collide.
Connections are reference-counted and closed when the last pump using one is
unloaded.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

from .const import (
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CONNECTION_TYPE,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_WAIT_BETWEEN_REQUESTS,
    CONNECTION_RTU_OVER_TCP,
    CONNECTION_SERIAL,
    CONNECTION_TCP,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

GATEWAYS_KEY = "gateways"

# A stalled socket is forced open again only this often, so several pumps on
# one bus reacting to the same slowness do not reconnect back-to-back.
MIN_SECONDS_BETWEEN_RECREATES = 60


def gateway_key(data: dict[str, Any]) -> tuple:
    """Identify the physical gateway a config entry talks to.

    The unit id is excluded: pumps sharing a gateway share its connection.
    Distinct TCP ports on one host are distinct buses, which is how a
    multi-port serial-to-Ethernet gateway (one port per RS-485 line) is
    handled.
    """
    conn_type = data[CONF_CONNECTION_TYPE]
    if conn_type == CONNECTION_SERIAL:
        return (
            conn_type,
            data["port"],
            data.get(CONF_BAUDRATE),
            data.get(CONF_PARITY),
            data.get(CONF_STOPBITS),
            data.get(CONF_BYTESIZE),
        )
    return (conn_type, data["host"], data["tcp_port"])


@dataclass
class GatewayHandle:
    """One shared connection to a physical Modbus gateway."""

    base_client: Any
    lock: asyncio.Lock
    connection_data: dict[str, Any]
    refcount: int = 0
    _unit_clients: dict[int, Any] = field(default_factory=dict)
    _last_recreate: float | None = None

    def client_for(self, unit_id: int) -> Any:
        """A client bound to one unit id, reusing the shared connection."""
        client = self._unit_clients.get(unit_id)
        if client is None:
            client = self.base_client.for_unit_id(unit_id)
            self._unit_clients[unit_id] = client
        return client

    def should_recreate_now(self) -> bool:
        """Whether the connection may be recycled now.

        Callers must hold ``lock`` so the check and the recreate that follows
        are atomic for this bus.
        """
        if self._last_recreate is None:
            return True
        return (time.monotonic() - self._last_recreate) >= MIN_SECONDS_BETWEEN_RECREATES

    async def recreate(self, reason: str | None = None) -> None:
        """Force-close and reopen the underlying connection.

        Used when a read stalls far past its deadline or the poll cadence
        drifts: a healthy gateway does neither, so the socket is assumed stuck
        and unlikely to recover on its own. Callers must hold ``lock``.
        """
        # Stamp first: a failed reopen must not invite a pile-up of retries.
        self._last_recreate = time.monotonic()
        _LOGGER.warning(
            "Ermangizer gateway %s: reconnecting (%s)",
            gateway_key(self.connection_data),
            reason or "unspecified",
        )
        try:
            await self.base_client.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error closing gateway connection before recreate")
        # Per-unit clients wrap the old transport, so they go with it.
        self._unit_clients.clear()
        await self.base_client.__aenter__()


async def _create_base_client(data: dict[str, Any]):
    """Create (not yet connect) the tmodbus client for a gateway.

    Timeouts are left at the tmodbus defaults rather than tuned per
    deployment: the defaults work across gateways, and a value copied from one
    operator's YAML is not portable.
    """
    # Imported lazily so tests can import this module before tmodbus is
    # installed.
    from tmodbus import (
        create_async_rtu_client,
        create_async_rtu_over_tcp_client,
        create_async_tcp_client,
    )

    conn_type = data[CONF_CONNECTION_TYPE]
    # Only bootstraps the connection; each pump gets its own client through
    # client_for().
    bootstrap_unit_id = 1
    # Stored in the config entry as whole milliseconds (friendlier in the UI);
    # tmodbus takes seconds.
    wait_between_requests = data.get(CONF_WAIT_BETWEEN_REQUESTS, 0) / 1000.0

    if conn_type == CONNECTION_TCP:
        return create_async_tcp_client(
            data["host"],
            data["tcp_port"],
            unit_id=bootstrap_unit_id,
            wait_between_requests=wait_between_requests,
        )
    if conn_type == CONNECTION_RTU_OVER_TCP:
        return create_async_rtu_over_tcp_client(
            data["host"],
            data["tcp_port"],
            unit_id=bootstrap_unit_id,
            wait_between_requests=wait_between_requests,
        )
    if conn_type == CONNECTION_SERIAL:
        return create_async_rtu_client(
            data["port"],
            unit_id=bootstrap_unit_id,
            baudrate=data.get(CONF_BAUDRATE),
            parity=data.get(CONF_PARITY),
            stopbits=data.get(CONF_STOPBITS),
            bytesize=data.get(CONF_BYTESIZE),
            wait_between_requests=wait_between_requests,
        )
    raise ValueError(f"Unknown connection_type: {conn_type}")


async def async_get_gateway(hass: HomeAssistant, data: dict[str, Any]) -> GatewayHandle:
    """Return the shared gateway handle for ``data``, opening it if needed,
    and increment its refcount."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    gateways: dict[tuple, GatewayHandle] = domain_data.setdefault(GATEWAYS_KEY, {})

    key = gateway_key(data)
    handle = gateways.get(key)
    if handle is None:
        _LOGGER.debug("Opening Ermangizer gateway connection: %s", key)
        base_client = await _create_base_client(data)
        await base_client.__aenter__()
        handle = GatewayHandle(base_client=base_client, lock=asyncio.Lock(), connection_data=data)
        gateways[key] = handle
    handle.refcount += 1
    return handle


async def async_release_gateway(hass: HomeAssistant, data: dict[str, Any]) -> None:
    """Drop one reference; close the connection when the last pump is gone."""
    domain_data = hass.data.get(DOMAIN, {})
    gateways: dict[tuple, GatewayHandle] = domain_data.get(GATEWAYS_KEY, {})

    key = gateway_key(data)
    handle = gateways.get(key)
    if handle is None:
        return
    handle.refcount -= 1
    if handle.refcount <= 0:
        _LOGGER.debug("Closing Ermangizer gateway connection: %s", key)
        gateways.pop(key, None)
        try:
            await handle.base_client.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Error closing Ermangizer gateway connection")
