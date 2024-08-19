import asyncio
import json

from fastapi import WebSocket
from lnbits.core.models import Payment
from lnbits.settings import settings
from lnbits.tasks import register_invoice_listener
from loguru import logger

from .crud import get_charge, get_charge_by_onchain_address, update_charge
from .helpers import call_webhook
from .models import Charge
from .websocket_handler import ws_receive_queue, ws_send_queue

tracked_addresses: list[str] = []
public_ws_listeners: dict[str, WebSocket] = {}


async def wait_for_paid_invoices():
    invoice_queue = asyncio.Queue()
    register_invoice_listener(invoice_queue, "ext_satspay")

    while settings.lnbits_running:
        payment = await invoice_queue.get()
        await on_invoice_paid(payment)


async def send_success_websocket(charge: Charge):
    for charge_id, listener in public_ws_listeners.items():
        if charge_id == charge.id:
            await listener.send_json(
                {
                    "paid": charge.paid,
                    "balance": charge.balance,
                    "pending": charge.pending,
                    "completelink": charge.completelink if charge.paid else None,
                }
            )


async def on_invoice_paid(payment: Payment) -> None:
    if payment.extra.get("tag") != "charge":
        return

    charge_id = payment.extra.get("charge")
    if not charge_id:
        return

    charge = await get_charge(charge_id)
    assert charge, f"On invoice paid, charge `{charge_id}` not found."

    if charge.lnbitswallet and charge.payment_hash == payment.payment_hash:
        charge.balance = int(payment.amount / 1000)
        charge.paid = True
        await send_success_websocket(charge)
        if charge.webhook:
            resp = await call_webhook(charge)
            charge.extra = json.dumps({**charge.config.dict(), **resp})
        await update_charge(charge)


def start_onchain_listener(address: str):
    if address in tracked_addresses:
        return
    tracked_addresses.append(address)
    logger.debug(f"start_onchain_listener ({len(tracked_addresses)}")
    ws_send_queue.put_nowait({"track-addresses": tracked_addresses})


def stop_onchain_listener(address: str):
    if address in tracked_addresses:
        tracked_addresses.remove(address)
        logger.debug(f"stop_onchain_listener ({len(tracked_addresses)}")
        ws_send_queue.put_nowait({"track-addresses": tracked_addresses})


async def wait_for_onchain():
    while settings.lnbits_running:
        ws_message = await ws_receive_queue.get()
        txs = ws_message.get("multi-address-transactions")
        if not txs:
            continue
        for address, data in txs.items():
            await _handle_ws_message(address, data)


def sum_outputs(address: str, vouts):
    return sum(
        [vout["value"] for vout in vouts if vout.get("scriptpubkey_address") == address]
    )


def sum_transactions(address: str, txs):
    return sum([sum_outputs(address, tx["vout"]) for tx in txs])


async def _handle_ws_message(address: str, data: dict):
    charge = await get_charge_by_onchain_address(address)
    assert charge, f"Charge with address `{address}` does not exist."
    unconfirmed_balance = sum_transactions(address, data.get("mempool", []))
    confirmed_balance = sum_transactions(address, data.get("confirmed", []))
    if charge.zeroconf:
        confirmed_balance += unconfirmed_balance
    charge.balance = confirmed_balance
    charge.pending = unconfirmed_balance
    charge.paid = charge.balance >= charge.amount
    await send_success_websocket(charge)
    if charge.paid:
        stop_onchain_listener(address)
        if charge.webhook:
            resp = await call_webhook(charge)
            charge.extra = json.dumps({**charge.config.dict(), **resp})
    await update_charge(charge)
