from typing import Tuple

import httpx
from lnbits.settings import settings
from loguru import logger

from .models import Charge, WalletAccountConfig


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


async def fetch_onchain_balance(charge: Charge):
    endpoint = (
        f"{charge.config.mempool_endpoint}/testnet"
        if charge.config.network == "Testnet"
        else charge.config.mempool_endpoint
    )
    assert endpoint
    assert charge.onchainaddress
    async with httpx.AsyncClient() as client:
        r = await client.get(endpoint + "/api/address/" + charge.onchainaddress)
        resp = r.json()
        return {
            "confirmed": resp["chain_stats"]["funded_txo_sum"],
            "unconfirmed": resp["mempool_stats"]["funded_txo_sum"],
        }


async def fetch_onchain_config(
    wallet_id: str, api_key: str
) -> Tuple[WalletAccountConfig, str]:
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
