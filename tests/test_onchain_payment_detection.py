import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio
from lnbits.core.models import Payment
from lnbits.db import Database
from lnbits.settings import settings

from .. import crud, helpers, migrations, tasks, views_api, websocket_handler
from ..models import Charge, OnchainBalance


def make_charge(**overrides) -> Charge:
    values: dict[str, Any] = {
        "id": "charge",
        "user": "user",
        "amount": 20000,
        "time": 30,
        "timestamp": datetime.now(),
        "onchainaddress": "address",
        "onchainwallet": "core:wallet",
        "zeroconf": True,
        "webhook": "https://example.com/webhook",
    }
    values.update(overrides)
    return Charge(**values)


def drain_queues():
    while not websocket_handler.ws_receive_queue.empty():
        websocket_handler.ws_receive_queue.get_nowait()
    while not websocket_handler.ws_send_queue.empty():
        websocket_handler.ws_send_queue.get_nowait()


@pytest.fixture
def refresh_mocks(monkeypatch):
    state = SimpleNamespace(
        charge=None,
        checked=None,
        notify_webhook=None,
        check_calls=[],
        updated=[],
        websocket=AsyncMock(),
        webhook=AsyncMock(return_value={"webhook_success": True}),
    )

    async def get_charge(address):
        return state.charge

    async def check_charge_balance(charge, notify_webhook=True):
        state.check_calls.append(charge)
        state.notify_webhook = notify_webhook
        return state.checked

    async def update_charge(charge):
        state.updated.append(charge)
        return charge

    async def update_pending_charge(charge):
        state.updated.append(charge)
        return True

    monkeypatch.setattr(tasks, "get_charge_by_onchain_address", get_charge)
    monkeypatch.setattr(tasks, "check_charge_balance", check_charge_balance)
    monkeypatch.setattr(tasks, "update_charge", update_charge)
    monkeypatch.setattr(tasks, "update_charge_webhook", AsyncMock(return_value=True))
    monkeypatch.setattr(tasks, "update_pending_charge", update_pending_charge)
    monkeypatch.setattr(tasks, "send_success_websocket", state.websocket)
    monkeypatch.setattr(tasks, "call_webhook", state.webhook)
    return state


def test_refresh_returns_false_for_paid_charge(refresh_mocks):
    refresh_mocks.charge = make_charge(paid=True)

    assert asyncio.run(tasks._refresh_onchain_charge("address")) is False
    assert refresh_mocks.check_calls == []


def test_refresh_returns_false_for_missing_charge(refresh_mocks):
    refresh_mocks.charge = None

    assert asyncio.run(tasks._refresh_onchain_charge("address")) is False
    assert refresh_mocks.check_calls == []


def test_refresh_returns_false_for_expired_charge(refresh_mocks):
    refresh_mocks.charge = make_charge(timestamp=datetime.now() - timedelta(hours=2))

    assert asyncio.run(tasks._refresh_onchain_charge("address")) is False
    assert refresh_mocks.check_calls == []


def test_refresh_returns_true_for_open_charge(refresh_mocks):
    refresh_mocks.charge = make_charge()
    refresh_mocks.checked = make_charge()

    assert asyncio.run(tasks._refresh_onchain_charge("address")) is True
    assert refresh_mocks.updated == []
    refresh_mocks.websocket.assert_not_called()
    refresh_mocks.webhook.assert_not_called()


def test_refresh_detects_paid_charge(refresh_mocks):
    refresh_mocks.charge = make_charge()
    refresh_mocks.checked = make_charge(balance=20000, pending=20000, paid=True)

    assert asyncio.run(tasks._refresh_onchain_charge("address")) is False
    assert refresh_mocks.notify_webhook is False
    assert refresh_mocks.updated[0] == refresh_mocks.checked
    refresh_mocks.websocket.assert_awaited_once_with(refresh_mocks.checked)
    refresh_mocks.webhook.assert_awaited_once()


