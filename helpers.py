import asyncio
import hmac
import ipaddress
import json
import socket
from time import time
from urllib.parse import quote, urlparse

import httpx
from lnbits.core.crud import get_standalone_payment
from lnbits.helpers import check_callback_url
from lnbits.settings import settings
from loguru import logger

from .crud import get_or_create_satspay_settings
from .models import Charge, OnchainBalance, validate_http_url


async def call_webhook(charge: Charge):
    try:
        if not charge.webhook or not charge.webhook_secret:
            raise ValueError("Webhook configuration is missing.")
        validate_http_url(charge.webhook)
        check_callback_url(charge.webhook)
        url = httpx.URL(charge.webhook)
        parsed = urlparse(str(url))
        addresses = await _resolve_webhook_host(url.host, url.port)
        if not getattr(settings, "lnbits_callback_allow_private_ips", False) and any(
            not address.is_global for address in addresses
        ):
            raise ValueError("Webhook target IP address is not allowed.")

        body = json.dumps(charge.status).encode()
        timestamp = str(int(time()))
        signature = hmac.new(
            charge.webhook_secret.encode(), timestamp.encode() + b"." + body, "sha256"
        ).hexdigest()
        headers = {
            "Host": parsed.netloc,
            "Content-Type": "application/json",
            "X-LNBits-Timestamp": timestamp,
            "X-LNBits-Signature": signature,
        }
        satspay_settings = await get_or_create_satspay_settings()
        async with httpx.AsyncClient(
            follow_redirects=False, trust_env=False, timeout=10
        ) as client:
            for address in addresses:
                try:
                    async with client.stream(
                        satspay_settings.webhook_method,
                        url.copy_with(host=str(address)),
                        headers=headers,
                        extensions={"sni_hostname": parsed.hostname},
                        content=body,
                    ) as response:
                        response.raise_for_status()
                        response_body = bytearray()
                        async for chunk in response.aiter_bytes(chunk_size=65_536):
                            response_body.extend(chunk)
                            if len(response_body) > 65_536:
                                raise ValueError("Webhook response is too large.")
                        logger.success(f"Webhook sent for charge {charge.id}")
                        return {
                            "webhook_success": True,
                            "webhook_message": f"HTTP {response.status_code}",
                            "webhook_response": response_body.decode(errors="replace"),
                        }
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if address == addresses[-1]:
                        raise
            raise ValueError("Webhook target could not be reached.")
    except Exception as exc:
        error = (
            f"HTTP {exc.response.status_code}"
            if isinstance(exc, httpx.HTTPStatusError)
            else type(exc).__name__
        )
        logger.warning(f"Failed to call webhook for charge {charge.id}: {error}")
        return {"webhook_success": False, "webhook_message": "Webhook request failed."}


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


async def fetch_onchain_address(wallet_id: str, api_key: str, network: str) -> str:
    async with httpx.AsyncClient() as client:
        wallets = await client.get(
            url=f"http://{settings.host}:{settings.port}/watchonly/api/v1/wallet",
            headers={"X-API-KEY": api_key},
            params={"network": network},
        )
        wallets.raise_for_status()
        if not any(wallet["id"] == wallet_id for wallet in wallets.json()):
            raise ValueError("Onchain wallet does not belong to you.")
        r = await client.get(
            url=(
                f"http://{settings.host}:{settings.port}/watchonly/api/v1/address/"
                f"{quote(wallet_id, safe='')}"
            ),
            headers={"X-API-KEY": api_key},
        )
        r.raise_for_status()
        address_data = r.json()
        if not isinstance(address_data, dict) or not address_data.get("address"):
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
                charge.paid = True
                return charge

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
            error = (
                f"HTTP {exc.response.status_code}"
                if isinstance(exc, httpx.HTTPStatusError)
                else type(exc).__name__
            )
            logger.warning(
                f"Onchain balance check failed for charge {charge.id}: {error}"
            )

    charge.paid = charge.balance >= charge.amount

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


async def _resolve_webhook_host(
    host: str, port: int | None
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, port, type=socket.SOCK_STREAM
    )
    addresses = list(dict.fromkeys(ipaddress.ip_address(info[4][0]) for info in infos))
    if not addresses:
        raise ValueError("Webhook target could not be resolved.")
    return addresses
