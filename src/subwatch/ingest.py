"""Applying detections to the database.

The same receipt seen twice must not create two charges, a cancellation must
not resurrect anything, and a low-confidence guess never overrides what the
user already confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from . import clock
from .config.schema import Config
from .db import Store
from .extract.engine import Learned, infer_next_charge, service_excluded
from .models import Charge, Detection, Subscription, service_key
from .period import Period


@dataclass
class Event:
    name: str
    subscription: Subscription | None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestResult:
    action: str
    subscription: Subscription | None = None
    events: list[Event] = field(default_factory=list)


def _status_for(det: Detection, config: Config, learned: Learned) -> str | None:
    key = service_key(det.service)
    if key in learned.accept_services and det.confidence >= config.extraction.review_threshold * 0.5:
        return "active"
    if det.confidence >= config.extraction.auto_accept:
        return "active"
    if det.confidence >= config.extraction.review_threshold:
        return "review"
    return None


def _review_reason(det: Detection) -> str:
    missing = []
    if det.amount is None:
        missing.append("amount")
    if det.period is None:
        missing.append("period")
    if not det.known_service:
        missing.append("unknown_service")
    return ",".join(missing) or "low_confidence"


class Ingestor:
    def __init__(self, store: Store, config: Config, learned: Learned | None = None):
        self.store = store
        self.config = config
        self.learned = learned or Learned.from_store(store)

    # ----------------------------------------------------------- matching

    def _existing(self, det: Detection) -> Subscription | None:
        key = service_key(det.service) + "|" + (det.currency or "").upper()
        if det.currency:
            found = self.store.find_by_key(key)
            if found:
                return found
        candidates = self.store.find_by_service(det.service)
        if not candidates:
            return None
        if det.currency:
            # Same service, the record has no currency yet (e.g. created from a
            # trial notice): adopt it.
            for sub in candidates:
                if not sub.currency:
                    return sub
            return None
        live = [s for s in candidates if s.status != "cancelled"]
        return (live or candidates)[0]

    # ------------------------------------------------------------- ingest

    def _add_history(self, sub: Subscription, det: Detection) -> None:
        for day, amount in det.extra.get("history", []):
            self.store.add_charge(Charge(sub.id or 0, day, amount, det.currency or sub.currency or "",
                                         det.source, det.source_ref))

    def ingest(self, det: Detection, category: str = "other", tags: list[str] | None = None) -> IngestResult:
        if service_excluded(det.service, self):  # type: ignore[arg-type]
            return IngestResult("ignored")
        status = _status_for(det, self.config, self.learned)
        existing = self._existing(det)
        today = clock.today()

        if det.kind == "cancellation":
            if status is None:
                return IngestResult("ignored")
            # A cancellation names the service, not a record: cancel every
            # live record of it (the same subscription may be seen in two
            # currencies, e.g. a receipt in USD and a bank debit in KZT).
            targets = [s for s in self.store.find_by_service(det.service) if s.status != "cancelled"]
            if not targets:
                return IngestResult("ignored")
            when = datetime.combine(det.received, time(12, 0), tzinfo=clock.local_tz()) \
                if det.received else clock.now()
            events = []
            for target in targets:
                target.status = "cancelled"
                target.cancelled_at = when
                target.next_charge = None
                self.store.update_subscription(target)
                events.append(Event("subscription_cancelled", target))
            return IngestResult("cancelled", targets[0], events)

        if status is None:
            return IngestResult("ignored")

        if existing is None:
            return self._create(det, status, category, tags or [], today)
        return self._update(existing, det, status, today)

    def _create(self, det: Detection, status: str, category: str, tags: list[str], today: date) -> IngestResult:
        period = det.period or Period("month", 1)
        sub = Subscription(
            service=det.service,
            amount=det.amount,
            currency=det.currency,
            period=period,
            category=category,
            tags=tags,
            status=status,
            confidence=det.confidence,
            source=det.source,
            source_account=det.source_account,
            sender=det.sender,
            cancel_url=det.cancel_url,
            plan=det.plan,
            snippet=det.snippet,
            trial_until=det.trial_until if det.kind == "trial" else None,
            review_reason=_review_reason(det) if status == "review" else None,
        )
        if det.charge_date:
            sub.last_charge = det.charge_date
            sub.anchor_day = det.charge_date.day
        sub.next_charge = infer_next_charge(det, today)
        if sub.next_charge and not sub.anchor_day and det.kind != "trial":
            sub.anchor_day = sub.next_charge.day
        if det.extra.get("anchor_day"):
            sub.anchor_day = int(det.extra["anchor_day"])
        events: list[Event] = []
        if det.kind == "charge" and det.old_amount is not None and det.amount is not None:
            sub.previous_amount = det.old_amount
            sub.price_changed_at = det.extra.get("price_step_date") or det.charge_date or today
        self.store.insert_subscription(sub)
        self._add_history(sub, det)
        if det.charge_date and det.amount is not None and det.currency:
            self.store.add_charge(Charge(sub.id or 0, det.charge_date, det.amount, det.currency,
                                         det.source, det.source_ref))
        if status == "active":
            events.append(Event("new_subscription", sub))
            if sub.previous_amount is not None:
                events.append(Event("price_changed", sub, {"old": str(sub.previous_amount),
                                                           "new": str(sub.amount)}))
        action = "created" if status == "active" else "review"
        return IngestResult(action, sub, events)

    def _update(self, sub: Subscription, det: Detection, status: str, today: date) -> IngestResult:
        events: list[Event] = []
        action = "updated"
        if sub.status == "cancelled":
            # Only a confident charge after the cancellation brings it back.
            reactivate = status == "active" and det.kind == "charge" and det.charge_date and (
                sub.cancelled_at is None or det.charge_date > sub.cancelled_at.date()
            )
            if not reactivate:
                return IngestResult("ignored", sub)
            sub.status = status
            sub.cancelled_at = None
            if status == "active":
                events.append(Event("new_subscription", sub))

        if det.currency and not sub.currency:
            sub.currency = det.currency
            sub.key = sub.make_key()

        # More evidence for the same service makes us more confident.
        was_review = sub.status == "review"
        if was_review:
            boosted = round(min(1.0, max(sub.confidence, det.confidence) + 0.1), 3)
            sub.confidence = boosted
            if status == "active" or boosted >= self.config.extraction.auto_accept:
                sub.status = "active"
                sub.review_reason = None
                events.append(Event("new_subscription", sub))
                action = "promoted"
        else:
            sub.confidence = max(sub.confidence, det.confidence)

        if det.period and (det.reasons and "period" in det.reasons):
            sub.period = det.period
        if det.cancel_url and not sub.cancel_url:
            sub.cancel_url = det.cancel_url
        if det.snippet and not sub.snippet:
            sub.snippet = det.snippet

        self._add_history(sub, det)
        old_amount = sub.amount
        new_amount = det.amount
        price_event = None
        if det.kind == "price_change" and new_amount is not None:
            base_old = det.old_amount if det.old_amount is not None else old_amount
            if base_old is not None and new_amount != base_old:
                price_event = (base_old, new_amount)
            sub.amount = new_amount
        elif det.kind == "charge" and det.charge_date and new_amount is not None:
            inserted = self.store.add_charge(
                Charge(sub.id or 0, det.charge_date, new_amount, det.currency or sub.currency or "",
                       det.source, det.source_ref)
            )
            is_latest = sub.last_charge is None or det.charge_date >= sub.last_charge
            if is_latest:
                if old_amount is not None and new_amount != old_amount:
                    price_event = (old_amount, new_amount)
                sub.amount = new_amount
                sub.last_charge = det.charge_date
                if sub.anchor_day is None:
                    sub.anchor_day = det.charge_date.day
            if not inserted and action == "updated":
                action = "duplicate"
        elif new_amount is not None and sub.amount is None:
            sub.amount = new_amount

        if det.kind == "trial" and det.trial_until:
            sub.trial_until = det.trial_until

        nxt = det.next_charge
        if nxt is None and sub.last_charge:
            nxt = sub.period.next_after(sub.period.advance(sub.last_charge, 1, sub.anchor_day), today,
                                        sub.anchor_day)
        if nxt is not None and (sub.next_charge is None or nxt >= today or sub.next_charge < today):
            sub.next_charge = nxt

        if price_event is not None:
            before, after = price_event
            change_pct = abs(after - before) / before * 100 if before else Decimal(100)
            if change_pct >= Decimal(str(self.config.detection.price_change_pct)):
                sub.previous_amount = before
                sub.price_changed_at = today
                events.append(Event("price_changed", sub, {"old": str(before), "new": str(after),
                                                           "change_pct": float(change_pct)}))
        self.store.update_subscription(sub)
        return IngestResult(action, sub, events)


def remember_review_decision(store: Store, sub: Subscription, accepted: bool) -> None:
    """Confirm/reject in the review queue becomes a rule for next time."""
    key = service_key(sub.service)
    if accepted:
        store.add_rule("accept_service", key, sub.service, origin="review")
    else:
        store.add_rule("ignore_service", key, sub.service, origin="review")
        if sub.sender and sub.source in ("gmail", "imap") and not _shared_sender(sub.sender):
            store.add_rule("ignore_sender", sub.sender.lower(), sub.service, origin="review")


def _shared_sender(sender: str) -> bool:
    domain = sender.rpartition("@")[2]
    return domain in {"gmail.com", "google.com", "apple.com", "yandex.ru", "mail.ru", "microsoft.com"}
