"""Support for Statistics Calendar sensor values."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
import logging
import statistics
import time
from typing import Any, cast

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.components.recorder import get_instance, history
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_ENTITY_ID,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    EventStateReportedData,
    HomeAssistant,
    State,
    callback,
    split_entity_id,
)
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_state_report_event,
)
from homeassistant.util import dt as dt_util

from .const import WINDOW_MODE, WINDOW_ROLLING, WINDOW_YESTERDAY

_LOGGER = logging.getLogger(__name__)

CONF_STATE_CHARACTERISTIC = "state_characteristic"
CONF_SAMPLES_MAX_BUFFER_SIZE = "sampling_size"
CONF_MAX_AGE = "max_age"
CONF_KEEP_LAST_SAMPLE = "keep_last_sample"
CONF_PRECISION = "precision"
CONF_PERCENTILE = "percentile"

DEFAULT_NAME = "Statistical calendar characteristic"
DEFAULT_PRECISION = 2
ICON = "mdi:calendar-clock"

STAT_MEAN = "mean"
STAT_SUM = "sum"
STAT_CHANGE = "change"
STAT_COUNT = "count"
STAT_VALUE_MAX = "value_max"
STAT_VALUE_MIN = "value_min"
STAT_PERCENTILE = "percentile"
STAT_COUNT_BINARY_ON = "count_on"
STAT_COUNT_BINARY_OFF = "count_off"


def _stat_mean(states: deque[bool | float], percentile: int) -> float | None:
    if not states:
        return None
    return statistics.mean(states)


def _stat_sum(states: deque[bool | float], percentile: int) -> float | None:
    if not states:
        return None
    return float(sum(states))


def _stat_change(states: deque[bool | float], percentile: int) -> float | None:
    if not states:
        return None
    return float(states[-1] - states[0])


def _stat_count(states: deque[bool | float], percentile: int) -> int:
    return len(states)


def _stat_value_max(states: deque[bool | float], percentile: int) -> float | None:
    if not states:
        return None
    return float(max(states))


def _stat_value_min(states: deque[bool | float], percentile: int) -> float | None:
    if not states:
        return None
    return float(min(states))


def _stat_percentile(states: deque[bool | float], percentile: int) -> float | None:
    if len(states) == 1:
        return cast(float, states[0])
    if len(states) >= 2:
        percentiles = statistics.quantiles(states, n=100, method="exclusive")
        return cast(float, percentiles[percentile - 1])
    return None


def _stat_binary_count_on(states: deque[bool | float], percentile: int) -> int:
    return states.count(True)


def _stat_binary_count_off(states: deque[bool | float], percentile: int) -> int:
    return states.count(False)


def _stat_binary_mean(states: deque[bool | float], percentile: int) -> float | None:
    if not states:
        return None
    return 100.0 / len(states) * states.count(True)


STATS_NUMERIC_SUPPORT: dict[str, Callable[[deque[bool | float], int], float | int | None]] = {
    STAT_MEAN: _stat_mean,
    STAT_SUM: _stat_sum,
    STAT_CHANGE: _stat_change,
    STAT_COUNT: _stat_count,
    STAT_VALUE_MAX: _stat_value_max,
    STAT_VALUE_MIN: _stat_value_min,
    STAT_PERCENTILE: _stat_percentile,
}

STATS_BINARY_SUPPORT: dict[str, Callable[[deque[bool | float], int], float | int | None]] = {
    STAT_COUNT: _stat_count,
    STAT_COUNT_BINARY_ON: _stat_binary_count_on,
    STAT_COUNT_BINARY_OFF: _stat_binary_count_off,
    STAT_MEAN: _stat_binary_mean,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Statistics Calendar from config entry."""
    sampling_size = entry.options.get(CONF_SAMPLES_MAX_BUFFER_SIZE)
    if sampling_size:
        sampling_size = int(sampling_size)

    max_age = None
    if max_age_input := entry.options.get(CONF_MAX_AGE):
        max_age = timedelta(**max_age_input)

    async_add_entities(
        [
            StatisticsCalendarSensor(
                hass=hass,
                source_entity_id=entry.options[CONF_ENTITY_ID],
                name=entry.options[CONF_NAME],
                unique_id=entry.entry_id,
                state_characteristic=entry.options[CONF_STATE_CHARACTERISTIC],
                window_mode=entry.options.get(WINDOW_MODE, WINDOW_ROLLING),
                samples_max_buffer_size=sampling_size,
                samples_max_age=max_age,
                samples_keep_last=entry.options.get(CONF_KEEP_LAST_SAMPLE, False),
                precision=int(entry.options.get(CONF_PRECISION, DEFAULT_PRECISION)),
                percentile=int(entry.options.get(CONF_PERCENTILE, 50)),
            )
        ],
        True,
    )


