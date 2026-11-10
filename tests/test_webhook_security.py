import asyncio
import socket
from datetime import datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from lnbits.settings import settings
from lnbits.utils.safe_http import SafeHttpClient

from .. import helpers
from ..models import Charge, SatspaySettings


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_webhook_keeps_payload_but_never_returns_response_body(
    monkeypatch, method
):
    monkeypatch.setattr(settings, "lnbits_callback_url_rules", [])
    monkeypatch.setattr(
        helpers,
        "get_or_create_satspay_settings",
        AsyncMock(return_value=SatspaySettings(webhook_method=method)),
    )
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
            ]
        ),
    )
    requests = []

    def factory(**kwargs):
        client = SafeHttpClient(**kwargs)

        def handler(request):
            requests.append(request)
            return httpx.Response(200, text="server-secret")

        client.client._transport = httpx.MockTransport(handler)
        return client

    monkeypatch.setattr(helpers, "SafeHttpClient", factory)
    charge = Charge(
        id="charge",
        user="user",
        amount=21,
        time=60,
        timestamp=datetime.now(),
        webhook="https://public.example/hook",
    )
    result = await helpers.call_webhook(charge)
    assert result == {
        "webhook_success": True,
        "webhook_message": "Webhook delivered.",
        "webhook_response": "",
    }
    assert requests[0].method == method
    import json

    payload = json.loads(requests[0].content)
    if method == "POST":
        payload = json.loads(payload)  # Preserve the existing Wordpress payload.
    assert payload["id"] == charge.id
    assert payload["amount"] == charge.amount


@pytest.mark.anyio
@pytest.mark.parametrize("mempool_private", [False, True])
async def test_private_webhook_returns_sanitized_failure(monkeypatch, mempool_private):
    monkeypatch.setattr(settings, "lnbits_callback_url_rules", [])
    monkeypatch.setattr(
        helpers,
        "get_or_create_satspay_settings",
        AsyncMock(
            return_value=SatspaySettings(mempool_allow_private_ips=mempool_private)
        ),
    )
    charge = Charge(
        id="charge",
        user="user",
        amount=21,
        time=60,
        timestamp=datetime.now(),
        webhook="http://127.0.0.1/?key=secret",
    )
    result = await helpers.call_webhook(charge)
    assert result == {
        "webhook_success": False,
        "webhook_message": "Webhook request failed.",
        "webhook_response": "",
    }
