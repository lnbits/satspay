from __future__ import annotations

import json
from typing import Optional

from fastapi.param_functions import Query
from pydantic import BaseModel

DEFAULT_MEMPOOL_ENDPOINT = "https://mempool.space"
DEFAULT_MEMPOOL_CONFIG = (
    '{"mempool_endpoint": "https://mempool.space", "network": "Mainnet"}'
)


class SatspaySettings(BaseModel):
    mempool_url: str = DEFAULT_MEMPOOL_ENDPOINT


class CreateCharge(BaseModel):
    onchainwallet: str = Query(None)
    lnbitswallet: str = Query(None)
    name: str = Query(None)
    description: str = Query(...)
    webhook: str = Query(None)
    completelink: str = Query(None)
    completelinktext: str = Query("Back to Merchant")
    time: int = Query(..., ge=1)
    amount: int = Query(..., ge=1)
    zeroconf: bool = Query(False)
    extra: str = DEFAULT_MEMPOOL_CONFIG
    custom_css: Optional[str] = Query(None)


class ChargeConfig(BaseModel):
    mempool_endpoint: Optional[str]
    network: Optional[str]
    webhook_message: Optional[str]
    webhook_success: bool = False
    misc: dict = {}


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
    extra: str = DEFAULT_MEMPOOL_CONFIG
    time: int
    amount: int
    zeroconf: bool
    balance: int
    pending: Optional[int] = 0
    timestamp: int
    last_accessed_at: Optional[int] = 0

    @property
    def paid(self):
        return self.balance >= self.amount

    @property
    def config(self) -> ChargeConfig:
        charge_config = json.loads(self.extra)
        return ChargeConfig(**charge_config)

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
        ]
        c = {k: v for k, v in self.dict().items() if k in public_keys}
        c["paid"] = self.paid
        if self.paid:
            c["completelink"] = self.completelink
            c["completelinktext"] = self.completelinktext
        return c


class CreateSatsPayTheme(BaseModel):
    title: str = Query(...)
    custom_css: str = Query(...)


class SatsPayTheme(BaseModel):
    css_id: str
    title: str
    custom_css: str
    user: str


class WalletAccountConfig(BaseModel):
    mempool_endpoint: str
    receive_gap_limit: int
    change_gap_limit: int
    sats_denominated: bool
    network: str
