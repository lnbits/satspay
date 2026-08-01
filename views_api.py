import json
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException, Request
from lnbits.core.crud import get_wallet
from lnbits.core.models import Wallet, WalletTypeInfo
from lnbits.decorators import (
    check_admin,
    require_admin_key,
    require_invoice_key,
)
from lnbits.utils.exchange_rates import get_fiat_rate_satoshis
from loguru import logger

from .crud import (
    create_charge,
    delete_charge,
    delete_satspay_settings,
    get_charge,
    get_charges,
    get_or_create_satspay_settings,
    update_charge,
    update_satspay_settings,
)
from .helpers import (
    call_webhook,
    check_charge_balance,
    create_fiat_invoice_for_charge,
    fetch_onchain_address,
    fetch_onchain_config_network,
    verify_fiat_webhook,
)
from .models import Charge, CreateCharge, SatspaySettings
from lnbits.settings import settings
from .tasks import (
    send_success_websocket,
    start_onchain_listener,
    stop_onchain_listener,
)
from .websocket_handler import restart_websocket_task

satspay_api_router = APIRouter()


async def _find_charge_by_fiat_checking_id(checking_id: str, provider: str) -> Charge | None:
    from .crud import db
    return await db.fetchone(
        """
        SELECT * FROM satspay.charges
        WHERE (
            (fiat_checking_id = :checking_id AND fiat_provider = :provider)
            OR (
                fiat_payment_requests IS NOT NULL
                AND json_extract(fiat_payment_requests, :json_path) = :checking_id
            )
        )
        """,
        {
            "checking_id": checking_id,
            "provider": provider,
            "json_path": f"$.{provider}.checking_id",
        },
        Charge,
    )


async def handle_fiat_webhook_event(
    provider: str, event: dict, metadata: dict
) -> bool:
    provider = provider.lower()
    if provider != "stripe" or metadata.get("source") != "satspay":
        return False

    event_type = event.get("type")
    event_object = event.get("data", {}).get("object", {})
    if event_type != "checkout.session.completed":
        return False
    if event_object.get("payment_status") != "paid":
        return False

    checking_id = event_object.get("id")
    if not checking_id:
        return False

    matching_charge = await _find_charge_by_fiat_checking_id(checking_id, provider)
    if not matching_charge:
        return False
    if metadata.get("satspay_charge_id") and metadata["satspay_charge_id"] != matching_charge.id:
        logger.warning(
            f"SatsPay charge metadata mismatch for Stripe session '{checking_id}'."
        )
        return False
    if matching_charge.paid:
        return True

    matching_charge.balance = matching_charge.amount
    matching_charge.paid = True
    matching_charge.settlement_method = provider
    matching_charge.settlement_proof = checking_id
    matching_charge = await update_charge(matching_charge)
    await send_success_websocket(matching_charge)
    if matching_charge.webhook:
        await call_webhook(matching_charge)
    return True


async def _get_wallet_network(wallet: Wallet) -> str:
    try:
        network = await fetch_onchain_config_network(wallet.inkey)
    except Exception as exc:
        logger.error(f"Error fetching onchain config: {exc!s}")
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="Error fetching onchain config.",
        ) from exc
    return network


@satspay_api_router.get("/api/v1")
async def api_enabled() -> dict:
    return {"message": "SatsPay API enabled."}


@satspay_api_router.get("/api/v1/fiat/providers")
async def api_fiat_providers(wallet: WalletTypeInfo = Depends(require_invoice_key)) -> list[str]:
    return settings.get_fiat_providers_for_user(wallet.wallet.user)


@satspay_api_router.post("/api/v1/fiat/webhook/{provider}")
async def api_fiat_webhook(provider: str, request: Request) -> dict:
    payload = await request.body()
    signature = request.headers.get("stripe-signature") or request.headers.get("paypal-transmission-sig")
    try:
        checking_id = await verify_fiat_webhook(provider, payload, signature)
    except ValueError as e:
        logger.warning(f"Fiat webhook verification failed: {e}")
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=str(e)) from e
    if checking_id:
        matching_charge = await _find_charge_by_fiat_checking_id(checking_id, provider)
        if matching_charge and not matching_charge.paid:
            matching_charge.balance = matching_charge.amount
            matching_charge.paid = True
            matching_charge.settlement_method = provider
            matching_charge.settlement_proof = checking_id
            matching_charge = await update_charge(matching_charge)
            await send_success_websocket(matching_charge)
            if matching_charge.webhook:
                await call_webhook(matching_charge)
    return {"status": "ok"}


