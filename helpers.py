import json
import traceback

import httpx
from lnbits.core.crud import get_standalone_payment
from lnbits.core.models import CreateInvoice
from lnbits.core.services import create_payment_request
from lnbits.settings import settings
from loguru import logger

from .crud import get_or_create_satspay_settings
from .models import Charge, CreateCharge, OnchainBalance


def _satspay_internal_host() -> str:
    return "127.0.0.1" if settings.host in ("0.0.0.0", "::") else settings.host


def _charge_json(charge: Charge) -> tuple[str, dict]:
    if hasattr(charge, "model_dump_json"):
        s = charge.model_dump_json()
    else:
        s = charge.json()
    return s, json.loads(s)


async def call_webhook(charge: Charge):
    try:
        assert charge.webhook, "charge has no webhook"
        charge_str, charge_data = _charge_json(charge)
        settings = await get_or_create_satspay_settings()
        async with httpx.AsyncClient() as client:
            # wordpress expects a GET request with json-encoded binary content
            if settings.webhook_method == "GET":
                r = await client.request(
                    method="GET",
                    url=charge.webhook,
                    content=charge_str,
                    timeout=10,
                )
            else:
                r = await client.post(
                    url=charge.webhook,
                    json=charge_data,
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
            url=f"http://{_satspay_internal_host()}:{settings.port}/watchonly/api/v1/config",
            headers={"X-API-KEY": api_key},
        )
        r.raise_for_status()
        config = r.json()
        return config["network"]


async def fetch_onchain_address(wallet_id: str, api_key: str) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            url=f"http://{_satspay_internal_host()}:{settings.port}/watchonly/api/v1/address/{wallet_id}",
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
                charge.settlement_method = "lightning"
                charge.settlement_proof = status.preimage
                charge.add_extra({"payment_method": "lightning"})
                charge.balance = charge.amount

    if charge.fiat_provider and charge.fiat_payment_requests:
        try:
            fiat_reqs = json.loads(charge.fiat_payment_requests)
            fiat_payment_hash = fiat_reqs.get(charge.fiat_provider, {}).get(
                "payment_hash"
            )
            if fiat_payment_hash:
                payment = await get_standalone_payment(fiat_payment_hash)
                if payment:
                    status = await payment.check_status()
                    if status.success:
                        charge.settlement_method = charge.fiat_provider
                        charge.settlement_proof = payment.extra.get("fiat_checking_id")
                        charge.add_extra({"payment_method": charge.fiat_provider})
                        charge.balance = charge.amount
        except Exception as exc:
            logger.warning(f"Charge check fiat payment failed with: {exc!s}")

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
                if charge.balance >= charge.amount:
                    charge.settlement_method = "onchain"
                    charge.settlement_proof = json.dumps(balance.txids)
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


async def create_fiat_invoice_for_charge(
    charge: Charge, data: CreateCharge, provider: str, wallet_id: str
) -> dict | None:
    """
    Create a fiat invoice via the core fiat provider integration.

    Core creates an internal payment tagged with the charge id, creates the
    checkout session with the provider and notifies invoice listeners (incl.
    this extension) once the provider confirms the payment via core's own
    webhook handlers.
    """
    fiat_currency = (data.fiat_currency or data.currency or "usd").upper()
    fiat_amount = data.currency_amount or 0.0
    if fiat_amount <= 0:
        logger.warning(f"Charge {charge.id}: fiat amount missing, cannot invoice.")
        return None

    try:
        payment = await create_payment_request(
            wallet_id,
            CreateInvoice(
                unit=fiat_currency,
                amount=fiat_amount,
                memo=data.description or f"SatsPay charge {charge.id}",
                fiat_provider=provider,
                extra={"tag": "charge", "charge": charge.id},
            ),
        )
        return {
            "payment_request": payment.extra.get("fiat_payment_request"),
            "checking_id": payment.extra.get("fiat_checking_id")
            or payment.checking_id,
            "payment_hash": payment.payment_hash,
        }
    except Exception as exc:
        logger.warning(f"Error creating fiat invoice for {provider}: {exc}")
        return None
