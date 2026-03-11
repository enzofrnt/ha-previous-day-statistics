from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_ENTITY_ID, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import DOMAIN
from .sensor import CONF_STATISTIC_TYPE, SUPPORTED_STAT_TYPES


class PreviousDayStatisticsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow pour Previous Day Statistics."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Première étape : choisir la source et le type de statistique."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Pas de validation complexe ici, on laisse HA/recorder gérer l'absence de stats
            return self.async_create_entry(
                title=user_input.get(CONF_NAME) or "Previous day statistic",
                data=user_input,
            )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_ENTITY_ID): selector.selector(
                    {
                        "entity": {
                            "domain": "sensor",
                        }
                    }
                ),
                vol.Required(CONF_STATISTIC_TYPE, default="mean"): vol.In(
                    list(SUPPORTED_STAT_TYPES.keys())
                ),
                vol.Optional(CONF_NAME): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )


@callback
def async_get_options_flow(
    config_entry: config_entries.ConfigEntry,
) -> config_entries.OptionsFlow:
    """Retourne un flow d'options minimal (pas d'options pour le moment)."""

    class _OptionsFlow(config_entries.OptionsFlow):
        async def async_step_init(
            self, user_input: dict[str, Any] | None = None
        ) -> FlowResult:
            return self.async_create_entry(title="", data=config_entry.options)

    return _OptionsFlow(config_entry)

