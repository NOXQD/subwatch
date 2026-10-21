"""Rich renderables for CLI output. All labels come from the catalog."""

from __future__ import annotations

from decimal import Decimal

from rich.table import Table
from rich.text import Text

from .. import paths
from ..config.schema import Config
from ..fmt import format_date, format_money, format_period, format_relative_days, format_when
from ..fx import Rates
from ..i18n import t
from ..models import Subscription
from .common import console

STATUS_STYLE = {"active": "green", "review": "yellow", "paused": "blue", "cancelled": "dim"}
STEP_STYLE = {"changed": "green", "unchanged": "dim", "skipped": "yellow", "removed": "cyan",
              "failed": "bold red", "planned": "magenta"}
CHECK_MARK = {"ok": ("✓", "green"), "warn": ("!", "yellow"), "fail": ("✗", "bold red"), "info": ("·", "cyan")}


def money_or_dash(amount, currency, config: Config) -> str:
    if amount is None:
        return "—"
    return format_money(amount, currency, decimals=config.ui.money_decimals)


def subscriptions_table(subs: list[Subscription], config: Config, rates: Rates) -> Table:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False, expand=False)
    table.add_column(t("table.id"), justify="right", style="dim")
    table.add_column(t("table.service"))
    table.add_column(t("table.amount"), justify="right")
    table.add_column(t("table.period"))
    table.add_column(t("table.monthly"), justify="right")
    table.add_column(t("table.next"))
    table.add_column(t("table.category"))
    table.add_column(t("table.status"))
    for s in subs:
        monthly = rates.convert(s.monthly_amount, s.currency) if s.monthly_amount is not None else None
        monthly_text = format_money(monthly, config.currency.base, decimals=0) if monthly is not None else "—"
        status = Text(t(f"status.{s.status}"), style=STATUS_STYLE.get(s.status, ""))
        if s.is_trial:
            status.append(" " + t("status.trial_mark"), style="magenta")
        next_text = format_when(s.next_charge, config.ui.date_style) if s.next_charge else "—"
        table.add_row(str(s.id), Text(s.service), money_or_dash(s.amount, s.currency, config),
                      format_period(s.period), monthly_text, next_text,
                      config.category_name(s.category), status)
    return table


def subscription_details(sub: Subscription, config: Config, rates: Rates, charges=None) -> Table:
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold")
    table.add_column()
    monthly = rates.convert(sub.monthly_amount, sub.currency) if sub.monthly_amount is not None else None
    rows = [
        (t("details.service"), sub.service + (f" ({sub.plan})" if sub.plan else "")),
        (t("details.amount"), money_or_dash(sub.amount, sub.currency, config)),
        (t("details.period"), format_period(sub.period)),
        (t("details.monthly"), format_money(monthly, config.currency.base) if monthly is not None else "—"),
        (t("details.next"), format_when(sub.next_charge) if sub.next_charge else "—"),
        (t("details.last"), format_date(sub.last_charge) if sub.last_charge else "—"),
        (t("details.category"), config.category_name(sub.category)),
        (t("details.tags"), ", ".join(sub.tags) or "—"),
        (t("details.status"), t(f"status.{sub.status}")),
        (t("details.source"), t(f"source.{sub.source}") if not sub.source.startswith("plugin")
         else sub.source),
        (t("details.confidence"), f"{round(sub.confidence * 100)} %"),
    ]
    if sub.trial_until:
        rows.append((t("details.trial"), format_when(sub.trial_until)))
    if sub.previous_amount is not None:
        rows.append((t("details.price_change"), t("details.price_change_value",
                                                 old=money_or_dash(sub.previous_amount, sub.currency, config),
                                                 new=money_or_dash(sub.amount, sub.currency, config),
                                                 date=format_date(sub.price_changed_at))))
    if sub.cancel_url:
        rows.append((t("details.cancel_url"), sub.cancel_url))
    if sub.track_usage:
        rows.append((t("details.last_used"), format_date(sub.last_used) if sub.last_used else "—"))
    if sub.review_reason:
        rows.append((t("details.review_reason"), ", ".join(t(f"review.reason.{r}") for r in sub.review_reason.split(","))))
    if sub.notes:
        rows.append((t("details.notes"), sub.notes))
    if sub.snippet:
        rows.append((t("details.snippet"), sub.snippet))
    for k, v in rows:
        table.add_row(k, Text(str(v)))
    if charges:
        history = ", ".join(f"{format_date(c.date)} — {format_money(c.amount, c.currency)}" for c in charges[-6:])
        table.add_row(t("details.history"), Text(history))
    return table


def upcoming_table(subs: list[Subscription], config: Config) -> Table:
    from .. import clock

    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column(t("table.date"))
    table.add_column(t("table.when"))
    table.add_column(t("table.service"))
    table.add_column(t("table.amount"), justify="right")
    today = clock.today()
    for s in subs:
        days = (s.next_charge - today).days  # type: ignore[operator]
        style = "bold red" if days <= 1 else ("yellow" if days <= 3 else "")
        table.add_row(format_date(s.next_charge), Text(format_relative_days(days), style=style),
                      Text(s.service), money_or_dash(s.amount, s.currency, config))
    return table


def bar_line(value: Decimal, maximum: Decimal, width: int = 30) -> str:
    if maximum <= 0:
        return ""
    filled = int(round(float(value / maximum) * width))
    return "█" * filled + "░" * (width - filled)


def print_steps(steps) -> None:
    for step in steps:
        style = STEP_STYLE.get(step.status, "")
        label = t(f"integrate.status.{step.status}")
        where = f" ({paths.contract_home(step.path)})" if step.path else ""
        line = Text()
        line.append(f"{label:<12}", style=style)
        line.append(f"{step.name:<11}", style="bold")
        line.append(t(step.key, **step.params) + where)
        console.print(line)


def print_checks(checks) -> None:
    group = None
    for c in checks:
        if c.group != group:
            group = c.group
            console.print(Text(t(f"doctor.group.{group}"), style="bold underline"))
        mark, style = CHECK_MARK[c.status]
        line = Text("  ")
        line.append(mark + " ", style=style)
        line.append(t(c.key, **c.params))
        console.print(line)
        if c.hint and c.status in ("warn", "fail", "info"):
            console.print(Text("    → " + t(c.hint, **c.params), style="dim"))
