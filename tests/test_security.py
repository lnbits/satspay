import hmac
import inspect
import ipaddress
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import lnbits.db as db_module
import pytest
from fastapi import FastAPI, HTTPException, Request, WebSocket
from lnbits.core.models import Account, KeyType, Payment, Wallet, WalletTypeInfo
from lnbits.db import Database
from lnbits.decorators import require_admin_key, require_invoice_key
from lnbits.settings import settings
from pydantic import ValidationError

from .. import (
    crud,
    helpers,
    migrations,
    satspay_ext,
    tasks,
    views,
    views_api,
    views_api_themes,
)
from ..models import (
    Charge,
    CreateCharge,
    CreateSatsPayTheme,
    OnchainBalance,
    SatsPayTheme,
)
from ..websocket_handler import ws_send_queue


@pytest.fixture
def anyio_backend():
    return "asyncio", {"use_uvloop": True}


@pytest.fixture
def charge():
    return Charge(
        id="charge",
        user="owner",
        amount=100,
        time=10,
        timestamp=datetime.now(timezone.utc),
        lnbitswallet="wallet",
        payment_hash="hash",
        onchainwallet="watch-wallet",
        onchainaddress="address",
        webhook="https://merchant.example/callback?token=secret",
        webhook_secret="a" * 64,
        extra='{"customer":"private"}',
    )


@pytest.fixture(autouse=True)
def state(monkeypatch):
    monkeypatch.setattr(db_module, "DB_TYPE", db_module.SQLITE)
    monkeypatch.setattr(settings, "lnbits_callback_url_rules", [])
    monkeypatch.setattr(settings, "lnbits_callback_allow_private_ips", False)
    monkeypatch.setattr(settings, "lnbits_running", True)
    tasks.tracked_addresses.clear()
    tasks.public_ws_listeners.clear()
    while not ws_send_queue.empty():
        ws_send_queue.get_nowait()
    yield
    tasks.tracked_addresses.clear()
    tasks.public_ws_listeners.clear()
    while not ws_send_queue.empty():
        ws_send_queue.get_nowait()


@pytest.fixture
async def database(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "lnbits_data_folder", str(tmp_path))
    db = Database("ext_satspay")
    monkeypatch.setattr(crud, "db", db)
    for name, migrate in inspect.getmembers(migrations, inspect.isfunction):
        if name.startswith("m"):
            await migrate(db)
    yield db
    await db.engine.dispose()


@pytest.fixture
async def client(database, charge, monkeypatch):
    await database.insert("satspay.charges", charge)
    monkeypatch.setattr(
        views_api, "get_wallet", AsyncMock(return_value=SimpleNamespace(user="owner"))
    )
    monkeypatch.setattr(
        crud,
        "create_invoice",
        AsyncMock(
            return_value=SimpleNamespace(payment_hash="new-hash", bolt11="invoice")
        ),
    )
    app = FastAPI()
    app.include_router(satspay_ext)

    async def invoice_auth(request: Request):
        user, kind = request.headers["X-API-KEY"].split("-")
        return WalletTypeInfo(
            KeyType.admin if kind == "admin" else KeyType.invoice,
            Wallet(
                id="wallet",
                name="wallet",
                user=user,
                inkey="invoice-key",
                adminkey="admin-key",
            ),
        )

    async def admin_auth(request: Request):
        info = await invoice_auth(request)
        if info.key_type != KeyType.admin:
            raise HTTPException(401)
        return info

    app.dependency_overrides[require_invoice_key] = invoice_auth
    app.dependency_overrides[require_admin_key] = admin_auth
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as session:
        yield session


@pytest.mark.anyio
@pytest.mark.parametrize("key", ["owner-invoice", "other-invoice", "other-admin"])
@pytest.mark.parametrize("path", ["charge/charge", "charge/balance/charge"])
async def test_invoice_reads_only_status(client, key, path):
    response = await client.get(f"/satspay/api/v1/{path}", headers={"X-API-KEY": key})
    assert response.status_code == 200
    data = response.json()
    assert not {"user", "webhook", "webhook_secret", "extra"} & data.keys()
    assert data["lnbitswallet"] == "wallet"
    assert data["paid"] is False


