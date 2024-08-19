import httpx
import json
from lnbits.core.crud import get_standalone_payment
from lnbits.settings import settings
from loguru import logger

from .models import Charge, OnchainBalance, WalletAccountConfig


async def call_webhook(charge: Charge):
    async with httpx.AsyncClient() as client:
        try:
            assert charge.webhook
            r = await client.post(
                charge.webhook,
                json=charge.public,
                timeout=40,
            )
            return {
                "webhook_success": r.is_success,
                "webhook_message": r.reason_phrase,
                "webhook_response": r.text,
            }
        except Exception as e:
            logger.warning(f"Failed to call webhook for charge {charge.id}")
            logger.warning(e)
            return {"webhook_success": False, "webhook_message": str(e)}


def get_endpoint(charge: Charge) -> str:
    assert charge.config.mempool_endpoint, "No mempool endpoint configured"
    return (
        f"{charge.config.mempool_endpoint}/testnet"
        if charge.config.network == "Testnet"
        else charge.config.mempool_endpoint or ""
    )


async def fetch_onchain_balance(
    onchain_address: str, mempool_endpoint: str
) -> OnchainBalance:
    async with httpx.AsyncClient() as client:
        res = await client.get(f"{mempool_endpoint}/api/address/{onchain_address}")
        res.raise_for_status()
        data = res.json()
        confirmed = data["chain_stats"]["funded_txo_sum"]
        unconfirmed = data["mempool_stats"]["funded_txo_sum"]
        return OnchainBalance(confirmed=confirmed, unconfirmed=unconfirmed)


async def fetch_onchain_config(
    wallet_id: str, api_key: str
) -> tuple[WalletAccountConfig, str]:
    async with httpx.AsyncClient() as client:
        headers = {"X-API-KEY": api_key}
        r = await client.get(
            url=f"http://{settings.host}:{settings.port}/watchonly/api/v1/config",
            headers=headers,
        )
        r.raise_for_status()
        config = r.json()

        r = await client.get(
            url=f"http://{settings.host}:{settings.port}/watchonly/api/v1/address/{wallet_id}",
            headers=headers,
        )
        r.raise_for_status()
        address_data = r.json()

        if not address_data:
            raise ValueError("Cannot fetch new address!")

        return WalletAccountConfig.parse_obj(config), address_data["address"]


async def check_charge_balance(charge: Charge) -> Charge:
    if charge.paid:
        return charge

    if charge.lnbitswallet and charge.payment_hash:
        payment = await get_standalone_payment(charge.payment_hash)
        assert payment, "Payment not found."
        status = await payment.check_status()
        if status.success:
            charge.balance = charge.amount

    if charge.onchainaddress:
        try:
            balance = await fetch_onchain_balance(
                charge.onchainaddress, charge.config.mempool_endpoint
            )
            if (
                balance.confirmed != charge.balance
                or balance.unconfirmed != charge.pending
            ):
                charge.balance = (
                    balance.confirmed + balance.unconfirmed
                    if charge.zeroconf
                    else balance.confirmed
                )
                charge.pending = balance.unconfirmed
        except Exception as exc:
            logger.warning(f"Charge check onchain address failed with: {exc!s}")

    if charge.paid and charge.webhook:
        resp = await call_webhook(charge)
        charge.extra = json.dumps({**charge.config.dict(), **resp})

    return charge
