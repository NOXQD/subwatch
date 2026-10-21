from datetime import date, timedelta
from decimal import Decimal

from subwatch.config.schema import Config
from subwatch.extract.merchants import MerchantBook
from subwatch.models import Transaction
from subwatch.period import add_months
from subwatch.recurrence import detect_recurring

BOOK = MerchantBook.load()
TODAY = date(2026, 10, 22)


def monthly(merchant, amount, start, n, jitter=(0,), currency="KZT"):
    out = []
    for i in range(n):
        d = add_months(start, i) + timedelta(days=jitter[i % len(jitter)])
        out.append(Transaction(d, Decimal(amount), currency, merchant))
    return out


def detect(txs, config=None):
    return {d.service: d for d in detect_recurring(txs, config or Config(), BOOK, today=TODAY)}


def test_monthly_known_merchant():
    found = detect(monthly("NETFLIX.COM*123", "3990", date(2026, 5, 3), 6))
    d = found["Netflix"]
    assert d.period.code == "1m" and d.amount == Decimal(3990)
    assert d.next_charge == date(2026, 11, 3)
    assert d.confidence >= 0.8 and d.known_service
    assert len(d.extra["history"]) == 6


def test_date_tolerance():
    txs = monthly("SPOTIFY P1234", "1590", date(2026, 4, 14), 7, jitter=(0, 2, -1, 3, 1, -2, 0))
    assert detect(txs)["Spotify"].period.code == "1m"


def test_date_tolerance_is_configurable():
    txs = monthly("SPOTIFY P1234", "1590", date(2026, 4, 14), 6, jitter=(0, 6, -5, 6, -5, 6))
    assert "Spotify" not in detect(txs)
    loose = Config.model_validate({"recurrence": {"tolerance_pct": 40, "max_tolerance_days": 12}})
    assert "Spotify" in detect(txs, loose)


def test_weekly_quarterly_yearly():
    weekly = [Transaction(date(2026, 8, 31) + timedelta(weeks=i), Decimal(500), "KZT", "SQ *GYM CLUB")
              for i in range(8)]
    quarterly = [Transaction(add_months(date(2025, 10, 10), 3 * i), Decimal(9000), "KZT", "ACME HOSTING")
                 for i in range(4)]
    yearly = [Transaction(date(2024, 11, 1), Decimal(119.88), "USD", "PAYPAL *DROPBOX"),
              Transaction(date(2025, 11, 2), Decimal(119.88), "USD", "PAYPAL *DROPBOX")]
    found = detect(weekly + quarterly + yearly)
    assert found["Gym Club"].period.code == "1w"
    assert found["Acme Hosting"].period.code == "3m"
    assert found["Dropbox"].period.code == "1y"


def test_amount_tolerance_and_price_step():
    txs = monthly("YANDEX*PLUS", "2490", date(2026, 3, 10), 4) + monthly("YANDEX*PLUS", "2990", date(2026, 7, 10), 3)
    d = detect(txs)["Яндекс Плюс"]
    assert d.amount == Decimal(2990) and d.old_amount == Decimal(2490)
    assert len(d.extra["history"]) == 7


def test_random_purchases_are_not_subscriptions():
    txs = [Transaction(date(2026, 1, 1) + timedelta(days=k * 9 + (k % 4) * 5), Decimal(1000 + k * 137), "KZT",
                       "MAGNUM CASH&CARRY") for k in range(25)]
    assert detect(txs) == {}


def test_too_few_occurrences():
    assert detect(monthly("NETFLIX.COM", "3990", date(2026, 8, 3), 2)) == {}
    two_years = [Transaction(date(2024, 10, 1), Decimal(10), "USD", "1PASSWORD.COM"),
                 Transaction(date(2025, 10, 1), Decimal(10), "USD", "1PASSWORD.COM")]
    strict = Config.model_validate({"recurrence": {"min_occurrences_yearly": 3}})
    assert detect(two_years, strict) == {}
    assert "1Password" in detect(two_years)


def test_stopped_long_ago_is_ignored():
    assert detect(monthly("NETFLIX.COM", "3990", date(2025, 1, 3), 5)) == {}


def test_periods_option():
    weekly = [Transaction(date(2026, 8, 31) + timedelta(weeks=i), Decimal(500), "KZT", "GYM CLUB")
              for i in range(8)]
    only_monthly = Config.model_validate({"recurrence": {"periods": [30]}})
    assert detect(weekly, only_monthly) == {}
