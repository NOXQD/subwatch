from datetime import date, datetime, timedelta
from decimal import Decimal

from subwatch import analysis, clock
from subwatch.config.schema import Config
from subwatch.extract.merchants import MerchantBook
from subwatch.fx import Rates
from subwatch.models import Subscription
from subwatch.period import Period

RATES = Rates("KZT", {"USD": Decimal(500), "RUB": Decimal("6.4")})


def sub(service, amount, currency="KZT", period="1m", category="other", status="active", **kw):
    return Subscription(service=service, amount=Decimal(amount), currency=currency, period=Period.parse(period),
                        category=category, status=status, **kw)


def test_totals_multi_currency_and_periods():
    subs = [sub("Netflix", "3990", category="video"), sub("Spotify", "10", "USD", category="music"),
            sub("Dropbox", "120", "USD", "1y", category="cloud"), sub("Иви", "399", "RUB", category="video"),
            sub("Skillbox", "1000", status="review"), sub("Okko", "999", status="cancelled")]
    tot = analysis.totals(subs, RATES, Config())
    assert tot.count == 4
    assert tot.monthly == Decimal("3990") + Decimal("5000") + Decimal("5000.00") + Decimal("2553.60")
    assert tot.by_category["video"] == Decimal("6543.60")
    with_review = analysis.totals(subs, RATES, Config.model_validate({"budget": {"include_review": True}}))
    assert with_review.count == 5


def test_unconverted_currency_is_reported():
    tot = analysis.totals([sub("X", "10", "GEL")], RATES, Config())
    assert tot.monthly == 0 and [s.service for s in tot.unconverted] == ["X"]


def test_base_currency_changes_totals():
    rates_usd = Rates("USD", {"KZT": Decimal("0.002")})
    tot = analysis.totals([sub("Netflix", "5000")], rates_usd, Config.model_validate({"currency": {"base": "USD"}}))
    assert tot.monthly == Decimal("10.00")


def test_budgets_levels():
    cfg = Config.model_validate({"budget": {"monthly_limit": 10000, "warn_at_pct": 80},
                                 "categories": {"video": {"name": "Видео", "budget": 3000}}})
    tot = analysis.totals([sub("Netflix", "3990", category="video"), sub("iCloud", "4500", category="cloud")],
                          RATES, cfg)
    st = {s.scope: s for s in analysis.budget_status(tot, cfg)}
    assert st["total"].level == "warn" and st["video"].level == "over"
    assert analysis.over_budget(list(st.values()))
    relaxed = Config.model_validate({"budget": {"monthly_limit": 20000}})
    assert [s.level for s in analysis.budget_status(analysis.totals([sub("A", "100")], RATES, relaxed), relaxed)] == ["ok"]


def test_duplicates():
    book = MerchantBook.load()
    subs = [sub("Netflix", "3990"), sub("Netflix", "15.49", "USD"), sub("Яндекс Плюс", "2490"),
            sub("Кинопоиск", "299", "RUB"), sub("Spotify Premium", "10", "USD"), sub("Spotify Premiun", "10", "USD")]
    for i, s in enumerate(subs, 1):
        s.id = i
    found = {(d.a.service, d.b.service, d.reason) for d in analysis.find_duplicates(subs, Config(), book)}
    assert ("Netflix", "Netflix", "same_service") in found
    assert ("Яндекс Плюс", "Кинопоиск", "bundle") in found
    assert ("Spotify Premium", "Spotify Premiun", "similar_name") in found
    off = Config.model_validate({"detection": {"duplicates": False}})
    assert analysis.find_duplicates(subs, off, book) == []


def test_zombies():
    today = clock.today()
    old = sub("Coursera Plus", "20", "USD", track_usage=True, last_used=today - timedelta(days=50))
    fresh = sub("Duolingo", "10", "USD", track_usage=True, last_used=today - timedelta(days=5))
    untracked = sub("Netflix", "3990")
    found = [z.service for z in analysis.find_zombies([old, fresh, untracked], Config())]
    assert found == ["Coursera Plus"]
    strict = Config.model_validate({"detection": {"zombie_days": 3}})
    assert len(analysis.find_zombies([old, fresh, untracked], strict)) == 2
    off = Config.model_validate({"detection": {"zombies": False}})
    assert analysis.find_zombies([old], off) == []


def test_monthly_spend_uses_charges_and_expected_dates(store):
    from subwatch.models import Charge

    s = sub("Netflix", "3990", next_charge=date(2026, 11, 5), last_charge=date(2026, 10, 5), anchor_day=5,
            category="video")
    s.created_at = datetime(2026, 5, 1, tzinfo=clock.local_tz())
    store.insert_subscription(s)
    s.created_at = datetime(2026, 5, 1, tzinfo=clock.local_tz())
    store.update_subscription(s)
    store.add_charge(Charge(s.id, date(2026, 9, 5), Decimal(3490), "KZT", "imap"))
    hist = analysis.monthly_spend(store, store.subscriptions(), RATES, Config(), months_back=5, months_ahead=2)
    months = {m.strftime("%Y-%m"): (v, f) for m, v, f, _ in hist}
    assert months["2026-09"] == (Decimal("3490.00"), False)   # real charge
    assert months["2026-08"] == (Decimal("3990.00"), False)   # expected while active
    assert months["2026-12"] == (Decimal("3990.00"), True)    # forecast
    assert "2026-04" not in months or months["2026-04"][0] == 0


def test_upcoming_window():
    today = clock.today()
    subs = [sub("A", "1", next_charge=today + timedelta(days=2)), sub("B", "1", next_charge=today + timedelta(days=40)),
            sub("C", "1", next_charge=today + timedelta(days=1), status="paused")]
    assert [s.service for s in analysis.upcoming(subs, 30)] == ["A"]
