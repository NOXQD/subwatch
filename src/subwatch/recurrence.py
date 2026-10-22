"""Finding subscriptions in bank statements.

Debits are grouped by normalised merchant and currency. For every candidate
period (recurrence.periods, days) we look for the longest chain of debits
whose gaps match the period within the tolerance and whose amounts stay
within amount_tolerance_pct of the previous one. One lasting price step is
allowed — that is a price change, not a different subscription.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import pstdev

from . import clock
from .config.schema import Config
from .extract.merchants import MerchantBook, normalize_descriptor
from .models import Detection, Transaction, service_key
from .period import Period


@dataclass
class Chain:
    items: list[Transaction]
    period_days: int

    @property
    def gaps(self) -> list[int]:
        return [(b.date - a.date).days for a, b in zip(self.items, self.items[1:], strict=False)]


def tolerance_days(period: int, config: Config) -> int:
    rc = config.recurrence
    return max(1, min(rc.max_tolerance_days, round(period * rc.tolerance_pct / 100)))


def _similar(a: Decimal, b: Decimal, pct: float) -> bool:
    if a == b:
        return True
    base = max(abs(a), abs(b))
    return base > 0 and abs(a - b) / base * 100 <= Decimal(str(pct))


def _gap_ok(gap: int, period: int, tol: int) -> bool:
    if period in (28, 29, 30, 31):
        return 28 - tol <= gap <= 31 + tol
    return abs(gap - period) <= tol


def best_chain(items: list[Transaction], config: Config) -> Chain | None:
    rc = config.recurrence
    best: Chain | None = None
    for period in rc.periods:
        tol = tolerance_days(period, config)
        for i in range(len(items)):
            chain = [items[i]]
            steps = 0
            j = i + 1
            while j < len(items):
                last = chain[-1]
                candidates = [k for k in range(j, len(items))
                              if _gap_ok((items[k].date - last.date).days, period, tol)]
                if not candidates:
                    break
                k = min(candidates, key=lambda k: abs((items[k].date - last.date).days - period))
                nxt = items[k]
                if not _similar(nxt.amount, last.amount, rc.amount_tolerance_pct):
                    if steps >= 1:
                        break
                    steps += 1
                chain.append(nxt)
                j = k + 1
            needed = rc.min_occurrences_yearly if period >= 300 else rc.min_occurrences
            if len(chain) < needed:
                continue
            cand = Chain(chain, period)
            if best is None or (len(chain), -_spread(cand)) > (len(best.items), -_spread(best)):
                best = cand
    return best


def _spread(chain: Chain) -> float:
    gaps = chain.gaps
    return pstdev(gaps) if len(gaps) > 1 else 0.0


def detect_recurring(transactions: list[Transaction], config: Config, book: MerchantBook,
                     today: date | None = None) -> list[Detection]:
    today = today or clock.today()
    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    names: dict[str, tuple[str, object]] = {}
    for tx in transactions:
        if tx.amount <= 0:
            continue
        name, merchant = normalize_descriptor(tx.merchant, book)
        key = service_key(name)
        names.setdefault(key, (name, merchant))
        groups[(key, tx.currency)].append(tx)
    out: list[Detection] = []
    for (key, currency), items in groups.items():
        # One debit per day per merchant is enough for period detection.
        by_day: dict[date, Transaction] = {}
        for tx in sorted(items, key=lambda x: x.date):
            by_day.setdefault(tx.date, tx)
        series = list(by_day.values())
        if len(series) < 2:
            continue
        chain = best_chain(series, config)
        if chain is None:
            continue
        name, merchant = names[key]
        period = Period.from_days(chain.period_days)
        last = chain.items[-1]
        anchor = chain.items[0].date.day
        nxt = period.advance(last.date, 1, anchor)
        tol = tolerance_days(chain.period_days, config)
        if nxt + timedelta(days=tol + chain.period_days) < today:
            continue  # stopped long ago
        nxt = period.next_after(nxt, today, anchor)
        amounts = [tx.amount for tx in chain.items]
        old_amount = None
        step_date = None
        for i in range(len(amounts) - 1, 0, -1):
            if not _similar(amounts[i], amounts[i - 1], config.recurrence.amount_tolerance_pct):
                old_amount, step_date = amounts[i - 1], chain.items[i].date
                break
        extra = len(chain.items) - (config.recurrence.min_occurrences_yearly
                                    if chain.period_days >= 300 else config.recurrence.min_occurrences)
        confidence = 0.5 + 0.08 * extra
        if merchant is not None and not getattr(merchant, "generic", False):
            confidence += 0.2
        if len(set(amounts)) == 1:
            confidence += 0.1
        if _spread(chain) <= 1.5:
            confidence += 0.05
        out.append(Detection(
            service=name,
            kind="charge",
            amount=last.amount,
            currency=currency,
            period=period,
            charge_date=last.date,
            next_charge=nxt,
            old_amount=old_amount,
            category=getattr(merchant, "category", None),
            cancel_url=getattr(merchant, "cancel_url", None),
            confidence=round(min(confidence, 0.95), 3),
            source="statement",
            source_ref=f"recurrence:{key}:{currency}",
            reasons=["recurrence", "period", "amount"],
            known_service=merchant is not None,
            extra={"history": [(tx.date, tx.amount) for tx in chain.items], "anchor_day": anchor,
                   "price_step_date": step_date},
        ))
    out.sort(key=lambda d: d.service.casefold())
    return out
