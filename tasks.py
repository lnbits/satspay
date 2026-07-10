import time

from fastapi import WebSocket
from lnbits.core.models import Payment
from lnbits.task_manager import task_manager  # pyright: ignore[reportMissingImports]
from lnbits.utils.electrum import (  # pyright: ignore[reportMissingImports]
    OnchainAddressEvent,
)
from loguru import logger

from .crud import (
    get_charge,
    get_charge_by_onchain_address,
    get_pending_charges,
    update_charge,
)
from .helpers import call_webhook
from .models import Charge

TASK_NAME = "ext_satspay"

public_ws_listeners: dict[str, list[WebSocket]] = {}
_satspay_tracked_addresses: set[str] = set()


async def restart_address_tracking():
    charges = await get_pending_charges()
    for charge in charges:
        if (
            charge.onchainaddress
            and charge.timestamp.timestamp() + charge.time * 60 > time.time()
        ):
            satspay_track_address(charge.onchainaddress)


def satspay_track_address(address: str) -> None:
    _satspay_tracked_addresses.add(address)
    task_manager.track_address(address, TASK_NAME)


def satspay_untrack_address(address: str) -> None:
    _satspay_tracked_addresses.discard(address)
    task_manager.untrack_address(address, TASK_NAME)


def satspay_untrack_all_addresses() -> None:
    for address in list(_satspay_tracked_addresses):
        task_manager.untrack_address(address, TASK_NAME)
    _satspay_tracked_addresses.clear()


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


async def on_address_event(event: OnchainAddressEvent) -> None:
    charge = await get_charge_by_onchain_address(event.address)
    if not charge:
        logger.warning(f"No charge found for address {event.address}")
        return

    charge.add_extra({"txids": event.txids})
    charge.balance = (
        event.confirmed + event.unconfirmed if charge.zeroconf else event.confirmed
    )
    charge.pending = event.unconfirmed
    charge.paid = charge.balance >= charge.amount

    if charge.paid:
        charge.add_extra({"payment_method": "onchain"})
        logger.success(f"Charge {charge.id} onchain paid.")
        satspay_untrack_address(event.address)

    charge = await update_charge(charge)
    await send_success_websocket(charge)
    if charge.webhook:
        resp = await call_webhook(charge)
        charge.add_extra(resp)
        await update_charge(charge)
