import asyncio
import time

from fastapi import WebSocket, WebSocketDisconnect
from lnbits.core.models import Payment
from lnbits.settings import settings
from lnbits.tasks import register_invoice_listener
from loguru import logger

from .crud import get_charge, get_pending_charges, update_charge
from .helpers import call_webhook, check_charge_balance, sum_transactions
from .models import Charge
from .websocket_handler import ws_receive_queue, ws_send_queue

MAX_TRACKED_ADDRESSES = 1000
tracked_addresses: dict[str, Charge] = {}
public_ws_listeners: dict[str, list[WebSocket]] = {}


async def restart_address_tracking():
    charges = await get_pending_charges()
    for charge in charges:
        if charge.onchainaddress and (
            charge.pending > 0
            or charge.balance > 0
            or charge.timestamp.timestamp() + charge.time * 60 > time.time()
        ):
            charge = await check_charge_balance(charge)
            notify_paid = charge.paid
            charge = await update_charge(charge)
            if charge.paid:
                logger.success(f"Charge {charge.id} marked as paid.")
                if notify_paid and charge.webhook:
                    charge.add_extra(await call_webhook(charge))
                    await update_charge(charge)
                continue
            try:
                start_onchain_listener(charge)
            except ValueError:
                logger.warning(f"Cannot track onchain charge {charge.id}")


async def expire_address_tracking():
    while settings.lnbits_running:
        prune_address_tracking()
        await asyncio.sleep(60)


async def wait_for_paid_invoices():
    invoice_queue = asyncio.Queue()
    register_invoice_listener(invoice_queue, "ext_satspay")

    while settings.lnbits_running:
        payment = await invoice_queue.get()
        await on_invoice_paid(payment)


async def send_success_websocket(charge: Charge):
    for listener in public_ws_listeners.get(charge.id, [])[:]:
        try:
            await listener.send_json(
                {
                    "paid": charge.paid_fasttrack,
                    "balance": charge.balance,
                    "pending": charge.pending,
                    "completelink": (
                        charge.safe_completelink if charge.paid_fasttrack else None
                    ),
                }
            )
        except (WebSocketDisconnect, RuntimeError, OSError):
            listeners = public_ws_listeners.get(charge.id, [])
            if listener in listeners:
                listeners.remove(listener)
            if not listeners:
                public_ws_listeners.pop(charge.id, None)


async def on_invoice_paid(payment: Payment) -> None:
    if not payment.extra or payment.extra.get("tag") != "charge":
        return

    charge_id = payment.extra.get("charge")
    if not charge_id:
        return

    charge = await get_charge(charge_id)
    if not charge or charge.paid:
        return

    if charge.lnbitswallet and charge.payment_hash == payment.payment_hash:
        charge.balance = int(payment.amount / 1000)
        charge.paid = charge.balance >= charge.amount
        logger.success(f"Charge {charge.id} invoice paid.")
        charge.add_extra({"payment_method": "lightning"})
        charge = await update_charge(charge)
        if charge.paid and charge.onchainaddress:
            stop_onchain_listener(charge.onchainaddress)
        await send_success_websocket(charge)
        if charge.paid and charge.webhook:
            charge.add_extra(await call_webhook(charge))
            await update_charge(charge)


def start_onchain_listener(charge: Charge):
    assert charge.onchainaddress
    prune_address_tracking()
    tracked = tracked_addresses.get(charge.onchainaddress)
    if tracked:
        if tracked.id != charge.id:
            raise ValueError("Onchain address is already tracked.")
        return
    if len(tracked_addresses) >= MAX_TRACKED_ADDRESSES:
        raise ValueError("Onchain tracking capacity reached.")
    tracked_addresses[charge.onchainaddress] = charge
    _send_tracking_update()


def stop_onchain_listener(address: str):
    if tracked_addresses.pop(address, None):
        _send_tracking_update()


def prune_address_tracking():
    expired = [
        address
        for address, charge in tracked_addresses.items()
        if charge.timestamp.timestamp() + charge.time * 60 <= time.time()
        and not charge.pending
        and not charge.balance
    ]
    for address in expired:
        tracked_addresses.pop(address)
    if expired:
        _send_tracking_update()


async def wait_for_onchain():
    while settings.lnbits_running:
        ws_message = await ws_receive_queue.get()
        txs = ws_message.get("multi-address-transactions")
        if not txs:
            continue
        prune_address_tracking()
        for address, data in txs.items():
            await _handle_ws_message(address, data)


def _send_tracking_update():
    if not ws_send_queue.empty():
        ws_send_queue.get_nowait()
    ws_send_queue.put_nowait({"track-addresses": list(tracked_addresses)})


async def _handle_ws_message(address: str, data: dict):
    tracked = tracked_addresses.get(address)
    if not tracked:
        return
    unconfirmed_balance = sum_transactions(address, data.get("mempool", []))
    confirmed_balance = sum_transactions(address, data.get("confirmed", []))
    tracked.pending = unconfirmed_balance
    tracked.balance = confirmed_balance
    charge = await get_charge(tracked.id)
    if not charge or charge.paid:
        stop_onchain_listener(address)
        return
    unconfirmed_txids = [tx["txid"] for tx in data.get("mempool", [])]
    confirmed_txids = [tx["txid"] for tx in data.get("confirmed", [])]
    charge.add_extra({"txids": confirmed_txids + unconfirmed_txids})
    if charge.zeroconf:
        confirmed_balance += unconfirmed_balance
    charge.balance = confirmed_balance
    charge.pending = unconfirmed_balance
    charge.paid = charge.balance >= charge.amount
    notify_paid = charge.paid
    if charge.paid:
        charge.add_extra({"payment_method": "onchain"})
        logger.success(f"Charge {charge.id} onchain paid.")
    charge = await update_charge(charge)
    if charge.paid:
        stop_onchain_listener(address)
    elif address in tracked_addresses:
        tracked_addresses[address] = charge
    await send_success_websocket(charge)
    if notify_paid and charge.webhook:
        charge.add_extra(await call_webhook(charge))
        await update_charge(charge)
