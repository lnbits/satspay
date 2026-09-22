from lnbits.db import Database
from sqlalchemy.exc import OperationalError


async def m001_initial(db: Database):
    """
    Initial wallet table.
    """

    await db.execute(
        f"""
        CREATE TABLE satspay.charges (
            id TEXT NOT NULL PRIMARY KEY,
            "user" TEXT,
            description TEXT,
            onchainwallet TEXT,
            onchainaddress TEXT,
            lnbitswallet TEXT,
            payment_request TEXT,
            payment_hash TEXT,
            webhook TEXT,
            completelink TEXT,
            completelinktext TEXT,
            time INTEGER,
            amount {db.big_int},
            balance {db.big_int} DEFAULT 0,
            timestamp TIMESTAMP NOT NULL DEFAULT """
        + db.timestamp_now
        + """
        );
    """
    )


async def m002_add_charge_extra_data(db: Database):
    """
    Add 'extra' column for storing various config about the charge (JSON format)
    """
    await db.execute("""
        ALTER TABLE satspay.charges
        ADD COLUMN extra TEXT DEFAULT
        '{"mempool_endpoint": "https://mempool.space", "network": "Mainnet"}'
        """)


async def m003_add_themes_table(db: Database):
    """
    Themes table
    """

    await db.execute("""
        CREATE TABLE satspay.themes (
            css_id TEXT NOT NULL PRIMARY KEY,
            "user" TEXT,
            title TEXT,
            custom_css TEXT
        );
    """)


async def m004_add_custom_css_to_charges(db: Database):
    """
    Add custom css option column to the 'charges' table
    """

    await db.execute("ALTER TABLE satspay.charges ADD COLUMN custom_css TEXT;")


async def m005_add_charge_last_accessed_at_column(db: Database):
    """
    Add 'last_accessed_at' column for storing the last updated time
    """
    await db.execute(
        "ALTER TABLE satspay.charges ADD COLUMN last_accessed_at TIMESTAMP;"
    )


async def m006_add_zeroconf_column(db: Database):
    """
    Add 'zeroconf' column for allowing zero confirmation payments
    """
    try:
        await db.execute("""
        ALTER TABLE satspay.charges ADD COLUMN zeroconf BOOLEAN NOT NULL DEFAULT FALSE
        """)

        await db.execute("""
            UPDATE satspay.charges
            SET zeroconf = FALSE
            """)
    except OperationalError:
        pass


async def m007_add_pending_column(db: Database):
    """
    Add 'pending' column for storing the pending amount
    """
    try:
        await db.execute(f"""
            ALTER TABLE satspay.charges
            ADD COLUMN pending {db.big_int} NOT NULL DEFAULT 0
        """)

        await db.execute("""
            UPDATE satspay.charges
            SET pending = 0
            """)
    except OperationalError:
        pass


async def m008_add_name_column(db: Database):
    """
    Add 'name' column for storing the name of the charge
    """
    try:
        await db.execute("ALTER TABLE satspay.charges ADD COLUMN name TEXT")
    except OperationalError:
        pass


async def m009_settings(db: Database):
    """
    Add settings table
    """
    try:
        await db.execute("""
            CREATE TABLE satspay.settings (
                mempool_url TEXT NOT NULL
            )
        """)
    except OperationalError:
        pass


async def m010_add_fiat(db: Database):
    """
    Add 'currency' and 'currency_amount' columns for storing the fiat amount
    """
    try:
        await db.execute("ALTER TABLE satspay.charges ADD COLUMN currency TEXT")
        await db.execute("ALTER TABLE satspay.charges ADD COLUMN currency_amount FLOAT")
    except OperationalError:
        pass


async def m011_persist_paid(db: Database):
    """
    Add 'paid' column for storing the charge status
    """
    try:
        await db.execute(
            "ALTER TABLE satspay.charges ADD COLUMN paid BOOLEAN DEFAULT FALSE"
        )
        await db.execute("""
            UPDATE satspay.charges
            SET paid = TRUE
            WHERE balance >= amount
            """)
    except OperationalError:
        pass


async def m012_add_setting_network(db: Database):
    """
    Add 'network' column for storing the network
    """
    try:
        await db.execute("ALTER TABLE satspay.settings ADD COLUMN network TEXT")
        await db.execute("UPDATE satspay.settings SET network = 'Mainnet'")
    except OperationalError:
        pass


