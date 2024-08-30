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
    charge_id = urlsafe_short_hash()
    if data.onchainwallet:
        if not onchainaddress:
            raise Exception(f"Wallet '{data.onchainwallet}' can no longer be accessed.")

    assert data.amount, "Amount is required"
    if data.lnbitswallet:
        payment_hash, payment_request = await create_invoice(
            wallet_id=data.lnbitswallet,
            amount=data.amount,
            memo=data.description,
            extra={"tag": "charge", "charge": charge_id},
            expiry=int(data.time * 60),  # convert minutes to seconds
        )
    else:
        payment_hash = None
        payment_request = None
    await db.execute(
        """
        INSERT INTO satspay.charges (
            id,
            "user",
            name,
            description,
            onchainwallet,
            onchainaddress,
            lnbitswallet,
            payment_request,
            payment_hash,
            webhook,
            completelink,
            completelinktext,
            time,
            amount,
            zeroconf,
            fasttrack,
            balance,
            extra,
            custom_css,
            currency,
            currency_amount
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            charge_id,
            user,
            data.name,
            data.description,
            data.onchainwallet,
            onchainaddress,
            data.lnbitswallet,
            payment_request,
            payment_hash,
            data.webhook,
            data.completelink,
            data.completelinktext,
            data.time,
            data.amount,
            data.zeroconf,
            data.fasttrack,
            0,
            data.extra,
            data.custom_css,
            data.currency,
            data.currency_amount,
        ),
    )
    charge = await get_charge(charge_id)
    assert charge, "Newly created charge does not exist"
    return charge


async def update_charge(charge: Charge) -> Charge:
    await db.execute(
        """
        UPDATE satspay.charges
        SET extra = ?, balance = ?, pending = ?, paid = ? WHERE id = ?
        """,
        (
            charge.extra,
            charge.balance,
            charge.pending,
            charge.paid,
            charge.id,
        ),
    )
    return charge


async def get_charge(charge_id: str) -> Optional[Charge]:
    row = await db.fetchone("SELECT * FROM satspay.charges WHERE id = ?", (charge_id,))
    return Charge(**row) if row else None


async def get_pending_charges() -> list[Charge]:
    rows = await db.fetchall("SELECT * FROM satspay.charges WHERE paid = false")
    return [Charge(**row) for row in rows]


async def get_charge_by_onchain_address(onchain_address: str) -> Optional[Charge]:
    row = await db.fetchone(
        "SELECT * FROM satspay.charges WHERE onchainaddress = ?", (onchain_address,)
    )
    return Charge(**row) if row else None


async def get_charges(user: str) -> list[Charge]:
    rows = await db.fetchall(
        """SELECT * FROM satspay.charges WHERE "user" = ? ORDER BY "timestamp" DESC """,
        (user,),
    )
    return [Charge(**row) for row in rows]


async def delete_charge(charge_id: str) -> None:
    await db.execute("DELETE FROM satspay.charges WHERE id = ?", (charge_id,))


async def create_theme(data: CreateSatsPayTheme, user_id: str) -> SatsPayTheme:
    css_id = urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO satspay.themes (
            css_id,
            title,
            "user",
            custom_css
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            css_id,
            data.title,
            user_id,
            data.custom_css,
        ),
    )
    theme = await get_theme(css_id)
    assert theme, "Newly created theme does not exist"
    return theme


async def update_theme(data: SatsPayTheme) -> SatsPayTheme:
    await db.execute(
        """
        UPDATE satspay.themes SET custom_css = ?, title = ? WHERE css_id = ?
        """,
        (data.custom_css, data.title, data.css_id),
    )
    theme = await get_theme(data.css_id)
    assert theme, "newly updated theme does not exist"
    return theme


async def get_theme(css_id: str) -> Optional[SatsPayTheme]:
    row = await db.fetchone("SELECT * FROM satspay.themes WHERE css_id = ?", (css_id,))
    return SatsPayTheme(**row) if row else None


async def get_themes(user_id: str) -> list[SatsPayTheme]:
    rows = await db.fetchall(
        """
        SELECT * FROM satspay.themes WHERE "user" = ? ORDER BY title DESC
        """,
        (user_id,),
    )
    return [SatsPayTheme(**row) for row in rows]


async def delete_theme(theme_id: str) -> None:
    await db.execute("DELETE FROM satspay.themes WHERE css_id = ?", (theme_id,))


async def get_or_create_satspay_settings() -> SatspaySettings:
    row = await db.fetchone("SELECT * FROM satspay.settings LIMIT 1")
    if row:
        return SatspaySettings(**row)
    else:
        settings = SatspaySettings()
        await db.execute(
            insert_query("satspay.settings", settings), (*settings.dict().values(),)
        )
        return settings


async def update_satspay_settings(settings: SatspaySettings) -> SatspaySettings:
    await db.execute(
        # 3rd arguments `WHERE clause` is empty for settings
        update_query("satspay.settings", settings, ""),
        (*settings.dict().values(),),
    )
    return settings


async def delete_satspay_settings() -> None:
    await db.execute("DELETE FROM satspay.settings")
