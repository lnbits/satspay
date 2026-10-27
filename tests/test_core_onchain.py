import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from lnbits.core.models import KeyType
from pydantic import ValidationError

from .. import helpers, views_api
from ..models import Charge, CoreOnchainWallet, CreateCharge, SatspaySettings


def core_wallet(**overrides):
    values = {
        "id": "core-wallet",
        "user": "user",
        "name": "Savings",
        "wallet_type": "onchain",
        "inkey": "core-inkey",
        "onchain_wallet_kind": "watch",
        "onchain_network": "Mainnet",
        "onchain_meta": SimpleNamespace(backup_confirmed=False),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def charge_payload(onchainwallet: str) -> dict:
    return {
        "description": "test charge",
        "time": 15,
        "amount": 1000,
        "onchainwallet": onchainwallet,
    }


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(views_api.satspay_api_router, prefix="/satspay")
    wallet = SimpleNamespace(id="merchant", user="user", inkey="merchant-inkey")
    info = SimpleNamespace(key_type=KeyType.invoice, wallet=wallet)

    async def get_info():
        return info

    app.dependency_overrides[views_api.require_invoice_key] = get_info
    return app


@pytest.fixture
def mocks(monkeypatch):
    created: dict = {}
    state = SimpleNamespace(
        created=created,
        calls=[],
        fetched_core_wallets=[],
        core_wallet=None,
        settings_network="Mainnet",
        mempool_url=None,
        fetch_onchain_address=AsyncMock(return_value="bc1qwatchonly"),
        fetch_onchain_config_network=AsyncMock(return_value="Mainnet"),
    )

    async def get_settings():
        return SatspaySettings(
            network=state.settings_network,
            mempool_url=state.mempool_url
            or helpers.MEMPOOL_SPACE_URLS[state.settings_network],
        )

    async def create_charge(user, data, onchainaddress=None):
        state.calls.append("create")
        created.update(user=user, data=data, address=onchainaddress)
        return Charge(
            id="charge",
            user=user,
            amount=data.amount,
            time=data.time,
            timestamp=datetime.now(),
            description=data.description,
            onchainwallet=data.onchainwallet,
            onchainaddress=onchainaddress,
        )

    async def fetch_core_address(wallet):
        state.fetched_core_wallets.append(wallet)
        return "bc1qcore"

    async def get_core_wallet(wallet_id):
        return state.core_wallet

    monkeypatch.setattr(views_api, "get_or_create_satspay_settings", get_settings)

    def start_listener(address):
        state.calls.append("start")

    monkeypatch.setattr(views_api, "create_charge", create_charge)
    monkeypatch.setattr(views_api, "start_onchain_listener", start_listener)
    monkeypatch.setattr(views_api, "fetch_core_onchain_address", fetch_core_address)
    monkeypatch.setattr(views_api, "fetch_onchain_address", state.fetch_onchain_address)
    monkeypatch.setattr(
        views_api,
        "fetch_onchain_config_network",
        state.fetch_onchain_config_network,
    )
    monkeypatch.setattr(helpers, "get_onchain_wallet", get_core_wallet)
    return state


def post_charge(app, payload: dict) -> httpx.Response:
    async def run():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post("/satspay/api/v1/charge", json=payload)

    return asyncio.run(run())


def test_onchain_wallet_reference_parsing():
    assert helpers.parse_onchain_wallet_ref("watch-id") == ("watchonly", "watch-id")
    assert helpers.parse_onchain_wallet_ref("core:core-id") == ("core", "core-id")
    for reference in [
        "core:",
        "core:a:b",
        "core:a/b",
        "core:a?b",
        "core:a#b",
        "core::a",
    ]:
        with pytest.raises(ValidationError):
            CreateCharge.parse_obj(charge_payload(reference))


def test_core_reference_generates_address_and_is_persisted(app, mocks):
    mocks.core_wallet = core_wallet()
    response = post_charge(app, charge_payload("core:core-wallet"))

    assert response.status_code == 200
    assert mocks.fetched_core_wallets[0].id == "core-wallet"
    assert mocks.created["data"].onchainwallet == "core:core-wallet"
    assert mocks.created["address"] == "bc1qcore"
    assert mocks.created["user"] == "user"
    assert mocks.calls == ["create", "start"]
    mocks.fetch_onchain_address.assert_not_called()
    mocks.fetch_onchain_config_network.assert_not_called()


def test_core_reference_requires_owner(app, mocks):
    mocks.core_wallet = core_wallet(user="other-user")
    response = post_charge(app, charge_payload("core:core-wallet"))

    assert response.status_code == 400
    assert response.json()["detail"] == "Onchain wallet does not exist."
    assert mocks.fetched_core_wallets == []
    mocks.fetch_onchain_address.assert_not_called()


def test_core_reference_requires_initialized_wallet(app, mocks):
    mocks.core_wallet = core_wallet(onchain_wallet_kind=None)
    response = post_charge(app, charge_payload("core:core-wallet"))

    assert response.status_code == 400
    assert response.json()["detail"] == "Set up this onchain wallet before receiving."
    assert mocks.fetched_core_wallets == []


def test_core_reference_requires_hot_wallet_backup(app, mocks):
    mocks.core_wallet = core_wallet(onchain_wallet_kind="hot")
    response = post_charge(app, charge_payload("core:core-wallet"))

    assert response.status_code == 400
    assert response.json()["detail"] == "Back up this onchain wallet before receiving."
    assert mocks.fetched_core_wallets == []


def test_core_reference_rejects_network_mismatch(app, mocks):
    mocks.core_wallet = core_wallet(onchain_network="Testnet4")
    response = post_charge(app, charge_payload("core:core-wallet"))

    assert response.status_code == 400
    assert response.json()["detail"] == "Onchain network mismatch. Testnet4 != Mainnet"
    assert mocks.fetched_core_wallets == []


def test_core_testnet4_reference_works_when_configured(app, mocks):
    mocks.settings_network = "Testnet4"
    mocks.core_wallet = core_wallet(onchain_network="Testnet4")
    response = post_charge(app, charge_payload("core:core-wallet"))

    assert response.status_code == 200
    assert mocks.fetched_core_wallets[0].id == "core-wallet"
    assert mocks.created["address"] == "bc1qcore"


def test_core_testnet4_reference_rejected_on_testnet(app, mocks):
    mocks.settings_network = "Testnet"
    mocks.core_wallet = core_wallet(onchain_network="Testnet4")
    response = post_charge(app, charge_payload("core:core-wallet"))

    assert response.status_code == 400
    assert response.json()["detail"] == "Onchain network mismatch. Testnet4 != Testnet"
    assert mocks.fetched_core_wallets == []


def test_charge_rejects_mismatched_mempool_url(app, mocks):
    mocks.mempool_url = "https://mempool.space/testnet"
    mocks.core_wallet = core_wallet()
    response = post_charge(app, charge_payload("core:core-wallet"))

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Mempool URL for Mainnet must be https://mempool.space."
    )
    assert mocks.fetched_core_wallets == []


