import json
from http import HTTPStatus

from fastapi import APIRouter, Depends, HTTPException
from lnbits.core.models import User, WalletTypeInfo
from lnbits.decorators import (
    check_admin,
    get_key_type,
    require_admin_key,
    require_invoice_key,
)
from loguru import logger

from .crud import (
    check_address_balance,
    create_charge,
    create_theme,
    delete_charge,
    delete_theme,
    get_charge,
    get_charges,
    get_theme,
    get_themes,
    update_charge,
    update_theme,
)
from .helpers import call_webhook, fetch_onchain_config
from .models import Charge, CreateCharge, CreateSatsPayTheme, SatsPayTheme

satspay_api_router = APIRouter()


@satspay_api_router.post("/api/v1/charge")
async def api_charge_create(
    data: CreateCharge, wallet: WalletTypeInfo = Depends(require_invoice_key)
):
    config = None
    new_address = None
    if data.onchainwallet:
        try:
            config, new_address = await fetch_onchain_config(
                data.onchainwallet, wallet.wallet.inkey
            )
        except Exception as exc:
            logger.error(f"Error fetching onchain config: {exc}")

    return await create_charge(
        user=wallet.wallet.user,
        data=data,
        config=config,
        onchainaddress=new_address,
    )


@satspay_api_router.put(
    "/api/v1/charge/{charge_id}", dependencies=[Depends(require_admin_key)]
)
async def api_charge_update(charge_id: str, data: CreateCharge) -> Charge:
    charge = Charge(
        id=charge_id,
        **data.dict(),
    )
    return await update_charge(charge)


@satspay_api_router.get("/api/v1/charges")
async def api_charges_retrieve(wallet: WalletTypeInfo = Depends(get_key_type)):
    try:
        return [
            {
                **charge.dict(),
                **{"time_elapsed": charge.time_elapsed},
                **{"time_left": charge.time_left},
                **{"paid": charge.paid},
                **{"webhook_message": charge.config.webhook_message},
            }
            for charge in await get_charges(wallet.wallet.user)
        ]
    except Exception:
        return ""


@satspay_api_router.get(
    "/api/v1/charge/{charge_id}", dependencies=[Depends(get_key_type)]
)
async def api_charge_retrieve(charge_id: str):
    charge = await get_charge(charge_id)

    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist."
        )

    return {
        **charge.dict(),
        **{"time_elapsed": charge.time_elapsed},
        **{"time_left": charge.time_left},
        **{"paid": charge.paid},
    }


@satspay_api_router.delete(
    "/api/v1/charge/{charge_id}", dependencies=[Depends(get_key_type)]
)
async def api_charge_delete(charge_id: str):
    charge = await get_charge(charge_id)
    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist."
        )
    await delete_charge(charge_id)


@satspay_api_router.get("/api/v1/charges/balance/{charge_ids}")
async def api_charges_balance(charge_ids):
    charge_id_list = charge_ids.split(",")
    charges = []
    for charge_id in charge_id_list:
        charge = await api_charge_balance(charge_id)
        charges.append(charge)
    return charges


@satspay_api_router.get("/api/v1/charge/balance/{charge_id}")
async def api_charge_balance(charge_id):
    charge = await check_address_balance(charge_id)

    if not charge:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Charge does not exist."
        )

    if charge.must_call_webhook():
        resp = await call_webhook(charge)
        extra = {**charge.config.dict(), **resp}
        charge.extra = json.dumps(extra)
        await update_charge(charge)

    return {**charge.public}


@satspay_api_router.post("/api/v1/themes")
async def api_themes_create(
    data: CreateSatsPayTheme,
    user: User = Depends(check_admin),
) -> SatsPayTheme:
    return await create_theme(data=data, user_id=user.id)


@satspay_api_router.post("/api/v1/themes/{css_id}")
async def api_themes_save(
    css_id: str,
    data: CreateSatsPayTheme,
    user: User = Depends(check_admin),
) -> SatsPayTheme:

    theme = SatsPayTheme(
        css_id=css_id,
        user=user.id,
        **data.dict(),
    )
    return await update_theme(theme)


@satspay_api_router.get("/api/v1/themes")
async def api_get_themes(user: User = Depends(check_admin)) -> list[SatsPayTheme]:
    return await get_themes(user.id)


@satspay_api_router.delete(
    "/api/v1/themes/{theme_id}", dependencies=[Depends(get_key_type)]
)
async def api_theme_delete(theme_id):
    theme = await get_theme(theme_id)
    if not theme:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Theme does not exist."
        )
    await delete_theme(theme_id)
