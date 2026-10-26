import asyncio
import time

from fastapi import WebSocket
from lnbits.core.models import Payment
from lnbits.settings import settings
from lnbits.tasks import register_invoice_listener
from loguru import logger

from .crud import (
    get_charge,
    get_charge_by_onchain_address,
    get_pending_charges,
    update_charge,
)
from .helpers import call_webhook, check_charge_balance
from .models import Charge
from .websocket_handler import tracked_addresses, ws_receive_queue, ws_send_queue

public_ws_listeners: dict[str, list[WebSocket]] = {}
poll_tasks: dict[str, asyncio.Task] = {}

ONCHAIN_POLL_INTERVAL = 30


async def restart_address_tracking():
    for charge in await get_pending_charges():
        if not charge.onchainaddress:
            continue
        if charge.timestamp.timestamp() + charge.time * 60 <= time.time():
            continue
        start_onchain_listener(charge.onchainaddress)
        try:
            if not await _refresh_onchain_charge(charge.onchainaddress):
                stop_onchain_listener(charge.onchainaddress)
        except Exception as exc:
            logger.warning(
                f"Onchain charge refresh failed for {charge.onchainaddress}: {exc!s}"
            )


async def wait_for_paid_invoices():
    invoice_queue = asyncio.Queue()
    register_invoice_listener(invoice_queue, "ext_satspay")

    while settings.lnbits_running:
        payment = await invoice_queue.get()
        await on_invoice_paid(payment)


async def send_success_websocket(charge: Charge):
    for charge_id, listeners in public_ws_listeners.items():
        if charge_id == charge.id:
            for listener in listeners:
                await listener.send_json(
                    {
                        "paid": charge.paid_fasttrack,
                        "balance": charge.balance,
                        "pending": charge.pending,
                        "completelink": (
                            charge.completelink if charge.paid_fasttrack else None
                        ),
                    }
                )


async def on_invoice_paid(payment: Payment) -> None:
    if not payment.extra or payment.extra.get("tag") != "charge":
        return

    charge_id = payment.extra.get("charge")
    if not charge_id:
        return

    charge = await get_charge(charge_id)
    assert charge, f"On invoice paid, charge `{charge_id}` not found."

    if charge.lnbitswallet and charge.payment_hash == payment.payment_hash:
        charge.balance = int(payment.amount / 1000)
        charge.paid = True
        logger.success(f"Charge {charge.id} invoice paid.")
        charge.add_extra({"payment_method": "lightning"})
        charge = await update_charge(charge)
        await send_success_websocket(charge)
        if charge.webhook:
            resp = await call_webhook(charge)
            charge.add_extra(resp)
            await update_charge(charge)


def start_onchain_listener(address: str):
    if address in tracked_addresses:
        return
    tracked_addresses.append(address)
    logger.debug(f"start_onchain_listener ({len(tracked_addresses)}")
    ws_send_queue.put_nowait({"track-addresses": list(tracked_addresses)})
    if address not in poll_tasks:
        poll_tasks[address] = asyncio.create_task(_poll_charge(address))


def stop_onchain_listener(address: str):
    if address in tracked_addresses:
        tracked_addresses.remove(address)
        logger.debug(f"stop_onchain_listener ({len(tracked_addresses)}")
        ws_send_queue.put_nowait({"track-addresses": list(tracked_addresses)})
    task = poll_tasks.pop(address, None)
    if task and task is not asyncio.current_task():
        task.cancel()


def stop_onchain_polling():
    for task in list(poll_tasks.values()):
        task.cancel()
    poll_tasks.clear()
    tracked_addresses.clear()


async def wait_for_onchain():
    while settings.lnbits_running:
        ws_message = await ws_receive_queue.get()
        tracking_error = ws_message.get("track-addresses-error")
        if tracking_error:
            logger.warning(f"Onchain address tracking rejected: {tracking_error}")
        txs = ws_message.get("multi-address-transactions")
        if not txs:
            continue
        for address in txs:
            try:
                if not await _refresh_onchain_charge(address):
                    stop_onchain_listener(address)
            except Exception as exc:
                logger.warning(f"Onchain charge update failed for {address}: {exc!s}")


async def _poll_charge(address: str):
    while settings.lnbits_running:
        await asyncio.sleep(ONCHAIN_POLL_INTERVAL)
        try:
            if not await _refresh_onchain_charge(address):
                stop_onchain_listener(address)
                return
        except Exception as exc:
            logger.warning(f"Onchain charge poll failed for {address}: {exc!s}")


async def _refresh_onchain_charge(address: str) -> bool:
    charge = await get_charge_by_onchain_address(address)
    if not charge or charge.paid:
        return False
    if charge.timestamp.timestamp() + charge.time * 60 <= time.time():
        return False
    balance_before = charge.balance
    pending_before = charge.pending
    charge = await check_charge_balance(charge, notify_webhook=False)
    if (
        charge.balance == balance_before
        and charge.pending == pending_before
        and not charge.paid
    ):
        return True
    await _notify_onchain_charge(charge)
    return not charge.paid


async def _notify_onchain_charge(charge: Charge):
    charge = await update_charge(charge)
    await send_success_websocket(charge)
    if charge.webhook:
        resp = await call_webhook(charge)
        charge.add_extra(resp)
        await update_charge(charge)
    if charge.paid:
        logger.success(f"Charge {charge.id} paid.")