def test_invalid_core_reference_never_falls_back_to_watchonly(app, mocks):
    mocks.core_wallet = None
    response = post_charge(app, charge_payload("core:missing"))

    assert response.status_code == 400
    assert response.json()["detail"] == "Onchain wallet does not exist."
    mocks.fetch_onchain_address.assert_not_called()
    mocks.fetch_onchain_config_network.assert_not_called()


def test_malformed_core_reference_is_rejected(app, mocks):
    response = post_charge(app, charge_payload("core:a/b"))

    assert response.status_code == 422
    mocks.fetch_onchain_address.assert_not_called()
    mocks.fetch_onchain_config_network.assert_not_called()


def test_empty_onchain_reference_stays_optional(app, mocks):
    response = post_charge(
        app, {"description": "test charge", "time": 15, "amount": 1000}
    )

    assert response.status_code == 400
    assert "either onchainwallet or lnbitswallet" in response.json()["detail"]
    mocks.fetch_onchain_address.assert_not_called()


def test_legacy_watchonly_reference_is_unchanged(app, mocks):
    response = post_charge(app, charge_payload("watch-id"))

    assert response.status_code == 200
    assert mocks.created["data"].onchainwallet == "watch-id"
    assert mocks.created["address"] == "bc1qwatchonly"
    mocks.fetch_onchain_address.assert_awaited_once_with("watch-id", "merchant-inkey")


def test_core_wallet_discovery_endpoint_returns_safe_fields(app, monkeypatch):
    async def get_core_wallets(user_id):
        assert user_id == "user"
        return [
            CoreOnchainWallet(
                id="core-wallet",
                name="Savings",
                network="Mainnet",
                status="ready",
            )
        ]

    monkeypatch.setattr(views_api, "get_core_onchain_wallets", get_core_wallets)

    async def run():
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/satspay/api/v1/onchain-wallets")

    response = asyncio.run(run())

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "core-wallet",
            "name": "Savings",
            "network": "Mainnet",
            "status": "ready",
        }
    ]


def test_core_address_uses_selected_wallet_key(monkeypatch):
    calls: list[dict] = []

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            calls.append({"url": url, "headers": headers})
            return httpx.Response(200, json={"address": "bc1qnew"})

    monkeypatch.setattr(helpers.httpx, "AsyncClient", FakeAsyncClient)
    wallet = core_wallet()
    address = asyncio.run(helpers.fetch_core_onchain_address(wallet))

    assert address == "bc1qnew"
    assert calls[0]["headers"] == {"X-API-KEY": "core-inkey"}
    assert "/api/v1/onchain/address/core-wallet" in calls[0]["url"]


def test_core_address_reports_unbacked_hot_wallet(monkeypatch):
    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, headers=None):
            return httpx.Response(409, json={"detail": "Back up this wallet"})

    monkeypatch.setattr(helpers.httpx, "AsyncClient", FakeAsyncClient)
    with pytest.raises(ValueError, match="Back up this onchain wallet"):
        asyncio.run(helpers.fetch_core_onchain_address(core_wallet()))


def test_core_wallet_discovery_reports_readiness(monkeypatch):
    wallets = [
        SimpleNamespace(id="setup"),
        SimpleNamespace(id="backup"),
        SimpleNamespace(id="ready"),
    ]
    by_id = {
        "setup": core_wallet(id="setup", onchain_wallet_kind=None),
        "backup": core_wallet(id="backup", onchain_wallet_kind="hot"),
        "ready": core_wallet(
            id="ready",
            onchain_wallet_kind="hot",
            onchain_meta=SimpleNamespace(backup_confirmed=True),
        ),
    }
    monkeypatch.setattr(helpers, "get_wallets", AsyncMock(return_value=wallets))

    async def get_onchain_wallet(wallet_id):
        return by_id[wallet_id]

    monkeypatch.setattr(helpers, "get_onchain_wallet", get_onchain_wallet)
    result = asyncio.run(helpers.get_core_onchain_wallets("user"))

    assert [(wallet.id, wallet.status) for wallet in result] == [
        ("setup", "setup"),
        ("backup", "backup"),
        ("ready", "ready"),
    ]
    assert set(result[0].dict()) == {"id", "name", "network", "status"}
