"""Tests for the web.dwh client."""

from __future__ import annotations

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.s_klima.api import (
    CompTrolAuthError,
    CompTrolClient,
    CompTrolConnectionError,
    CompTrolUnsupportedError,
    build_body,
    parse_response,
    units_list_expression,
)

from .conftest import HOST
from .fake_zlt import FakeZLT


def test_body_matches_web_ui() -> None:
    """Body must be byte-identical to what the web UI sends (captured live)."""
    body = build_body(
        1745448749,
        ["#$DateToStr(##000171, 'YYYY-MM-DD hh:mm:ss')", "##000187", "##Outside.Temperature"],
    )
    assert body == (
        "mg=1745448749&V=%23%24DateToStr(%23%23000171%2C%20'YYYY-MM-DD%20hh%3Amm%3Ass')"
        "&V=%23%23000187&V=%23%23Outside.Temperature"
    )
    body = build_body(5, ["G=##Users.User[0].Units.Count\t##IndoorUnits.Unit[1].Id"])
    assert body == (
        "mg=5&G%3D%23%23Users.User%5B0%5D.Units.Count%09%23%23IndoorUnits.Unit%5B1%5D.Id"
    )


def test_parse_real_responses() -> None:
    """Responses captured from the real device."""
    ok = parse_response("254\r\n\r\n254\r\n0\r\n")
    assert ok.header == "254" and ok.data == ["", "254"] and ok.error == "0"
    bad = parse_response("0\r\n0\r\n§§§\r\n-104\r\n")
    assert bad.data == ["0", "§§§"] and bad.error == "-104"
    write = parse_response("254\r\n250\r\n0\r\n")
    assert write.data == ["250"] and write.error == "0"


def test_list_expression() -> None:
    """List expression format."""
    expr = units_list_expression()
    assert expr.startswith("G=##IndoorUnits.Count\t##IndoorUnits.Unit[##IndoorUnits.GetItemId[##X+0]].Id\t")
    assert expr.endswith("\t#$IndoorUnits.Unit[##IndoorUnits.GetItemId[##X+0]].Name")


async def test_get_state_and_write(hass: HomeAssistant, mock_zlt: FakeZLT) -> None:
    """Read all units, write a value."""
    client = CompTrolClient(async_get_clientsession(hass), HOST, "ha", "secret")
    state = await client.async_get_state()
    assert state.outside_temperature == 8.9
    assert list(state.units) == [1000, 1001, 1002]
    unit = state.units[1000]
    assert unit.name == "Restaurant Right"
    assert unit.address == "1-0"
    assert unit.running is True and unit.mode == 4
    assert unit.set_temperature == 25.0 and unit.room_temperature == 20.7
    assert unit.min_set_temp == 16.0 and unit.max_set_temp == 30.0
    assert unit.louver_supported and unit.auto_fan_supported
    assert mock_zlt.logins == 1

    await client.async_write_unit(1001, {"Mode": 2, "Running": 1})
    assert mock_zlt.writes == [
        "##IndoorUnits.Unit[1001].Mode:=2",
        "##IndoorUnits.Unit[1001].Running:=1",
    ]
    with pytest.raises(ValueError):
        await client.async_write_unit(1001, {"Name": 1})

    # session expires on the device -> transparent re-login
    mock_zlt.expire_sessions()
    state = await client.async_get_state()
    assert state.units[1001].mode == 2
    assert mock_zlt.logins == 2

    await client.async_logout()
    assert mock_zlt.logouts == 1 and not mock_zlt.sessions


async def test_errors(hass: HomeAssistant, mock_zlt: FakeZLT) -> None:
    """Wrong password, encryption, HTTP error."""
    session = async_get_clientsession(hass)
    with pytest.raises(CompTrolAuthError):
        await CompTrolClient(session, HOST, "ha", "wrong").async_get_state()

    mock_zlt.rsa_key = '01("abc;def")'
    with pytest.raises(CompTrolUnsupportedError):
        await CompTrolClient(session, HOST, "ha", "secret").async_get_state()
    mock_zlt.rsa_key = ""

    mock_zlt.fail_http = True
    with pytest.raises(CompTrolConnectionError):
        await CompTrolClient(session, HOST, "ha", "secret").async_get_state()


def test_parse_live_poll_response() -> None:
    """Response captured from the real CompTrol ZLT for our poll request."""
    from pathlib import Path

    from custom_components.s_klima.api import parse_state

    text = (Path(__file__).parent / "data" / "live_poll_response.txt").read_bytes().decode()
    result = parse_response(text)
    assert result.error == "0"
    assert result.data[0] == "254"  # ##USERLEVELS()
    state = parse_state(result.data[1:])
    assert state.outside_temperature == 8.9
    assert len(state.units) == 10
    first = state.units[1000]
    assert (first.name, first.address, first.running, first.mode) == ("Restaurant Right", "1-0", True, 4)
    assert (first.set_temperature, first.room_temperature) == (25.0, 28.0)
    assert (first.fan_speed, first.louver, first.fan_speed_max) == (1, 3, 4)
    assert first.is_online and not first.is_error and not first.louver_locked
    assert state.units[1009].name == "Office Beige"
    assert state.units[1009].room_temperature == 24.2
