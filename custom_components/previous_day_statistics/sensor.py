from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, CONF_ENTITY_ID, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import DOMAIN


CONF_STATISTIC_TYPE = "statistic_type"

SUPPORTED_STAT_TYPES: dict[str, str] = {
    "mean": "mean",
    "min": "min",
    "max": "max",
    "sum": "sum",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Yesterday statistics sensors from a config entry."""
    data = entry.data
    entity_id: str = data[CONF_ENTITY_ID]
    statistic_type: str = data[CONF_STATISTIC_TYPE]
    name: str | None = data.get(CONF_NAME)

    sensor = YesterdayStatisticSensor(
        hass=hass,
        config_entry_id=entry.entry_id,
        source_entity_id=entity_id,
        statistic_type=statistic_type,
        name=name,
    )
    async_add_entities([sensor])


class YesterdayStatisticSensor(SensorEntity):
    """Capteur de statistique pour le jour précédent."""

    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry_id: str,
        source_entity_id: str,
        statistic_type: str,
        name: str | None = None,
    ) -> None:
        self._hass = hass
        self._config_entry_id = config_entry_id
        self._source_entity_id = source_entity_id
        self._statistic_type = statistic_type
        self._state: float | None = None

        stat_label = statistic_type
        if name:
            self._attr_name = name
        else:
            self._attr_name = f"{source_entity_id} {stat_label} hier"

        self._attr_unique_id = f"{DOMAIN}_{config_entry_id}"
        self._attr_extra_state_attributes = {
            ATTR_ENTITY_ID: source_entity_id,
            CONF_STATISTIC_TYPE: statistic_type,
        }

    @property
    def state(self) -> float | None:
        return self._state

    async def async_added_to_hass(self) -> None:
        async def update(_=None) -> None:
            await self.async_calculate()

        async_track_time_change(
            self.hass,
            update,
            hour=0,
            minute=0,
            second=5,
        )

        await self.async_calculate()

    async def async_calculate(self) -> None:
        """Calcule la statistique du jour précédent."""
        end = dt_util.start_of_local_day(dt_util.now())
        start = end - timedelta(days=1)

        def _calc() -> float | None:
            stats = statistics_during_period(
                self._hass,
                start,
                end,
                statistic_ids=[self._source_entity_id],
                period="day",
            )

            values: list[dict[str, Any]] | None = stats.get(self._source_entity_id)
            if not values:
                return None

            last_bucket = values[-1]
            field = SUPPORTED_STAT_TYPES.get(self._statistic_type)
            if not field:
                return None

            value = last_bucket.get(field)
            if value is None:
                return None

            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        result = await self._hass.async_add_executor_job(_calc)

        self._state = result
        self.async_write_ha_state()
