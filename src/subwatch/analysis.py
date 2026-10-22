"""Totals, budgets and change detection (price, duplicates, zombies)."""

from __future__ import annotations

import difflib
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from . import clock
from .config.schema import Config
from .db import Store
from .extract.merchants import MerchantBook
from .fx import Rates
from .models import Subscription, service_key
from .period import add_months, iter_months, month_start


@dataclass
class Totals:
    monthly: Decimal = Decimal(0)
    yearly: Decimal = Decimal(0)
    by_category: dict[str, Decimal] = field(default_factory=dict)
    unconverted: list[Subscription] = field(default_factory=list)
    count: int = 0


def counted(subs: list[Subscription], config: Config) -> list[Subscription]:
    statuses = {"active"} | ({"review"} if config.budget.include_review else set())
    return [s for s in subs if s.status in statuses]


def totals(subs: list[Subscription], rates: Rates, config: Config) -> Totals:
    out = Totals()
    for sub in counted(subs, config):
        out.count += 1
        monthly = sub.monthly_amount
        if monthly is None:
            continue
        value = rates.convert(monthly, sub.currency)
        if value is None:
            out.unconverted.append(sub)
            continue
        out.monthly += value
        out.by_category[sub.category] = out.by_category.get(sub.category, Decimal(0)) + value
    out.monthly = out.monthly.quantize(Decimal("0.01"))
    out.yearly = (out.monthly * 12).quantize(Decimal("0.01"))
    return out


@dataclass
class BudgetStatus:
    scope: str  # "total" or a category key
    limit: Decimal
    spent: Decimal
    level: str  # ok | warn | over

    @property
    def pct(self) -> float:
        return float(self.spent / self.limit * 100) if self.limit else 0.0


def budget_status(tot: Totals, config: Config) -> list[BudgetStatus]:
    out = []
    warn = Decimal(config.budget.warn_at_pct) / 100

    def level(spent: Decimal, limit: Decimal) -> str:
        if spent > limit:
            return "over"
        if spent >= limit * warn:
            return "warn"
        return "ok"

    if config.budget.monthly_limit > 0:
        out.append(BudgetStatus("total", config.budget.monthly_limit, tot.monthly,
                                level(tot.monthly, config.budget.monthly_limit)))
    for key, cat in config.categories.items():
        if cat.budget > 0:
            spent = tot.by_category.get(key, Decimal(0))
            out.append(BudgetStatus(key, cat.budget, spent, level(spent, cat.budget)))
    return out


def over_budget(statuses: list[BudgetStatus]) -> bool:
    return any(s.level == "over" for s in statuses)


# ------------------------------------------------------------ duplicates


@dataclass
class Duplicate:
    a: Subscription
    b: Subscription
    reason: str  # same_service | similar_name | bundle

    @property
    def key(self) -> str:
        ids = sorted([self.a.id or 0, self.b.id or 0])
        return f"{ids[0]}-{ids[1]}"


def find_duplicates(subs: list[Subscription], config: Config, book: MerchantBook) -> list[Duplicate]:
    if not config.detection.duplicates:
        return []
    live = [s for s in subs if s.status in ("active", "review")]
    out: list[Duplicate] = []
    for i, a in enumerate(live):
        ka = service_key(a.service)
        partners = book.bundle_partners(a.service)
        for b in live[i + 1:]:
            kb = service_key(b.service)
            if ka == kb:
                out.append(Duplicate(a, b, "same_service"))
            elif kb in partners:
                # Put the bundle first: "b is already included in a".
                pair = (a, b) if book.includes(a.service, b.service) else (b, a)
                out.append(Duplicate(pair[0], pair[1], "bundle"))
            elif difflib.SequenceMatcher(None, ka, kb).ratio() >= config.detection.duplicate_similarity:
                out.append(Duplicate(a, b, "similar_name"))
    return out


