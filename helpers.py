import traceback

import httpx
from lnbits.core.crud import get_standalone_payment
from lnbits.core.services import (  # type: ignore[attr-defined]
    fetch_onchain_balance,  # pyright: ignore[reportAttributeAccessIssue]
)
from lnbits.settings import settings
from loguru import logger

from .crud import get_or_create_satspay_settings
from .models import Charge


async def call_webhook(charge: Charge):
    try:
        assert charge.webhook, "charge has no webhook"
        settings = await get_or_create_satspay_settings()
        async with httpx.AsyncClient() as client:
            # wordpress expects a GET request with json-encoded binary content
            if settings.webhook_method == "GET":
                r = await client.request(
                    method="GET",
                    url=charge.webhook,
                    content=charge.json(),
                    timeout=10,
                )
            else:
                r = await client.post(
                    url=charge.webhook,
                    json=charge.json(),
                    timeout=10,
                )
            r.raise_for_status()
            logger.success(f"Webhook sent for charge {charge.id}")
            return {
                "webhook_success": True,
                "webhook_message": r.reason_phrase,
                "webhook_response": r.text,
            }
    except Exception as e:
        logger.warning(f"Failed to call webhook for charge {charge.id}")
        logger.warning(charge.webhook)
        logger.warning(traceback.format_exc())
        return {"webhook_success": False, "webhook_message": str(e)}


async def fetch_onchain_config_network(api_key: str) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            url=f"http://{settings.host}:{settings.port}/watchonly/api/v1/config",
            headers={"X-API-KEY": api_key},
        )
        r.raise_for_status()
        config = r.json()
        return config["network"]


async def fetch_onchain_address(wallet_id: str, api_key: str) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            url=f"http://{settings.host}:{settings.port}/watchonly/api/v1/address/{wallet_id}",
            headers={"X-API-KEY": api_key},
        )
        r.raise_for_status()
        address_data = r.json()
        if not address_data and "address" not in address_data:
            raise ValueError("Cannot fetch new address!")
        return address_data["address"]


async def check_charge_balance(charge: Charge) -> Charge:
    if charge.paid:
        return charge

    if charge.lnbitswallet and charge.payment_hash:
        payment = await get_standalone_payment(charge.payment_hash)
        if payment:
            status = await payment.check_status()
            if status.success:
                charge.add_extra({"payment_method": "lightning"})
                charge.balance = charge.amount

    if charge.onchainaddress:
        try:
            data = await fetch_onchain_balance(charge.onchainaddress)
            charge.add_extra({"txids": [entry.tx_hash for entry in data.history]})
            if (
                data.balance.confirmed != charge.balance
                or data.balance.unconfirmed != charge.pending
            ):
                charge.balance = (
                    data.balance.confirmed + data.balance.unconfirmed
                    if charge.zeroconf
                    else data.balance.confirmed
                )
                charge.pending = data.balance.unconfirmed
                charge.add_extra({"payment_method": "onchain"})
        except Exception as exc:
            logger.warning(f"Charge check onchain address failed with: {exc!s}")

    charge.paid = charge.balance >= charge.amount

    if charge.webhook:
        resp = await call_webhook(charge)
        charge.add_extra(resp)

    return charge
