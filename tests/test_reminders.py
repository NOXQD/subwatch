from datetime import date, datetime, timedelta
from decimal import Decimal

from subwatch import clock, reminders
from subwatch.config.schema import Config
from subwatch.fx import Rates
from subwatch.models import Subscription
from subwatch.period import Period

TZ = clock.local_tz


def at(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=TZ())


def sub(service="Netflix", amount="3990", currency="KZT", next_charge="2026-10-30", category="video", **kw):
    return Subscription(service=service, amount=Decimal(amount), currency=currency, period=Period("month", 1),
                        next_charge=date.fromisoformat(next_charge), category=category, **kw)


RATES = Rates("KZT", {"USD": Decimal(500)})


def plan(s, cfg=None, now="2026-10-22T12:00:00"):
    return reminders.plan_for(s, cfg or Config(), RATES, at(now))


def test_default_days_and_time():
    p = plan(sub())
    assert [(x.days_before, x.due_at) for x in p] == [(3, at("2026-10-27T10:00:00")),
                                                     (1, at("2026-10-29T10:00:00"))]


def test_days_before_and_time_from_config():
    cfg = Config.model_validate({"reminders": {"days_before": [7, 0], "time": "18:45"}})
    assert [x.due_at for x in plan(sub(), cfg)] == [at("2026-10-23T18:45:00"), at("2026-10-30T18:45:00")]


def test_rule_specificity_service_beats_amount_beats_category():
    cfg = Config.model_validate({"reminders": {"rules": [
        {"name": "video", "categories": ["video"], "days_before": [2]},
        {"name": "expensive", "min_amount": 3000, "days_before": [5]},
        {"name": "netflix", "services": ["netflix"], "days_before": [9], "time": "08:00"},
    ]}})
    netflix = reminders.effective_settings(sub(), cfg, RATES)
    assert netflix.rule == "netflix" and netflix.days_before == [9]
    other_video = reminders.effective_settings(sub("Okko"), cfg, RATES)
    assert other_video.rule == "expensive" and other_video.days_before == [5]
    cheap_video = reminders.effective_settings(sub("Okko", amount="399"), cfg, RATES)
    assert cheap_video.rule == "video" and cheap_video.days_before == [2]


def test_amount_rule_uses_base_currency_and_basis():
    cfg = Config.model_validate({"reminders": {"rules": [{"min_amount": 10000, "days_before": [10]}]}})
    usd = sub("JetBrains", amount="25", currency="USD")
    assert reminders.effective_settings(usd, cfg, RATES).days_before == [10]  # 25 * 500 = 12 500
    yearly = sub("Dropbox", amount="60000")
    yearly.period = Period("year", 1)
    monthly_basis = Config.model_validate({"reminders": {"amount_basis": "monthly",
                                                         "rules": [{"min_amount": 10000, "days_before": [10]}]}})
    assert reminders.effective_settings(yearly, cfg, RATES).days_before == [10]
    assert reminders.effective_settings(yearly, monthly_basis, RATES).days_before == [3, 1]


def test_disabled_rule_silences_service():
    cfg = Config.model_validate({"reminders": {"rules": [{"services": ["iCloud+"], "enabled": False}]}})
    assert plan(sub("iCloud+"), cfg) == []


def test_quiet_hours_shift():
    cfg = Config.model_validate({"reminders": {"time": "23:30", "quiet_hours": {"start": "22:00", "end": "08:00"}}})
    p = plan(sub(), cfg)
    assert p[0].due_at == at("2026-10-28T08:00:00")
    off = Config.model_validate({"reminders": {"time": "23:30", "quiet_hours": {"enabled": False}}})
    assert plan(sub(), off)[0].due_at == at("2026-10-27T23:30:00")
    day_window = Config.model_validate({"reminders": {"time": "13:00", "quiet_hours": {"start": "12:00", "end": "14:00"}}})
    assert plan(sub(), day_window)[0].due_at == at("2026-10-27T14:00:00")


def test_trial_reminders():
    s = sub(next_charge="2026-10-25", trial_until="2026-10-25")
    s.trial_until = date(2026, 10, 25)
    kinds = {(x.kind, x.days_before) for x in plan(s)}
    assert ("trial", 2) in kinds and ("trial", 0) in kinds


def _store_with(store, s):
    store.insert_subscription(s)
    return s


def test_run_sends_once_then_repeats_and_stops(store):
    cfg = Config.model_validate({"reminders": {"days_before": [3], "repeat_every": "4h", "max_repeats": 2}})
    s = _store_with(store, sub(next_charge="2026-10-25"))
    sent = []
    notifier = lambda note, _cfg: sent.append(note)  # noqa: E731
    r = reminders.run(store, cfg, RATES, at("2026-10-22T12:00:00"), notifier=notifier)
    assert len(r.sent) == 1 and not r.sent[0].repeat
    body = sent[0].body.replace("\xa0", " ")
    assert "Netflix" in sent[0].summary and "через 3 дня" in body and "3 990,00 ₸" in body
    assert reminders.run(store, cfg, RATES, at("2026-10-22T13:00:00"), notifier=notifier).sent == []
    assert reminders.run(store, cfg, RATES, at("2026-10-22T16:05:00"), notifier=notifier).sent[0].repeat
    assert reminders.run(store, cfg, RATES, at("2026-10-22T20:10:00"), notifier=notifier).sent[0].repeat
    assert reminders.run(store, cfg, RATES, at("2026-10-23T09:00:00"), notifier=notifier).sent == []
    assert len(sent) == 3
    assert s.id


