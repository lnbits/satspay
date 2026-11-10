from contextlib import asynccontextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
from lnbits import decorators
from lnbits.core.models import Wallet
from lnbits.core.views import generic
from lnbits.settings import settings

from .. import tasks, views, views_api
from ..models import Charge, SatspaySettings

READ_ROUTES = [
    ("GET", "/satspay/api/v1/charge/charge"),
    ("GET", "/satspay/api/v1/charge/balance/charge"),
]
WRITE_ROUTES = [
    ("PUT", "/satspay/api/v1/charge/balance/charge"),
    ("GET", "/satspay/api/v1/charge/webhook/charge"),
    ("DELETE", "/satspay/api/v1/charge/charge"),
]


@pytest.fixture
def state(monkeypatch):
    charge = Charge(
        id="charge",
        user="owner",
        amount=1000,
        time=30,
        timestamp=datetime.now(),
        onchainwallet="core:receiving-wallet",
        onchainaddress="bc1qcheckout",
        lnbitswallet="receiving-wallet",
        payment_request="lnbc-checkout-invoice",
        webhook="https://merchant.example/private-webhook",
        completelink="https://merchant.example/success",
        extra='{"private": "merchant-metadata"}',
    )
    state = SimpleNamespace(
        charge=charge,
        get_charge=AsyncMock(return_value=charge),
        check_charge_balance=AsyncMock(
            return_value=charge.model_copy(update={"pending": 500})
        ),
        update_charge=AsyncMock(side_effect=lambda value: value),
        call_webhook=AsyncMock(return_value={"webhook_success": True}),
        update_charge_webhook=AsyncMock(return_value=True),
        delete_charge=AsyncMock(),
        stop_onchain_listener=Mock(),
        listeners={},
    )
    for name in (
        "get_charge",
        "check_charge_balance",
        "update_charge",
        "call_webhook",
        "update_charge_webhook",
        "delete_charge",
        "stop_onchain_listener",
    ):
        monkeypatch.setattr(views_api, name, getattr(state, name))
    monkeypatch.setattr(views, "get_charge", state.get_charge)
    monkeypatch.setattr(views, "public_ws_listeners", state.listeners)
    monkeypatch.setattr(tasks, "public_ws_listeners", state.listeners)
    monkeypatch.setattr(settings, "lnbits_running", True)
    monkeypatch.setattr(
        views_api,
        "get_or_create_satspay_settings",
        AsyncMock(return_value=SatspaySettings()),
    )
    return state


