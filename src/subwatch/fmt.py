"""Locale-aware formatting of numbers, money, dates and periods.

Separators, month names and phrases come from the catalog, so the output
follows ui.language without touching the system locale.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from . import clock
from .i18n import t, tget, tn
from .money import currency_decimals, currency_symbol, quantize, to_decimal
from .period import Period


def format_number(value: Decimal | int | float | str, decimals: int = 2) -> str:
    amount = quantize(to_decimal(value), decimals)
    negative = amount < 0
    amount = abs(amount)
    text = f"{amount:.{decimals}f}"
    whole, _, frac = text.partition(".")
    group = t("fmt.group_separator")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    out = group.join(groups)
    if decimals > 0:
        out += t("fmt.decimal_separator") + frac
    return ("-" if negative else "") + out


def format_money(
    amount: Decimal | int | float | str | None,
    currency: str | None,
    decimals: int | None = None,
    compact: bool = False,
) -> str:
    """1299 KZT -> "1 299,00 ₸" (ru) or "₸1,299.00" (en)."""
    if amount is None:
        return t("fmt.unknown_amount")
    value = to_decimal(amount)
    places = currency_decimals(currency or "") if decimals is None else decimals
    if compact and value == value.to_integral_value():
        places = 0
    return t(
        "fmt.money",
        amount=format_number(value, places),
        symbol=currency_symbol(currency or ""),
        code=(currency or "").upper(),
    )


def month_name(month: int, form: str = "genitive") -> str:
    names = tget(f"fmt.months.{form}") or tget("fmt.months.genitive")
    return str(names[month - 1])


def weekday_name(d: date, short: bool = False) -> str:
    names = tget("fmt.weekdays.short" if short else "fmt.weekdays.full")
    return str(names[d.weekday()])


def format_date(d: date | datetime | None, year: str = "auto", weekday: bool = False) -> str:
    """Day and month, plus the year when it is not the current one.
    year: auto | always | never."""
    if d is None:
        return t("fmt.no_date")
    if isinstance(d, datetime):
        d = clock.to_local(d).date()
    show_year = year == "always" or (year == "auto" and d.year != clock.today().year)
    key = "fmt.date_year" if show_year else "fmt.date"
    text = t(key, day=d.day, month=month_name(d.month), year=d.year)
    if weekday:
        text = t("fmt.date_weekday", weekday=weekday_name(d), date=text)
    return text


def format_short_date(d: date) -> str:
    return t("fmt.date_short", day=d.day, month=month_name(d.month, "short"))


def format_time(value: datetime) -> str:
    return clock.to_local(value).strftime("%H:%M")


def format_datetime(value: datetime) -> str:
    return t("fmt.datetime", date=format_date(value), time=format_time(value))


def days_until(d: date, today: date | None = None) -> int:
    return (d - (today or clock.today())).days


def format_relative_days(n: int) -> str:
    if n == 0:
        return t("fmt.rel.today")
    if n == 1:
        return t("fmt.rel.tomorrow")
    if n == -1:
        return t("fmt.rel.yesterday")
    if n > 0:
        return tn("fmt.rel.in_days", n)
    return tn("fmt.rel.days_ago", -n)


def format_when(d: date | None, style: str = "both") -> str:
    """Date for lists: absolute, relative or both, per ui.date_style."""
    if d is None:
        return t("fmt.no_date")
    rel = format_relative_days(days_until(d))
    if style == "relative":
        return rel
    if style == "absolute":
        return format_date(d)
    return t("fmt.when", date=format_date(d), relative=rel)


def format_period(period: Period | str | None) -> str:
    if period is None:
        return t("fmt.no_period")
    p = Period.parse(period)
    if p.count == 1:
        return t(f"fmt.period.every_1_{p.unit}")
    if p.unit == "month" and p.count == 3:
        return t("fmt.period.quarterly")
    return tn(f"fmt.period.every_n_{p.unit}", p.count)


def format_period_short(period: Period | str) -> str:
    p = Period.parse(period)
    if p.count == 1:
        return t(f"fmt.period.short_{p.unit}")
    return t("fmt.period.short_n", n=p.count, unit=t(f"fmt.period.short_{p.unit}"))


def format_duration(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds % 86400 == 0 and seconds >= 86400:
        return tn("fmt.units.day", seconds // 86400)
    if seconds % 3600 == 0 and seconds >= 3600:
        return tn("fmt.units.hour", seconds // 3600)
    return tn("fmt.units.minute", max(1, seconds // 60))


def format_percent(value: float | Decimal, decimals: int = 0) -> str:
    return t("fmt.percent", value=format_number(Decimal(str(value)), decimals))


def plural_count(key: str, n: int) -> str:
    return tn(key, n)
