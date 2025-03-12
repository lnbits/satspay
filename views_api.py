from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
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
    fetch_onchain_address,
    fetch_onchain_config_network,
)
from .models import Charge, CreateCharge, SatspaySettings
from .tasks import start_onchain_listener, stop_onchain_listener
from .websocket_handler import restart_websocket_task

satspay_api_router = APIRouter()


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


@satspay_api_router.post("/api/v1/charge")
async def api_charge_create(
    data: CreateCharge, key_type: WalletTypeInfo = Depends(require_invoice_key)
) -> Charge:
    if not data.amount and not data.currency_amount:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="either amount or currency_amount are required.",
        )
    if data.currency and data.currency_amount:
        rate = await get_fiat_rate_satoshis(data.currency)
        data.amount = round(rate * data.currency_amount)
    if not data.onchainwallet and not data.lnbitswallet:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="either onchainwallet or lnbitswallet are required.",
        )
    if data.lnbitswallet:
        lnbitswallet = await get_wallet(data.lnbitswallet)
        if not lnbitswallet:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="LNbits wallet does not exist.",
            )
        if lnbitswallet.user != key_type.wallet.user:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="LNbits wallet does not belong to you.",
            )
    if data.onchainwallet:
        settings = await get_or_create_satspay_settings()
        network = await _get_wallet_network(key_type.wallet)
        if network != settings.network:
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail=f"Onchain network mismatch. {network} != {settings.network}",
            )
        try:
            new_address = await fetch_onchain_address(
                data.onchainwallet, key_type.wallet.inkey
            )
            start_onchain_listener(new_address)
            return await create_charge(
                user=key_type.wallet.user,
                onchainaddress=new_address,
                data=data,
            )
        except Exception as exc:
            logger.error(f"Error fetching onchain config: {exc}")
            raise HTTPException(
                status_code=HTTPStatus.BAD_REQUEST,
                detail="Error fetching onchain address.",
            ) from exc
    return await create_charge(user=key_type.wallet.user, data=data)


@satspay_api_router.get("/api/v1/charges")
async def api_charges_retrieve(
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> list[Charge]:
    return await get_charges(wallet.wallet.user)


@satspay_api_router.get(
    "/api/v1/charge/{charge_id}", dependencies=[Depends(require_invoice_key)]
)
@satspay_api_router.get(
    "/api/v1/charge/balance/{charge_id}",
    dependencies=[Depends(require_invoice_key)],
    deprecated=True,
)
async def api_charge_retrieve(charge_id: str) -> Charge:
    """
    This endpoint is used by the woocommerce plugin to check if the status of a charge
    is paid. you can refresh the success page of the webshop to trigger this endpoint.
    useful if the webhook is not working or fails for some reason.
    https://github.com/lnbits/woocommerce-payment-gateway/blob/main/lnbits.php#L312
    """
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist."
        )
    return charge


@satspay_api_router.put(
    "/api/v1/charge/balance/{charge_id}", dependencies=[Depends(require_admin_key)]
)
async def api_charge_check_balance(charge_id: str) -> Charge:
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist."
        )
    if charge.paid:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="Charge is already paid."
        )
    balance_before = charge.balance
    pending_before = charge.pending
    charge = await check_charge_balance(charge)
    if charge.balance != balance_before or charge.pending != pending_before:
        charge = await update_charge(charge)
    return charge


@satspay_api_router.get(
    "/api/v1/charge/webhook/{charge_id}", dependencies=[Depends(require_admin_key)]
)
async def api_charge_webhook(charge_id: str) -> Charge:
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist."
        )
    if not charge.webhook:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST, detail="No webhook set."
        )
    resp = await call_webhook(charge)
    charge.add_extra(resp)
    charge = await update_charge(charge)
    return charge


@satspay_api_router.delete(
    "/api/v1/charge/{charge_id}", dependencies=[Depends(require_admin_key)]
)
async def api_charge_delete(charge_id: str):
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist."
        )
    if charge.onchainaddress:
        stop_onchain_listener(charge.onchainaddress)

    await delete_charge(charge_id)


@satspay_api_router.get("/api/v1/settings", dependencies=[Depends(check_admin)])
async def api_get_or_create_settings() -> SatspaySettings:
    return await get_or_create_satspay_settings()


@satspay_api_router.put("/api/v1/settings", dependencies=[Depends(check_admin)])
async def api_update_settings(data: SatspaySettings) -> SatspaySettings:
    settings = await update_satspay_settings(data)
    restart_websocket_task()
    return settings


@satspay_api_router.delete("/api/v1/settings", dependencies=[Depends(check_admin)])
async def api_delete_settings() -> None:
    await delete_satspay_settings()
    restart_websocket_task()
