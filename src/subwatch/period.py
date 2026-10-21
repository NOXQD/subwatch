"""Billing periods and date arithmetic.

A period is stored as a short code: "1m", "3m", "1y", "1w", "14d".
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

UNITS = ("day", "week", "month", "year")
_CODE = {"d": "day", "w": "week", "m": "month", "y": "year"}
_UNIT_CODE = {v: k for k, v in _CODE.items()}

# Words accepted on the command line and in config files besides the codes.
# Localised words come from the extraction keyword lists, not from here.
_WORDS = {
    "daily": ("day", 1),
    "day": ("day", 1),
    "weekly": ("week", 1),
    "week": ("week", 1),
    "biweekly": ("week", 2),
    "monthly": ("month", 1),
    "month": ("month", 1),
    "quarterly": ("month", 3),
    "quarter": ("month", 3),
    "semiannual": ("month", 6),
    "yearly": ("year", 1),
    "annual": ("year", 1),
    "annually": ("year", 1),
    "year": ("year", 1),
}


class PeriodError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class Period:
    unit: str = "month"
    count: int = 1

    def __post_init__(self) -> None:
        if self.unit not in UNITS:
            raise PeriodError(self.unit)
        if self.count < 1:
            raise PeriodError(str(self.count))

    @classmethod
    def parse(cls, text: str | "Period" | None) -> "Period":
        if isinstance(text, Period):
            return text
        if not text:
            return cls()
        s = str(text).strip().lower()
        m = re.fullmatch(r"(\d+)\s*([dwmy])", s)
        if m:
            return cls(_CODE[m.group(2)], int(m.group(1)))
        if s in _WORDS:
            unit, count = _WORDS[s]
            return cls(unit, count)
        if s.isdigit():
            return cls.from_days(int(s))
        raise PeriodError(s)

    @classmethod
    def from_days(cls, days: int) -> "Period":
        """Best calendar period for a detected interval in days."""
        if days <= 0:
            raise PeriodError(str(days))
        if days % 7 == 0 and days < 28:
            return cls("week", days // 7)
        if 27 <= days <= 33:
            return cls("month", 1)
        if 58 <= days <= 63:
            return cls("month", 2)
        if 85 <= days <= 95:
            return cls("month", 3)
        if 175 <= days <= 188:
            return cls("month", 6)
        if 355 <= days <= 376:
            return cls("year", 1)
        return cls("day", days)

    @property
    def code(self) -> str:
        return f"{self.count}{_UNIT_CODE[self.unit]}"

    def __str__(self) -> str:
        return self.code

    @property
    def approx_days(self) -> float:
        per = {"day": 1.0, "week": 7.0, "month": 30.4375, "year": 365.25}[self.unit]
        return per * self.count

    @property
    def per_month(self) -> Decimal:
        """How many charges of this period fit into an average month."""
        return Decimal("30.4375") / Decimal(str(self.approx_days))

    def advance(self, start: date, times: int = 1, anchor_day: int | None = None) -> date:
        if self.unit == "day":
            return start + timedelta(days=self.count * times)
        if self.unit == "week":
            return start + timedelta(weeks=self.count * times)
        months = self.count * times * (12 if self.unit == "year" else 1)
        return add_months(start, months, anchor_day)

    def next_after(self, last: date, today: date, anchor_day: int | None = None) -> date:
        """First charge date strictly after `today` (or today itself)."""
        current = last
        guard = 0
        while current < today and guard < 10_000:
            current = self.advance(current, 1, anchor_day)
            guard += 1
        return current


def add_months(start: date, months: int, anchor_day: int | None = None) -> date:
    total = start.year * 12 + (start.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = anchor_day or start.day
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def month_start(d: date) -> date:
    return d.replace(day=1)


def iter_months(start: date, end: date):
    """Yield the first day of every month from start to end inclusive."""
    current = month_start(start)
    while current <= end:
        yield current
        current = add_months(current, 1)