def test_no_repeat_when_disabled(store):
    cfg = Config.model_validate({"reminders": {"days_before": [3], "repeat_unacknowledged": False}})
    _store_with(store, sub(next_charge="2026-10-25"))
    n = lambda *_: None  # noqa: E731
    assert reminders.run(store, cfg, RATES, at("2026-10-22T12:00:00"), notifier=n).sent
    assert reminders.run(store, cfg, RATES, at("2026-10-22T20:00:00"), notifier=n).sent == []


def test_quiet_hours_block_repeats(store):
    cfg = Config.model_validate({"reminders": {"days_before": [3], "repeat_every": "1h"}})
    _store_with(store, sub(next_charge="2026-10-25"))
    n = lambda *_: None  # noqa: E731
    reminders.run(store, cfg, RATES, at("2026-10-22T12:00:00"), notifier=n)
    assert reminders.run(store, cfg, RATES, at("2026-10-22T23:00:00"), notifier=n).sent == []


def test_actions_keep_snooze_cancel(store):
    cfg = Config.model_validate({"reminders": {"days_before": [3, 1]}})
    s = _store_with(store, sub(next_charge="2026-10-25"))
    n = lambda *_: None  # noqa: E731
    sent = reminders.run(store, cfg, RATES, at("2026-10-22T12:00:00"), notifier=n).sent
    rid = sent[0].reminder_id
    assert reminders.apply_action(store, cfg, rid, "snooze", "1d") == "remind.action.snoozed"
    assert reminders.run(store, cfg, RATES, at("2026-10-23T11:00:00"), notifier=n).sent == []
    again = reminders.run(store, cfg, RATES, at("2026-10-23T13:00:00"), notifier=n).sent
    assert again and again[0].reminder_id == rid
    assert reminders.apply_action(store, cfg, rid, "keep") == "remind.action.kept"
    # "keep" silences the remaining offsets for this charge too.
    assert reminders.run(store, cfg, RATES, at("2026-10-24T10:30:00"), notifier=n).sent == []
    s2 = _store_with(store, sub("Okko", next_charge="2026-10-25", cancel_url=None))
    rid2 = reminders.run(store, cfg, RATES, at("2026-10-22T12:00:00"), notifier=n).sent[0].reminder_id
    assert reminders.apply_action(store, cfg, rid2, "cancel", open_page=False) == "remind.action.cancelled"
    assert store.get_subscription(s2.id).status == "cancelled"
    assert s.id


def test_roll_forward_after_charge(store):
    s = _store_with(store, sub(next_charge="2026-10-20"))
    s.anchor_day = 20
    assert reminders.roll_forward(store, s, date(2026, 10, 22))
    fresh = store.get_subscription(s.id)
    assert fresh.next_charge == date(2026, 11, 20) and fresh.last_charge == date(2026, 10, 20)


def test_late_detection_sends_only_latest_offset(store):
    cfg = Config.model_validate({"reminders": {"days_before": [7, 3, 1]}})
    _store_with(store, sub(next_charge="2026-10-24"))
    sent = reminders.run(store, cfg, RATES, at("2026-10-23T12:00:00"), notifier=lambda *_: None).sent
    assert len(sent) == 1
    row = store.reminder(sent[0].reminder_id)
    assert row["days_before"] == 1


def test_reminders_disabled(store):
    cfg = Config.model_validate({"reminders": {"enabled": False}})
    _store_with(store, sub(next_charge="2026-10-25"))
    assert reminders.run(store, cfg, RATES, at("2026-10-22T12:00:00"), notifier=lambda *_: None).sent == []


def test_paused_and_cancelled_are_silent(store):
    _store_with(store, sub(next_charge="2026-10-25", status="paused"))
    _store_with(store, sub("Okko", next_charge="2026-10-25", status="cancelled"))
    assert reminders.run(store, Config(), RATES, at("2026-10-22T12:00:00"), notifier=lambda *_: None).sent == []


def test_hook_upcoming_charge(store, tmp_path):
    out = tmp_path / "hook.txt"
    cfg = Config.model_validate({"reminders": {"days_before": [3]},
                                 "hooks": {"upcoming_charge": [f'echo "$SUBWATCH_SERVICE $SUBWATCH_DAYS_LEFT" >> {out}']}})
    _store_with(store, sub(next_charge="2026-10-25"))
    reminders.run(store, cfg, RATES, at("2026-10-22T12:00:00"), notifier=lambda *_: None)
    assert out.read_text().strip() == "Netflix 3"


def test_now_helper_is_frozen():
    assert clock.now().date() == date(2026, 10, 22)
    assert clock.today() + timedelta(days=1) == date(2026, 10, 23)