def find_zombies(subs: list[Subscription], config: Config, today: date | None = None) -> list[Subscription]:
    if not config.detection.zombies:
        return []
    today = today or clock.today()
    limit = timedelta(days=config.detection.zombie_days)
    out = []
    for s in subs:
        if s.status != "active" or not s.track_usage:
            continue
        reference = s.last_used or (s.created_at.date() if s.created_at else today)
        if today - reference >= limit:
            out.append(s)
    return out


def recent_price_changes(subs: list[Subscription], days: int = 60,
                         today: date | None = None) -> list[Subscription]:
    today = today or clock.today()
    return [s for s in subs if s.price_changed_at and (today - s.price_changed_at).days <= days]


# ---------------------------------------------------------- monthly spend


def expected_dates(sub: Subscription, start: date, end: date) -> list[date]:
    """Charge dates of a subscription between start and end (inclusive)."""
    anchor = sub.next_charge or sub.last_charge
    if anchor is None:
        return []
    out = []
    current = anchor
    guard = 0
    while current > start and guard < 2000:
        prev = _step_back(sub, current)
        if prev >= current:
            break
        current = prev
        guard += 1
    guard = 0
    while current <= end and guard < 2000:
        if current >= start:
            out.append(current)
        current = sub.period.advance(current, 1, sub.anchor_day)
        guard += 1
    return out


def _step_back(sub: Subscription, d: date) -> date:
    p = sub.period
    if p.unit == "day":
        return d - timedelta(days=p.count)
    if p.unit == "week":
        return d - timedelta(weeks=p.count)
    months = p.count * (12 if p.unit == "year" else 1)
    return add_months(d, -months, sub.anchor_day)


def monthly_spend(store: Store, subs: list[Subscription], rates: Rates, config: Config,
                  months_back: int = 11, months_ahead: int = 0) -> list[tuple[date, Decimal, bool, dict[str, Decimal]]]:
    """[(month, total in base, is_forecast, by_category)].

    Real charges are used where we have them; months without a recorded charge
    use the expected charge dates of subscriptions that were active then.
    """
    today = clock.today()
    first = add_months(month_start(today), -months_back)
    last_month = add_months(month_start(today), months_ahead)
    end = add_months(last_month, 1) - timedelta(days=1)
    charges = store.charges(since=first)
    by_sub_month: dict[tuple[int, date], list] = defaultdict(list)
    for c in charges:
        by_sub_month[(c.subscription_id, month_start(c.date))].append(c)
    result: dict[date, dict[str, Decimal]] = {m: defaultdict(Decimal) for m in iter_months(first, end)}
    for sub in subs:
        if sub.status not in ("active", "cancelled", "paused"):
            continue
        created = sub.created_at.date() if sub.created_at else first
        started = min(created, sub.last_charge or created)
        stopped = sub.cancelled_at.date() if sub.cancelled_at else None
        for month in result:
            recorded = by_sub_month.get((sub.id or 0, month))
            if recorded:
                for c in recorded:
                    value = rates.convert(c.amount, c.currency)
                    if value is not None:
                        result[month][sub.category] += value
                continue
            if sub.amount is None or sub.status == "paused":
                continue
            month_end = add_months(month, 1) - timedelta(days=1)
            for d in expected_dates(sub, month, month_end):
                if d < started or (stopped and d > stopped):
                    continue
                value = rates.convert(sub.amount, sub.currency)
                if value is not None:
                    result[month][sub.category] += value
    out = []
    for month in sorted(result):
        cats = {k: v.quantize(Decimal("0.01")) for k, v in result[month].items() if v}
        out.append((month, sum(cats.values(), Decimal(0)), month > month_start(today), cats))
    return out


def upcoming(subs: list[Subscription], days: int, today: date | None = None) -> list[Subscription]:
    today = today or clock.today()
    limit = today + timedelta(days=days)
    items = [s for s in subs if s.status == "active" and s.next_charge and today <= s.next_charge <= limit]
    items.sort(key=lambda s: (s.next_charge, s.service.casefold()))
    return items
