from decimal import Decimal

import pytest

from subwatch.extract.patterns import find_amounts
from subwatch.money import parse_number, resolve_currency


@pytest.mark.parametrize("text,value", [
    ("1 299,00", "1299.00"), ("1 299,00", "1299.00"), ("1,299.00", "1299.00"),
    ("1.299,00", "1299.00"), ("9.99", "9.99"), ("9,99", "9.99"), ("2 990", "2990"),
    ("12.990", "12990"), ("1,299", "1299"), ("-3 990,50", "-3990.50"), ("15", "15"),
    ("1'299.50", "1299.50"),
])
def test_parse_number(text, value):
    assert parse_number(text) == Decimal(value)


@pytest.mark.parametrize("text", ["", "abc", "1.2.3.4x", "--"])
def test_parse_number_rejects(text):
    assert parse_number(text) is None


@pytest.mark.parametrize("token,code", [
    ("₸", "KZT"), ("тг", "KZT"), ("теңге", "KZT"), ("тенге", "KZT"), ("₽", "RUB"), ("руб.", "RUB"),
    ("р.", "RUB"), ("$", "USD"), ("USD", "USD"), ("€", "EUR"), ("евро", "EUR"), ("грн", "UAH"),
])
def test_resolve_currency(token, code):
    assert resolve_currency(token) == code


@pytest.mark.parametrize("text,amount,code", [
    ("Итого: 1 299,00 ₸", "1299.00", "KZT"), ("$9.99/mo", "9.99", "USD"),
    ("Сумма 2 990 тг", "2990", "KZT"), ("KZT 4 990", "4990", "KZT"), ("12,99 €", "12.99", "EUR"),
    ("₽299", "299", "RUB"), ("299 руб.", "299", "RUB"), ("charged USD 20.00", "20.00", "USD"),
    ("Сома: 2 490 теңге", "2490", "KZT"), ("1,299.00 USD", "1299.00", "USD"),
])
def test_find_amounts(text, amount, code):
    hits = find_amounts(text)
    assert hits and hits[0].amount == Decimal(amount) and hits[0].currency == code


@pytest.mark.parametrize("text", [
    "Try 30 days free",           # "try" is not Turkish lira
    "Ваш заказ 2026 года",          # a year is not money
    "Код 482913",
])
def test_find_amounts_ignores_non_money(text):
    assert find_amounts(text) == []


def test_year_does_not_glue_to_amount():
    hits = find_amounts("22.10.2026 299 ₸")
    assert [h.amount for h in hits] == [Decimal(299)]
