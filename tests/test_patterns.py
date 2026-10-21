from datetime import date

import pytest

from subwatch.extract.keywords import Keywords
from subwatch.extract.patterns import find_dates, find_period
from subwatch.period import Period, add_months

REF = date(2026, 10, 22)
KW = Keywords()


@pytest.mark.parametrize("text,expected", [
    ("Следующее списание 22 октября 2026", "2026-10-22"),
    ("до 5 марта", "2027-03-05"),
    ("next billing date: Oct 22, 2026", "2026-10-22"),
    ("November 3rd", "2026-11-03"),
    ("renews on 2026-11-05", "2026-11-05"),
    ("05.12.2026", "2026-12-05"),
    ("05.12.26", "2026-12-05"),
    ("Келесі төлем: 2026 жылғы 22 қараша", "2026-11-22"),
    ("22 қазанда 2026", "2026-10-22"),
    ("1 мая 2027 г.", "2027-05-01"),
    ("29 Feb 2028", "2028-02-29"),
])
def test_dates(text, expected):
    hits = find_dates(text, REF)
    assert hits and hits[0].value == date.fromisoformat(expected)


def test_us_numeric_dates_in_english():
    assert find_dates("on 11/09/2026", REF, english_numeric=True)[0].value == date(2026, 11, 9)
    assert find_dates("on 11/09/2026", REF, english_numeric=False)[0].value == date(2026, 9, 11)
    assert find_dates("on 25/11/2026", REF, english_numeric=True)[0].value == date(2026, 11, 25)


@pytest.mark.parametrize("text", ["22 марафона", "Тариф 12 мес.", "версия 1.2.3", "31.02.2026"])
def test_not_dates(text):
    assert find_dates(text, REF) == []


@pytest.mark.parametrize("text,code", [
    ("299 ₽ в месяц", "1m"), ("annual plan, billed yearly", "1y"), ("айына 2 990 ₸", "1m"),
    ("12 месяцев", "1y"), ("$5/mo", "1m"), ("жылына", "1y"), ("раз в квартал, 3 месяца", "3m"),
    ("per week", "1w"), ("на полгода", "6m"),
])
def test_period_words(text, code):
    assert find_period(text.casefold(), KW).code == code


def test_period_nearest_to_amount():
    text = "Годовая подписка 9 990 ₸. Или 990 ₸ в месяц.".casefold()
    assert find_period(text, KW, near=text.find("990 ₸ в")).code == "1m"


@pytest.mark.parametrize("start,months,anchor,expected", [
    ("2026-01-31", 1, None, "2026-02-28"),
    ("2026-01-31", 1, 31, "2026-02-28"),
    ("2026-02-28", 1, 31, "2026-03-31"),
    ("2024-02-29", 12, None, "2025-02-28"),
    ("2026-11-15", 2, None, "2027-01-15"),
])
def test_add_months(start, months, anchor, expected):
    assert add_months(date.fromisoformat(start), months, anchor) == date.fromisoformat(expected)


@pytest.mark.parametrize("days,code", [(7, "1w"), (14, "2w"), (30, "1m"), (31, "1m"), (90, "3m"),
                                       (182, "6m"), (365, "1y"), (45, "45d")])
def test_period_from_days(days, code):
    assert Period.from_days(days).code == code


def test_period_parse_and_monthly_factor():
    assert Period.parse("monthly") == Period("month", 1)
    assert round(float(Period.parse("1y").per_month), 4) == round(1 / 12, 4)
    assert round(float(Period.parse("1w").per_month), 2) == 4.35
