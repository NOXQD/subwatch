"""What happens after data changes: hooks, notifications, one-time events."""

from datetime import date, timedelta
from decimal import Decimal

from conftest import write_config

from subwatch import clock
from subwatch.app import AppContext
from subwatch.ingest import Event
from subwatch.models import Subscription
from subwatch.period import Period
from subwatch.scan import react


def add(ctx, service, amount="1000", currency="KZT", **kw):
    s = Subscription(service=service, amount=Decimal(amount), currency=currency, period=Period("month", 1),
                     next_charge=date(2026, 11, 1), **kw)
    return ctx.store.insert_subscription(s)


def test_price_change_notifies_and_runs_hook(tmp_path, notifications):
    log = tmp_path / "h.log"
    write_config(f"[hooks]\nprice_changed = ['echo \"$SUBWATCH_SERVICE $SUBWATCH_OLD $SUBWATCH_NEW\" >> {log}']\n")
    ctx = AppContext.load()
    s = add(ctx, "Netflix", "4490")
    react(ctx, [Event("price_changed", s, {"old": "3990", "new": "4490"})])
    assert log.read_text().strip() == "Netflix 3990 4490"
    note = [n for n in notifications() if n["kind"] == "price"][0]
    assert note["summary"] == "Подорожание: Netflix"
    assert "3 990,00 ₸" in note["body"] and "4 490,00 ₸" in note["body"]
    ctx.close()


def test_price_notification_can_be_disabled(notifications):
    write_config("[notifications]\non_price_change = false\n")
    ctx = AppContext.load()
    s = add(ctx, "Netflix")
    react(ctx, [Event("price_changed", s, {"old": "1", "new": "2"})])
    assert not [n for n in notifications() if n["kind"] == "price"]
    ctx.close()


def test_duplicates_reported_once(tmp_path, notifications):
    log = tmp_path / "d.log"
    write_config(f"[hooks]\nduplicate_found = ['echo \"$SUBWATCH_REASON\" >> {log}']\n")
    ctx = AppContext.load()
    add(ctx, "Яндекс Плюс")
    add(ctx, "Кинопоиск", currency="RUB")
    react(ctx, [])
    react(ctx, [])
    assert log.read_text().split() == ["bundle"]
    assert len([n for n in notifications() if n["kind"] == "duplicate"]) == 1
    ctx.close()


def test_zombie_reported_then_quiet_for_a_month(notifications):
    write_config("[detection]\nzombie_days = 30\n")
    ctx = AppContext.load()
    add(ctx, "Coursera Plus", track_usage=True, last_used=clock.today() - timedelta(days=40))
    react(ctx, [])
    react(ctx, [])
    zombies = [n for n in notifications() if n["kind"] == "zombie"]
    assert len(zombies) == 1 and "Coursera Plus" in zombies[0]["summary"]
    ctx.close()


def test_budget_exceeded_once_per_month(tmp_path, notifications):
    log = tmp_path / "b.log"
    write_config(f"[budget]\nmonthly_limit = 1500\n[hooks]\nbudget_exceeded = ['echo \"$SUBWATCH_SCOPE\" >> {log}']\n")
    ctx = AppContext.load()
    add(ctx, "A", "1000")
    add(ctx, "B", "1000")
    react(ctx, [])
    react(ctx, [])
    assert log.read_text().split() == ["total"]
    note = [n for n in notifications() if n["kind"] == "budget"][0]
    assert note["urgency"] == "critical" and "1 500" in note["body"]
    ctx.close()


def test_category_budget(notifications):
    write_config("[categories.video]\nname = \"Видео\"\nbudget = 500\n")
    ctx = AppContext.load()
    add(ctx, "Netflix", "3990", category="video")
    react(ctx, [])
    assert any("Видео" in n["body"] for n in notifications() if n["kind"] == "budget")
    ctx.close()


def test_job_failed_hook_and_notification(tmp_path, notifications):
    log = tmp_path / "f.log"
    write_config(f"[hooks]\njob_failed = ['echo \"$SUBWATCH_SOURCE\" >> {log}']\n")
    ctx = AppContext.load()
    react(ctx, [], errors=[("imap", "сервер недоступен")])
    assert log.read_text().strip() == "imap"
    assert any(n["kind"] == "error" and n["body"] == "сервер недоступен" for n in notifications())
    ctx.close()


def test_new_subscription_and_cancel_hooks(tmp_path):
    log = tmp_path / "n.log"
    write_config(f"[hooks]\nnew_subscription = ['echo new >> {log}']\nsubscription_cancelled = ['echo gone >> {log}']\n")
    ctx = AppContext.load()
    s = add(ctx, "Okko")
    react(ctx, [Event("new_subscription", s), Event("subscription_cancelled", s)])
    assert log.read_text().split() == ["new", "gone"]
    ctx.close()