@satspay_api_router.post("/api/v1/charge")
async def api_charge_create(data: CreateCharge, key_type: WalletTypeInfo = Depends(require_invoice_key)) -> Charge:
    if not data.amount and not data.currency_amount:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="either amount or currency_amount are required.")
    if data.currency and data.currency_amount:
        rate = await get_fiat_rate_satoshis(data.currency)
        data.amount = round(rate * data.currency_amount)
    user = key_type.wallet.user
    available_fiat = settings.get_fiat_providers_for_user(user)
    if data.fiat_provider and data.fiat_provider not in available_fiat:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=f"Fiat provider '{data.fiat_provider}' is not enabled or not authorized for your user.")
    if not data.onchainwallet and not data.lnbitswallet and not data.fiat_provider and not available_fiat:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="either onchainwallet, lnbitswallet, or fiat_provider are required.")
    if data.lnbitswallet:
        lnbitswallet = await get_wallet(data.lnbitswallet)
        if not lnbitswallet:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="LNbits wallet does not exist.")
        if lnbitswallet.user != user:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="LNbits wallet does not belong to you.")
    if data.onchainwallet:
        settings_data = await get_or_create_satspay_settings()
        network = await _get_wallet_network(key_type.wallet)
        if network != settings_data.network:
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail=f"Onchain network mismatch. {network} != {settings_data.network}")
        try:
            new_address = await fetch_onchain_address(data.onchainwallet, key_type.wallet.inkey)
            start_onchain_listener(new_address)
            charge = await create_charge(user=user, onchainaddress=new_address, data=data)
        except Exception as exc:
            logger.error(f"Error fetching onchain config: {exc}")
            raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Error fetching onchain address.") from exc
    else:
        charge = await create_charge(user=user, data=data)

    if data.fiat_provider:
        try:
            fiat_result = await create_fiat_invoice_for_charge(charge, data, data.fiat_provider)
            if fiat_result:
                charge.fiat_payment_requests = json.dumps({
                    data.fiat_provider: {
                        "payment_request": fiat_result.get("payment_request"),
                        "checking_id": fiat_result.get("checking_id"),
                    }
                })
                charge = await update_charge(charge)
        except Exception as exc:
            logger.warning(f"Failed to create fiat invoice for {data.fiat_provider}: {exc}")
    return charge


@satspay_api_router.get("/api/v1/charges")
async def api_charges_retrieve(wallet: WalletTypeInfo = Depends(require_admin_key)) -> list[Charge]:
    return await get_charges(wallet.wallet.user)


@satspay_api_router.get("/api/v1/charge/{charge_id}", dependencies=[Depends(require_invoice_key)])
@satspay_api_router.get("/api/v1/charge/balance/{charge_id}", dependencies=[Depends(require_invoice_key)], deprecated=True)
async def api_charge_retrieve(charge_id: str) -> Charge:
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist.")
    return charge


@satspay_api_router.put("/api/v1/charge/balance/{charge_id}", dependencies=[Depends(require_admin_key)])
async def api_charge_check_balance(charge_id: str) -> Charge:
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist.")
    if charge.paid:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="Charge is already paid.")
    balance_before = charge.balance
    pending_before = charge.pending
    charge = await check_charge_balance(charge)
    if charge.balance != balance_before or charge.pending != pending_before:
        charge = await update_charge(charge)
    return charge


@satspay_api_router.get("/api/v1/charge/webhook/{charge_id}", dependencies=[Depends(require_admin_key)])
async def api_charge_webhook(charge_id: str) -> Charge:
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist.")
    if not charge.webhook:
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST, detail="No webhook set.")
    charge = await update_charge(charge)
    resp = await call_webhook(charge)
    charge.add_extra(resp)
    charge = await update_charge(charge)
    return charge


@satspay_api_router.delete("/api/v1/charge/{charge_id}", dependencies=[Depends(require_admin_key)])
async def api_charge_delete(charge_id: str):
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist.")
    if charge.onchainaddress:
        stop_onchain_listener(charge.onchainaddress)
    await delete_charge(charge_id)


@satspay_api_router.get("/api/v1/settings/public")
async def api_get_public_settings() -> dict:
    satspay_settings = await get_or_create_satspay_settings()
    return {
        "network": satspay_settings.network,
        "mempool_url": satspay_settings.mempool_url,
    }


@satspay_api_router.get("/api/v1/charge/public/{charge_id}")
async def api_get_charge_public(charge_id: str) -> dict:
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist."
        )
    satspay_settings = await get_or_create_satspay_settings()
    return {**charge.public, "mempool_url": satspay_settings.mempool_url}


@satspay_api_router.get("/api/v1/settings", dependencies=[Depends(check_admin)])
async def api_get_or_create_settings() -> SatspaySettings:
    return await get_or_create_satspay_settings()


@satspay_api_router.put("/api/v1/settings", dependencies=[Depends(check_admin)])
async def api_update_settings(data: SatspaySettings) -> SatspaySettings:
    settings_data = await update_satspay_settings(data)
    restart_websocket_task()
    return settings_data


@satspay_api_router.delete("/api/v1/settings", dependencies=[Depends(check_admin)])
async def api_delete_settings() -> None:
    await delete_satspay_settings()
    restart_websocket_task()
