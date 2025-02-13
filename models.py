from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi.param_functions import Query
from pydantic import BaseModel


class SatspaySettings(BaseModel):
    webhook_method: str = "GET"
    mempool_url: str = "https://mempool.space"
    network: str = "Mainnet"


class CreateCharge(BaseModel):
    onchainwallet: str = Query(None)
    lnbitswallet: str = Query(None)
    name: str = Query(None)
    description: str = Query(...)
    webhook: str = Query(None)
    completelink: str = Query(None)
    completelinktext: str = Query("Back to Merchant")
    time: int = Query(..., ge=1)
    amount: Optional[int] = Query(None, ge=1)
    zeroconf: bool = Query(False)
    fasttrack: bool = Query(False)
    custom_css: Optional[str] = Query(None)
    currency: str = Query(None)
    currency_amount: Optional[float] = Query(None)
    extra: Optional[str] = Query(None)


class Charge(BaseModel):
    id: str
    user: str
    amount: int
    time: int
    timestamp: datetime
    balance: int = 0
    pending: int = 0
    zeroconf: bool = False
    fasttrack: bool = False
    paid: bool = False
    completelinktext: Optional[str] = "Back to Merchant"
    name: Optional[str] = None
    description: Optional[str] = None
    onchainwallet: Optional[str] = None
    onchainaddress: Optional[str] = None
    lnbitswallet: Optional[str] = None
    payment_request: Optional[str] = None
    payment_hash: Optional[str] = None
    webhook: Optional[str] = None
    completelink: Optional[str] = None
    custom_css: Optional[str] = None
    currency: Optional[str] = None
    currency_amount: Optional[float] = None
    extra: Optional[str] = None

    def add_extra(self, extra: dict):
        old_extra = json.loads(self.extra) if self.extra else {}
        self.extra = json.dumps({**old_extra, **extra})

    @property
    def paid_fasttrack(self):
        """
        ignore the pending status if fasttrack is enabled tell the frontend its paid
        """
        return (self.pending or 0) >= self.amount and self.fasttrack or self.paid

    @property
    def public(self):
        public_keys = [
            "id",
            "name",
            "description",
            "onchainaddress",
            "payment_request",
            "payment_hash",
            "time",
            "amount",
            "zeroconf",
            "fasttrack",
            "balance",
            "pending",
            "timestamp",
            "custom_css",
            "paid",
            "completelinktext",
        ]
        c = {k: v for k, v in self.dict().items() if k in public_keys}
        c["paid"] = self.paid_fasttrack
        c["timestamp"] = self.timestamp.isoformat()
        if self.paid_fasttrack:
            c["completelink"] = self.completelink
        return c


class CreateSatsPayTheme(BaseModel):
    title: str = Query(...)
    custom_css: str = Query(...)


class SatsPayTheme(BaseModel):
    css_id: str
    title: str
    custom_css: str
    user: str


class OnchainBalance(BaseModel):
    confirmed: int
    unconfirmed: int
    txids: list[str]
