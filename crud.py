import json
from typing import List, Optional

from lnbits.core.crud import get_standalone_payment
from lnbits.core.services import create_invoice
from lnbits.db import Database
from lnbits.helpers import urlsafe_short_hash
from loguru import logger

from .helpers import fetch_onchain_balance
from .models import (
    Charge,
    CreateCharge,
    CreateSatsPayTheme,
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
            balance,
            extra,
            custom_css
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    await db.execute(
        f"""
    UPDATE satspay.charges
    SET last_accessed_at = {db.timestamp_now} WHERE id = ?
    """,
        (charge_id,),
    )

    row = await db.fetchone("SELECT * FROM satspay.charges WHERE id = ?", (charge_id,))
    return Charge(**row) if row else None


async def get_charges(user: str) -> List[Charge]:
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


async def check_address_balance(charge_id: str) -> Charge:
    charge = await get_charge(charge_id)
    assert charge, "balance check failed, charge does not exist"
    if charge.paid:
        return charge
    if charge.onchainaddress:
        try:
            balance = await fetch_onchain_balance(charge)
            confirmed = int(balance["confirmed"])
            unconfirmed = int(balance["unconfirmed"])
            if confirmed != charge.balance or unconfirmed != charge.pending:
                charge.balance = confirmed
                charge.pending = unconfirmed
                return await update_charge(charge)
        except Exception as e:
            logger.warning(e)
    if charge.lnbitswallet and charge.payment_hash:
        payment = await get_standalone_payment(charge.payment_hash)
        status = (await payment.check_status()).success if payment else False
        if status:
            charge.balance = charge.amount
            return await update_charge(charge)
    return charge


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


async def get_themes(user_id: str) -> List[SatsPayTheme]:
    rows = await db.fetchall(
        """
        SELECT * FROM satspay.themes WHERE "user" = ? ORDER BY title DESC
        """,
        (user_id,),
    )
    return [SatsPayTheme(**row) for row in rows]


async def delete_theme(theme_id: str) -> None:
    await db.execute("DELETE FROM satspay.themes WHERE css_id = ?", (theme_id,))
