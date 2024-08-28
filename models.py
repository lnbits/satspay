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
    custom_css: Optional[str] = Query(None)
    currency: str = Query(None)
    currency_amount: Optional[float] = Query(None)
    extra: Optional[str] = Query(None)


class Charge(BaseModel):
    id: str
    name: Optional[str]
    description: Optional[str]
    onchainwallet: Optional[str]
    onchainaddress: Optional[str]
    lnbitswallet: Optional[str]
    payment_request: Optional[str]
    payment_hash: Optional[str]
    webhook: Optional[str]
    completelink: Optional[str]
    completelinktext: Optional[str] = "Back to Merchant"
    custom_css: Optional[str]
    time: int
    amount: int
    zeroconf: bool
    balance: int
    pending: Optional[int] = 0
    timestamp: datetime
    last_accessed_at: Optional[datetime] = None  # unused, TODO: remove
    currency: Optional[str] = None
    currency_amount: Optional[float] = None
    paid: bool = False
    extra: Optional[str] = None

    def add_extra(self, extra: dict):
        old_extra = json.loads(self.extra) if self.extra else {}
        self.extra = json.dumps({**old_extra, **extra})

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
            "balance",
            "pending",
            "timestamp",
            "custom_css",
            "paid",
            "completelinktext",
        ]
        c = {k: v for k, v in self.dict().items() if k in public_keys}
        c["timestamp"] = self.timestamp.isoformat()
        if self.paid:
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
