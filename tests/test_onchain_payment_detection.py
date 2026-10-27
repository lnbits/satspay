import asyncio
import sqlite3
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from lnbits.db import insert_query, model_to_dict, update_query
from lnbits.settings import settings

from .. import crud, helpers, migrations, tasks, websocket_handler
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


@pytest.mark.parametrize("payment_during", ["balance_fetch", "webhook"])
def test_refresh_preserves_concurrent_lightning_payment(monkeypatch, payment_during):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("ATTACH ':memory:' AS satspay")

    async def execute(query, values=None):
        return connection.execute(query, values or {})

    async def fetchone(query, values, model):
        row = connection.execute(query, values).fetchone()
        return model(**dict(row)) if row else None

    async def update(table, charge):
        await execute(update_query(table, charge), model_to_dict(charge))

    db = SimpleNamespace(
        execute=execute,
        fetchone=fetchone,
        update=update,
        big_int="INTEGER",
        timestamp_now="(strftime('%s', 'now'))",
    )
    monkeypatch.setattr(crud, "db", db)
    websocket = AsyncMock()
    webhook = AsyncMock()
    monkeypatch.setattr(tasks, "send_success_websocket", websocket)
    monkeypatch.setattr(tasks, "call_webhook", webhook)
    monkeypatch.setattr(helpers, "get_standalone_payment", AsyncMock(return_value=None))
    payment = SimpleNamespace(
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

    async def run():
        try:
            for name in sorted(vars(migrations)):
                if name.startswith("m0"):
                    await getattr(migrations, name)(db)
            charge = make_charge(lnbitswallet="lightning", payment_hash="hash")
            await execute(
                insert_query("satspay.charges", charge), model_to_dict(charge)
            )

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
            connection.close()

    asyncio.run(run())


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
