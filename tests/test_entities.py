"""Entity tests."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_FAN_MODES,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_SWING_MODE,
    ATTR_SWING_MODES,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_SWING_MODE,
    SERVICE_SET_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from .fake_zlt import FakeZLT

ENTITY = "climate.restaurant_right"


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities_created(
    hass: HomeAssistant, mock_zlt: FakeZLT, config_entry: MockConfigEntry
) -> None:
    """Climate, sensors and binary sensors exist with correct values."""
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    state = hass.states.get(ENTITY)
    assert state.state == HVACMode.HEAT
    assert state.attributes["current_temperature"] == 20.7
    assert state.attributes[ATTR_TEMPERATURE] == 25.0
    assert state.attributes["min_temp"] == 16.0
    assert state.attributes["max_temp"] == 30.0
    assert state.attributes[ATTR_HVAC_MODES] == [
        HVACMode.OFF, HVACMode.HEAT_COOL, HVACMode.HEAT, HVACMode.COOL,
        HVACMode.DRY, HVACMode.FAN_ONLY,
    ]
    assert state.attributes[ATTR_FAN_MODES] == ["auto", "1", "2", "3", "4"]
    assert state.attributes[ATTR_FAN_MODE] == "1"
    assert state.attributes[ATTR_SWING_MODES] == [
        "position_1", "position_2", "position_3", "position_4", "swing"
    ]
    assert state.attributes[ATTR_SWING_MODE] == "position_4"
    assert state.attributes["address"] == "1-0"

    assert hass.states.get("climate.restaurant_left") is not None
    assert hass.states.get("climate.meeting_right") is not None
    assert hass.states.get("sensor.comptrol_zlt_outside_temperature").state == "8.9"
    assert hass.states.get("sensor.restaurant_right_room_temperature").state == "20.7"
    assert hass.states.get("sensor.restaurant_right_error_code").state == "0"
    assert hass.states.get("binary_sensor.restaurant_right_fault").state == "off"
    assert hass.states.get("binary_sensor.restaurant_right_filter").state == "off"
    assert hass.states.get("binary_sensor.restaurant_right_online").state == "on"

    ent_reg = er.async_get(hass)
    power = ent_reg.async_get("sensor.restaurant_right_power")
    assert power is not None and power.disabled_by is not None

    dev_reg = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(dev_reg, config_entry.entry_id)
    assert len(devices) == 4  # hub + 3 units


async def test_climate_services(
    hass: HomeAssistant, mock_zlt: FakeZLT, config_entry: MockConfigEntry
) -> None:
    """Commands are written to the device."""
    await _setup(hass, config_entry)

    async def call(service: str, **data) -> None:
        await hass.services.async_call(
            CLIMATE_DOMAIN, service, {ATTR_ENTITY_ID: ENTITY, **data}, blocking=True
        )

    await call(SERVICE_SET_TEMPERATURE, temperature=22.5)
    assert mock_zlt.writes[-1] == "##IndoorUnits.Unit[1000].SetTemperature:=225"
    assert hass.states.get(ENTITY).attributes[ATTR_TEMPERATURE] == 22.5

    with pytest.raises(HomeAssistantError):  # outside 16..30 -> rejected by HA
        await call(SERVICE_SET_TEMPERATURE, temperature=40)
    assert mock_zlt.writes[-1] == "##IndoorUnits.Unit[1000].SetTemperature:=225"

    await call(SERVICE_SET_HVAC_MODE, hvac_mode=HVACMode.OFF)
    assert mock_zlt.writes[-1] == "##IndoorUnits.Unit[1000].Running:=0"
    assert hass.states.get(ENTITY).state == HVACMode.OFF

    await call(SERVICE_SET_HVAC_MODE, hvac_mode=HVACMode.COOL)
    assert mock_zlt.writes[-2:] == [
        "##IndoorUnits.Unit[1000].Mode:=2",
        "##IndoorUnits.Unit[1000].Running:=1",
    ]
    assert hass.states.get(ENTITY).state == HVACMode.COOL

    await call(SERVICE_SET_HVAC_MODE, hvac_mode=HVACMode.HEAT_COOL)
    assert mock_zlt.writes[-1] == "##IndoorUnits.Unit[1000].Mode:=0"

    await call(SERVICE_SET_TEMPERATURE, temperature=21, hvac_mode=HVACMode.DRY)
    assert mock_zlt.writes[-2:] == [
        "##IndoorUnits.Unit[1000].Mode:=1",
        "##IndoorUnits.Unit[1000].SetTemperature:=210",
    ]

    await call(SERVICE_TURN_OFF)
    assert mock_zlt.writes[-1] == "##IndoorUnits.Unit[1000].Running:=0"
    await call(SERVICE_TURN_ON)
    assert mock_zlt.writes[-1] == "##IndoorUnits.Unit[1000].Running:=1"
    assert hass.states.get(ENTITY).state == HVACMode.DRY

    await call(SERVICE_SET_FAN_MODE, fan_mode="auto")
    assert mock_zlt.writes[-1] == "##IndoorUnits.Unit[1000].FanSpeed:=0"
    await call(SERVICE_SET_FAN_MODE, fan_mode="3")
    assert mock_zlt.writes[-1] == "##IndoorUnits.Unit[1000].FanSpeed:=3"
    assert hass.states.get(ENTITY).attributes[ATTR_FAN_MODE] == "3"

    await call(SERVICE_SET_SWING_MODE, swing_mode="swing")
    assert mock_zlt.writes[-1] == "##IndoorUnits.Unit[1000].Louver:=10"
    await call(SERVICE_SET_SWING_MODE, swing_mode="position_1")
    assert mock_zlt.writes[-1] == "##IndoorUnits.Unit[1000].Louver:=0"

    # other units untouched
    assert all("Unit[1000]" in w for w in mock_zlt.writes)


async def test_locked_setpoint(
    hass: HomeAssistant, mock_zlt: FakeZLT, config_entry: MockConfigEntry
) -> None:
    """A lock set on the ZLT is respected."""
    mock_zlt.units[1000]["IsSetPointLocked"] = 1
    await _setup(hass, config_entry)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: ENTITY, ATTR_TEMPERATURE: 20},
            blocking=True,
        )
    assert mock_zlt.writes == []


async def test_polling_offline_and_relogin(
    hass: HomeAssistant, mock_zlt: FakeZLT, config_entry: MockConfigEntry
) -> None:
    """Changes on the device appear after polling; session loss is handled."""
    await _setup(hass, config_entry)

    mock_zlt.units[1000]["RoomTemperature"] = 231
    mock_zlt.units[1001]["IsOnline"] = 0
    mock_zlt.units[1002]["IsError"] = 1
    mock_zlt.units[1002]["ErrorCode"] = 9
    mock_zlt.expire_sessions()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    # status flags are only accepted after 3 polls in a row
    assert hass.states.get("binary_sensor.restaurant_left_online").state == "on"
    coordinator = config_entry.runtime_data
    for _ in range(2):
        await coordinator.async_refresh()
        await hass.async_block_till_done()

    assert hass.states.get(ENTITY).attributes["current_temperature"] == 23.1
    assert hass.states.get("climate.restaurant_left").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.restaurant_left_online").state == "off"
    assert hass.states.get("binary_sensor.meeting_right_fault").state == "on"
    assert hass.states.get("sensor.meeting_right_error_code").state == "9"
    assert mock_zlt.logins == 2

    # a single failed request is retried -> entities stay available
    mock_zlt.fail_count = 1
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=46))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == HVACMode.HEAT
    assert mock_zlt.fail_count == 0

    # device unreachable: last state is kept for 3 polls, then unavailable
    mock_zlt.fail_http = True
    for _ in range(3):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(ENTITY).state == HVACMode.HEAT
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE

    mock_zlt.fail_http = False
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == HVACMode.HEAT


async def test_unload(
    hass: HomeAssistant, mock_zlt: FakeZLT, config_entry: MockConfigEntry
) -> None:
    """Unload logs out."""
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED
    assert mock_zlt.logouts == 1
    assert not mock_zlt.sessions


async def test_wrong_password_starts_reauth(
    hass: HomeAssistant, mock_zlt: FakeZLT, config_entry: MockConfigEntry
) -> None:
    """Auth failure on setup triggers reauth."""
    mock_zlt.password = "changed"
    config_entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)
