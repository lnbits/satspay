import hashlib
import hmac
import json
import traceback
import uuid

import httpx
from lnbits.core.crud import get_standalone_payment
from lnbits.helpers import normalize_endpoint
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
    charge: Charge, data: CreateCharge, provider: str
) -> dict | None:
    payment_hash = uuid.uuid4().hex
    fiat_currency = data.fiat_currency or data.currency or "usd"
    fiat_amount = data.currency_amount or 0.0

    try:
        if provider == "stripe":
            result = await _create_stripe_checkout(
                fiat_amount, fiat_currency, payment_hash,
                charge_id=charge.id,
                success_url=charge.completelink
            )
        elif provider == "paypal":
            result = await _create_paypal_checkout(fiat_amount, fiat_currency, payment_hash)
        elif provider == "revolut":
            result = await _create_revolut_checkout(fiat_amount, fiat_currency, payment_hash)
        elif provider == "square":
            result = await _create_square_checkout(fiat_amount, fiat_currency, payment_hash)
        else:
            return None
        return result
    except Exception as exc:
        logger.warning(f"Error creating fiat invoice for {provider}: {exc}")
        return None


async def verify_fiat_webhook(
    provider: str, payload: bytes, signature: str | None
) -> str | None:
    if not signature:
        raise ValueError(f"Missing webhook signature for {provider}")
    if provider == "stripe":
        secret = settings.stripe_webhook_signing_secret
        if secret:
            return _verify_stripe_webhook(payload, signature, secret)
    if provider == "revolut":
        secret = settings.revolut_webhook_signing_secret
        if secret:
            return _verify_revolut_webhook(payload, signature, secret)
    raise ValueError(f"Webhook verification not supported for {provider}")


def _verify_stripe_webhook(payload: bytes, sig_header: str, secret: str) -> str | None:
    try:
        sig_parts = sig_header.split(",")
        t_val = v1_val = None
        for part in sig_parts:
            if "=" in part:
                key, val = part.split("=", 1)
                if key.strip() == "t": t_val = val.strip()
                elif key.strip() == "v1": v1_val = val.strip()
        if not t_val or not v1_val:
            raise ValueError("Invalid signature format")
        signed_payload = f"{t_val}.{payload.decode()}"
        expected = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, v1_val):
            raise ValueError("Invalid signature")
        return json.loads(payload).get("data", {}).get("object", {}).get("id")
    except Exception as e:
        raise ValueError(f"Stripe webhook verification failed: {e}") from e


def _verify_revolut_webhook(payload: bytes, signature: str, secret: str) -> str | None:
    try:
        computed = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(computed, signature.replace("v1=", "")):
            raise ValueError("Invalid signature")
        return json.loads(payload).get("data", {}).get("object", {}).get("id")
    except Exception as e:
        raise ValueError(f"Revolut webhook verification failed: {e}") from e


async def _create_stripe_checkout(
    amount: float, currency: str, payment_hash: str,
    charge_id: str,
    success_url: str | None = None
) -> dict:
    from urllib.parse import urlencode
    api_key = settings.stripe_api_secret_key
    if not api_key:
        raise ValueError("Stripe API secret key not configured in LNbits core settings")
    endpoint = settings.stripe_api_endpoint or "https://api.stripe.com"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/x-www-form-urlencoded", "User-Agent": settings.user_agent}
    amount_cents = int(amount * 100)
    success_url = success_url or settings.stripe_payment_success_url or "https://lnbits.com"
    form_data = {"mode": "payment", "success_url": success_url, "metadata[payment_hash]": payment_hash, "metadata[source]": "satspay", "metadata[satspay_charge_id]": charge_id, "line_items[0][price_data][currency]": currency.lower(), "line_items[0][price_data][product_data][name]": "SatsPay Payment", "line_items[0][price_data][unit_amount]": str(amount_cents), "line_items[0][quantity]": "1"}
    async with httpx.AsyncClient(base_url=endpoint, headers=headers) as client:
        r = await client.post("/v1/checkout/sessions", content=urlencode(form_data))
        if r.status_code >= 400:
            logger.warning(f"Stripe error {r.status_code}: {r.text}")
        r.raise_for_status()
        data = r.json()
        return {"payment_request": data.get("url"), "checking_id": data.get("id")}


