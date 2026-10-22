"""Rule based extraction: one email in, at most one Detection out.

Cheap to expensive: the dictionary of known services and keyword lists
decide whether a message is about a subscription at all, regexes pull the
amount, period and dates, and the confidence score says how sure we are.
The optional AI layer (see ai.py) only looks at what this module could not
handle.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from datetime import date

from .. import clock
from ..config.schema import Config
from ..models import Detection, RawMessage, service_key
from ..period import Period
from .keywords import Keywords
from .merchants import MerchantBook, MerchantMatch, guess_name_from_sender
from .patterns import AmountHit, date_after_phrase, find_dates, find_period, pick_amount
from .text import message_text


@dataclass
class Learned:
    """Decisions remembered from the review queue and manual edits."""

    ignore_services: set[str] = field(default_factory=set)
    ignore_senders: set[str] = field(default_factory=set)
    accept_services: set[str] = field(default_factory=set)
    aliases: dict[str, str] = field(default_factory=dict)
    categories: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_store(cls, store) -> "Learned":
        out = cls()
        for row in store.rules():
            kind, pattern, value = row["kind"], row["pattern"], row["value"]
            if kind == "ignore_service":
                out.ignore_services.add(pattern)
            elif kind == "ignore_sender":
                out.ignore_senders.add(pattern)
            elif kind == "accept_service":
                out.accept_services.add(pattern)
            elif kind == "alias" and value:
                out.aliases[pattern] = value
            elif kind == "category" and value:
                out.categories[pattern] = value
        return out


@dataclass
class Context:
    config: Config
    book: MerchantBook
    keywords: Keywords
    learned: Learned = field(default_factory=Learned)

    @classmethod
    def build(cls, config: Config, book: MerchantBook, learned: Learned | None = None) -> "Context":
        kw = Keywords(config.extraction.languages, config.extraction.extra_keywords)
        return cls(config, book, kw, learned or Learned())


@dataclass
class Analysis:
    detection: Detection | None
    signals: bool
    text: str
    skipped: str | None = None


def glob_match(pattern: str, value: str) -> bool:
    return fnmatch.fnmatch(value.casefold(), pattern.casefold())


def sender_excluded(sender: str, ctx: Context) -> bool:
    sender = (sender or "").lower()
    domain = sender.rpartition("@")[2]
    patterns = list(ctx.config.filters.exclude_senders) + list(ctx.learned.ignore_senders)
    return any(glob_match(pat, sender) or glob_match(pat, domain) for pat in patterns)


def service_excluded(service: str, ctx: Context) -> bool:
    key = service_key(service)
    if key in ctx.learned.ignore_services:
        return True
    return any(service_key(s) == key for s in ctx.config.filters.exclude_services)


def _looks_english(text: str) -> bool:
    latin = len(re.findall(r"[A-Za-z]", text))
    cyr = len(re.findall(r"[\u0400-\u04FF]", text))
    return latin > cyr * 2


def _snippet(text: str, hit: AmountHit | None, chars: int) -> str:
    from .redact import redact

    if hit is None:
        piece = text[:chars]
    else:
        start = max(0, hit.start - chars // 2)
        piece = text[start: start + chars]
    return redact(piece).strip()


def analyse(msg: RawMessage, ctx: Context) -> Analysis:
    text = message_text(msg)
    subject = msg.subject or ""
    if sender_excluded(msg.sender, ctx):
        return Analysis(None, False, text, skipped="sender")
    subject_cf = subject.casefold()
    if any(k.casefold() in subject_cf for k in ctx.config.filters.exclude_keywords):
        return Analysis(None, False, text, skipped="keyword")

    kw = ctx.keywords
    full = subject + "\n" + text
    cf = full.casefold()
    text_cf = text.casefold()

    match: MerchantMatch | None = ctx.book.match_message(msg.sender, subject, text)
    sub_subject = kw.any(subject_cf, "subscription")
    sub_body = kw.any(text_cf, "subscription")
    is_cancel = kw.any(cf, "cancellation")
    is_trial = kw.any(cf, "trial")
    is_price = kw.any(cf, "price_change")
    is_renewal = kw.any(cf, "renewal")
    is_paid = kw.any(cf, "paid")
    negative = kw.any(cf, "negative")
    lifecycle = is_cancel or is_trial or is_price or is_renewal or is_paid

    signals = bool(match) or sub_subject or (sub_body and lifecycle)
    if not signals:
        return Analysis(None, False, text)

    reasons: list[str] = []
    if is_cancel:
        kind = "cancellation"
    elif is_price:
        kind = "price_change"
    elif is_trial and not is_paid:
        kind = "trial"
    elif is_renewal and not is_paid:
        kind = "renewal"
    else:
        kind = "charge"

    prefer = [h.end for h in kw.find(cf, "price_new")] if kind == "price_change" else None
    amount = pick_amount(full, kw, prefer_after=prefer)
    old_amount = None
    if kind == "price_change" and amount is not None:
        from .patterns import find_amounts

        others = [h for h in find_amounts(full) if h.amount != amount.amount and h.currency == amount.currency]
        if others:
            old_amount = others[0].amount

    if amount is None and not (is_cancel or is_trial or (match and lifecycle)):
        # Mentions a service or the word "subscription" but nothing we can use.
        return Analysis(None, True, text)

    reference = (clock.to_local(msg.date).date() if msg.date else clock.today())
    english = _looks_english(full)
    explicit_period = find_period(cf, kw, near=amount.start if amount else None)
    period = explicit_period
    if period is None and match and match.merchant.period:
        period = match.merchant.period

    next_charge = date_after_phrase(full, cf, kw, "next_date", reference, english_numeric=english)
    trial_until = None
    if is_trial:
        trial_until = date_after_phrase(full, cf, kw, "trial_end", reference, english_numeric=english)
        if trial_until is None:
            future = [d.value for d in find_dates(full, reference, english) if d.value > reference]
            trial_until = future[0] if future else None
    if next_charge is None and kind in ("renewal", "price_change"):
        future = [d.value for d in find_dates(full, reference, english) if d.value >= reference]
        next_charge = future[0] if future else None

    if match:
        service = match.merchant.name
        category = match.merchant.category
        cancel_url = match.merchant.cancel_url
    else:
        service = guess_name_from_sender(msg.sender_name, msg.sender)
        category = None
        cancel_url = None
    service = ctx.learned.aliases.get(service_key(service), service)
    if not service:
        return Analysis(None, True, text)

    # Confidence.
    score = 0.0
    if match:
        m = match.merchant
        if match.sender_hit and not (m.shared or m.generic):
            score += 0.35
            reasons.append("sender")
        elif match.subject_hit:
            score += 0.25
            reasons.append("subject")
        elif match.sender_hit and match.body_hit:
            score += 0.2
            reasons.append("sender+body")
        elif match.body_hit:
            score += 0.1
            reasons.append("body")
        if m.generic:
            score -= 0.05
    if sub_subject:
        score += 0.2
        reasons.append("keyword_subject")
    elif sub_body:
        score += 0.1
        reasons.append("keyword_body")
    if lifecycle:
        # A cancellation notice says nothing about money but is unambiguous.
        score += 0.2 if kind == "cancellation" else 0.1
        reasons.append("lifecycle")
    if amount is not None:
        score += 0.2
        reasons.append("amount")
    if explicit_period is not None:
        score += 0.1
        reasons.append("period")
    elif period is not None:
        score += 0.03
    if next_charge is not None:
        score += 0.05
        reasons.append("next_date")
    if negative:
        score -= 0.3
        reasons.append("negative")
    if msg.headers.get("List-Unsubscribe") and not (is_paid or is_renewal):
        score -= 0.05
    score = max(0.0, min(1.0, round(score, 3)))

    snippet = None
    if ctx.config.extraction.store_snippets:
        snippet = _snippet(text, amount, ctx.config.extraction.snippet_chars)

    detection = Detection(
        service=service,
        kind=kind,
        amount=amount.amount if amount else None,
        currency=amount.currency if amount else None,
        period=period,
        charge_date=reference if kind == "charge" and amount is not None else None,
        next_charge=next_charge,
        trial_until=trial_until,
        old_amount=old_amount,
        category=category,
        cancel_url=cancel_url,
        confidence=score,
        source=msg.source,
        source_ref=msg.key,
        source_account=msg.account,
        sender=msg.sender or None,
        snippet=snippet,
        reasons=reasons,
        known_service=bool(match and not match.merchant.generic),
        received=reference,
    )
    return Analysis(detection, True, text)


def detection_period(det: Detection) -> Period:
    return det.period or Period("month", 1)


def infer_next_charge(det: Detection, today: date | None = None) -> date | None:
    today = today or clock.today()
    if det.next_charge:
        return det.next_charge
    if det.trial_until:
        return det.trial_until
    if det.charge_date:
        period = detection_period(det)
        return period.next_after(period.advance(det.charge_date), today)
    return None
