from datetime import datetime
from typing import Optional

from lnbits.core.services import create_invoice
from lnbits.db import Database
from lnbits.helpers import insert_query, update_query, urlsafe_short_hash

from .models import (
    Charge,
    CreateCharge,
    CreateSatsPayTheme,
    SatspaySettings,
    SatsPayTheme,
)

db = Database("ext_satspay")


async def create_charge(
    user: str,
    data: CreateCharge,
    onchainaddress: Optional[str] = None,
) -> Charge:
    if not data.amount or data.amount <= 0:
        raise Exception("Amount must be greater than 0")

    charge = Charge(
        id=urlsafe_short_hash(),
        timestamp=datetime.now(),
        user=user,
        onchainaddress=onchainaddress,
        payment_request=None,
        payment_hash=None,
        balance=0,
        pending=False,
        paid=False,
        name=data.name,
        description=data.description,
        onchainwallet=data.onchainwallet,
        lnbitswallet=data.lnbitswallet,
        webhook=data.webhook,
        completelink=data.completelink,
        completelinktext=data.completelinktext,
        time=data.time,
        amount=data.amount,
        zeroconf=data.zeroconf,
        fasttrack=data.fasttrack,
        extra=data.extra,
        custom_css=data.custom_css,
        currency=data.currency,
        currency_amount=data.currency_amount,
    )

    if data.onchainwallet:
        if not onchainaddress:
            raise Exception(f"Wallet '{data.onchainwallet}' can no longer be accessed.")

    if data.lnbitswallet:
        payment_hash, payment_request = await create_invoice(
            wallet_id=data.lnbitswallet,
            amount=data.amount,
            memo=data.description,
            extra={"tag": "charge", "charge": charge.id},
            expiry=int(data.time * 60),
        )
        charge.payment_hash = payment_hash
        charge.payment_request = payment_request
    await db.execute(
        insert_query("satspay.charges", charge),
        charge.dict(),
    )
    return charge


async def update_charge(charge: Charge) -> Charge:
    await db.execute(
        update_query("satspay.charges", charge),
        charge.dict(),
    )
    return charge


async def get_charge(charge_id: str) -> Optional[Charge]:
    row = await db.fetchone(
        "SELECT * FROM satspay.charges WHERE id = :id",
        {"id": charge_id},
    )
    return Charge(**row) if row else None


async def get_pending_charges() -> list[Charge]:
    rows = await db.fetchall("SELECT * FROM satspay.charges WHERE paid = false")
    return [Charge(**row) for row in rows]


async def get_charge_by_onchain_address(onchain_address: str) -> Optional[Charge]:
    row = await db.fetchone(
        "SELECT * FROM satspay.charges WHERE onchainaddress = :address",
        {"address": onchain_address},
    )
    return Charge(**row) if row else None


async def get_charges(user: str) -> list[Charge]:
    rows = await db.fetchall(
        """
        SELECT * FROM satspay.charges WHERE "user" = :user ORDER BY "timestamp" DESC
        """,
        {"user": user},
    )
    return [Charge(**row) for row in rows]


async def delete_charge(charge_id: str) -> None:
    await db.execute("DELETE FROM satspay.charges WHERE id = :id", {"id": charge_id})


async def create_theme(data: CreateSatsPayTheme, user_id: str) -> SatsPayTheme:
    theme = SatsPayTheme(
        css_id=urlsafe_short_hash(),
        title=data.title,
        custom_css=data.custom_css,
        user=user_id,
    )
    await db.execute(
        insert_query("satspay.themes", theme),
        theme.dict(),
    )
    return theme


async def update_theme(theme: SatsPayTheme) -> SatsPayTheme:
    await db.execute(
        update_query("satspay.themes", theme, "css_id = :css_id"),
        theme.dict(),
    )
    return theme


async def get_theme(css_id: str) -> Optional[SatsPayTheme]:
    row = await db.fetchone(
        "SELECT * FROM satspay.themes WHERE css_id = :css_id", {"css_id": css_id}
    )
    return SatsPayTheme(**row) if row else None


async def get_themes(user_id: str) -> list[SatsPayTheme]:
    rows = await db.fetchall(
        """
        SELECT * FROM satspay.themes WHERE "user" = :user ORDER BY title DESC
        """,
        {"user": user_id},
    )
    return [SatsPayTheme(**row) for row in rows]


async def delete_theme(theme_id: str) -> None:
    await db.execute(
        "DELETE FROM satspay.themes WHERE css_id = :css_id", {"css_id": theme_id}
    )


async def get_or_create_satspay_settings() -> SatspaySettings:
    row = await db.fetchone("SELECT * FROM satspay.settings LIMIT 1")
    if row:
        return SatspaySettings(**row)
    else:
        settings = SatspaySettings()
        await db.execute(insert_query("satspay.settings", settings), settings.dict())
        return settings


async def update_satspay_settings(settings: SatspaySettings) -> SatspaySettings:
    await db.execute(
        # 3rd arguments `WHERE clause` is empty for settings
        update_query("satspay.settings", settings, ""),
        settings.dict(),
    )
    return settings


async def delete_satspay_settings() -> None:
    await db.execute("DELETE FROM satspay.settings")
