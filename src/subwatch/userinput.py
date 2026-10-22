"""Parsing what people type: dates, periods, amounts and categories.

Shared by the CLI, the TUI and the settings window."""

from __future__ import annotations

from datetime import date, timedelta

from . import clock
from .errors import SubwatchError
from .i18n import t


def parse_user_date(text: str) -> date:
    from .extract.patterns import find_dates

    s = text.strip()
    if s.startswith("+") and s[1:-1].isdigit() and s[-1] in "dwm":
        n = int(s[1:-1])
        if s[-1] == "d":
            return clock.today() + timedelta(days=n)
        if s[-1] == "w":
            return clock.today() + timedelta(weeks=n)
        from .period import add_months

        return add_months(clock.today(), n)
    aliases = {t("input.today"): 0, t("input.tomorrow"): 1}
    if s.casefold() in aliases:
        return clock.today() + timedelta(days=aliases[s.casefold()])
    hits = find_dates(s, clock.today(), english_numeric=False)
    if hits:
        return hits[0].value
    raise SubwatchError("cli.err.bad_date", hint="cli.hint.date_formats", value=text)


def parse_user_period(text: str):
    from .i18n import tget
    from .period import Period, PeriodError

    aliases = {str(k).casefold(): v for k, v in (tget("input.period") or {}).items()}
    s = text.strip().casefold()
    try:
        return Period.parse(aliases.get(s, s))
    except PeriodError:
        raise SubwatchError("cli.err.bad_period", hint="cli.hint.period_formats", value=text) from None


def parse_user_amount(text: str, default_currency: str):
    from .extract.patterns import find_amounts
    from .money import is_valid_code, parse_number, resolve_currency

    s = text.strip()
    hits = find_amounts(s)
    if hits:
        return hits[0].amount, hits[0].currency
    value = parse_number(s)
    if value is None:
        parts = s.rsplit(" ", 1)
        if len(parts) == 2:
            value = parse_number(parts[0])
            code = resolve_currency(parts[1]) or (parts[1].upper() if is_valid_code(parts[1].upper()) else None)
            if value is not None and code:
                return value, code
        raise SubwatchError("cli.err.bad_amount", hint="cli.hint.amount_formats", value=text)
    return value, default_currency


def parse_category(text: str, config) -> str:
    s = text.strip()
    if s in config.categories:
        return s
    for key, cat in config.categories.items():
        if cat.name.casefold() == s.casefold():
            return key
    raise SubwatchError("cli.err.bad_category", hint="cli.hint.categories", value=text,
                        known=", ".join(f"{k} ({c.name})" for k, c in config.categories.items()))
