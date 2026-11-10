"""Config flow tests."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.s_klima.const import CONF_SCAN_INTERVAL, DOMAIN

from .conftest import HOST
from .fake_zlt import FakeZLT

INPUT = {"host": f"http://{HOST}/", "username": "ha", "password": "secret"}


async def test_user_flow(hass: HomeAssistant, mock_zlt: FakeZLT) -> None:
    """Happy path, plus error handling."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**INPUT, "password": "wrong"}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**INPUT, "password": "it's"}
    )
    assert result["errors"] == {"base": "invalid_characters"}

    mock_zlt.fail_http = True
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["errors"] == {"base": "cannot_connect"}
    mock_zlt.fail_http = False

    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {"host": HOST, "username": "ha", "password": "secret"}
    assert result["result"].unique_id == HOST
    await hass.async_block_till_done()
    # validation session was closed again
    assert mock_zlt.logouts >= 1

    # second time -> already configured
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_and_options(
    hass: HomeAssistant, mock_zlt: FakeZLT, config_entry: MockConfigEntry
) -> None:
    """Reauth updates credentials; options change the interval."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    mock_zlt.password = "new-pass"
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "ha", "password": "bad"}
    )
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"username": "ha", "password": "new-pass"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["password"] == "new-pass"
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert config_entry.runtime_data.update_interval.total_seconds() == 60
