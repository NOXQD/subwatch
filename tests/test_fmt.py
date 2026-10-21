from datetime import date, timedelta
from decimal import Decimal

import pytest

from subwatch import clock, fmt
from subwatch.i18n import plural_category, set_language, tn

NB = " "


@pytest.mark.parametrize("n,expected", [
    (0, "0 дней"), (1, "1 день"), (2, "2 дня"), (3, "3 дня"), (4, "4 дня"), (5, "5 дней"),
    (11, "11 дней"), (12, "12 дней"), (14, "14 дней"), (21, "21 день"), (22, "22 дня"),
    (25, "25 дней"), (101, "101 день"), (111, "111 дней"), (112, "112 дней"), (1000, "1000 дней"),
])
def test_russian_plural_days(n, expected):
    assert tn("fmt.units.day", n) == expected


def test_plural_categories():
    assert [plural_category(n, "ru") for n in (1, 2, 5, 21, 22, 25, 11)] == \
        ["one", "few", "many", "one", "few", "many", "many"]


@pytest.mark.parametrize("n,expected", [(1, "1 подписка"), (3, "3 подписки"), (7, "7 подписок")])
def test_plural_subscriptions(n, expected):
    assert tn("fmt.units.subscription", n) == expected


def test_money_ru():
    assert fmt.format_money(Decimal("1299"), "KZT") == f"1{NB}299,00{NB}₸"
    assert fmt.format_money(Decimal("1299"), "KZT").replace(NB, " ") == "1 299,00 ₸"
    assert fmt.format_money(Decimal("9.99"), "USD") == f"9,99{NB}$"
    assert fmt.format_money(Decimal("1234567.5"), "RUB") == f"1{NB}234{NB}567,50{NB}₽"
    assert fmt.format_money(Decimal("12490"), "KZT", decimals=0) == f"12{NB}490{NB}₸"
    assert fmt.format_money(Decimal("100"), "KZT", compact=True) == f"100{NB}₸"
    assert fmt.format_money(Decimal("-50"), "EUR") == f"-50,00{NB}€"
    assert fmt.format_money(None, "KZT") == "сумма неизвестна"


def test_dates_ru():
    assert fmt.format_date(date(2026, 10, 22)) == "22 октября"
    assert fmt.format_date(date(2026, 3, 1)) == "1 марта"
    assert fmt.format_date(date(2027, 5, 9)) == "9 мая 2027"
    assert fmt.format_date(date(2026, 10, 22), year="always") == "22 октября 2026"
    assert fmt.format_date(date(2026, 10, 22), weekday=True) == "четверг, 22 октября"


def test_relative_days():
    today = clock.today()
    assert fmt.format_relative_days(0) == "сегодня"
    assert fmt.format_relative_days(1) == "завтра"
    assert fmt.format_relative_days(-1) == "вчера"
    assert fmt.format_relative_days(3) == "через 3 дня"
    assert fmt.format_relative_days(5) == "через 5 дней"
    assert fmt.format_relative_days(21) == "через 21 день"
    assert fmt.format_relative_days(-2) == "2 дня назад"
    assert fmt.format_when(today + timedelta(days=3)) == "25 октября, через 3 дня"


def test_periods():
    assert fmt.format_period("1m") == "ежемесячно"
    assert fmt.format_period("1y") == "ежегодно"
    assert fmt.format_period("1w") == "еженедельно"
    assert fmt.format_period("3m") == "раз в квартал"
    assert fmt.format_period("2m") == "раз в 2 месяца"
    assert fmt.format_period("6m") == "раз в 6 месяцев"
    assert fmt.format_period("14d") == "раз в 14 дней"
    assert fmt.format_period("2y") == "раз в 2 года"


def test_switch_to_english():
    set_language("en")
    assert fmt.format_money(Decimal("1299"), "KZT") == "₸1,299.00"
    assert fmt.format_date(date(2026, 10, 22)) == "October 22"
    assert fmt.format_relative_days(3) == "in 3 days"
    assert fmt.format_relative_days(1) == "tomorrow"
    assert tn("fmt.units.day", 1) == "1 day"
    set_language("ru")
    assert fmt.format_relative_days(3) == "через 3 дня"


def test_unknown_language_falls_back_to_russian():
    assert set_language("xx") == "ru"
    assert fmt.format_relative_days(2) == "через 2 дня"