class StatisticsCalendarSensor(SensorEntity):
    """Representation of a Statistics Calendar sensor."""

    _attr_should_poll = False
    _attr_icon = ICON

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        source_entity_id: str,
        name: str,
        unique_id: str | None,
        state_characteristic: str,
        window_mode: str,
        samples_max_buffer_size: int | None,
        samples_max_age: timedelta | None,
        samples_keep_last: bool,
        precision: int,
        percentile: int,
    ) -> None:
        """Initialize the sensor."""
        self.hass = hass
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._source_entity_id = source_entity_id
        self._state_characteristic = state_characteristic
        self._window_mode = window_mode
        self._samples_max_buffer_size = samples_max_buffer_size
        self._samples_max_age = samples_max_age.total_seconds() if samples_max_age else None
        self._samples_keep_last = samples_keep_last
        self._precision = precision
        self._percentile = percentile
        self._attr_extra_state_attributes: dict[str, Any] = {}
        self._attr_available = False

        self.is_binary = split_entity_id(self._source_entity_id)[0] == BINARY_SENSOR_DOMAIN
        self.states: deque[float | bool] = deque(maxlen=samples_max_buffer_size)
        self.ages: deque[float] = deque(maxlen=samples_max_buffer_size)

        self._update_listener: CALLBACK_TYPE | None = None
        self._rollover_listener: CALLBACK_TYPE | None = None
        self._preview_callback: Callable[[str, Mapping[str, Any]], None] | None = None
        self._window_start_ts: float | None = None
        self._window_end_ts: float | None = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await self._async_sensor_startup()

    async def async_start_preview(
        self,
        preview_callback: Callable[[str, Mapping[str, Any]], None],
    ) -> CALLBACK_TYPE:
        """Render preview updates for options/config flow."""
        self._preview_callback = preview_callback
        await self._async_sensor_startup()
        return self._call_on_remove_callbacks

    async def _async_sensor_startup(self) -> None:
        """Initialize from recorder and subscribe to source state updates."""
        if "recorder" in self.hass.config.components:
            await self._initialize_from_database()

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self._source_entity_id],
                self._async_state_change_listener,
            )
        )
        self.async_on_remove(
            async_track_state_report_event(
                self.hass,
                [self._source_entity_id],
                self._async_state_report_listener,
            )
        )

        if self._window_mode == WINDOW_YESTERDAY:
            self._schedule_next_rollover()

    @callback
    def _async_state_change_listener(self, event: Event[EventStateChangedData]) -> None:
        """Handle source state_changed events."""
        if (new_state := event.data["new_state"]) is None:
            return
        self._async_handle_new_state(new_state, new_state.last_updated_timestamp)

    @callback
    def _async_state_report_listener(self, event: Event[EventStateReportedData]) -> None:
        """Handle source state_reported events."""
        self._async_handle_new_state(
            event.data["new_state"], event.data["last_reported"].timestamp()
        )

    def _async_handle_new_state(self, reported_state: State, timestamp: float) -> None:
        """Handle a new source state."""
        self._attr_available = reported_state.state != STATE_UNAVAILABLE
        if not self._attr_available or reported_state.state in (STATE_UNKNOWN, None, ""):
            self._push_state()
            return

        if not self._timestamp_in_window(timestamp):
            self._push_state()
            return

        try:
            if self.is_binary:
                if reported_state.state not in ("on", "off"):
                    return
                self.states.append(reported_state.state == "on")
            else:
                self.states.append(float(reported_state.state))
            self.ages.append(timestamp)
        except ValueError:
            _LOGGER.debug(
                "%s: unable to parse source state '%s'",
                self.entity_id,
                reported_state.state,
            )
            return

        self._refresh_value()
        self._push_state()

    def _timestamp_in_window(self, timestamp: float) -> bool:
        """Return True if timestamp is in the active window."""
        if self._window_mode == WINDOW_ROLLING:
            return True
        if self._window_start_ts is None or self._window_end_ts is None:
            return False
        return self._window_start_ts <= timestamp < self._window_end_ts

    def _refresh_value(self) -> None:
        """Recalculate state value and attributes."""
        if self._window_mode == WINDOW_ROLLING and self._samples_max_age is not None:
            self._purge_old_states(self._samples_max_age)

        fn_map = STATS_BINARY_SUPPORT if self.is_binary else STATS_NUMERIC_SUPPORT
        fn = fn_map.get(self._state_characteristic, _stat_mean)
        value = fn(self.states, self._percentile)
        if isinstance(value, float):
            value = round(value, self._precision)
            if self._precision == 0:
                value = int(value)
        self._attr_native_value = value
        self._attr_extra_state_attributes["sample_count"] = len(self.states)
        self._attr_extra_state_attributes[WINDOW_MODE] = self._window_mode
        if self._window_mode == WINDOW_YESTERDAY:
            self._attr_extra_state_attributes["window_start"] = (
                dt_util.utc_from_timestamp(self._window_start_ts).isoformat()
                if self._window_start_ts
                else None
            )
            self._attr_extra_state_attributes["window_end"] = (
                dt_util.utc_from_timestamp(self._window_end_ts).isoformat()
                if self._window_end_ts
                else None
            )

    def _purge_old_states(self, max_age: float) -> None:
        """Remove states older than max_age (rolling mode)."""
        now_timestamp = time.time()
        while self.ages and (now_timestamp - self.ages[0]) > max_age:
            if self._samples_keep_last and len(self.ages) == 1:
                break
            self.ages.popleft()
            self.states.popleft()

    def _compute_yesterday_window(self) -> tuple[datetime, datetime]:
        """Compute yesterday bounds in local timezone, returned in UTC."""
        local_now = dt_util.as_local(dt_util.utcnow())
        local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        local_yesterday_start = local_today_start - timedelta(days=1)
        return local_yesterday_start.astimezone(dt_util.UTC), local_today_start.astimezone(
            dt_util.UTC
        )

    def _schedule_next_rollover(self) -> None:
        """Schedule a window rebuild at next local midnight."""
        if self._rollover_listener:
            self._rollover_listener()
            self._rollover_listener = None

        local_now = dt_util.as_local(dt_util.utcnow())
        local_next_midnight = (
            local_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        )
        self._rollover_listener = async_track_point_in_utc_time(
            self.hass, self._async_rollover, local_next_midnight.astimezone(dt_util.UTC)
        )
        self.async_on_remove(self._rollover_listener)

    async def _async_rollover(self, now: datetime) -> None:
        """Rebuild queue when calendar window changes."""
        await self._initialize_from_database(reset=True)
        self._schedule_next_rollover()

    def _fetch_states_from_database(self) -> list[State]:
        """Fetch source states for active window."""
        lower_entity_id = self._source_entity_id.lower()
        end_time = None
        if self._window_mode == WINDOW_YESTERDAY:
            start_time, end_time = self._compute_yesterday_window()
            self._window_start_ts = start_time.timestamp()
            self._window_end_ts = end_time.timestamp()
        elif self._samples_max_age is not None:
            start_time = dt_util.utcnow() - timedelta(seconds=self._samples_max_age)
        else:
            start_time = datetime.fromtimestamp(0, tz=dt_util.UTC)

        return history.state_changes_during_period(
            self.hass,
            start_time,
            end_time=end_time,
            entity_id=lower_entity_id,
            descending=True,
            limit=self._samples_max_buffer_size,
            include_start_time_state=False,
        ).get(lower_entity_id, [])

    async def _initialize_from_database(self, reset: bool = False) -> None:
        """Initialize buffer from recorder history."""
        if reset:
            self.states.clear()
            self.ages.clear()

        states = await get_instance(self.hass).async_add_executor_job(
            self._fetch_states_from_database
        )
        for state in reversed(states):
            self._async_handle_new_state(state, state.last_reported_timestamp)
        self._refresh_value()
        self._push_state()

    def _push_state(self) -> None:
        """Push state to HA or preview callback."""
        if self._preview_callback:
            self._preview_callback(str(self.native_value), self.extra_state_attributes or {})
            return
        self.async_write_ha_state()
