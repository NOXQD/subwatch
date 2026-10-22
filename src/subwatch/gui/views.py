"""What the Omarchy widget and the settings window show, already formatted.

The QML side only lays things out: every amount, date, plural and label is
rendered here, in the current language, so the shell never has to know how
Russian counts days.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from .. import clock
from ..analysis import (
    budget_status,
    find_duplicates,
    find_zombies,
    monthly_spend,
    recent_price_changes,
    totals,
    upcoming,
)
from ..fmt import (
    format_date,
    format_money,
    format_percent,
    format_period,
    format_relative_days,
    format_when,
    month_name,
    weekday_name,
)
from ..i18n import get_language, t, tget, tn
from ..models import Subscription
from ..period import month_start

if TYPE_CHECKING:
    from ..app import AppContext

UPCOMING_DAYS = 30
HISTORY_MONTHS = 6
POPUP_ROWS = 5


WINDOW_PAGES = ("overview", "subscriptions", "review", "categories", "health")


def strings() -> dict[str, str]:
    """Static interface strings for the QML side, page titles included."""
    from .settings import page_ids

    table = tget("gui.ui") or {}
    out = {k: v for k, v in table.items() if isinstance(v, str)}
    for pid in (*WINDOW_PAGES, *page_ids()):
        out[f"page_{pid}"] = t(f"gui.page.{pid}.title")
        out[f"sub_{pid}"] = t(f"gui.page.{pid}.subtitle")
    return out


def _money(amount: Decimal | None, currency: str | None, decimals: int | None = None,
           compact: bool = False) -> str:
    if amount is None:
        return "—"
    return format_money(amount, currency, decimals=decimals, compact=compact)


def _float(value: Decimal | None) -> float:
    return float(value) if value is not None else 0.0


def _days(d: date | None, today: date) -> int | None:
    return (d - today).days if d else None


def _category(ctx: AppContext, key: str | None) -> dict[str, str]:
    key = key or "other"
    return {"key": key, "name": ctx.config.category_name(key), "icon": ctx.config.category_icon(key)}


def subscription_row(ctx: AppContext, sub: Subscription, rates, today: date) -> dict[str, Any]:
    cfg = ctx.config
    base = cfg.currency.base
    monthly = rates.convert(sub.monthly_amount, sub.currency) if sub.monthly_amount is not None else None
    days = _days(sub.next_charge, today)
    status_text = t(f"status.{sub.status}")
    if sub.is_trial:
        status_text += " · " + t("status.trial_mark")
    return {
        "id": sub.id,
        "service": sub.service,
        "plan": sub.plan or "",
        "amount": _money(sub.amount, sub.currency, cfg.ui.money_decimals),
        "amount_raw": str(sub.amount) if sub.amount is not None else "",
        "currency": sub.currency or "",
        "monthly": _money(monthly, base, 0) if monthly is not None else "",
        "monthly_value": _float(monthly),
        "converted": bool(sub.currency and sub.currency != base and monthly is not None),
        "period": format_period(sub.period),
        "period_code": sub.period.code,
        "next": format_when(sub.next_charge, cfg.ui.date_style) if sub.next_charge else "",
        "next_date": format_date(sub.next_charge) if sub.next_charge else "",
        "next_raw": sub.next_charge.strftime("%d.%m.%Y") if sub.next_charge else "",
        "next_iso": sub.next_charge.isoformat() if sub.next_charge else "",
        "relative": format_relative_days(days) if days is not None else "",
        "days": days if days is not None else -1,
        "last": format_date(sub.last_charge) if sub.last_charge else "",
        "category": _category(ctx, sub.category),
        "tags": list(sub.tags),
        "status": sub.status,
        "status_text": status_text,
        "trial": sub.is_trial,
        "trial_until": sub.trial_until.strftime("%d.%m.%Y") if sub.trial_until else "",
        "trial_text": format_when(sub.trial_until) if sub.trial_until else "",
        "source": t(f"source.{sub.source}") if not sub.source.startswith("plugin") else sub.source,
        "sender": sub.sender or "",
        "confidence": round(sub.confidence * 100),
        "review_reason": t(f"review.reason.{sub.review_reason}") if sub.review_reason else "",
        "cancel_url": sub.cancel_url or "",
        "notes": sub.notes or "",
        "track_usage": sub.track_usage,
        "last_used": format_date(sub.last_used) if sub.last_used else "",
        "price_change": t("details.price_change_value",
                          old=_money(sub.previous_amount, sub.currency),
                          new=_money(sub.amount, sub.currency),
                          date=format_date(sub.price_changed_at)) if sub.previous_amount is not None else "",
        "search": " ".join([sub.service, sub.plan or "", cfg.category_name(sub.category), *sub.tags]).casefold(),
    }


def _upcoming_item(ctx: AppContext, sub: Subscription, rates, today: date) -> dict[str, Any]:
    base = ctx.config.currency.base
    days = (sub.next_charge - today).days  # type: ignore[operator]
    converted = None
    if sub.amount is not None and sub.currency and sub.currency != base:
        value = rates.convert(sub.amount, sub.currency)
        converted = _money(value, base, 0) if value is not None else None
    return {
        "id": sub.id,
        "service": sub.service,
        "day": sub.next_charge.day,  # type: ignore[union-attr]
        "month": month_name(sub.next_charge.month, "short"),  # type: ignore[union-attr]
        "weekday": weekday_name(sub.next_charge, short=True),  # type: ignore[arg-type]
        "date": format_date(sub.next_charge),
        "relative": format_relative_days(days),
        "days": days,
        "amount": _money(sub.amount, sub.currency, compact=True),
        "converted": converted or "",
        "category": _category(ctx, sub.category),
        "trial": bool(sub.trial_until and sub.trial_until >= today),
        "has_cancel_url": bool(sub.cancel_url),
    }


def _insights(ctx: AppContext, subs: list[Subscription], today: date) -> list[dict[str, str]]:
    cfg = ctx.config
    out: list[dict[str, str]] = []
    for sub in subs:
        if sub.status == "active" and sub.trial_until and 0 <= (sub.trial_until - today).days <= 7:
            out.append({"kind": "trial", "text": t("gui.insight.trial", service=sub.service,
                                                   when=format_relative_days((sub.trial_until - today).days))})
    for sub in recent_price_changes([s for s in subs if s.status == "active"], 45, today):
        if sub.previous_amount is None:
            continue
        out.append({"kind": "price", "text": t("gui.insight.price", service=sub.service,
                                               old=_money(sub.previous_amount, sub.currency),
                                               new=_money(sub.amount, sub.currency))})
    for dup in find_duplicates(subs, cfg, ctx.book)[:2]:
        out.append({"kind": "duplicate", "text": t("gui.insight.duplicate", first=dup.a.service,
                                                   second=dup.b.service)})
    for sub in find_zombies(subs, cfg, today)[:2]:
        idle = (today - (sub.last_used or today)).days
        out.append({"kind": "zombie", "text": t("gui.insight.zombie", service=sub.service,
                                                days=tn("fmt.units.day", idle))})
    return out[:4]


def dashboard(ctx: AppContext) -> dict[str, Any]:
    """Everything the bar widget and its popup show."""
    from ..bar import bar_data

    cfg = ctx.config
    base = cfg.currency.base
    today = clock.today()
    subs = ctx.store.subscriptions()
    rates = ctx.rates()
    tot = totals(subs, rates, cfg)
    statuses = budget_status(tot, cfg)
    review = [s for s in subs if s.status == "review"]
    soon = upcoming(subs, UPCOMING_DAYS, today)

    total_budget = next((s for s in statuses if s.scope == "total"), None)
    budget = None
    if total_budget is not None:
        left = total_budget.limit - total_budget.spent
        budget = {
            "fraction": min(1.0, total_budget.pct / 100),
            "pct": format_percent(total_budget.pct),
            "limit": _money(total_budget.limit, base, 0),
            "level": total_budget.level,
            "note": t("gui.budget.left", amount=_money(left, base, 0)) if left >= 0 else
            t("gui.budget.over", amount=_money(-left, base, 0)),
        }

    cat_budgets = {s.scope: s for s in statuses if s.scope != "total"}
    monthly_total = tot.monthly or Decimal(1)
    categories = []
    for key, value in sorted(tot.by_category.items(), key=lambda kv: -kv[1]):
        if not value:
            continue
        item = {**_category(ctx, key), "amount": _money(value, base, 0), "value": float(value),
                "share": float(value / monthly_total), "pct": format_percent(value / monthly_total * 100)}
        st = cat_budgets.get(key)
        if st is not None:
            item["budget"] = {"fraction": min(1.0, st.pct / 100), "level": st.level,
                              "limit": _money(st.limit, base, 0)}
        categories.append(item)

    history = []
    for month, total, _forecast, _cats in monthly_spend(ctx.store, subs, rates, cfg,
                                                        months_back=HISTORY_MONTHS - 1):
        history.append({"label": month_name(month.month, "short"), "value": float(total),
                        "amount": _money(total, base, 0), "current": month == month_start(today)})

    bar = bar_data(subs, cfg, rates, review_count=len(review), today=today)
    nearest = soon[0] if soon else None
    near_days = (nearest.next_charge - today).days if nearest else None  # type: ignore[operator]
    show_next = nearest is not None and (cfg.bar.mode == "next" or (
        cfg.bar.mode == "auto" and near_days is not None and near_days <= cfg.bar.next_within_days))
    if tot.count == 0:
        label, state = "", "empty"
    elif show_next and nearest is not None:
        label = t("gui.bar.next", service=nearest.service, when=format_relative_days(near_days or 0))
        state = "soon" if (near_days or 0) <= 1 else "next"
    else:
        label, state = _money(tot.monthly, base, 0), "total"
    level = "over" if "over-budget" in bar["class"] else ("warn" if "warn-budget" in bar["class"] else "ok")
    if budget is not None:
        ring = budget["fraction"]
    elif near_days is not None:
        ring = max(0.04, 1 - min(near_days, UPCOMING_DAYS) / UPCOMING_DAYS)
    else:
        ring = 0.0

    return {
        "version": 1,
        "language": get_language(),
        "generated": clock.now().isoformat(timespec="seconds"),
        "today": format_date(today, weekday=True),
        "strings": strings(),
        "base": base,
        "widget": {"label": label, "state": state, "level": level, "ring": ring,
                   "alert": state == "soon" or level == "over", "tooltip": bar["tooltip"],
                   "interval": cfg.bar.interval, "hide": tot.count == 0 and cfg.bar.hide_when_empty},
        "totals": {
            "monthly": _money(tot.monthly, base, 0),
            "yearly": _money(tot.yearly, base, 0),
            "daily": _money((tot.monthly / Decimal("30.4375")).quantize(Decimal("1")), base, 0),
            "count": tot.count,
            "count_text": tn("fmt.units.subscription", tot.count),
            "unconverted": [s.service for s in tot.unconverted],
        },
        "budget": budget,
        "upcoming": [_upcoming_item(ctx, s, rates, today) for s in soon],
        "upcoming_title": t("gui.upcoming_window", days=tn("fmt.units.day", UPCOMING_DAYS)),
        "upcoming_rows": POPUP_ROWS,
        "upcoming_more": tn("gui.more_upcoming", len(soon) - POPUP_ROWS) if len(soon) > POPUP_ROWS else "",
        "updated": t("gui.updated", time=clock.now().strftime("%H:%M")),
        "upcoming_sum": _money(sum((rates.convert(s.amount, s.currency) or Decimal(0)
                                    for s in soon if s.amount is not None), Decimal(0)), base, 0),
        "categories": categories,
        "history": history,
        "insights": _insights(ctx, subs, today),
        "review": {"count": len(review), "text": tn("gui.review_count", len(review)) if review else ""},
    }


def subscriptions(ctx: AppContext) -> dict[str, Any]:
    today = clock.today()
    rates = ctx.rates()
    subs = [s for s in ctx.store.subscriptions() if s.status != "review"]
    order = {"active": 0, "paused": 1, "cancelled": 2}
    subs.sort(key=lambda s: (order.get(s.status, 3), s.next_charge or date.max, s.service.casefold()))
    rows = [subscription_row(ctx, s, rates, today) for s in subs]
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ("active", "paused", "cancelled")}
    counts["trial"] = sum(1 for r in rows if r["trial"])
    counts["all"] = len(rows)
    return {"items": rows, "counts": counts, "form": form_options(ctx)}


def form_options(ctx: AppContext) -> dict[str, Any]:
    """Choices for the add/edit form."""
    from ..money import currency_symbol

    cfg = ctx.config
    codes = [cfg.currency.base, "USD", "EUR", "RUB", "KZT", "GBP", "TRY", "CNY", "UZS", "KGS"]
    seen: list[str] = []
    for code in codes + sorted(cfg.currency.manual_rates):
        if code not in seen:
            seen.append(code)
    periods = ["1w", "1m", "3m", "6m", "1y"]
    return {
        "categories": [{"value": "", "label": t("gui.form.auto_category")}]
        + [{"value": k, "label": (c.icon + "  " if c.icon else "") + c.name} for k, c in cfg.categories.items()],
        "currencies": [{"value": c, "label": f"{c}  {currency_symbol(c)}"} for c in seen],
        "periods": [{"value": p, "label": format_period(p)} for p in periods],
        "statuses": [{"value": s, "label": t(f"status.{s}")} for s in ("active", "paused", "cancelled")],
        "base": cfg.currency.base,
        "date_hint": t("gui.form.date_hint"),
        "amount_hint": t("gui.form.amount_hint"),
    }


def review(ctx: AppContext) -> dict[str, Any]:
    today = clock.today()
    rates = ctx.rates()
    rows = [subscription_row(ctx, s, rates, today) for s in ctx.store.review_queue()]
    return {"items": rows}


def categories(ctx: AppContext) -> dict[str, Any]:
    cfg = ctx.config
    base = cfg.currency.base
    subs = ctx.store.subscriptions()
    tot = totals(subs, ctx.rates(), cfg)
    counts: dict[str, int] = {}
    for s in subs:
        if s.status in ("active", "paused"):
            counts[s.category] = counts.get(s.category, 0) + 1
    items = []
    for key, cat in cfg.categories.items():
        spent = tot.by_category.get(key, Decimal(0))
        fraction = float(spent / cat.budget) if cat.budget else 0.0
        items.append({
            "key": key, "name": cat.name, "icon": cat.icon,
            "budget": format(cat.budget.normalize(), "f") if cat.budget else "",
            "spent": _money(spent, base, 0), "spent_value": float(spent),
            "fraction": min(1.0, fraction), "over": bool(cat.budget and spent > cat.budget),
            "count_text": tn("fmt.units.subscription", counts.get(key, 0)),
            "removable": key != "other",
        })
    return {"items": items, "base": base, "total": _money(tot.monthly, base, 0)}


def last_scan(ctx: AppContext) -> dict[str, Any]:
    import json
    from datetime import datetime

    raw = ctx.store.get_meta("last_scan")
    if not raw:
        return {"text": t("gui.sources.never"), "errors": 0}
    try:
        data = json.loads(raw)
        when = clock.to_local(datetime.fromisoformat(data["at"]))
    except (ValueError, KeyError, TypeError):
        return {"text": t("gui.sources.never"), "errors": 0}
    return {"text": t("gui.sources.last_scan", when=format_date(when.date()), time=when.strftime("%H:%M"),
                      found=tn("fmt.units.subscription", int(data.get("created", 0)))),
            "errors": int(data.get("errors", 0))}


def sources(ctx: AppContext) -> dict[str, Any]:
    """Connected mail accounts, the last scan and the timers."""
    from .. import secrets
    from ..integrate import systemd

    cfg = ctx.config
    accounts = []
    for acc in cfg.sources.imap.accounts:
        accounts.append({
            "name": acc.name, "host": acc.host, "username": acc.username,
            "folders": ", ".join(acc.folders), "enabled": acc.enabled,
            "connected": secrets.exists(secrets.imap_password_name(acc.name)),
        })
    enabled, active, nxt = systemd.timer_state("subwatch-scan.timer")
    return {
        "gmail": {"enabled": cfg.sources.gmail.enabled, "account": cfg.sources.gmail.account,
                  "connected": secrets.exists(secrets.gmail_token_name(cfg.sources.gmail.account))},
        "imap": accounts,
        "statements_dir": cfg.sources.statements.inbox_dir,
        "last_scan": last_scan(ctx),
        "timer": {"enabled": enabled, "active": active, "next": nxt or ""},
    }


def rates(ctx: AppContext) -> dict[str, Any]:
    cfg = ctx.config
    values, fetched, source = ctx.store.load_rates(cfg.currency.base)
    items = []
    for code in sorted(values):
        if code == cfg.currency.base:
            continue
        items.append({"code": code, "value": format_money(values[code], cfg.currency.base,
                                                           decimals=2 if values[code] < 100 else 0)})
    return {
        "base": cfg.currency.base,
        "source": source or "",
        "fetched": format_when(clock.to_local(fetched).date(), "both") if fetched else "",
        "items": items,
    }


def health(ctx: AppContext) -> dict[str, Any]:
    from ..doctor import run_checks

    groups: dict[str, list[dict[str, str]]] = {}
    order: list[str] = []
    for check in run_checks():
        if check.group not in groups:
            groups[check.group] = []
            order.append(check.group)
        groups[check.group].append({
            "status": check.status, "text": t(check.key, **check.params),
            "hint": t(check.hint, **check.params) if check.hint else "", "fixable": check.fix is not None,
        })
    worst = "ok"
    for items in groups.values():
        for item in items:
            if item["status"] == "fail":
                worst = "fail"
            elif item["status"] == "warn" and worst != "fail":
                worst = "warn"
    return {"groups": [{"title": t(f"doctor.group.{g}"), "items": groups[g]} for g in order],
            "worst": worst}


def history(ctx: AppContext, months: int = 12) -> list[dict[str, Any]]:
    cfg = ctx.config
    base = cfg.currency.base
    today = clock.today()
    subs = ctx.store.subscriptions()
    out = []
    for month, total, forecast, cats in monthly_spend(ctx.store, subs, ctx.rates(), cfg,
                                                      months_back=months - 2, months_ahead=1):
        out.append({"label": month_name(month.month, "short"), "value": float(total),
                    "amount": _money(total, base, 0), "current": month == month_start(today),
                    "forecast": forecast,
                    "categories": [{"key": k, "value": float(v)} for k, v in
                                   sorted(cats.items(), key=lambda kv: -kv[1])]})
    return out


def overview(ctx: AppContext) -> dict[str, Any]:
    data = dashboard(ctx)
    data["history_long"] = history(ctx)
    data["upcoming"] = data["upcoming"]
    year_ahead = clock.today() + timedelta(days=365)
    data["year_note"] = t("gui.overview.year_note", date=format_date(year_ahead))
    return data
