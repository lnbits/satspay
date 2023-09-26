import json
from typing import List, Optional

from loguru import logger

from lnbits.core.services import create_invoice
from lnbits.core.views.api import api_payment
from lnbits.helpers import urlsafe_short_hash

from . import db
from .helpers import fetch_onchain_balance
from .models import Charges, CreateCharge, SatsPayThemes, WalletAccountConfig


async def create_charge(
    user: str,
    data: CreateCharge,
    config: Optional[WalletAccountConfig],
    onchainaddress: Optional[str] = None,
) -> Charges:
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            charge_id,
            user,
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


async def update_charge(charge_id: str, **kwargs) -> Optional[Charges]:
    q = ", ".join([f"{field[0]} = ?" for field in kwargs.items()])
    await db.execute(
        f"UPDATE satspay.charges SET {q} WHERE id = ?", (*kwargs.values(), charge_id)
    )
    return await get_charge(charge_id)


async def get_charge(charge_id: str) -> Optional[Charges]:
    await db.execute(
        f"UPDATE satspay.charges SET last_accessed_at = {db.timestamp_now} WHERE id = ?",
        (charge_id,),
    )

    row = await db.fetchone("SELECT * FROM satspay.charges WHERE id = ?", (charge_id,))
    return Charges.from_row(row) if row else None


async def get_charges(user: str) -> List[Charges]:
    await db.execute(
        f"""UPDATE satspay.charges SET last_accessed_at = {db.timestamp_now} WHERE "user"  = ?""",
        (user,),
    )
    rows = await db.fetchall(
        """SELECT * FROM satspay.charges WHERE "user" = ? ORDER BY "timestamp" DESC """,
        (user,),
    )
    return [Charges.from_row(row) for row in rows]


async def delete_charge(charge_id: str) -> None:
    await db.execute("DELETE FROM satspay.charges WHERE id = ?", (charge_id,))


async def check_address_balance(charge_id: str) -> Optional[Charges]:
    charge = await get_charge(charge_id)
    assert charge
    if not charge.paid:
        if charge.onchainaddress:
            try:
                balance = await fetch_onchain_balance(charge)
                confirmed = int(balance["confirmed"])
                unconfirmed = int(balance["unconfirmed"])
                if confirmed != charge.balance or unconfirmed != charge.pending:
                    if charge.zeroconf:
                        confirmed += unconfirmed

                    await update_charge(
                        charge_id=charge_id,
                        balance=confirmed,
                        pending=unconfirmed,
                    )
            except Exception as e:
                logger.warning(e)
        if charge.lnbitswallet:
            try:
                invoice_status = await api_payment(charge.payment_hash)

                if invoice_status["paid"]:
                    return await update_charge(
                        charge_id=charge_id, balance=charge.amount
                    )
            except Exception as e:
                logger.warning(e)
    return await get_charge(charge_id)


################## SETTINGS ###################


async def save_theme(data: SatsPayThemes, css_id: Optional[str]):
    # insert or update
    if css_id:
        await db.execute(
            """
            UPDATE satspay.themes SET custom_css = ?, title = ? WHERE css_id = ?
            """,
            (data.custom_css, data.title, css_id),
        )
    else:
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
                data.user,
                data.custom_css,
            ),
        )
    return await get_theme(css_id)


async def get_theme(css_id: str) -> Optional[SatsPayThemes]:
    row = await db.fetchone("SELECT * FROM satspay.themes WHERE css_id = ?", (css_id,))
    return SatsPayThemes.from_row(row) if row else None


async def get_themes(user_id: str) -> List[SatsPayThemes]:
    rows = await db.fetchall(
        """SELECT * FROM satspay.themes WHERE "user" = ? ORDER BY "title" DESC """,
        (user_id,),
    )
    return [SatsPayThemes.from_row(row) for row in rows]


async def delete_theme(theme_id: str) -> None:
    await db.execute("DELETE FROM satspay.themes WHERE css_id = ?", (theme_id,))
