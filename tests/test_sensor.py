from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.const import ATTR_ENTITY_ID, CONF_ENTITY_ID, CONF_NAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.previous_day_statistics.const import DOMAIN
from custom_components.previous_day_statistics.sensor import (
    CONF_STATISTIC_TYPE,
    YesterdayStatisticSensor,
    async_setup_entry,
)


def _make_entry(entity_id: str = "sensor.source", statistic_type: str = "mean", name: str | None = "My stat"):
    data = {CONF_ENTITY_ID: entity_id, CONF_STATISTIC_TYPE: statistic_type}
    if name:
        data[CONF_NAME] = name
    return MockConfigEntry(domain=DOMAIN, data=data, entry_id="entry_abc")


@pytest.mark.asyncio
async def test_setup_entry_creates_sensor(hass):
    entry = _make_entry()
    added = []

    def _add(entities):
        added.extend(entities)

    await async_setup_entry(hass, entry, _add)

    assert len(added) == 1
    sensor = added[0]
    assert isinstance(sensor, YesterdayStatisticSensor)
    assert sensor._source_entity_id == "sensor.source"
    assert sensor._statistic_type == "mean"
    assert sensor.name == "My stat"


def test_default_name_without_custom_name(hass):
    sensor = YesterdayStatisticSensor(
        hass=hass,
        config_entry_id="abc",
        source_entity_id="sensor.temp",
        statistic_type="max",
        name=None,
    )
    assert sensor.name == "sensor.temp max hier"


def test_extra_state_attributes(hass):
    sensor = YesterdayStatisticSensor(
        hass=hass,
        config_entry_id="abc",
        source_entity_id="sensor.temp",
        statistic_type="mean",
        name=None,
    )
    attrs = sensor.extra_state_attributes
    assert attrs[CONF_ENTITY_ID] == "sensor.temp"
    assert attrs[CONF_STATISTIC_TYPE] == "mean"


@pytest.mark.asyncio
async def test_midnight_schedule(monkeypatch, hass):
    sensor = YesterdayStatisticSensor(
        hass=hass, config_entry_id="abc", source_entity_id="sensor.test", statistic_type="mean", name=None
    )
    sensor.hass = hass
    sensor.async_calculate = AsyncMock()

    track_mock = MagicMock()
    monkeypatch.setattr(
        "custom_components.previous_day_statistics.sensor.async_track_time_change",
        track_mock,
    )

    await sensor.async_added_to_hass()

    track_mock.assert_called_once()
    _, kwargs = track_mock.call_args
    assert kwargs["hour"] == 0
    assert kwargs["minute"] == 0
    assert kwargs["second"] == 5
    sensor.async_calculate.assert_awaited_once()


@pytest.mark.asyncio
async def test_midnight_callback_triggers_calculate(monkeypatch, hass):
    sensor = YesterdayStatisticSensor(
        hass=hass, config_entry_id="abc", source_entity_id="sensor.test", statistic_type="mean", name=None
    )
    sensor.hass = hass
    sensor.async_calculate = AsyncMock()

    captured = None

    def _track(hass, callback, **kwargs):
        nonlocal captured
        captured = callback
        return MagicMock()

    monkeypatch.setattr(
        "custom_components.previous_day_statistics.sensor.async_track_time_change",
        _track,
    )

    await sensor.async_added_to_hass()
    assert captured is not None

    await captured()
    assert sensor.async_calculate.await_count == 2


@pytest.mark.asyncio
async def test_calculate_returns_correct_field_for_yesterday(monkeypatch, hass):
    sensor = YesterdayStatisticSensor(
        hass=hass, config_entry_id="abc", source_entity_id="sensor.test", statistic_type="mean", name=None
    )
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()

    fixed_end = datetime(2026, 3, 11, 0, 0, 0)
    monkeypatch.setattr("custom_components.previous_day_statistics.sensor.dt_util.now", lambda: fixed_end)
    monkeypatch.setattr("custom_components.previous_day_statistics.sensor.dt_util.start_of_local_day", lambda _: fixed_end)

    def fake_stats(hass_arg, start, end, statistic_ids, period):
        assert start == fixed_end - timedelta(days=1)
        assert end == fixed_end
        assert statistic_ids == ["sensor.test"]
        assert period == "day"
        return {"sensor.test": [{"mean": 99.5, "min": 1.0, "max": 100.0}]}

    monkeypatch.setattr(
        "custom_components.previous_day_statistics.sensor.statistics_during_period",
        fake_stats,
    )
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f: f())

    await sensor.async_calculate()

    assert sensor.state == pytest.approx(99.5)
    sensor.async_write_ha_state.assert_called_once()


@pytest.mark.asyncio
async def test_calculate_returns_none_when_no_stats(monkeypatch, hass):
    sensor = YesterdayStatisticSensor(
        hass=hass, config_entry_id="abc", source_entity_id="sensor.test", statistic_type="mean", name=None
    )
    sensor.hass = hass
    sensor.async_write_ha_state = MagicMock()

    fixed_end = datetime(2026, 3, 11, 0, 0, 0)
    monkeypatch.setattr("custom_components.previous_day_statistics.sensor.dt_util.now", lambda: fixed_end)
    monkeypatch.setattr("custom_components.previous_day_statistics.sensor.dt_util.start_of_local_day", lambda _: fixed_end)
    monkeypatch.setattr(
        "custom_components.previous_day_statistics.sensor.statistics_during_period",
        lambda *a, **kw: {},
    )
    hass.async_add_executor_job = AsyncMock(side_effect=lambda f: f())

    await sensor.async_calculate()

    assert sensor.state is None
    sensor.async_write_ha_state.assert_called_once()
