"""Changes to subscriptions made by hand: from the TUI, the settings window
and the CLI. Each function saves, runs the hooks and refreshes the bar and
the calendar, so the callers only have to report the result.

Form values are what a person typed, as strings:
service, amount, currency, period, next, category, tags (comma separated),
cancel_url, notes, status, track_usage (bool), trial_until.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from . import clock
from .errors import SubwatchError
from .models import STATUSES, Subscription, service_key
from .userinput import parse_category, parse_user_amount, parse_user_date, parse_user_period

if TYPE_CHECKING:
    from .app import AppContext


def _text(values: dict[str, Any], key: str) -> str:
    value = values.get(key)
    return "" if value is None else str(value).strip()


def validate_values(ctx: AppContext, values: dict[str, Any]) -> None:
    if not _text(values, "service"):
        raise SubwatchError("cli.err.need_service")
    if _text(values, "amount"):
        parse_user_amount(_text(values, "amount"), _text(values, "currency").upper() or ctx.config.currency.base)
    parse_user_period(_text(values, "period") or "1m")
    for key in ("next", "trial_until"):
        if _text(values, key):
            parse_user_date(_text(values, key))
    if _text(values, "category"):
        parse_category(_text(values, "category"), ctx.config)
    status = _text(values, "status")
    if status and status not in STATUSES:
        raise SubwatchError("cli.err.bad_status", value=status, known=", ".join(STATUSES))


def apply_values(ctx: AppContext, sub: Subscription, values: dict[str, Any]) -> Subscription:
    """Copy form values onto a subscription. Keys that are absent stay as they are."""
    cfg = ctx.config
    validate_values(ctx, {**_current(sub), **values})
    before = sub.service if sub.id else ""
    if "service" in values:
        sub.service = _text(values, "service")
    if "amount" in values or "currency" in values:
        amount_text = _text(values, "amount") if "amount" in values else (
            str(sub.amount) if sub.amount is not None else "")
        currency = (_text(values, "currency") if "currency" in values else (sub.currency or "")).upper()
        if amount_text:
            # A currency typed with the amount ("9.99 USD") wins over the field.
            sub.amount, sub.currency = parse_user_amount(amount_text, currency or cfg.currency.base)
        else:
            sub.amount = None
            sub.currency = currency or None
    if "period" in values:
        sub.period = parse_user_period(_text(values, "period") or "1m")
    if "next" in values:
        sub.next_charge = parse_user_date(_text(values, "next")) if _text(values, "next") else None
        if sub.next_charge:
            sub.anchor_day = sub.next_charge.day
    if "trial_until" in values:
        sub.trial_until = parse_user_date(_text(values, "trial_until")) if _text(values, "trial_until") else None
    if "category" in values and _text(values, "category"):
        category = parse_category(_text(values, "category"), cfg)
        if category != sub.category and sub.id:
            ctx.store.add_rule("category", service_key(sub.service), category)
        sub.category = category
    if "tags" in values:
        raw = values["tags"]
        items = raw if isinstance(raw, list) else str(raw or "").split(",")
        sub.tags = [str(x).strip() for x in items if str(x).strip()]
    if "cancel_url" in values:
        sub.cancel_url = _text(values, "cancel_url") or None
    if "notes" in values:
        sub.notes = _text(values, "notes") or None
    if _text(values, "status"):
        status = _text(values, "status")
        if status == "cancelled" and sub.status != "cancelled":
            sub.cancelled_at = clock.now()
            sub.next_charge = None
        elif status != "cancelled":
            sub.cancelled_at = None
        sub.status = status
    if "track_usage" in values:
        track = bool(values["track_usage"])
        if track and not sub.track_usage:
            sub.last_used = sub.last_used or clock.today()
        sub.track_usage = track
    if before and service_key(before) != service_key(sub.service):
        ctx.store.add_rule("alias", service_key(before), sub.service)
    sub.key = sub.make_key()
    return sub


def _current(sub: Subscription) -> dict[str, Any]:
    return {
        "service": sub.service,
        "amount": str(sub.amount) if sub.amount is not None else "",
        "currency": sub.currency or "",
        "period": sub.period.code,
        "category": sub.category,
    }


def create(ctx: AppContext, values: dict[str, Any], via: str) -> Subscription:
    from .classify import assign_category
    from .extract.merchants import default_book
    from .hooks import run_hooks

    values = dict(values)
    known = default_book().find_service(_text(values, "service"))
    if known:
        values["service"] = known.name
        if not _text(values, "period") and known.period:
            values["period"] = known.period.code
        if not _text(values, "cancel_url") and known.cancel_url:
            values["cancel_url"] = known.cancel_url
    if not _text(values, "category"):
        values["category"] = assign_category(_text(values, "service"), ctx.config, ctx.learned(),
                                             suggested=known.category if known else None)
    sub = apply_values(ctx, Subscription(service=_text(values, "service"), source="manual", confidence=1.0),
                       values)
    existing = ctx.store.find_by_key(sub.key)
    if existing and existing.status != "cancelled":
        raise SubwatchError("cli.err.exists", hint="cli.hint.edit", service=sub.service, id=existing.id)
    if existing:
        sub.id = existing.id
        sub.created_at = existing.created_at
        ctx.store.update_subscription(sub)
    else:
        ctx.store.insert_subscription(sub)
    run_hooks(ctx.config, "new_subscription", sub, {"via": via})
    ctx.after_change()
    return sub


def update(ctx: AppContext, sub: Subscription, values: dict[str, Any]) -> Subscription:
    was_cancelled = sub.status == "cancelled"
    apply_values(ctx, sub, values)
    ctx.store.update_subscription(sub)
    if sub.status == "cancelled" and not was_cancelled:
        from .hooks import run_hooks

        run_hooks(ctx.config, "subscription_cancelled", sub, {"via": "edit"})
    ctx.after_change()
    return sub


def remove(ctx: AppContext, sub: Subscription) -> None:
    ctx.store.delete_subscription(sub.id or 0)
    ctx.after_change()


def cancel(ctx: AppContext, sub: Subscription, via: str, open_page: bool = True) -> bool:
    """Mark as cancelled; opens the cancellation page if there is one. Returns
    whether a page was opened."""
    from .hooks import run_hooks
    from .reminders import open_url

    opened = False
    if sub.cancel_url and open_page:
        open_url(sub.cancel_url)
        opened = True
    sub.status = "cancelled"
    sub.cancelled_at = clock.now()
    sub.next_charge = None
    ctx.store.update_subscription(sub)
    run_hooks(ctx.config, "subscription_cancelled", sub, {"via": via})
    ctx.after_change()
    return opened


def pause(ctx: AppContext, sub: Subscription) -> None:
    sub.status = "paused"
    ctx.store.update_subscription(sub)
    ctx.after_change()


def resume(ctx: AppContext, sub: Subscription) -> None:
    sub.status = "active"
    sub.cancelled_at = None
    if sub.next_charge is None and sub.last_charge:
        sub.next_charge = sub.period.next_after(sub.last_charge, clock.today(), sub.anchor_day)
    ctx.store.update_subscription(sub)
    ctx.after_change()


def mark_used(ctx: AppContext, sub: Subscription, when=None) -> None:
    sub.track_usage = True
    sub.last_used = when or clock.today()
    ctx.store.update_subscription(sub)
    ctx.after_change()


def decide(ctx: AppContext, sub: Subscription, accepted: bool) -> None:
    """Confirm or reject a finding from the review queue; the decision is
    remembered as a rule."""
    from .hooks import run_hooks
    from .ingest import remember_review_decision

    remember_review_decision(ctx.store, sub, accepted)
    if accepted:
        sub.status = "active"
        sub.review_reason = None
        sub.confidence = max(sub.confidence, ctx.config.extraction.auto_accept)
        ctx.store.update_subscription(sub)
        run_hooks(ctx.config, "new_subscription", sub, {"via": "review"})
    else:
        ctx.store.delete_subscription(sub.id or 0)
    ctx.after_change()