async def _create_paypal_checkout(amount: float, currency: str, payment_hash: str) -> dict:
    client_id = settings.paypal_client_id
    client_secret = settings.paypal_client_secret
    if not client_id or not client_secret:
        raise ValueError("PayPal client ID and secret must be configured in LNbits core settings")
    endpoint = normalize_endpoint(settings.paypal_api_endpoint or "https://api-m.paypal.com")
    async with httpx.AsyncClient(base_url=endpoint) as client:
        r = await client.post("/v1/oauth2/token", data={"grant_type": "client_credentials"}, auth=(client_id, client_secret), headers={"Accept": "application/json"})
        r.raise_for_status()
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        checkout_data = {"intent": "CAPTURE", "purchase_units": [{"amount": {"currency_code": currency.upper(), "value": f"{amount:.2f}"}, "custom_id": payment_hash}], "payment_source": {"paypal": {"experience_context": {"return_url": settings.paypal_payment_success_url or "https://lnbits.com", "cancel_url": settings.paypal_payment_success_url or "https://lnbits.com"}}}}
        r = await client.post("/v2/checkout/orders", json=checkout_data, headers=headers)
        r.raise_for_status()
        data = r.json()
        payment_url = next((link["href"] for link in data.get("links", []) if link.get("rel") == "payer-action"), None)
        return {"payment_request": payment_url, "checking_id": data.get("id")}


async def _create_revolut_checkout(amount: float, currency: str, payment_hash: str) -> dict:
    api_key = settings.revolut_api_secret_key
    if not api_key:
        raise ValueError("Revolut API secret key not configured in LNbits core settings")
    endpoint = normalize_endpoint(settings.revolut_api_endpoint or "https://merchant.revolut.com")
    api_version = settings.revolut_api_version or "2026-04-20"
    headers = {"Authorization": f"Bearer {api_key}", "Revolut-Api-Version": api_version, "Content-Type": "application/json", "User-Agent": settings.user_agent}
    checkout_data = {"amount": int(amount * 100), "currency": currency.upper(), "description": "SatsPay Payment", "merchant_order_ext_ref": payment_hash, "redirect_url": settings.revolut_payment_success_url or "https://lnbits.com"}
    async with httpx.AsyncClient(base_url=endpoint, headers=headers) as client:
        r = await client.post("/api/orders", json=checkout_data)
        r.raise_for_status()
        data = r.json()
        return {"payment_request": data.get("checkout_url"), "checking_id": data.get("id")}


async def _create_square_checkout(amount: float, currency: str, payment_hash: str) -> dict:
    access_token = settings.square_access_token
    location_id = settings.square_location_id
    if not access_token or not location_id:
        raise ValueError("Square access token and location ID must be configured in LNbits core settings")
    endpoint = normalize_endpoint(settings.square_api_endpoint or "https://connect.squareup.com")
    version = settings.square_api_version or "2026-01-22"
    headers = {"Authorization": f"Bearer {access_token}", "Square-Version": version, "Content-Type": "application/json", "User-Agent": settings.user_agent}
    amount_cents = int(amount * 100)
    checkout_data = {"idempotency_key": uuid.uuid4().hex, "order": {"order": {"location_id": location_id, "line_items": [{"quantity": "1", "name": "SatsPay Payment", "base_price_money": {"amount": amount_cents, "currency": currency.upper()}}]}}, "redirect_url": settings.square_payment_success_url or "https://lnbits.com", "ask_for_shipping_address": False}
    async with httpx.AsyncClient(base_url=endpoint, headers=headers) as client:
        r = await client.post("/v2/online-checkout/payment-links", json=checkout_data)
        r.raise_for_status()
        data = r.json()
        payment_link = data.get("payment_link", {})
        return {"payment_request": payment_link.get("url"), "checking_id": payment_link.get("id")}
