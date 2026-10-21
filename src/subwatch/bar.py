"""Output for status bars (Omarchy shell `command` modules and Waybar).

Prints Waybar-style JSON: {"text", "tooltip", "class", "alt", "percentage"}.
The Omarchy bar highlights a module whose class contains "active", so the
"over-budget" state adds it to change the colour there too.

The result is cached (see barcache.py) and reused while the database, config
and date stay the same.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import clock
from .analysis import budget_status, over_budget, totals, upcoming
from .config.schema import Config
from .fmt import format_date, format_money, format_relative_days
from .i18n import t, tn

from .barcache import invalidate as invalidate_cache  # noqa: E402,F401
from .barcache import read as read_cache  # noqa: E402,F401
from .barcache import write as write_cache  # noqa: E402,F401


def bar_data(subs, config: Config, rates, review_count: int = 0, today: date | None = None) -> dict[str, Any]:
    today = today or clock.today()
    cfg = config.bar
    tot = totals(subs, rates, config)
    statuses = budget_status(tot, config)
    soon = upcoming(subs, max(cfg.next_within_days, 31), today)
    total_text = format_money(tot.monthly, config.currency.base, decimals=0)
    classes = ["subwatch"]
    if tot.count == 0:
        classes.append("empty")
    level = "ok"
    if over_budget(statuses):
        classes += ["over-budget", "active"]
        level = "over"
    elif any(s.level == "warn" for s in statuses):
        classes.append("warn-budget")
        level = "warn"

    nearest = soon[0] if soon else None
    show_next = cfg.mode == "next" or (
        cfg.mode == "auto" and nearest is not None
        and (nearest.next_charge - today).days <= cfg.next_within_days  # type: ignore[operator]
    )
    if show_next and nearest is not None:
        days = (nearest.next_charge - today).days  # type: ignore[operator]
        text = t("bar.text_next", icon=cfg.icon, service=nearest.service,
                 when=format_relative_days(days))
        classes.append("next")
        if days <= 1:
            classes.append("soon")
    elif tot.count == 0:
        text = "" if cfg.hide_when_empty else t("bar.text_empty", icon=cfg.icon)
    else:
        text = t("bar.text_total", icon=cfg.icon, total=total_text)

    lines = [t("bar.tip_total", total=format_money(tot.monthly, config.currency.base),
               count=tn("fmt.units.subscription", tot.count))]
    for st in statuses:
        name = t("bar.tip_budget_total") if st.scope == "total" else config.category_name(st.scope)
        lines.append(t(f"bar.tip_budget_{st.level}", name=name,
                       spent=format_money(st.spent, config.currency.base, decimals=0),
                       limit=format_money(st.limit, config.currency.base, decimals=0)))
    if soon:
        lines.append("")
        lines.append(t("bar.tip_upcoming"))
        for sub in soon[: cfg.tooltip_items]:
            days = (sub.next_charge - today).days  # type: ignore[operator]
            lines.append(t("bar.tip_item", date=format_date(sub.next_charge), service=sub.service,
                           amount=format_money(sub.amount, sub.currency) if sub.amount is not None else "",
                           relative=format_relative_days(days)))
    if review_count:
        lines.append("")
        lines.append(t("bar.tip_review", count=tn("fmt.units.item", review_count)))
    lines.append("")
    lines.append(t("bar.tip_hint"))
    pct = 0
    for st in statuses:
        if st.scope == "total":
            pct = min(100, int(st.pct))
    return {"text": text, "tooltip": "\n".join(lines), "class": classes, "alt": level,
            "percentage": pct}