def test_refresh_reports_partial_payment(refresh_mocks):
    refresh_mocks.charge = make_charge()
    refresh_mocks.checked = make_charge(balance=10000, pending=10000)

    assert asyncio.run(tasks._refresh_onchain_charge("address")) is True
    assert refresh_mocks.updated[0] == refresh_mocks.checked
    refresh_mocks.websocket.assert_awaited_once_with(refresh_mocks.checked)
    refresh_mocks.webhook.assert_awaited_once()


def test_check_charge_balance_can_skip_webhook(monkeypatch):
    charge = make_charge()
    webhook = AsyncMock()

    async def fetch_balance(address):
        return OnchainBalance(confirmed=0, unconfirmed=20000, txids=["txid"])

    monkeypatch.setattr(helpers, "fetch_onchain_balance", fetch_balance)
    monkeypatch.setattr(helpers, "call_webhook", webhook)

    charge = asyncio.run(helpers.check_charge_balance(charge, notify_webhook=False))

    assert charge.balance == 20000
    assert charge.pending == 20000
    assert charge.paid is True
    webhook.assert_not_called()


def test_refresh_persists_replacement_txid_without_notification(refresh_mocks):
    refresh_mocks.charge = make_charge(pending=10000, extra='{"txids": ["old"]}')
    refresh_mocks.checked = make_charge(pending=10000, extra='{"txids": ["new"]}')

    assert asyncio.run(tasks._refresh_onchain_charge("address")) is True
    assert refresh_mocks.updated == [refresh_mocks.checked]
    refresh_mocks.websocket.assert_not_called()
    refresh_mocks.webhook.assert_not_called()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def charge_db(tmp_path_factory):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            settings, "lnbits_data_folder", str(tmp_path_factory.mktemp("satspay"))
        )
        db = Database("ext_satspay")
        monkeypatch.setattr(crud, "db", db)
        try:
            async with db.connect() as conn:
                for name in sorted(vars(migrations)):
                    if name.startswith("m0"):
                        await getattr(migrations, name)(conn)
            yield db
        finally:
            await db.engine.dispose()


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("payment_during", ["balance_fetch", "webhook"])
async def test_refresh_preserves_concurrent_lightning_payment(
    monkeypatch, charge_db, payment_during
):
    websocket = AsyncMock()
    webhook = AsyncMock()
    monkeypatch.setattr(tasks, "send_success_websocket", websocket)
    monkeypatch.setattr(tasks, "call_webhook", webhook)
    monkeypatch.setattr(helpers, "get_standalone_payment", AsyncMock(return_value=None))
    payment = Payment(
        checking_id="hash",
        wallet_id="lightning",
        fee=0,
        bolt11="",
        status="success",
        extra={"tag": "charge", "charge": "charge"},
        payment_hash="hash",
        amount=20000000,
    )

    async def fetch_balance(address):
        if payment_during == "balance_fetch":
            await tasks.on_invoice_paid(payment)
        return OnchainBalance(confirmed=0, unconfirmed=10000, txids=["partial"])

    async def call_webhook(charge):
        if payment_during == "webhook" and not charge.paid:
            await tasks.on_invoice_paid(payment)
        return {"webhook_success": True}

    monkeypatch.setattr(helpers, "fetch_onchain_balance", fetch_balance)
    webhook.side_effect = call_webhook

    charge = make_charge(lnbitswallet="lightning", payment_hash="hash")
    await charge_db.insert("satspay.charges", charge)

    try:
        await tasks._refresh_onchain_charge("address")

        stored = await crud.get_charge(charge.id)
        assert stored
        assert stored.paid is True
        assert stored.balance == charge.amount
        assert '"payment_method": "lightning"' in (stored.extra or "")
        expected_notifications = 1 if payment_during == "balance_fetch" else 2
        assert webhook.await_count == expected_notifications
        assert websocket.await_count == webhook.await_count
    finally:
        await crud.delete_charge(charge.id)