@pytest.fixture
def client(monkeypatch, state):
    # Keep real key validation; replace only wallet storage and account policy.
    wallets = [
        Wallet(
            id=f"{user}-api-wallet",
            user=user,
            name="API wallet",
            inkey=f"{user}-invoice",
            adminkey=f"{user}-admin",
        )
        for user in ("owner", "other")
    ]

    async def get_wallet(key, conn=None):
        return next((w for w in wallets if key in (w.inkey, w.adminkey)), None)

    @asynccontextmanager
    async def connection():
        yield None

    monkeypatch.setattr(decorators, "db", SimpleNamespace(connect=connection))
    monkeypatch.setattr(decorators, "get_wallet_for_key", get_wallet)
    monkeypatch.setattr(decorators, "_check_user_access", AsyncMock())
    app = FastAPI()
    app.include_router(views_api.satspay_api_router, prefix="/satspay")
    app.include_router(views.satspay_generic_router, prefix="/satspay")
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("method,path", READ_ROUTES + WRITE_ROUTES)
@pytest.mark.parametrize("exists", [False, True])
def test_private_routes_reject_other_users_without_side_effects(
    client, state, method, path, exists
):
    if not exists:
        state.get_charge.return_value = None
    response = client.request(method, path, headers={"X-API-KEY": "other-admin"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Charge does not exist."}
    state.check_charge_balance.assert_not_awaited()
    state.call_webhook.assert_not_awaited()
    state.update_charge.assert_not_awaited()
    state.update_charge_webhook.assert_not_awaited()
    state.delete_charge.assert_not_awaited()
    state.stop_onchain_listener.assert_not_called()


@pytest.mark.parametrize("method,path", READ_ROUTES + WRITE_ROUTES)
def test_private_routes_require_authentication(client, state, method, path):
    response = client.request(method, path)

    assert response.status_code == 401
    state.get_charge.assert_not_awaited()


@pytest.mark.parametrize("method,path", READ_ROUTES)
@pytest.mark.parametrize("key", ["owner-invoice", "owner-admin"])
def test_owner_can_read_charge_with_either_key(client, state, method, path, key):
    response = client.request(method, path, headers={"X-API-KEY": key})

    assert response.status_code == 200
    assert response.json()["id"] == state.charge.id
    assert response.json()["webhook"] == state.charge.webhook


@pytest.mark.parametrize("method,path", WRITE_ROUTES)
def test_invoice_key_cannot_mutate_own_charge(client, state, method, path):
    response = client.request(method, path, headers={"X-API-KEY": "owner-invoice"})

    assert response.status_code == 403
    state.get_charge.assert_not_awaited()


@pytest.mark.parametrize("method,path", WRITE_ROUTES)
def test_owner_can_manage_charge_with_admin_key(client, state, method, path):
    response = client.request(method, path, headers={"X-API-KEY": "owner-admin"})

    assert response.status_code == 200
    if method == "PUT":
        state.check_charge_balance.assert_awaited_once_with(state.charge)
        state.update_charge.assert_awaited_once()
        assert response.json()["pending"] == 500
    elif method == "DELETE":
        state.delete_charge.assert_awaited_once_with(state.charge.id)
        state.stop_onchain_listener.assert_called_once_with(state.charge.onchainaddress)
    else:
        state.call_webhook.assert_awaited_once_with(state.charge)
        state.update_charge_webhook.assert_awaited_once()


@pytest.mark.parametrize(
    "paid,fasttrack,pending",
    [
        (False, False, 0),
        (True, False, 0),
        (False, True, 1000),
    ],
)
def test_public_status_keeps_checkout_fields_without_private_data(
    client, state, paid, fasttrack, pending
):
    state.charge.paid = paid
    state.charge.fasttrack = fasttrack
    state.charge.pending = pending

    response = client.get("/satspay/api/v1/charge/public/charge")

    assert response.status_code == 200
    data = response.json()
    assert data["onchainaddress"] == state.charge.onchainaddress
    assert data["payment_request"] == state.charge.payment_request
    assert data["paid"] == (paid or fasttrack)
    assert data["amount"] == state.charge.amount
    assert (
        not {"user", "webhook", "extra", "lnbitswallet", "onchainwallet"} & data.keys()
    )
    if paid or fasttrack:
        assert data["completelink"] == state.charge.completelink
    else:
        assert "completelink" not in data


def test_public_page_does_not_require_a_key(client, monkeypatch):
    renderer = Mock()
    renderer.TemplateResponse.return_value = HTMLResponse("checkout")
    monkeypatch.setattr(generic, "template_renderer", Mock(return_value=renderer))

    response = client.get("/satspay/charge")

    assert response.status_code == 200
    assert response.text == "checkout"
    renderer.TemplateResponse.assert_called_once()


def test_public_websocket_receives_payment_updates_without_a_key(client, state):
    with client.websocket_connect("/satspay/charge/ws") as websocket:
        assert client.portal
        client.portal.call(tasks.send_success_websocket, state.charge)
        unpaid = websocket.receive_json()
        assert unpaid == {
            "paid": False,
            "balance": 0,
            "pending": 0,
            "completelink": None,
        }

        state.charge.paid = True
        state.charge.balance = state.charge.amount
        client.portal.call(tasks.send_success_websocket, state.charge)
        paid = websocket.receive_json()
        assert paid == {
            "paid": True,
            "balance": 1000,
            "pending": 0,
            "completelink": state.charge.completelink,
        }
    assert state.listeners["charge"] == []
