"""Domain objects shared by the extractor, storage and UI."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .period import Period

STATUSES = ("active", "review", "paused", "cancelled")
ACTIVE_STATUSES = ("active", "paused")


def service_key(name: str) -> str:
    """Identity of a service name: lower case, letters and digits only."""
    text = unicodedata.normalize("NFKC", name or "").casefold()
    text = text.replace("+", "plus")
    return re.sub(r"[\W_]+", "", text)


@dataclass
class Subscription:
    service: str
    amount: Decimal | None = None
    currency: str | None = None
    period: Period = field(default_factory=Period)
    next_charge: date | None = None
    last_charge: date | None = None
    anchor_day: int | None = None
    category: str = "other"
    tags: list[str] = field(default_factory=list)
    status: str = "active"
    trial_until: date | None = None
    confidence: float = 1.0
    source: str = "manual"
    source_account: str | None = None
    sender: str | None = None
    cancel_url: str | None = None
    plan: str | None = None
    notes: str | None = None
    snippet: str | None = None
    review_reason: str | None = None
    track_usage: bool = False
    last_used: date | None = None
    previous_amount: Decimal | None = None
    price_changed_at: date | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    cancelled_at: datetime | None = None
    id: int | None = None
    key: str = ""

    def __post_init__(self) -> None:
        if not self.key:
            self.key = self.make_key()

    def make_key(self) -> str:
        return service_key(self.service) + "|" + (self.currency or "").upper()

    @property
    def monthly_amount(self) -> Decimal | None:
        if self.amount is None:
            return None
        return self.amount * self.period.per_month

    @property
    def is_trial(self) -> bool:
        return self.trial_until is not None

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES


@dataclass
class Charge:
    subscription_id: int
    date: date
    amount: Decimal
    currency: str
    source: str
    source_ref: str | None = None
    kind: str = "charge"
    id: int | None = None


@dataclass
class Transaction:
    """One debit from a bank statement, reduced to what detection needs."""

    date: date
    amount: Decimal
    currency: str
    merchant: str
    merchant_key: str = ""
    description: str = ""
    file_sha256: str = ""
    seq: int = 0

    def __post_init__(self) -> None:
        if not self.merchant_key:
            self.merchant_key = service_key(self.merchant)


@dataclass
class RawMessage:
    """An email as handed over by a source, before extraction.

    `key` must be stable for the same message across runs (Gmail id, IMAP
    folder/uidvalidity/uid, Message-ID); it is hashed before storage.
    """

    source: str
    key: str
    sender: str = ""
    sender_name: str = ""
    subject: str = ""
    date: datetime | None = None
    text: str = ""
    html: str = ""
    account: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def sender_domain(self) -> str:
        _, _, domain = self.sender.rpartition("@")
        return domain.lower().strip(">").strip()


@dataclass
class Detection:
    """What the extractor understood about one message or transaction group."""

    service: str
    kind: str = "charge"  # charge | renewal | trial | cancellation | price_change
    amount: Decimal | None = None
    currency: str | None = None
    period: Period | None = None
    charge_date: date | None = None
    next_charge: date | None = None
    trial_until: date | None = None
    old_amount: Decimal | None = None
    category: str | None = None
    cancel_url: str | None = None
    plan: str | None = None
    confidence: float = 0.0
    source: str = "manual"
    source_ref: str | None = None
    source_account: str | None = None
    sender: str | None = None
    snippet: str | None = None
    reasons: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    known_service: bool = False
    received: date | None = None