@pytest.mark.anyio
async def test_owner_admin_can_read_full_charge(client):
    response = await client.get(
        "/satspay/api/v1/charge/charge", headers={"X-API-KEY": "owner-admin"}
    )
    assert response.json()["webhook_secret"] == "a" * 64


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["invoice", "admin"])
async def test_creation_response_respects_key_type(client, kind):
    response = await client.post(
        "/satspay/api/v1/charge",
        headers={"X-API-KEY": f"owner-{kind}"},
        json={
            "description": "order",
            "amount": 100,
            "time": 10,
            "lnbitswallet": "wallet",
            "webhook": "https://merchant.example/callback",
            "extra": '{"order":"private"}',
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    stored = await crud.get_charge(data["id"])
    assert stored and stored.webhook_secret
    assert len(stored.webhook_secret) == 64
    assert ("user" in data) is (kind == "admin")
    if kind == "invoice":
        assert not {"webhook", "webhook_secret", "extra"} & data.keys()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method,path",
    [
        ("DELETE", "charge/charge"),
        ("PUT", "charge/balance/charge"),
        ("GET", "charge/webhook/charge"),
        ("POST", "charge/webhook/charge"),
    ],
)
async def test_foreign_admin_rejected_before_side_effects(
    client, charge, monkeypatch, method, path
):
    callback = AsyncMock()
    refresh = AsyncMock()
    monkeypatch.setattr(views_api, "call_webhook", callback)
    monkeypatch.setattr(views_api, "check_charge_balance", refresh)
    tasks.start_onchain_listener(charge)
    response = await client.request(
        method, f"/satspay/api/v1/{path}", headers={"X-API-KEY": "other-admin"}
    )
    assert response.status_code == 404
    assert await crud.get_charge(charge.id) == charge
    assert charge.onchainaddress in tasks.tracked_addresses
    callback.assert_not_called()
    refresh.assert_not_called()


@pytest.mark.anyio
async def test_owner_delete_stops_tracking(client, charge):
    tasks.start_onchain_listener(charge)
    response = await client.delete(
        "/satspay/api/v1/charge/charge", headers={"X-API-KEY": "owner-admin"}
    )
    assert response.status_code == 200
    assert await crud.get_charge(charge.id) is None
    assert not tasks.tracked_addresses


@pytest.mark.anyio
async def test_refresh_persists_paid_before_callback(client, monkeypatch):
    monkeypatch.setattr(helpers, "get_standalone_payment", AsyncMock(return_value=None))
    balance = AsyncMock(
        return_value=OnchainBalance(confirmed=0, unconfirmed=100, txids=[])
    )
    monkeypatch.setattr(helpers, "fetch_onchain_balance", balance)

    async def callback(charge):
        stored = await crud.get_charge(charge.id)
        assert stored and stored.paid
        return {"webhook_success": True}

    webhook = AsyncMock(side_effect=callback)
    monkeypatch.setattr(views_api, "call_webhook", webhook)
    path = "/satspay/api/v1/charge/balance/charge"
    headers = {"X-API-KEY": "owner-admin"}
    response = await client.put(path, headers=headers)
    assert response.status_code == 200
    assert response.json()["paid"] is False
    webhook.assert_not_called()
    balance.return_value = OnchainBalance(confirmed=100, unconfirmed=0, txids=[])
    response = await client.put(path, headers=headers)
    assert response.json()["paid"] is True
    assert (await client.put(path, headers=headers)).status_code == 400
    webhook.assert_awaited_once()


@pytest.mark.anyio
async def test_lightning_settlement_not_overwritten_by_onchain(charge, monkeypatch):
    payment = SimpleNamespace(
        check_status=AsyncMock(return_value=SimpleNamespace(success=True))
    )
    monkeypatch.setattr(
        helpers, "get_standalone_payment", AsyncMock(return_value=payment)
    )
    balance = AsyncMock()
    monkeypatch.setattr(helpers, "fetch_onchain_balance", balance)
    updated = await helpers.check_charge_balance(charge)
    assert updated.paid and updated.balance == updated.amount
    balance.assert_not_called()


@pytest.mark.parametrize("extra", ["invalid", "[]", '"text"', "null"])
def test_extra_is_validated_and_old_records_are_safe(charge, extra):
    with pytest.raises(ValidationError):
        CreateCharge(description="order", amount=100, time=1, extra=extra)
    charge.extra = extra
    charge.add_extra({"payment_method": "lightning"})
    assert json.loads(charge.extra) == {"payment_method": "lightning"}


@pytest.mark.parametrize("value", [-1, 0, float("inf"), float("nan")])
def test_fiat_amount_must_be_positive_and_finite(value):
    with pytest.raises(ValidationError):
        CreateCharge(description="order", currency_amount=value, time=1)


@pytest.mark.anyio
async def test_fiat_rounding_to_zero_is_rejected(client, monkeypatch):
    invoice = AsyncMock()
    monkeypatch.setattr(crud, "create_invoice", invoice)
    monkeypatch.setattr(
        views_api, "get_fiat_rate_satoshis", AsyncMock(return_value=0.01)
    )
    response = await client.post(
        "/satspay/api/v1/charge",
        headers={"X-API-KEY": "owner-invoice"},
        json={
            "description": "order",
            "time": 1,
            "currency": "USD",
            "currency_amount": 1,
            "lnbitswallet": "wallet",
        },
    )
    assert response.status_code == 400
    invoice.assert_not_awaited()


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,hello",
        "/relative",
        "https://example.com:99999",
    ],
)
def test_completion_url_validation_covers_legacy_records(charge, url):
    with pytest.raises(ValidationError):
        CreateCharge(description="order", time=1, amount=1, completelink=url)
    charge.completelink = url
    charge.paid = True
    assert charge.status["completelink"] is None
    assert charge.public["completelink"] is None


