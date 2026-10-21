"""Text charts for the TUI: spend by month and by category, budgets."""

from __future__ import annotations

from decimal import Decimal

from rich.markup import escape

from ..config.schema import Config
from ..fmt import format_money, month_name
from ..i18n import t

BLOCKS = " ▏▎▍▌▋▊▉█"


def _bar(value: Decimal, peak: Decimal, width: int) -> str:
    if peak <= 0 or value <= 0:
        return ""
    cells = float(value / peak) * width
    full = int(cells)
    rest = int((cells - full) * 8)
    return "█" * full + (BLOCKS[rest] if rest and full < width else "")


def monthly(history, config: Config, width: int = 40) -> str:
    base = config.currency.base
    peak = max((v for _, v, _, _ in history), default=Decimal(0))
    lines = [f"[b]{escape(t('tui.charts.by_month'))}[/b]", ""]
    if not history or peak == 0:
        lines.append(escape(t("tui.charts.empty")))
        return "\n".join(lines)
    for month, value, forecast, _ in history:
        label = f"{month_name(month.month, 'short')} {str(month.year)[2:]}"
        color = "$secondary" if forecast else "$primary"
        amount = format_money(value, base, decimals=0)
        lines.append(f"{label:>7} [{color}]{_bar(value, peak, width)}[/] {escape(amount)}"
                     + (f" [dim]{escape(t('tui.charts.forecast'))}[/]" if forecast else ""))
    return "\n".join(lines)


def by_category(totals_by_cat: dict[str, Decimal], config: Config, width: int = 30) -> str:
    base = config.currency.base
    lines = [f"[b]{escape(t('tui.charts.by_category'))}[/b]", ""]
    if not totals_by_cat:
        lines.append(escape(t("tui.charts.empty")))
        return "\n".join(lines)
    peak = max(totals_by_cat.values())
    total = sum(totals_by_cat.values(), Decimal(0))
    name_w = max(len(config.category_name(k)) for k in totals_by_cat) + 2
    for key, value in sorted(totals_by_cat.items(), key=lambda kv: kv[1], reverse=True):
        name = f"{config.category_icon(key)} {config.category_name(key)}"
        share = round(float(value / total * 100)) if total else 0
        lines.append(f"{escape(name):<{name_w + 2}} [$accent]{_bar(value, peak, width)}[/] "
                     f"{escape(format_money(value, base, decimals=0))} [dim]{share}%[/]")
    return "\n".join(lines)


def budgets(statuses, config: Config, width: int = 30) -> str:
    base = config.currency.base
    lines = [f"[b]{escape(t('tui.charts.budgets'))}[/b]", ""]
    if not statuses:
        lines.append(escape(t("tui.charts.no_budgets")))
        return "\n".join(lines)
    for st in statuses:
        name = t("bar.tip_budget_total") if st.scope == "total" else config.category_name(st.scope)
        color = {"ok": "$success", "warn": "$warning", "over": "$error"}[st.level]
        filled = min(width, int(st.pct / 100 * width))
        gauge = "█" * filled + "░" * (width - filled)
        lines.append(f"{escape(name):<16} [{color}]{gauge}[/] {escape(format_money(st.spent, base, 0))} / "
                     f"{escape(format_money(st.limit, base, 0))} ({round(st.pct)}%)")
    return "\n".join(lines)
