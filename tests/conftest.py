"""Shared fixtures.

pytest-homeassistant-custom-component supplies `hass` and
`enable_custom_integrations`; this adds a helper that drives the real config
flow to a set-up entry, so end-to-end tests exercise the same path the UI
takes rather than hand-building a ConfigEntry.
"""
from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.ermangizer.const import CONF_CONNECTION_TYPE, DOMAIN


async def add_entry(
    hass: HomeAssistant, gateway: dict[str, Any], pumps: list[dict[str, Any]]
):
    """Run the config flow to completion and return the set-up entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={CONF_CONNECTION_TYPE: gateway[CONF_CONNECTION_TYPE]},
    )
    network = {k: v for k, v in gateway.items() if k != CONF_CONNECTION_TYPE}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input=network
    )
    for pump in pumps:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input=pump
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={"next_step_id": "finish"}
        )
        if result["type"] == "menu":
            continue
    await hass.async_block_till_done()
    assert result["type"] == "create_entry", result
    return result["result"]
