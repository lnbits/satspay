from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from lnbits.core.models import WalletTypeInfo
from lnbits.decorators import (
    require_admin_key,
    require_invoice_key,
)
from loguru import logger

from .crud import (
    create_charge,
    delete_charge,
    get_charge,
    get_charges,
)
from .helpers import fetch_onchain_config
from .models import Charge, CreateCharge
from .tasks import start_onchain_listener, stop_onchain_listener

satspay_api_router = APIRouter()


@satspay_api_router.post("/api/v1/charge")
async def api_charge_create(
    data: CreateCharge, wallet: WalletTypeInfo = Depends(require_invoice_key)
) -> Charge:
    config = None
    new_address = None
    if data.onchainwallet:
        try:
            config, new_address = await fetch_onchain_config(
                data.onchainwallet, wallet.wallet.inkey
            )
            start_onchain_listener(new_address)
        except Exception as exc:
            logger.error(f"Error fetching onchain config: {exc}")

    return await create_charge(
        user=wallet.wallet.user,
        data=data,
        config=config,
        onchainaddress=new_address,
    )


@satspay_api_router.get("/api/v1/charges")
async def api_charges_retrieve(
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> list[Charge]:
    return await get_charges(wallet.wallet.user)


@satspay_api_router.get(
    "/api/v1/charge/{charge_id}", dependencies=[Depends(require_admin_key)]
)
async def api_charge_retrieve(charge_id: str) -> Charge:
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist."
        )
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
