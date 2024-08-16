import json
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
    WalletAccountConfig,
)

db = Database("ext_satspay")


async def create_charge(
    user: str,
    data: CreateCharge,
    config: Optional[WalletAccountConfig],
    onchainaddress: Optional[str] = None,
) -> Charge:
    data = CreateCharge(**data.dict())
    charge_id = urlsafe_short_hash()
    if data.onchainwallet:
        if not onchainaddress or not config:
            raise Exception(f"Wallet '{data.onchainwallet}' can no longer be accessed.")
        data.extra = json.dumps(
            {"mempool_endpoint": config.mempool_endpoint, "network": config.network}
        )

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
            balance,
            extra,
            custom_css
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            0,
            data.extra,
            data.custom_css,
        ),
    )
    charge = await get_charge(charge_id)
    assert charge, "Newly created charge does not exist"
    return charge


async def update_charge(charge: Charge) -> Charge:
    q = ", ".join([f"{field[0]} = ?" for field in charge.dict().items()])
    await db.execute(
        f"UPDATE satspay.charges SET {q} WHERE id = ?",
        (*charge.dict().values(), charge.id),
    )
    return charge


async def get_charge(charge_id: str) -> Optional[Charge]:
    row = await db.fetchone("SELECT * FROM satspay.charges WHERE id = ?", (charge_id,))
    return Charge(**row) if row else None


async def get_charge_by_onchain_address(onchain_address: str) -> Optional[Charge]:
    row = await db.fetchone(
        "SELECT * FROM satspay.charges WHERE onchainaddress = ?", (onchain_address,)
    )
    return Charge(**row) if row else None


async def get_charges(user: str) -> list[Charge]:
    await db.execute(
        f"""
    UPDATE satspay.charges SET last_accessed_at = {db.timestamp_now} WHERE "user"  = ?
    """,
        (user,),
    )
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