def test_fasttrack_does_not_change_api_settlement_status(charge):
    charge.pending = charge.amount
    charge.fasttrack = True
    assert charge.public["paid"] is True
    assert charge.status["paid"] is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    "ip",
    ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1", "::ffff:127.0.0.1"],
)
async def test_webhook_rejects_private_dns_results(charge, monkeypatch, ip):
    monkeypatch.setattr(
        helpers,
        "_resolve_webhook_host",
        AsyncMock(return_value=[ipaddress.ip_address(ip)]),
    )
    client = Mock()
    monkeypatch.setattr(helpers.httpx, "AsyncClient", client)
    result = await helpers.call_webhook(charge)
    assert result == {
        "webhook_success": False,
        "webhook_message": "Webhook request failed.",
    }
    client.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://user:password@merchant.example/",
    ],
)
async def test_webhook_rejects_invalid_schemes_and_credentials(
    charge, monkeypatch, url
):
    charge.webhook = url
    resolve = AsyncMock()
    monkeypatch.setattr(helpers, "_resolve_webhook_host", resolve)
    assert not (await helpers.call_webhook(charge))["webhook_success"]
    resolve.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize(
    "response_status,response_body", [(200, b"ok"), (302, b""), (200, b"x" * 65537)]
)
async def test_webhook_pins_target_signs_safe_body_and_bounds_response(
    charge, monkeypatch, method, response_status, response_body
):
    monkeypatch.setattr(
        helpers,
        "_resolve_webhook_host",
        AsyncMock(return_value=[ipaddress.ip_address("93.184.216.34")]),
    )
    monkeypatch.setattr(
        helpers,
        "get_or_create_satspay_settings",
        AsyncMock(return_value=SimpleNamespace(webhook_method=method)),
    )
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "merchant.example"
        assert request.extensions["sni_hostname"] == "merchant.example"
        assert request.method == method
        payload = json.loads(request.content)
        assert not {"user", "extra", "webhook", "webhook_secret"} & payload.keys()
        signed = request.headers["X-LNBits-Timestamp"].encode() + b"." + request.content
        assert hmac.compare_digest(
            request.headers["X-LNBits-Signature"],
            hmac.new(charge.webhook_secret.encode(), signed, "sha256").hexdigest(),
        )
        return httpx.Response(
            response_status,
            content=response_body,
            headers={"Location": "http://127.0.0.1/"},
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        helpers.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    result = await helpers.call_webhook(charge)
    assert result["webhook_success"] is (
        response_status == 200 and len(response_body) <= 65536
    )
    assert len(requests) == 1


@pytest.mark.anyio
async def test_watchonly_ownership_checked_before_requesting_address(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/watchonly/api/v1/wallet"
        return httpx.Response(200, json=[{"id": "own-wallet"}])

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        helpers.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ValueError, match="does not belong"):
        await helpers.fetch_onchain_address("foreign-wallet", "invoice-key", "Mainnet")
    assert len(requests) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("data", [None, {}, {"address": ""}])
async def test_watchonly_invalid_address_response(monkeypatch, data):
    def handler(request):
        return httpx.Response(
            200,
            json=(
                [{"id": "own-wallet"}] if request.url.path.endswith("/wallet") else data
            ),
        )

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        helpers.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    with pytest.raises(ValueError):
        await helpers.fetch_onchain_address("own-wallet", "invoice-key", "Mainnet")


@pytest.mark.anyio
async def test_theme_writes_require_owner(database):
    theme = SatsPayTheme(
        css_id="theme", user="owner", title="original", custom_css="body {}"
    )
    await database.insert("satspay.themes", theme)
    for user in ["other", "owner"]:
        data = CreateSatsPayTheme(title="updated", custom_css="p {}")
        if user == "other":
            with pytest.raises(HTTPException) as exc:
                await views_api_themes.api_themes_save(
                    theme.css_id, data, Account(id=user)
                )
            assert exc.value.status_code == 404
            with pytest.raises(HTTPException):
                await views_api_themes.api_theme_delete(theme.css_id, Account(id=user))
        else:
            await views_api_themes.api_themes_save(theme.css_id, data, Account(id=user))
            updated = await crud.get_theme(theme.css_id)
            assert updated and updated.title == "updated"
            await views_api_themes.api_theme_delete(theme.css_id, Account(id=user))
            assert await crud.get_theme(theme.css_id) is None


@pytest.mark.anyio
async def test_onchain_callbacks_only_for_paid_and_stale_updates_ignored(
    database, charge, monkeypatch
):
    await database.insert("satspay.charges", charge)
    webhook = AsyncMock(return_value={"webhook_success": True})
    monkeypatch.setattr(tasks, "call_webhook", webhook)
    tasks.start_onchain_listener(charge)
    await tasks._handle_ws_message("address", {"mempool": [], "confirmed": []})
    webhook.assert_not_called()
    await tasks._handle_ws_message(
        "address",
        {
            "confirmed": [
                {
                    "txid": "tx",
                    "vout": [{"scriptpubkey_address": "address", "value": 100}],
                }
            ]
        },
    )
    webhook.assert_awaited_once()
    stored = await crud.get_charge(charge.id)
    assert stored and stored.paid
    assert not tasks.tracked_addresses
    await tasks._handle_ws_message("address", {"confirmed": []})
    stored = await crud.get_charge(charge.id)
    assert stored and stored.paid
    webhook.assert_awaited_once()


@pytest.mark.anyio
async def test_lightning_completion_untracks_combined_charge(
    database, charge, monkeypatch
):
    await database.insert("satspay.charges", charge)
    webhook = AsyncMock(return_value={"webhook_success": True})
    monkeypatch.setattr(tasks, "call_webhook", webhook)
    tasks.start_onchain_listener(charge)
    payment = Payment(
        checking_id="checking-id",
        wallet_id="wallet",
        fee=0,
        bolt11="invoice",
        extra={"tag": "charge", "charge": charge.id},
        payment_hash="hash",
        amount=100000,
    )
    await tasks.on_invoice_paid(payment)
    await tasks.on_invoice_paid(payment)
    assert not tasks.tracked_addresses
    stored = await crud.get_charge(charge.id)
    assert stored and stored.paid
    webhook.assert_awaited_once()


def test_tracking_expiry_limit_mapping_and_queue_coalescing(charge, monkeypatch):
    monkeypatch.setattr(tasks, "MAX_TRACKED_ADDRESSES", 1)
    tasks.start_onchain_listener(charge)
    assert ws_send_queue.qsize() == 1
    other = charge.copy(update={"id": "other", "onchainaddress": "other-address"})
    with pytest.raises(ValueError, match="capacity"):
        tasks.start_onchain_listener(other)
    charge.timestamp = datetime.now() - timedelta(hours=1)
    tasks.prune_address_tracking()
    assert not tasks.tracked_addresses
    assert ws_send_queue.qsize() == 1
    assert ws_send_queue.get_nowait() == {"track-addresses": []}
    tasks.start_onchain_listener(other)
    with pytest.raises(ValueError, match="already tracked"):
        tasks.start_onchain_listener(other.copy(update={"id": "different"}))


@pytest.mark.anyio
async def test_public_websocket_cleanup_and_limits(charge, monkeypatch):
    monkeypatch.setattr(views, "get_charge", AsyncMock(return_value=charge))
    send = AsyncMock()
    receive = AsyncMock(
        side_effect=[
            {"type": "websocket.connect"},
            {"type": "websocket.disconnect", "code": 1000},
        ]
    )
    ws = WebSocket({"type": "websocket", "client": ("source", 1234)}, receive, send)
    await views.websocket_charge(ws, charge.id)
    assert not tasks.public_ws_listeners
    tasks.public_ws_listeners[charge.id] = [ws] * views.MAX_PUBLIC_WS_PER_IP
    rejected = WebSocket(
        {"type": "websocket", "client": ("source", 1235)},
        AsyncMock(return_value={"type": "websocket.connect"}),
        send,
    )
    send.reset_mock()
    await views.websocket_charge(rejected, charge.id)
    send.assert_any_await({"type": "websocket.close", "code": 1013, "reason": ""})
    assert send.await_count == 2


@pytest.mark.anyio
async def test_secret_migration_backfills_existing_charges(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "lnbits_data_folder", str(tmp_path))
    db = Database("ext_satspay")
    try:
        for name, migrate in inspect.getmembers(migrations, inspect.isfunction):
            if name.startswith("m") and name < "m015":
                await migrate(db)
        await db.execute(
            "INSERT INTO satspay.charges (id, webhook) VALUES (:id, :webhook)",
            {"id": "old", "webhook": "https://merchant.example/"},
        )
        await migrations.m015_add_webhook_secret(db)
        row = await db.fetchone(
            "SELECT webhook_secret FROM satspay.charges WHERE id = :id", {"id": "old"}
        )
        assert row and len(row["webhook_secret"]) == 64
    finally:
        await db.engine.dispose()


@pytest.mark.anyio
async def test_stale_update_cannot_reset_settled_charge(database, charge):
    await database.insert("satspay.charges", charge)
    paid = charge.copy(update={"paid": True, "balance": charge.amount})
    paid.add_extra({"payment_method": "lightning"})
    await crud.update_charge(paid)
    current = await crud.update_charge(charge)
    assert current.paid and current.balance == charge.amount
    assert json.loads(current.extra or "{}")["payment_method"] == "lightning"
    current.add_extra({"webhook_success": True})
    await crud.update_charge(current)
    stored = await crud.get_charge(charge.id)
    assert stored and stored.paid
    assert json.loads(stored.extra or "{}")["webhook_success"] is True


@pytest.mark.anyio
async def test_startup_refresh_preserves_concurrent_payment(
    database, charge, monkeypatch
):
    await database.insert("satspay.charges", charge)
    callback = AsyncMock(return_value={"webhook_success": True})
    monkeypatch.setattr(tasks, "call_webhook", callback)

    async def refresh(stale):
        paid = stale.copy(update={"paid": True, "balance": stale.amount})
        await crud.update_charge(paid)
        await callback(paid)
        return stale

    monkeypatch.setattr(tasks, "check_charge_balance", refresh)
    await tasks.restart_address_tracking()
    stored = await crud.get_charge(charge.id)
    assert stored and stored.paid and stored.balance == charge.amount
    assert not tasks.tracked_addresses
    callback.assert_awaited_once()


@pytest.mark.anyio
async def test_pending_payment_confirms_after_expiry(database, charge, monkeypatch):
    await database.insert("satspay.charges", charge)
    callback = AsyncMock(return_value={"webhook_success": True})
    monkeypatch.setattr(tasks, "call_webhook", callback)
    tasks.start_onchain_listener(charge)
    tx = {
        "txid": "tx",
        "vout": [{"scriptpubkey_address": "address", "value": charge.amount}],
    }
    await tasks._handle_ws_message("address", {"mempool": [tx]})
    assert tasks.tracked_addresses["address"].pending == charge.amount
    monkeypatch.setattr(
        tasks.time, "time", lambda: charge.timestamp.timestamp() + charge.time * 60 + 1
    )
    tasks.prune_address_tracking()
    assert "address" in tasks.tracked_addresses
    await tasks._handle_ws_message("address", {"confirmed": [tx]})
    stored = await crud.get_charge(charge.id)
    assert stored and stored.paid
    assert not tasks.tracked_addresses
    callback.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("balance,pending", [(0, 100), (50, 0)])
async def test_restart_keeps_funded_expired_charges(
    database, charge, monkeypatch, balance, pending
):
    charge.timestamp -= timedelta(hours=1)
    charge.balance = balance
    charge.pending = pending
    await database.insert("satspay.charges", charge)
    monkeypatch.setattr(
        tasks, "check_charge_balance", AsyncMock(side_effect=lambda value: value)
    )
    await tasks.restart_address_tracking()
    tasks.prune_address_tracking()
    assert charge.onchainaddress in tasks.tracked_addresses


@pytest.mark.anyio
async def test_migration_retry_preserves_existing_secrets(database, charge):
    await database.insert("satspay.charges", charge)
    missing = charge.copy(update={"id": "missing", "webhook_secret": None})
    await database.insert("satspay.charges", missing)
    await migrations.m015_add_webhook_secret(database)
    original = await crud.get_charge(charge.id)
    filled = await crud.get_charge(missing.id)
    assert original and original.webhook_secret == charge.webhook_secret
    assert filled and filled.webhook_secret and len(filled.webhook_secret) == 64
    await migrations.m015_add_webhook_secret(database)
    retried = await crud.get_charge(missing.id)
    assert retried and retried.webhook_secret == filled.webhook_secret


@pytest.mark.anyio
async def test_broadcast_only_registers_accepted_websocket(charge, monkeypatch):
    monkeypatch.setattr(views, "get_charge", AsyncMock(return_value=charge))
    send = AsyncMock()
    receiving_connect = True

    async def receive():
        nonlocal receiving_connect
        if receiving_connect:
            receiving_connect = False
            assert charge.id not in tasks.public_ws_listeners
            await tasks.send_success_websocket(charge)
            return {"type": "websocket.connect"}
        assert ws in tasks.public_ws_listeners[charge.id]
        await tasks.send_success_websocket(charge)
        return {"type": "websocket.disconnect", "code": 1000}

    ws = WebSocket({"type": "websocket", "client": ("source", 1234)}, receive, send)
    await views.websocket_charge(ws, charge.id)
    assert [call.args[0]["type"] for call in send.await_args_list] == [
        "websocket.accept",
        "websocket.send",
    ]
    assert not tasks.public_ws_listeners


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure", [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout]
)
async def test_webhook_failover_and_safe_logs(charge, monkeypatch, failure):
    ips = ["2001:4860:4860::8888", "93.184.216.34"]
    monkeypatch.setattr(
        helpers,
        "_resolve_webhook_host",
        AsyncMock(return_value=[ipaddress.ip_address(value) for value in ips]),
    )
    monkeypatch.setattr(
        helpers,
        "get_or_create_satspay_settings",
        AsyncMock(return_value=SimpleNamespace(webhook_method="POST")),
    )
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            raise failure("secret-url-token", request=request)
        assert request.headers["host"] == "merchant.example"
        assert request.extensions["sni_hostname"] == "merchant.example"
        return httpx.Response(200, text="ok")

    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        helpers.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    logs = []
    sink = helpers.logger.add(lambda message: logs.append(str(message)))
    try:
        result = await helpers.call_webhook(charge)
    finally:
        helpers.logger.remove(sink)
    retry = failure in (httpx.ConnectError, httpx.ConnectTimeout)
    assert result["webhook_success"] is retry
    assert [request.url.host for request in requests] == (ips if retry else ips[:1])
    assert "secret-url-token" not in "".join(logs)
    assert "token=secret" not in "".join(logs)
    if not retry:
        assert "ReadTimeout" in "".join(logs)


