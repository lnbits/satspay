import traceback
from http import HTTPStatus
from urllib.parse import urlsplit

import httpx
from lnbits.core.crud import get_standalone_payment
from lnbits.core.crud.wallets import get_onchain_wallet, get_wallets
from lnbits.core.models.wallets import OnchainWallet, WalletType
from lnbits.settings import settings
from loguru import logger

from .crud import get_or_create_satspay_settings
from .models import (
    CORE_ONCHAIN_WALLET_PREFIX,
    Charge,
    CoreOnchainWallet,
    CoreWalletStatus,
    OnchainBalance,
)

MEMPOOL_SPACE_URLS = {
    "Mainnet": "https://mempool.space",
    "Testnet": "https://mempool.space/testnet",
    "Testnet4": "https://mempool.space/testnet4",
}


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


def parse_onchain_wallet_ref(reference: str) -> tuple[str, str]:
    """Split a stored onchain wallet reference into its source and wallet ID."""
    if reference.startswith(CORE_ONCHAIN_WALLET_PREFIX):
        return "core", reference[len(CORE_ONCHAIN_WALLET_PREFIX) :]
    return "watchonly", reference


def validate_mempool_url(network: str, mempool_url: str) -> None:
    url = (mempool_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("Mempool URL is required.")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Mempool URL must be an HTTP(S) URL.")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Mempool URL cannot contain credentials, query or fragment.")
    expected = MEMPOOL_SPACE_URLS.get(network)
    if (
        expected
        and parts.hostname in ("mempool.space", "www.mempool.space")
        and parts.path.rstrip("/") != urlsplit(expected).path
    ):
        raise ValueError(f"Mempool URL for {network} must be {expected}.")


def core_wallet_status(wallet: OnchainWallet) -> CoreWalletStatus:
    if not wallet.onchain_wallet_kind:
        return "setup"
    if wallet.onchain_wallet_kind == "hot" and not wallet.onchain_meta.backup_confirmed:
        return "backup"
    return "ready"


async def require_core_onchain_wallet(wallet_id: str, owner_id: str) -> OnchainWallet:
    """Load a core onchain wallet only if its owner can receive with it."""
    wallet = await get_onchain_wallet(wallet_id)
    if not wallet or wallet.user != owner_id:
        raise ValueError("Onchain wallet does not exist.")
    status = core_wallet_status(wallet)
    if status == "setup":
        raise ValueError("Set up this onchain wallet before receiving.")
    if status == "backup":
        raise ValueError("Back up this onchain wallet before receiving.")
    return wallet


async def get_core_onchain_wallets(user_id: str) -> list[CoreOnchainWallet]:
    wallets = await get_wallets(user_id, wallet_type=WalletType.ONCHAIN)
    result: list[CoreOnchainWallet] = []
    for wallet in wallets:
        onchain_wallet = await get_onchain_wallet(wallet.id)
        if not onchain_wallet:
            continue
        result.append(
            CoreOnchainWallet(
                id=onchain_wallet.id,
                name=onchain_wallet.name,
                network=onchain_wallet.onchain_network or "Mainnet",
                status=core_wallet_status(onchain_wallet),
            )
        )
    return result


async def fetch_core_onchain_address(wallet: OnchainWallet) -> str:
    """Request a fresh address through the core endpoint and its safeguards."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"http://{settings.host}:{settings.port}"
                f"/api/v1/onchain/address/{wallet.id}",
                headers={"X-API-KEY": wallet.inkey},
            )
    except httpx.HTTPError as exc:
        raise ValueError("Cannot reach the onchain wallet service.") from exc
    if r.status_code == HTTPStatus.CONFLICT:
        raise ValueError("Back up this onchain wallet before receiving.")
    if r.status_code in (
        HTTPStatus.UNAUTHORIZED,
        HTTPStatus.FORBIDDEN,
        HTTPStatus.NOT_FOUND,
    ):
        raise ValueError("Onchain wallet is not available for receiving.")
    if r.is_error:
        raise ValueError("Cannot fetch a new onchain address.")
    try:
        address = r.json().get("address")
    except ValueError as exc:
        raise ValueError("Cannot fetch a new onchain address.") from exc
    if not address:
        raise ValueError("Cannot fetch a new onchain address.")
    return address


async def check_charge_balance(charge: Charge, notify_webhook: bool = True) -> Charge:
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

    if charge.webhook and notify_webhook:
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
