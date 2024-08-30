import httpx
from lnbits.core.crud import get_standalone_payment
from lnbits.settings import settings
from loguru import logger

from .crud import get_or_create_satspay_settings
from .models import Charge, OnchainBalance


async def call_webhook(charge: Charge):
    try:
        assert charge.webhook
        settings = await get_or_create_satspay_settings()
        async with httpx.AsyncClient() as client:
            # wordpress expect a GET request with json_encoded binary content
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
            if r.is_success:
                logger.success(f"Webhook sent for charge {charge.id}")
            else:
                logger.warning(f"Failed to call webhook for charge {charge.id}")
                logger.warning(charge.webhook)
                logger.warning(r.text)
            return {
                "webhook_success": r.is_success,
                "webhook_message": r.reason_phrase,
                "webhook_response": r.text,
            }
    except Exception as e:
        logger.warning(f"Failed to call webhook for charge {charge.id}")
        logger.warning(e)
        return {"webhook_success": False, "webhook_message": str(e)}


async def fetch_onchain_balance(onchain_address: str) -> OnchainBalance:
    settings = await get_or_create_satspay_settings()
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{settings.mempool_url}/api/address/{onchain_address}/txs"
        )
        res.raise_for_status()
        data = res.json()
        confirmed_txs = [tx for tx in data if tx["status"]["confirmed"]]
        unconfirmed_txs = [tx for tx in data if not tx["status"]["confirmed"]]
        txids = [tx["txid"] for tx in data]
        confirmed = sum_transactions(onchain_address, confirmed_txs)
        unconfirmed = sum_transactions(onchain_address, unconfirmed_txs)
        return OnchainBalance(confirmed=confirmed, unconfirmed=unconfirmed, txids=txids)


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
        assert payment, "Payment not found."
        status = await payment.check_status()
        if status.success:
            charge.add_extra({"payment_method": "lightning"})
            charge.balance = charge.amount

    if charge.onchainaddress:
        try:
            balance = await fetch_onchain_balance(charge.onchainaddress)
            charge.add_extra({"txids": balance.txids})
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
                charge.add_extra({"payment_method": "onchain"})
        except Exception as exc:
            logger.warning(f"Charge check onchain address failed with: {exc!s}")

    charge.paid = charge.balance >= charge.amount

    if charge.webhook:
        resp = await call_webhook(charge)
        charge.add_extra(resp)

    return charge


def sum_outputs(address: str, vouts) -> int:
    return sum(
        [vout["value"] for vout in vouts if vout.get("scriptpubkey_address") == address]
    )


def sum_transactions(address: str, txs) -> int:
    return sum([sum_outputs(address, tx["vout"]) for tx in txs])


def get_txids(address: str, data) -> list[str]:
    confirmed_txs = data.get("confirmed", [])
    confirmed_txids = [
        vout["txid"]
        for vout in confirmed_txs
        if vout.get("scriptpubkey_address") == address
    ]
    mempool_txs = data.get("mempool", [])
    mempool_txids = [
        vout["txid"]
        for vout in mempool_txs
        if vout.get("scriptpubkey_address") == address
    ]
    return confirmed_txids + mempool_txids
