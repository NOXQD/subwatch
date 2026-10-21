from datetime import timedelta
from decimal import Decimal

from subwatch import clock
from subwatch.config.schema import Config
from subwatch.fx import get_rates, parse_cbr, parse_nbk, parse_inverse_json, source_chain

NBK = """<?xml version="1.0" encoding="utf-8"?><rates><date>22.10.2026</date>
<item><fullname>ДОЛЛАР США</fullname><title>USD</title><description>520.50</description><quant>1</quant></item>
<item><fullname>РОССИЙСКИЙ РУБЛЬ</fullname><title>RUB</title><description>6.40</description><quant>1</quant></item>
<item><fullname>ЕВРО</fullname><title>EUR</title><description>565.00</description><quant>1</quant></item>
<item><fullname>ЯПОНСКИХ ИЕН</fullname><title>JPY</title><description>34.80</description><quant>10</quant></item>
</rates>""".encode()

CBR = """<?xml version="1.0" encoding="windows-1251"?><ValCurs Date="22.10.2026">
<Valute><CharCode>USD</CharCode><Nominal>1</Nominal><Value>81,3300</Value></Valute>
<Valute><CharCode>KZT</CharCode><Nominal>100</Nominal><Value>15,6200</Value></Valute>
</ValCurs>""".encode("cp1251")

OPEN = b'{"result":"success","base_code":"USD","rates":{"USD":1,"KZT":520.5,"EUR":0.92}}'


def test_parsers():
    nbk = parse_nbk(NBK)
    assert nbk["USD"] == Decimal("520.50") and nbk["JPY"] == Decimal("3.48")
    cbr = parse_cbr(CBR)
    assert cbr["USD"] == Decimal("81.33") and cbr["KZT"] == Decimal("0.1562")
    inv = parse_inverse_json(OPEN, "rates")
    assert round(inv["KZT"], 6) == round(Decimal(1) / Decimal("520.5"), 6)


def test_source_chain_by_base():
    assert source_chain(Config()) == ["nbk", "open_er_api"]
    assert source_chain(Config.model_validate({"currency": {"base": "RUB"}})) == ["cbr", "open_er_api"]
    assert source_chain(Config.model_validate({"currency": {"base": "EUR"}})) == ["open_er_api", "frankfurter"]
    assert source_chain(Config.model_validate({"currency": {"rates_source": "frankfurter"}})) == ["frankfurter"]
    assert source_chain(Config.model_validate({"currency": {"rates_source": "manual"}})) == []


def test_download_cache_and_offline_fallback(store):
    calls = []

    def ok(url, timeout):
        calls.append(url)
        return NBK

    def offline(url, timeout):
        calls.append(url)
        raise OSError("network is unreachable")

    cfg = Config()
    r = get_rates(store, cfg, allow_network=True, fetcher=ok)
    assert r.source == "nbk" and not r.stale and r.convert(Decimal(10), "USD") == Decimal("5205.00")
    assert r.convert(Decimal(1000), "RUB") == Decimal("6400.00")
    calls.clear()
    r2 = get_rates(store, cfg, allow_network=True, fetcher=offline)
    assert calls == [] and r2.rate("USD") == Decimal("520.50")  # fresh cache, no request
    store.conn.execute("UPDATE fx_rates SET fetched_at = ?", (clock.iso(clock.now() - timedelta(days=3)),))
    r3 = get_rates(store, cfg, allow_network=True, fetcher=offline)
    assert len(calls) == 2 and r3.stale and r3.rate("USD") == Decimal("520.50")


def test_manual_rates_are_the_last_resort(store):
    cfg = Config.model_validate({"currency": {"manual_rates": {"USD": 500, "GEL": 190}}})
    r = get_rates(store, cfg, allow_network=True, fetcher=lambda u, t: NBK)
    assert r.rate("USD") == Decimal("520.50")  # downloaded wins
    assert r.rate("GEL") == Decimal(190) and "GEL" in r.from_manual
    offline_store_cfg = Config.model_validate({"currency": {"manual_rates": {"USD": 500}}})
    from subwatch.db import Store

    empty = Store.memory()
    r2 = get_rates(empty, offline_store_cfg, allow_network=True, fetcher=lambda u, t: (_ for _ in ()).throw(OSError()))
    assert r2.rate("USD") == Decimal(500)


def test_manual_only_mode_never_downloads(store):
    cfg = Config.model_validate({"currency": {"rates_source": "manual", "manual_rates": {"USD": 499}}})
    r = get_rates(store, cfg, allow_network=True, fetcher=lambda u, t: (_ for _ in ()).throw(AssertionError()))
    assert r.rate("USD") == Decimal(499)


def test_cross_rates_for_other_base(store):
    cfg = Config.model_validate({"currency": {"base": "USD", "rates_source": "nbk"}})
    r = get_rates(store, cfg, allow_network=True, fetcher=lambda u, t: NBK)
    assert round(r.rate("KZT"), 6) == round(Decimal(1) / Decimal("520.50"), 6)
    assert round(r.rate("EUR"), 4) == round(Decimal("565") / Decimal("520.5"), 4)