def test_subscription_messages_include_init_and_addresses():
    websocket_handler.tracked_addresses.clear()
    try:
        assert websocket_handler.subscription_messages() == [{"action": "init"}]

        websocket_handler.tracked_addresses.append("address")
        assert websocket_handler.subscription_messages() == [
            {"action": "init"},
            {"track-addresses": ["address"]},
        ]
    finally:
        websocket_handler.tracked_addresses.clear()


def test_ws_message_refreshes_tracked_address(monkeypatch):
    called = asyncio.Event()
    refreshed: list[str] = []

    async def refresh(address):
        refreshed.append(address)
        called.set()
        return True

    async def run():
        websocket_handler.ws_receive_queue.put_nowait(
            {"multi-address-transactions": {"address": {}}}
        )
        task = asyncio.create_task(tasks.wait_for_onchain())
        try:
            await asyncio.wait_for(called.wait(), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    monkeypatch.setattr(settings, "lnbits_running", True)
    monkeypatch.setattr(tasks, "_refresh_onchain_charge", refresh)
    try:
        asyncio.run(run())
    finally:
        drain_queues()

    assert refreshed == ["address"]


def test_ws_message_stops_tracking_paid_charge(monkeypatch):
    called = asyncio.Event()
    stop = Mock()
    stop.side_effect = lambda address: called.set()

    async def refresh(address):
        return False

    async def run():
        websocket_handler.ws_receive_queue.put_nowait(
            {"multi-address-transactions": {"address": {}}}
        )
        task = asyncio.create_task(tasks.wait_for_onchain())
        try:
            await asyncio.wait_for(called.wait(), 1)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    monkeypatch.setattr(settings, "lnbits_running", True)
    monkeypatch.setattr(tasks, "_refresh_onchain_charge", refresh)
    monkeypatch.setattr(tasks, "stop_onchain_listener", stop)
    try:
        asyncio.run(run())
    finally:
        drain_queues()

    stop.assert_called_once_with("address")


def test_open_charge_gets_its_own_poll_task(monkeypatch):
    async def run():
        websocket_handler.tracked_addresses.clear()
        tasks.poll_tasks.clear()
        drain_queues()

        tasks.start_onchain_listener("address")
        poll_task = tasks.poll_tasks["address"]
        assert not poll_task.done()

        tasks.stop_onchain_listener("address")
        assert "address" not in tasks.poll_tasks
        await asyncio.gather(poll_task, return_exceptions=True)
        assert poll_task.cancelled()

    monkeypatch.setattr(settings, "lnbits_running", True)
    try:
        asyncio.run(run())
    finally:
        websocket_handler.tracked_addresses.clear()
        tasks.poll_tasks.clear()
        drain_queues()


def test_poll_stops_when_refresh_returns_false(monkeypatch):
    refresh = AsyncMock(return_value=False)
    stop = Mock()

    monkeypatch.setattr(settings, "lnbits_running", True)
    monkeypatch.setattr(tasks, "ONCHAIN_POLL_INTERVAL", 0)
    monkeypatch.setattr(tasks, "_refresh_onchain_charge", refresh)
    monkeypatch.setattr(tasks, "stop_onchain_listener", stop)

    asyncio.run(tasks._poll_charge("address"))

    refresh.assert_awaited_once_with("address")
    stop.assert_called_once_with("address")


def test_poll_continues_until_charge_closes(monkeypatch):
    refresh = AsyncMock(side_effect=[True, False])
    stop = Mock()

    monkeypatch.setattr(settings, "lnbits_running", True)
    monkeypatch.setattr(tasks, "ONCHAIN_POLL_INTERVAL", 0)
    monkeypatch.setattr(tasks, "_refresh_onchain_charge", refresh)
    monkeypatch.setattr(tasks, "stop_onchain_listener", stop)

    asyncio.run(tasks._poll_charge("address"))

    assert refresh.await_count == 2
    stop.assert_called_once_with("address")


def test_tracking_messages_snapshot_addresses(monkeypatch):
    async def run():
        websocket_handler.tracked_addresses.clear()
        tasks.poll_tasks.clear()
        drain_queues()

        tasks.start_onchain_listener("address-a")
        tasks.start_onchain_listener("address-b")
        poll_a = tasks.poll_tasks["address-a"]
        poll_b = tasks.poll_tasks["address-b"]

        first = websocket_handler.ws_send_queue.get_nowait()
        second = websocket_handler.ws_send_queue.get_nowait()

        assert first == {"track-addresses": ["address-a"]}
        assert second == {"track-addresses": ["address-a", "address-b"]}

        tasks.stop_onchain_listener("address-a")
        tasks.stop_onchain_listener("address-b")
        await asyncio.gather(poll_a, poll_b, return_exceptions=True)

    monkeypatch.setattr(settings, "lnbits_running", True)
    try:
        asyncio.run(run())
    finally:
        websocket_handler.tracked_addresses.clear()
        tasks.poll_tasks.clear()
        drain_queues()


@pytest.mark.asyncio(loop_scope="module")
async def test_websocket_waits_for_poll_payment_notification(monkeypatch, charge_db):
    charge = make_charge()
    await charge_db.insert("satspay.charges", charge)
    webhook_started = asyncio.Event()
    release_webhook = asyncio.Event()
    refresh_requested = asyncio.Event()
    refresh_finished = asyncio.Event()
    consumer = None
    original_refresh = tasks._refresh_onchain_charge
    read_charge = AsyncMock(wraps=crud.get_charge_by_onchain_address)

    async def refresh(address):
        if asyncio.current_task() is consumer:
            refresh_requested.set()
        result = await original_refresh(address)
        if asyncio.current_task() is consumer:
            refresh_finished.set()
        return result

    async def webhook(charge):
        webhook_started.set()
        await release_webhook.wait()
        return {"webhook_success": True}

    monkeypatch.setattr(settings, "lnbits_running", True)
    monkeypatch.setattr(tasks, "ONCHAIN_POLL_INTERVAL", 0)
    monkeypatch.setattr(tasks, "ws_receive_queue", asyncio.Queue())
    monkeypatch.setattr(tasks, "_refresh_onchain_charge", refresh)
    monkeypatch.setattr(tasks, "get_charge_by_onchain_address", read_charge)
    monkeypatch.setattr(tasks, "send_success_websocket", AsyncMock())
    webhook_mock = AsyncMock(side_effect=webhook)
    monkeypatch.setattr(tasks, "call_webhook", webhook_mock)
    monkeypatch.setattr(
        helpers,
        "fetch_onchain_balance",
        AsyncMock(
            return_value=OnchainBalance(
                confirmed=charge.amount, unconfirmed=0, txids=["paid"]
            )
        ),
    )
    tasks.start_onchain_listener("address")
    poll = tasks.poll_tasks["address"]
    try:
        await asyncio.wait_for(webhook_started.wait(), 1)
        stored = await crud.get_charge(charge.id)
        assert stored and stored.paid
        consumer = asyncio.create_task(tasks.wait_for_onchain())
        tasks.ws_receive_queue.put_nowait(
            {"multi-address-transactions": {"address": {}}}
        )
        await asyncio.wait_for(refresh_requested.wait(), 1)
        # A second refresh must not act on the intermediate paid state.
        assert read_charge.await_count == 1
        release_webhook.set()
        await asyncio.wait_for(asyncio.shield(poll), 1)
        await asyncio.wait_for(refresh_finished.wait(), 1)
        assert not poll.cancelled()
        webhook_mock.assert_awaited_once()
        stored = await crud.get_charge(charge.id)
        assert stored and '"webhook_success": true' in (stored.extra or "")
        assert "address" not in tasks.poll_tasks
    finally:
        release_webhook.set()
        tasks.stop_onchain_polling()
        if consumer:
            consumer.cancel()
        await asyncio.gather(
            *([poll, consumer] if consumer else [poll]), return_exceptions=True
        )
        drain_queues()
        await crud.delete_charge(charge.id)


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("source", ["onchain", "manual"])
@pytest.mark.parametrize("paid", [False, True])
async def test_slow_webhook_preserves_newer_payment_state(
    monkeypatch, charge_db, source, paid
):
    charge = make_charge(balance=5000, extra='{"txids": ["first"]}')
    await charge_db.insert("satspay.charges", charge)
    webhook_started = asyncio.Event()
    release_webhook = asyncio.Event()

    async def webhook(charge):
        webhook_started.set()
        await release_webhook.wait()
        return {"webhook_success": False}

    monkeypatch.setattr(tasks, "send_success_websocket", AsyncMock())
    monkeypatch.setattr(tasks, "call_webhook", webhook)
    monkeypatch.setattr(views_api, "call_webhook", webhook)
    notification = asyncio.create_task(
        tasks._notify_onchain_charge(charge)
        if source == "onchain"
        else views_api.api_charge_webhook(
            charge.id, SimpleNamespace(wallet=SimpleNamespace(user=charge.user))
        )
    )
    try:
        await asyncio.wait_for(webhook_started.wait(), 1)
        newer = make_charge(
            balance=20000 if paid else 10000,
            paid=paid,
            extra='{"txids": ["first", "second"], "webhook_success": true}',
        )
        assert await crud.update_pending_charge(newer)
        release_webhook.set()
        await asyncio.wait_for(notification, 1)
        stored = await crud.get_charge(charge.id)
        assert stored
        assert stored.balance == newer.balance
        assert stored.paid == newer.paid
        assert stored.extra == newer.extra
    finally:
        release_webhook.set()
        await asyncio.gather(notification, return_exceptions=True)
        await crud.delete_charge(charge.id)


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize("fasttrack", [False, True])
async def test_payment_seen_before_expiry_can_confirm(
    monkeypatch, charge_db, fasttrack
):
    charge = make_charge(
        timestamp=datetime.now() - timedelta(hours=2),
        zeroconf=False,
        fasttrack=fasttrack,
        pending=20000,
        extra='{"txids": ["paid-before-expiry"]}',
    )
    await charge_db.insert("satspay.charges", charge)
    webhook = AsyncMock(return_value={"webhook_success": True})
    monkeypatch.setattr(tasks, "send_success_websocket", AsyncMock())
    monkeypatch.setattr(tasks, "call_webhook", webhook)
    monkeypatch.setattr(
        helpers,
        "fetch_onchain_balance",
        AsyncMock(
            return_value=OnchainBalance(
                confirmed=20000, unconfirmed=0, txids=["paid-before-expiry"]
            )
        ),
    )
    try:
        assert await tasks._refresh_onchain_charge("address") is False
        stored = await crud.get_charge(charge.id)
        assert stored and stored.paid
        assert stored.balance == 20000
        assert stored.pending == 0
        webhook.assert_awaited_once()
        assert '"webhook_success": true' in (stored.extra or "")
    finally:
        await crud.delete_charge(charge.id)


@pytest.mark.parametrize("pending", [0, 20000])
def test_restart_tracks_expired_charges_only_with_pending_funds(monkeypatch, pending):
    charge = make_charge(timestamp=datetime.now() - timedelta(hours=2), pending=pending)
    start = Mock()
    refresh = AsyncMock(return_value=True)
    monkeypatch.setattr(tasks, "get_pending_charges", AsyncMock(return_value=[charge]))
    monkeypatch.setattr(tasks, "start_onchain_listener", start)
    monkeypatch.setattr(tasks, "_refresh_onchain_charge", refresh)

    asyncio.run(tasks.restart_address_tracking())

    if pending:
        start.assert_called_once_with("address")
        refresh.assert_awaited_once_with("address")
    else:
        start.assert_not_called()
        refresh.assert_not_awaited()


def test_expired_pending_charge_stops_tracking_if_payment_disappears(refresh_mocks):
    timestamp = datetime.now() - timedelta(hours=2)
    refresh_mocks.charge = make_charge(timestamp=timestamp, pending=20000)
    refresh_mocks.checked = make_charge(timestamp=timestamp)

    assert asyncio.run(tasks._refresh_onchain_charge("address")) is False
    assert refresh_mocks.updated == [refresh_mocks.checked]