@pytest.mark.anyio
async def test_onchain_logs_http_status_without_url(charge, monkeypatch):
    request = httpx.Request("GET", "https://mempool.example/?token=private")
    response = httpx.Response(503, request=request)
    error = httpx.HTTPStatusError("token=private", request=request, response=response)
    monkeypatch.setattr(helpers, "get_standalone_payment", AsyncMock(return_value=None))
    monkeypatch.setattr(helpers, "fetch_onchain_balance", AsyncMock(side_effect=error))
    logs = []
    sink = helpers.logger.add(lambda message: logs.append(str(message)))
    try:
        await helpers.check_charge_balance(charge)
    finally:
        helpers.logger.remove(sink)
    assert "HTTP 503" in "".join(logs)
    assert "token=private" not in "".join(logs)


@pytest.mark.anyio
async def test_onchain_prunes_once_per_message(monkeypatch):
    prune = Mock()
    monkeypatch.setattr(tasks, "prune_address_tracking", prune)
    handle = AsyncMock(
        side_effect=lambda *_: setattr(settings, "lnbits_running", False)
    )
    monkeypatch.setattr(tasks, "_handle_ws_message", handle)
    tasks.ws_receive_queue.put_nowait(
        {"multi-address-transactions": {"a": {}, "b": {}}}
    )
    await tasks.wait_for_onchain()
    assert handle.await_count == 2
    prune.assert_called_once()
