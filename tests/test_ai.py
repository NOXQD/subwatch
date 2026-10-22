"""AI layer with mocked models: nothing here touches the network."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from conftest import write_config

from subwatch import secrets
from subwatch.ai import AIExtractor, answer_to_detection, is_local, merge, needs_key, parse_answer
from subwatch.app import AppContext
from subwatch.config.schema import Config
from subwatch.extract.keywords import Keywords
from subwatch.extract.redact import minimize, redact
from subwatch.models import Detection, RawMessage

LEAKY = """Здравствуйте, Айгерим Сапарова!
Ваш адрес: г. Алматы, ул. Абая 150, кв. 12
Телефон: +7 (701) 555-12-34
Карта: 4400 4302 1234 5678, или **** 5678
IBAN KZ86125KZT5004100100
Почта для связи: aigerim.s@example.kz
Подписка «Облако Про» продлена: 1 990 ₸ в месяц.
Следующее списание 22 ноября 2026.
Ссылка: https://cloud.example/billing?token=SECRET123&user=42
"""


def msg(text=LEAKY, subject="Чек об оплате", sender="billing@cloud.example"):
    return RawMessage(source="imap", key="k1", sender=sender, sender_name="Облако", subject=subject,
                      date=datetime(2026, 10, 22, tzinfo=UTC), text=text)


def test_redact_removes_personal_data():
    out = redact(LEAKY)
    for secret in ("Айгерим", "Абая", "555-12-34", "4400 4302", "5678", "KZ86125", "aigerim.s@", "SECRET123", "user=42"):
        assert secret not in out, secret
    assert "1 990 ₸" in out and "22 ноября 2026" in out and "cloud.example" in out


def test_minimize_keeps_only_relevant_lines_and_limit():
    out = minimize(LEAKY + "\nНовости компании и прочий текст без цифр\n", "Чек об оплате", Keywords(), 200)
    assert "Новости компании" not in out and len(out) <= 200
    assert "1 990 ₸" in out


def test_local_detection():
    assert is_local(Config().ai)  # ollama on localhost
    cloud = Config.model_validate({"ai": {"provider": "openai", "model": "gpt-4o-mini"}}).ai
    assert not is_local(cloud) and needs_key(cloud)
    remote_ollama = Config.model_validate({"ai": {"api_base": "http://gpu-box.lan:11434"}}).ai
    assert not is_local(remote_ollama)


def test_dry_run_shows_exact_payload_and_sends_nothing():
    cfg = Config.model_validate({"ai": {"provider": "openai", "model": "gpt-4o-mini", "max_input_chars": 400}})

    def boom(*a):
        raise AssertionError("must not be called in dry run")

    ex = AIExtractor(cfg, None, dry_run=True, completion=boom)
    assert ex.extract(msg(), LEAKY) is None
    item = ex.dry_runs[0]
    payload = item.messages[-1]["content"]
    assert payload.startswith("From: cloud.example") and "billing@" not in payload
    assert "+7 (701)" not in payload and "4400" not in payload and len(payload) <= 420
    assert item.messages[0]["role"] == "system" and "2026-10-22" in item.messages[0]["content"]
    assert not item.is_local


def test_cloud_without_key_is_skipped(store):
    cfg = Config.model_validate({"ai": {"enabled": True, "provider": "openai", "model": "x"}})
    ex = AIExtractor(cfg, store, completion=lambda *a: pytest.fail("no key, no call"))
    assert ex.extract(msg(), LEAKY) is None and ex.disabled_reason == "no_key"


def test_mocked_cloud_call_is_audited(store):
    secrets.put(secrets.ai_key_name("openai"), "sk-test")
    cfg = Config.model_validate({"ai": {"enabled": True, "provider": "openai", "model": "gpt-4o-mini"}})
    seen = {}

    def fake(messages, ai_cfg, key):
        seen["key"], seen["payload"] = key, messages[-1]["content"]
        return json.dumps({"is_subscription": True, "service": "Облако Про", "kind": "charge", "amount": 1990,
                           "currency": "KZT", "period": "1m", "next_charge": "2026-11-22", "confidence": 0.9})

    det = AIExtractor(cfg, store, completion=fake).extract(msg(), LEAKY)
    assert det.service == "Облако Про" and det.amount == Decimal(1990) and det.next_charge.isoformat() == "2026-11-22"
    assert seen["key"] == "sk-test" and "4400" not in seen["payload"]
    row = store.ai_log()[0]
    assert row["provider"] == "openai" and row["is_local"] == 0 and row["payload"] is None
    assert row["chars"] == len(seen["payload"]) and row["outcome"] == "detected"


def test_audit_payloads_option(store):
    cfg = Config.model_validate({"ai": {"enabled": True, "audit_payloads": True}})
    AIExtractor(cfg, store, completion=lambda *a: '{"is_subscription": false}').extract(msg(), LEAKY)
    assert store.ai_log()[0]["payload"].startswith("From:")


def test_local_model_can_skip_redaction():
    cfg = Config.model_validate({"ai": {"redact_local": False}})
    ex = AIExtractor(cfg, None, dry_run=True)
    ex.extract(msg(), LEAKY)
    assert "4400 4302" in ex.dry_runs[0].messages[-1]["content"]


def test_limits_per_scan_and_per_day(store):
    cfg = Config.model_validate({"ai": {"enabled": True, "max_requests_per_scan": 2, "max_requests_per_day": 3}})
    calls = []
    fake = lambda *a: calls.append(1) or '{"is_subscription": false}'  # noqa: E731
    ex = AIExtractor(cfg, store, completion=fake)
    for _ in range(5):
        ex.extract(msg(), LEAKY)
    assert len(calls) == 2
    ex2 = AIExtractor(cfg, store, completion=fake)
    for _ in range(5):
        ex2.extract(msg(), LEAKY)
    assert len(calls) == 3


def test_parse_answer_is_tolerant():
    assert parse_answer('Sure! ```json\n{"is_subscription": true, "service": "X"}\n```')["service"] == "X"
    assert parse_answer("no json here") is None
    assert answer_to_detection({"is_subscription": True, "service": "X", "kind": "weird"}, msg()) is None
    d = answer_to_detection({"is_subscription": True, "service": "X", "amount": "abc", "currency": "kzt"}, msg())
    assert d.amount is None and d.currency is None


def test_merge_never_auto_accepts_ai_alone():
    ai = Detection(service="X", amount=Decimal(1), currency="USD", confidence=0.99)
    assert merge(None, ai).confidence == 0.75
    rule = Detection(service="X", confidence=0.6)
    merged = merge(rule, Detection(service="X", amount=Decimal(5), currency="USD", confidence=0.9))
    assert merged.amount == Decimal(5) and merged.confidence == 0.75 and "ai" in merged.reasons


def test_scan_uses_ai_only_for_unresolved_mail(monkeypatch):
    from fixtures.emails import EMAILS
    from mock_imap import MockImapServer, ServerState

    from subwatch import ai as ai_mod
    from subwatch.scan import run_job

    state = ServerState()
    for e in EMAILS:
        state.folders["INBOX"].append(e.to_bytes())
    calls = []

    def fake(messages, cfg, key):
        calls.append(messages[-1]["content"])
        return '{"is_subscription": false}'

    monkeypatch.setattr(ai_mod, "builtin_completion", fake)
    with MockImapServer(state) as srv:
        write_config(f"""
[ai]
enabled = true
[[sources.imap.accounts]]
name = "mock"
host = "127.0.0.1"
port = {srv.port}
ssl = false
username = "user@example.org"
""")
        secrets.put(secrets.imap_password_name("mock"), "app-password")
        ctx = AppContext.load(quiet_logs=True)
        run_job(ctx)
        ctx.close()
    # Only messages the rules were not sure about went to the model.
    assert 0 < len(calls) < len(EMAILS) / 2
    assert not any("Netflix" in c and "3 990" in c and "Следующее списание" in c for c in calls)


def test_scan_ai_dry_run_cli(monkeypatch, capsys):
    from subwatch.__main__ import main

    write_config('[sources.imap]\nenabled = false\n')
    try:
        main(["scan", "--ai-dry-run"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert "В модель не ушло бы ничего" in out and "Ничего нового не найдено" in out
