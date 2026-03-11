from __future__ import annotations

import pytest

from homeassistant.const import CONF_ENTITY_ID, CONF_NAME
from homeassistant.data_entry_flow import FlowResultType

from custom_components.previous_day_statistics.config_flow import PreviousDayStatisticsConfigFlow
from custom_components.previous_day_statistics.sensor import CONF_STATISTIC_TYPE


@pytest.mark.asyncio
async def test_flow_shows_user_form(hass):
    flow = PreviousDayStatisticsConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user(None)

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_flow_creates_entry_with_valid_input(hass):
    flow = PreviousDayStatisticsConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user(
        {
            CONF_ENTITY_ID: "sensor.temperature",
            CONF_STATISTIC_TYPE: "mean",
        }
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ENTITY_ID] == "sensor.temperature"
    assert result["data"][CONF_STATISTIC_TYPE] == "mean"


@pytest.mark.asyncio
async def test_flow_uses_custom_name_as_title(hass):
    flow = PreviousDayStatisticsConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user(
        {
            CONF_ENTITY_ID: "sensor.temperature",
            CONF_STATISTIC_TYPE: "mean",
            CONF_NAME: "Temp hier",
        }
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Temp hier"
