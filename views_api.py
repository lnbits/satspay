from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from lnbits.core.models import WalletTypeInfo
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
from .helpers import check_charge_balance, fetch_onchain_config
from .models import Charge, CreateCharge, SatspaySettings
from .tasks import start_onchain_listener, stop_onchain_listener

satspay_api_router = APIRouter()


@satspay_api_router.post("/api/v1/charge")
async def api_charge_create(
    data: CreateCharge, wallet: WalletTypeInfo = Depends(require_invoice_key)
) -> Charge:
    if not data.amount and not data.currency_amount:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail="either amount or currency_amount are required.",
        )
    if data.currency and data.currency_amount:
        rate = await get_fiat_rate_satoshis(data.currency)
        data.amount = round(rate * data.currency_amount)
    if data.onchainwallet:
        try:
            config, new_address = await fetch_onchain_config(
                data.onchainwallet, wallet.wallet.inkey
            )
            start_onchain_listener(new_address)
            return await create_charge(
                user=wallet.wallet.user,
                onchainaddress=new_address,
                data=data,
                config=config,
            )
        except Exception as exc:
            logger.error(f"Error fetching onchain config: {exc}")
    return await create_charge(user=wallet.wallet.user, data=data)


@satspay_api_router.get("/api/v1/charges")
async def api_charges_retrieve(
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> list[Charge]:
    return await get_charges(wallet.wallet.user)


"""
This endpoint is used by the woocommerce plugin to check if the status of a charge
is paid (if `res['paid']` == `true`). you can refresh the success page of the webshop to
trigger this endpoint. useful if the webhook is not working or fails for some reason.
"""
@satspay_api_router.get(
    "/api/v1/charge/{charge_id}", dependencies=[Depends(require_invoice_key)]
)
async def api_charge_retrieve(charge_id: str) -> dict:
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist."
        )
    return charge.public


@satspay_api_router.get(
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
    return await update_satspay_settings(data)


@satspay_api_router.delete("/api/v1/settings", dependencies=[Depends(check_admin)])
async def api_delete_settings() -> None:
    await delete_satspay_settings()
