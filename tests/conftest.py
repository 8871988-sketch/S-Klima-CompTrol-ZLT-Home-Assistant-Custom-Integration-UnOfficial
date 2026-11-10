"""Fixtures."""

from __future__ import annotations

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.s_klima.const import DOMAIN

from .fake_zlt import FakeZLT

HOST = "192.0.2.10"
URL = f"http://{HOST}/web.dwh"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations."""
    return


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    """Do not wait between poll retries in tests."""
    monkeypatch.setattr("custom_components.s_klima.coordinator.RETRY_DELAY", 0)


@pytest.fixture
def fake_zlt() -> FakeZLT:
    """Fake device."""
    return FakeZLT()


@pytest.fixture
def mock_zlt(aioclient_mock: AiohttpClientMocker, fake_zlt: FakeZLT) -> FakeZLT:
    """Route web.dwh requests to the fake device."""

    async def handler(method, url, data):
        if fake_zlt.fail_http:
            return AiohttpClientMockResponse(method, url, status=500)
        if fake_zlt.fail_count > 0:
            fake_zlt.fail_count -= 1
            return AiohttpClientMockResponse(method, url, status=500)
        body = data.decode() if isinstance(data, bytes) else data
        return AiohttpClientMockResponse(method, url, text=fake_zlt.handle(body))

    aioclient_mock.post(URL, side_effect=handler)
    return fake_zlt


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"CompTrol ZLT ({HOST})",
        unique_id=HOST,
        data={"host": HOST, "username": "ha", "password": "secret"},
    )
