"""Regexes for amounts, currencies, billing periods and dates (ru, en, kk)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

from ..money import ISO_CODE_PATTERN, currency_token_pattern, is_known_currency, parse_number, resolve_currency
from ..period import Period
from .keywords import Keywords, month_alternation, month_number


@dataclass(frozen=True)
class AmountHit:
    amount: Decimal
    currency: str
    start: int
    end: int
    text: str


_NUM = r"(?<![\d.,])(?:\d{1,3}(?:[   .,'’]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)(?![\d])"


@lru_cache(maxsize=1)
def _amount_regexes() -> tuple[re.Pattern[str], ...]:
    tok = currency_token_pattern()
    return (
        re.compile(rf"(?P<cur>{tok})\s?(?P<num>{_NUM})", re.IGNORECASE),
        re.compile(rf"(?P<num>{_NUM})\s?(?P<cur>{tok})", re.IGNORECASE),
        re.compile(rf"(?P<iso>{ISO_CODE_PATTERN})\s?(?P<num>{_NUM})"),
        re.compile(rf"(?P<num>{_NUM})\s?(?P<iso>{ISO_CODE_PATTERN})"),
    )


def find_amounts(text: str) -> list[AmountHit]:
    hits: dict[tuple[int, int], AmountHit] = {}
    for rx in _amount_regexes():
        for m in rx.finditer(text):
            code = None
            if "iso" in rx.groupindex and m.group("iso"):
                iso = m.group("iso")
                code = iso if is_known_currency(iso) else None
            elif m.group("cur"):
                code = resolve_currency(m.group("cur"))
            if not code:
                continue
            value = parse_number(m.group("num"))
            if value is None or value <= 0 or value > Decimal("10000000"):
                continue
            span = m.span("num")
            if span in hits:
                continue
            hits[span] = AmountHit(value, code, m.start(), m.end(), m.group(0))
    return sorted(hits.values(), key=lambda h: h.start)


def pick_amount(text: str, kw: Keywords, prefer_after: list[int] | None = None) -> AmountHit | None:
    """Choose the amount that is most likely the price."""
    hits = find_amounts(text)
    if not hits:
        return None
    cf = text.casefold()
    labels = kw.find(cf, "amount_label")
    noise = kw.find(cf, "amount_noise")
    best: tuple[float, AmountHit] | None = None
    for index, hit in enumerate(hits):
        score = 0.0
        line_start = cf.rfind("\n", 0, hit.start) + 1
        line_end = cf.find("\n", hit.end)
        line_end = len(cf) if line_end < 0 else line_end
        for lab in labels:
            if line_start <= lab.pos <= hit.start or 0 <= hit.start - lab.end <= 40:
                score += 3
                break
        for nz in noise:
            if line_start <= nz.pos <= line_end:
                score -= 4
                break
        for pos in prefer_after or []:
            if 0 <= hit.start - pos <= 80:
                score += 4
                break
        score -= index * 0.01
        if best is None or score > best[0]:
            best = (score, hit)
    return best[1] if best else None


# ------------------------------------------------------------------ periods

_PERIOD_GROUPS = (
    ("period_week", Period("week", 1)),
    ("period_quarter", Period("month", 3)),
    ("period_halfyear", Period("month", 6)),
    ("period_year", Period("year", 1)),
    ("period_month", Period("month", 1)),
)


def find_period(text_cf: str, kw: Keywords, near: int | None = None) -> Period | None:
    found: list[tuple[int, int, Period]] = []
    for priority, (group, period) in enumerate(_PERIOD_GROUPS):
        for hit in kw.find(text_cf, group):
            # "12 месяцев" must not also count as a monthly hit.
            found.append((hit.pos, priority, period))
    if not found:
        return None
    if near is not None:
        found.sort(key=lambda f: (abs(f[0] - near), f[1]))
    else:
        found.sort(key=lambda f: (f[1], f[0]))
    return found[0][2]


# -------------------------------------------------------------------- dates


@lru_cache(maxsize=1)
def _date_regexes() -> tuple[tuple[str, re.Pattern[str]], ...]:
    month = month_alternation()
    return (
        ("iso", re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")),
        ("kk", re.compile(rf"(?<!\d)(\d{{4}})\s*ж(?:ылғы|\.)?\s*(\d{{1,2}})\s*({month})(?!\w)", re.I)),
        ("dmy_word", re.compile(rf"(?<!\d)(\d{{1,2}})(?:st|nd|rd|th)?\s+({month})(?!\w)\.?,?(?:\s+(\d{{4}}))?", re.I)),
        ("mdy_word", re.compile(rf"\b({month})(?!\w)\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?!\d)", re.I)),
        ("numeric", re.compile(r"(?<![\d.])(\d{1,2})([./])(\d{1,2})\2(\d{4}|\d{2})(?![\d])")),
    )


@dataclass(frozen=True)
class DateHit:
    value: date
    start: int
    end: int
    has_year: bool


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str, reference: date, english_numeric: bool = False) -> list[DateHit]:
    """All dates in the text. Years missing in "22 октября" are resolved to the
    first occurrence on or after `reference`."""
    out: dict[int, DateHit] = {}
    for kind, rx in _date_regexes():
        for m in rx.finditer(text):
            if any(h.start <= m.start() < h.end for h in out.values()):
                continue
            value = None
            has_year = True
            if kind == "iso":
                value = _make(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            elif kind == "kk":
                mon = month_number(m.group(3))
                value = _make(int(m.group(1)), mon, int(m.group(2))) if mon else None
            elif kind == "dmy_word":
                mon = month_number(m.group(2))
                if mon:
                    if m.group(3):
                        value = _make(int(m.group(3)), mon, int(m.group(1)))
                    else:
                        has_year = False
                        value = _infer_year(mon, int(m.group(1)), reference)
            elif kind == "mdy_word":
                mon = month_number(m.group(1))
                if mon:
                    if m.group(3):
                        value = _make(int(m.group(3)), mon, int(m.group(2)))
                    else:
                        has_year = False
                        value = _infer_year(mon, int(m.group(2)), reference)
            elif kind == "numeric":
                a, sep, b, y = int(m.group(1)), m.group(2), int(m.group(3)), int(m.group(4))
                if y < 100:
                    y += 2000
                if sep == "/" and english_numeric and a <= 12 and b <= 31:
                    a, b = b, a
                if b > 12 and a <= 12:
                    a, b = b, a
                value = _make(y, b, a)
            if value is not None and 2000 <= value.year <= 2100:
                out[m.start()] = DateHit(value, m.start(), m.end(), has_year)
    return sorted(out.values(), key=lambda h: h.start)


def _infer_year(month: int, day: int, reference: date) -> date | None:
    for year in (reference.year, reference.year + 1):
        candidate = _make(year, month, day)
        if candidate and candidate >= reference - timedelta(days=1):
            return candidate
    return _make(reference.year, month, day)


def date_after_phrase(
    text: str, text_cf: str, kw: Keywords, group: str, reference: date, window: int = 90,
    english_numeric: bool = False,
) -> date | None:
    phrases = kw.find(text_cf, group)
    if not phrases:
        return None
    dates = find_dates(text, reference, english_numeric)
    for ph in phrases:
        for dh in dates:
            if 0 <= dh.start - ph.end <= window:
                return dh.value
    return None
