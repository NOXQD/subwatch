"""Exchange rates.

Rates are stored as "how much base currency one unit costs". Order of
preference: fresh download -> cached copy (even stale, offline) -> manual
rates from config. With currency.rates_source = "manual" only the manual
rates are used.
"""

from __future__ import annotations

import json
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Callable

from . import clock, log
from .config.schema import Config
from .money import parse_number, quantize

Fetcher = Callable[[str, float], bytes]

SOURCES = {
    "nbk": "https://nationalbank.kz/rss/get_rates.cfm?fdate={date}",
    "cbr": "https://www.cbr.ru/scripts/XML_daily.asp",
    "open_er_api": "https://open.er-api.com/v6/latest/{base}",
    "frankfurter": "https://api.frankfurter.app/latest?from={base}",
}


def http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "subwatch/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _cross(native: dict[str, Decimal], native_base: str, base: str) -> dict[str, Decimal]:
    """Re-express rates given in native_base as rates in `base`."""
    table = dict(native)
    table[native_base] = Decimal(1)
    if base == native_base:
        return {k: v for k, v in table.items() if k != base}
    if base not in table:
        raise KeyError(base)
    pivot = table[base]
    return {code: value / pivot for code, value in table.items() if code != base}


def parse_nbk(data: bytes) -> dict[str, Decimal]:
    root = ET.fromstring(data)
    out = {}
    for item in root.iter("item"):
        code = (item.findtext("title") or "").strip().upper()
        value = parse_number(item.findtext("description") or "")
        quant = parse_number(item.findtext("quant") or "1") or Decimal(1)
        if code and value:
            out[code] = value / quant
    return out


def parse_cbr(data: bytes) -> dict[str, Decimal]:
    root = ET.fromstring(data)
    out = {}
    for val in root.iter("Valute"):
        code = (val.findtext("CharCode") or "").strip().upper()
        value = parse_number(val.findtext("Value") or "")
        nominal = parse_number(val.findtext("Nominal") or "1") or Decimal(1)
        if code and value:
            out[code] = value / nominal
    return out


def parse_inverse_json(data: bytes, key: str) -> dict[str, Decimal]:
    """{"rates": {"USD": 0.0019}} meaning 1 base = 0.0019 USD."""
    payload = json.loads(data)
    out = {}
    for code, value in (payload.get(key) or {}).items():
        try:
            v = Decimal(str(value))
        except InvalidOperation:
            continue
        if v > 0:
            out[code.upper()] = Decimal(1) / v
    return out


def fetch_from(source: str, base: str, timeout: float, fetcher: Fetcher = http_get) -> dict[str, Decimal]:
    if source == "nbk":
        url = SOURCES["nbk"].format(date=clock.today().strftime("%d.%m.%Y"))
        return _cross(parse_nbk(fetcher(url, timeout)), "KZT", base)
    if source == "cbr":
        return _cross(parse_cbr(fetcher(SOURCES["cbr"], timeout)), "RUB", base)
    if source == "open_er_api":
        return parse_inverse_json(fetcher(SOURCES["open_er_api"].format(base=base), timeout), "rates")
    if source == "frankfurter":
        return parse_inverse_json(fetcher(SOURCES["frankfurter"].format(base=base), timeout), "rates")
    raise KeyError(source)


def source_chain(config: Config) -> list[str]:
    chosen = config.currency.rates_source
    base = config.currency.base
    if chosen == "manual":
        return []
    if chosen != "auto":
        return [chosen]
    if base == "KZT":
        return ["nbk", "open_er_api"]
    if base == "RUB":
        return ["cbr", "open_er_api"]
    return ["open_er_api", "frankfurter"]


@dataclass
class Rates:
    base: str
    table: dict[str, Decimal]
    fetched_at: datetime | None = None
    source: str = "manual"
    stale: bool = False
    from_manual: frozenset[str] = frozenset()

    def rate(self, currency: str | None) -> Decimal | None:
        if not currency:
            return None
        currency = currency.upper()
        if currency == self.base:
            return Decimal(1)
        return self.table.get(currency)

    def convert(self, amount: Decimal | None, currency: str | None) -> Decimal | None:
        if amount is None:
            return None
        rate = self.rate(currency)
        if rate is None:
            return None
        return quantize(amount * rate, 2)

    def has(self, currency: str | None) -> bool:
        return self.rate(currency) is not None


def get_rates(store, config: Config, allow_network: bool = False, force: bool = False,
              fetcher: Fetcher = http_get) -> Rates:
    base = config.currency.base
    manual = dict(config.currency.manual_rates)
    if config.currency.rates_source == "manual":
        return Rates(base, manual, None, "manual", False, frozenset(manual))
    cached, fetched_at, cached_source = store.load_rates(base) if store else ({}, None, None)
    ttl = timedelta(hours=config.currency.cache_ttl_hours)
    fresh = fetched_at is not None and clock.now() - fetched_at < ttl
    if allow_network and (force or not fresh):
        for name in source_chain(config):
            try:
                table = fetch_from(name, base, config.currency.timeout, fetcher)
            except Exception as exc:
                log.warning("fx_fetch_failed", source=name, error=str(exc))
                continue
            if table:
                if store:
                    store.save_rates(base, table, name)
                cached, fetched_at, cached_source, fresh = table, clock.now(), name, True
                log.info("fx_updated", source=name, count=len(table))
                break
    merged = {**manual, **cached}
    missing = frozenset(code for code in manual if code not in cached)
    return Rates(base, merged, fetched_at, cached_source or "manual", not fresh, missing)
