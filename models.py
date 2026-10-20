from __future__ import annotations

import json
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, validator


class SatspaySettings(BaseModel):
    webhook_method: Literal["GET", "POST"] = "GET"
    mempool_url: str = "https://mempool.space"
    network: str = "Mainnet"


class CreateCharge(BaseModel):
    onchainwallet: str | None = Field(default=None, regex=r"^[a-zA-Z0-9_-]+$")
    lnbitswallet: str | None = None
    name: str | None = None
    description: str
    webhook: str | None = None
    completelink: str | None = None
    completelinktext: str = "Back to Merchant"
    time: int = Field(..., ge=1)
    amount: int | None = Field(default=None, ge=1)
    zeroconf: bool = False
    fasttrack: bool = False
    custom_css: str | None = None
    currency: str | None = None
    currency_amount: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    extra: str | None = None

    @validator("webhook", "completelink")
    @classmethod
    def validate_url(cls, value):
        return _http_url(value)

    @validator("extra")
    @classmethod
    def validate_extra(cls, value):
        if value is not None and not isinstance(json.loads(value), dict):
            raise ValueError("extra must be a JSON object.")
        return value


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
    completelinktext: str | None = "Back to Merchant"
    name: str | None = None
    description: str | None = None
    onchainwallet: str | None = None
    onchainaddress: str | None = None
    lnbitswallet: str | None = None
    payment_request: str | None = None
    payment_hash: str | None = None
    webhook: str | None = None
    webhook_secret: str | None = None
    completelink: str | None = None
    custom_css: str | None = None
    currency: str | None = None
    currency_amount: float | None = None
    extra: str | None = None

    def add_extra(self, extra: dict):
        try:
            old_extra = json.loads(self.extra) if self.extra else {}
        except (TypeError, ValueError):
            old_extra = {}
        if not isinstance(old_extra, dict):
            old_extra = {}
        self.extra = json.dumps({**old_extra, **extra})

    @property
    def paid_fasttrack(self):
        """
        ignore the pending status if fasttrack is enabled tell the frontend its paid
        """
        return ((self.pending or 0) >= self.amount and self.fasttrack) or self.paid

    @property
    def status(self):
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
            "currency",
            "currency_amount",
            "lnbitswallet",
            "onchainwallet",
        ]
        c = {k: v for k, v in self.dict().items() if k in public_keys}
        c["timestamp"] = self.timestamp.isoformat()
        if self.paid_fasttrack:
            c["completelink"] = self.safe_completelink
        return c

    @property
    def public(self):
        return {**self.status, "paid": self.paid_fasttrack}

    @property
    def safe_completelink(self):
        try:
            return _http_url(self.completelink)
        except ValueError:
            return None


class CreateSatsPayTheme(BaseModel):
    title: str
    custom_css: str


class SatsPayTheme(BaseModel):
    css_id: str
    title: str
    custom_css: str
    user: str


class OnchainBalance(BaseModel):
    confirmed: int
    unconfirmed: int
    txids: list[str]


def _http_url(value: str | None) -> str | None:
    if not value:
        return None
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
    ):
        raise ValueError("URL must be an absolute HTTP or HTTPS URL.")
    # Accessing port also rejects malformed and out-of-range ports.
    _ = url.port
    return value