async def m013_add_setting_webhook(db: Database):
    """
    Add 'webhook_method' column for storing the webhook method
    """
    try:
        await db.execute("ALTER TABLE satspay.settings ADD COLUMN webhook_method TEXT")
        await db.execute("UPDATE satspay.settings SET webhook_method = 'GET'")
    except OperationalError:
        pass


async def m014_fasttrack_to_charge(db: Database):
    """
    Add 'fasttrack' column to charge for allowing fasttrack checkout without 0conf
    """
    try:
        await db.execute(
            "ALTER TABLE satspay.charges ADD COLUMN fasttrack BOOLEAN DEFAULT FALSE"
        )
    except OperationalError:
        pass


async def m015_add_fiat_charge_columns(db: Database):
    """
    Add fiat-related columns to charges.
    """
    try:
        await db.execute(
            "ALTER TABLE satspay.charges ADD COLUMN fiat_provider TEXT"
        )
    except OperationalError:
        pass

    try:
        await db.execute(
            "ALTER TABLE satspay.charges ADD COLUMN fiat_currency TEXT"
        )
    except OperationalError:
        pass

    try:
        await db.execute(
            "ALTER TABLE satspay.charges ADD COLUMN fiat_payment_request TEXT"
        )
    except OperationalError:
        pass

    try:
        await db.execute(
            "ALTER TABLE satspay.charges ADD COLUMN fiat_checking_id TEXT"
        )
    except OperationalError:
        pass


async def m016_add_fiat_payment_requests(db: Database):
    """
    Add fiat_payment_requests column for storing multiple fiat provider
    payment requests per charge as JSON.
    """
    try:
        await db.execute(
            "ALTER TABLE satspay.charges ADD COLUMN fiat_payment_requests TEXT"
        )
    except OperationalError:
        pass

async def m017_add_settlement_columns(db: Database):
    """
    Add settlement_method and settlement_proof columns to record how a
    charge was actually settled (method + proof: preimage / txids / fiat id).
    """
    try:
        await db.execute(
            "ALTER TABLE satspay.charges ADD COLUMN settlement_method TEXT"
        )
    except OperationalError:
        pass

    try:
        await db.execute(
            "ALTER TABLE satspay.charges ADD COLUMN settlement_proof TEXT"
        )
    except OperationalError:
        pass

async def m018_backfill_settlement(db: Database):
    """
    Backfill settlement_method and settlement_proof for charges paid before
    those columns existed, using data already stored on the charge row.
    """
    import json as _json

    from loguru import logger

    from lnbits.core.crud import get_standalone_payment

    rows = await db.fetchall(
        "SELECT id, payment_hash, fiat_provider, fiat_checking_id, "
        "fiat_payment_requests, extra FROM satspay.charges "
        "WHERE paid = true AND settlement_method IS NULL"
    )

    backfilled = 0
    for row in rows:
        extra = {}
        if row["extra"]:
            try:
                extra = _json.loads(row["extra"])
            except Exception:
                extra = {}

        method = None
        proof = None
        marker = extra.get("payment_method")

        if marker == "lightning":
            method = "lightning"
            proof = None
            if row["payment_hash"]:
                try:
                    payment = await get_standalone_payment(row["payment_hash"])
                    if payment and payment.preimage:
                        proof = payment.preimage
                except Exception:
                    pass
            if not proof:
                proof = row["payment_hash"]

        elif marker == "onchain":
            method = "onchain"
            txids = extra.get("txids")
            if txids:
                proof = _json.dumps(txids)

        elif row["fiat_provider"]:
            checking_id = row["fiat_checking_id"]
            if not checking_id and row["fiat_payment_requests"]:
                try:
                    reqs = _json.loads(row["fiat_payment_requests"])
                    checking_id = reqs.get(row["fiat_provider"], {}).get("checking_id")
                except Exception:
                    checking_id = None
            if checking_id:
                method = row["fiat_provider"]
                proof = checking_id

        if not method:
            continue

        await db.execute(
            "UPDATE satspay.charges SET settlement_method = :method, "
            "settlement_proof = :proof WHERE id = :id",
            {"method": method, "proof": proof, "id": row["id"]},
        )
        backfilled += 1

    if backfilled:
        logger.info(f"SatsPay: backfilled settlement info for {backfilled} charges.")

