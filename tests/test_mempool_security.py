import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest
from lnbits.db import Database
from lnbits.settings import settings
from lnbits.utils.safe_http import SafeHttpClient
from pydantic import ValidationError

from .. import crud, helpers, migrations, views_api
from ..models import SatspaySettings

ADDRESS = "bc1qexampleaddress000000000000000000000000"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def policy(monkeypatch):
    monkeypatch.setattr(settings, "lnbits_callback_url_rules", [])
    monkeypatch.setattr(settings, "lnbits_baseurl", "https://lnbits.example/")
    monkeypatch.setattr(settings, "lnbits_outbound_host_ips", [])


def dns(monkeypatch, address):
    monkeypatch.setattr(
        asyncio.get_running_loop(),
        "getaddrinfo",
        AsyncMock(
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
        ),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("private", [False, True])
async def test_balance_uses_pinned_core_transport_preserving_accounting(
    monkeypatch, private
):
    config = SatspaySettings(
        mempool_url="https://mempool.example/testnet", mempool_allow_private_ips=private
    )
    monkeypatch.setattr(
        helpers, "get_or_create_satspay_settings", AsyncMock(return_value=config)
    )
    address = "10.0.0.2" if private else "93.184.216.34"
    dns(monkeypatch, address)
    requests = []

    def factory(**kwargs):
        client = SafeHttpClient(**kwargs)

        def handler(request):
            requests.append(request)
            return httpx.Response(
                200,
                json=[
                    {
                        "txid": "confirmed",
                        "status": {"confirmed": True},
                        "vout": [{"scriptpubkey_address": ADDRESS, "value": 21000}],
                    },
                    {
                        "txid": "pending",
                        "status": {"confirmed": False},
                        "vout": [{"scriptpubkey_address": ADDRESS, "value": 1000}],
                    },
                ],
            )

        client.client._transport = httpx.MockTransport(handler)
        return client

    monkeypatch.setattr(helpers, "SafeHttpClient", factory)
    result = await helpers.fetch_onchain_balance(ADDRESS)
    assert (result.confirmed, result.unconfirmed, result.txids) == (
        21000,
        1000,
        ["confirmed", "pending"],
    )
    assert requests[0].url.host == address
    assert requests[0].url.path == f"/testnet/api/address/{ADDRESS}/txs"
    assert requests[0].headers["host"] == "mempool.example"


@pytest.mark.anyio
async def test_private_mempool_requires_opt_in_and_public_self_is_always_blocked(
    monkeypatch,
):
    config = SatspaySettings(mempool_url="https://mempool.example")
    monkeypatch.setattr(
        helpers, "get_or_create_satspay_settings", AsyncMock(return_value=config)
    )
    dns(monkeypatch, "127.0.0.1")
    with pytest.raises(ValueError):
        await helpers.fetch_onchain_balance(ADDRESS)
    config.mempool_allow_private_ips = True
    monkeypatch.setattr(settings, "lnbits_outbound_host_ips", ["8.8.8.8"])
    dns(monkeypatch, "8.8.8.8")
    with pytest.raises(ValueError, match="this server"):
        await helpers.fetch_onchain_balance(ADDRESS)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "address",
    ["../../admin", "address?url=file:///secret", "abc#fragment", "%2e%2e", "a/b"],
)
async def test_address_cannot_change_request_path(monkeypatch, address):
    get_settings = AsyncMock()
    monkeypatch.setattr(helpers, "get_or_create_satspay_settings", get_settings)
    with pytest.raises(ValueError, match="Invalid onchain"):
        await helpers.fetch_onchain_balance(address)
    get_settings.assert_not_awaited()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:password@host",
        "https://host?path=/secret",
        "https://host#secret",
    ],
)
def test_invalid_mempool_configuration_rejected(url):
    with pytest.raises(ValidationError):
        SatspaySettings(mempool_url=url)


@pytest.mark.anyio
async def test_settings_validation_rejects_before_persisting_or_restarting(monkeypatch):
    dns(monkeypatch, "169.254.169.254")
    update = AsyncMock()
    monkeypatch.setattr(views_api, "update_satspay_settings", update)
    with pytest.raises(views_api.HTTPException) as exc:
        await views_api.api_update_settings(
            SatspaySettings(
                mempool_url="http://metadata.example", mempool_allow_private_ips=True
            )
        )
    assert exc.value.status_code == 422
    update.assert_not_awaited()


@pytest.mark.anyio
async def test_migration_defaults_existing_settings_to_off_and_persists_opt_in(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "lnbits_data_folder", str(tmp_path))
    db = Database("ext_satspay")
    monkeypatch.setattr(crud, "db", db)
    try:
        await migrations.m009_settings(db)
        await migrations.m012_add_setting_network(db)
        await migrations.m013_add_setting_webhook(db)
        await db.execute(
            "INSERT INTO satspay.settings (mempool_url, network, webhook_method) "
            "VALUES ('http://127.0.0.1:3006', 'Mainnet', 'GET')"
        )
        await migrations.m015_private_mempool_opt_in(db)
        config = await crud.get_or_create_satspay_settings()
        assert config.mempool_allow_private_ips is False
        config.mempool_allow_private_ips = True
        await crud.update_satspay_settings(config)
        assert (
            await crud.get_or_create_satspay_settings()
        ).mempool_allow_private_ips is True
    finally:
        await db.engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("private", [False, True])
async def test_live_updates_use_same_endpoint_policy(monkeypatch, private):
    from unittest.mock import Mock

    from .. import websocket_handler as ws

    config = SatspaySettings(
        mempool_url="https://mempool.example/testnet", mempool_allow_private_ips=private
    )
    monkeypatch.setattr(
        ws, "get_or_create_satspay_settings", AsyncMock(return_value=config)
    )
    connection = Mock(return_value=AsyncMock())
    monkeypatch.setattr(ws, "safe_websocket", connection)
    monkeypatch.setattr(ws, "consumer_handler", AsyncMock())
    monkeypatch.setattr(ws, "producer_handler", AsyncMock())
    with pytest.raises(Exception, match="unexpectedly finished"):
        await ws.websocket_handler()
    connection.assert_called_once_with(
        "wss://mempool.example/testnet/api/v1/ws",
        private_endpoint=config.mempool_url if private else None,
    )
