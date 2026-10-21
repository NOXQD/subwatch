from datetime import date
from decimal import Decimal

from subwatch.config.schema import Config
from subwatch.extract.engine import Learned
from subwatch.ingest import Ingestor, remember_review_decision
from subwatch.models import Detection
from subwatch.period import Period


def det(service="Netflix", amount="3990", currency="KZT", conf=0.95, kind="charge", day="2026-10-01", **kw):
    return Detection(service=service, amount=Decimal(amount) if amount else None, currency=currency if amount else None,
                     period=Period("month", 1), charge_date=date.fromisoformat(day) if day and kind == "charge" else None,
                     confidence=conf, kind=kind, source="imap", reasons=["period"], known_service=True, **kw)


def test_create_and_dedupe(store):
    ing = Ingestor(store, Config())
    r = ing.ingest(det())
    assert r.action == "created" and r.events[0].name == "new_subscription"
    assert r.subscription.next_charge == date(2026, 11, 1)
    again = ing.ingest(det())
    assert again.action == "duplicate" and len(store.charges(r.subscription.id)) == 1


def test_thresholds_decide_status(store):
    cfg = Config.model_validate({"extraction": {"auto_accept": 0.9, "review_threshold": 0.6}})
    ing = Ingestor(store, cfg)
    assert ing.ingest(det("A", conf=0.95)).action == "created"
    assert ing.ingest(det("B", conf=0.7)).action == "review"
    assert ing.ingest(det("C", conf=0.5)).action == "ignored"


def test_review_promotes_with_more_evidence(store):
    ing = Ingestor(store, Config())
    first = ing.ingest(det("Tasklane", conf=0.6, day="2026-09-03"))
    assert first.action == "review"
    second = ing.ingest(det("Tasklane", conf=0.6, day="2026-10-03"))
    assert second.subscription.status == "review" and second.subscription.confidence == 0.7
    third = ing.ingest(det("Tasklane", conf=0.6, day="2026-11-03"))
    assert third.action == "promoted" and third.subscription.status == "active"


def test_price_change_from_charges(store):
    ing = Ingestor(store, Config())
    ing.ingest(det(amount="3990", day="2026-09-01"))
    r = ing.ingest(det(amount="4490", day="2026-10-01"))
    names = [e.name for e in r.events]
    assert "price_changed" in names
    assert r.subscription.previous_amount == Decimal(3990) and r.subscription.amount == Decimal(4490)
    # An older receipt arriving late does not overwrite the current price.
    r2 = ing.ingest(det(amount="3490", day="2026-08-01"))
    assert r2.subscription.amount == Decimal(4490)


def test_price_change_threshold(store):
    cfg = Config.model_validate({"detection": {"price_change_pct": 20}})
    ing = Ingestor(store, cfg)
    ing.ingest(det(amount="1000", day="2026-09-01"))
    assert not [e for e in ing.ingest(det(amount="1100", day="2026-10-01")).events if e.name == "price_changed"]


def test_cancellation_and_reactivation(store):
    ing = Ingestor(store, Config())
    ing.ingest(det(day="2026-09-01"))
    c = ing.ingest(Detection(service="Netflix", kind="cancellation", confidence=0.8, source="imap",
                             received=date(2026, 9, 20)))
    assert c.action == "cancelled" and c.subscription.status == "cancelled"
    weak = ing.ingest(det(conf=0.6, day="2026-10-05"))
    assert weak.subscription.status == "cancelled"
    strong = ing.ingest(det(conf=0.95, day="2026-10-05"))
    assert strong.subscription.status == "active"


def test_learned_rules(store):
    ing = Ingestor(store, Config())
    sub = ing.ingest(det("Мегадиск", conf=0.6)).subscription
    remember_review_decision(store, sub, accepted=True)
    ing2 = Ingestor(store, Config(), Learned.from_store(store))
    assert ing2.ingest(det("Мегадиск", conf=0.5, day="2026-10-02")).subscription.status == "active"
    other = ing2.ingest(det("Спамсервис", conf=0.6)).subscription
    remember_review_decision(store, other, accepted=False)
    ing3 = Ingestor(store, Config(), Learned.from_store(store))
    assert ing3.ingest(det("Спамсервис", conf=0.99)).action == "ignored"


def test_exclude_services_option(store):
    cfg = Config.model_validate({"filters": {"exclude_services": ["Netflix"]}})
    assert Ingestor(store, cfg).ingest(det()).action == "ignored"


def test_trial_creates_with_trial_date(store):
    r = Ingestor(store, Config()).ingest(Detection(service="Notion", kind="trial", amount=Decimal(10), currency="USD",
                                                   period=Period("month", 1), trial_until=date(2026, 10, 25),
                                                   confidence=0.9, source="imap"))
    assert r.subscription.trial_until == date(2026, 10, 25) and r.subscription.next_charge == date(2026, 10, 25)
