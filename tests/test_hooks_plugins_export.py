import json
import textwrap
from datetime import date
from decimal import Decimal

from conftest import write_config
from subwatch import paths
from subwatch.app import AppContext
from subwatch.config.schema import Config
from subwatch.export import build_ics, subscription_rows, to_csv, write_ics
from subwatch.fx import Rates
from subwatch.hooks import run_hooks
from subwatch.models import Subscription
from subwatch.period import Period
from subwatch.scan import run_job
from subwatch.sources.base import REGISTRY, available, load_plugins


def netflix(**kw):
    base = dict(service="Netflix", amount=Decimal(3990), currency="KZT", period=Period("month", 1),
                next_charge=date(2026, 10, 25), category="video", id=1,
                cancel_url="https://www.netflix.com/cancelplan")
    base.update(kw)
    return Subscription(**base)


# ------------------------------------------------------------------ hooks


def test_hook_env_and_stdin(tmp_path):
    out = tmp_path / "out.json"
    cfg = Config.model_validate({"hooks": {"price_changed": [
        f'cat > {out}.stdin; echo "$SUBWATCH_EVENT|$SUBWATCH_SERVICE|$SUBWATCH_AMOUNT|$SUBWATCH_OLD" > {out}']}})
    runs = run_hooks(cfg, "price_changed", netflix(), {"old": "3490", "new": "3990"})
    assert runs[0].returncode == 0
    assert out.read_text().strip() == "price_changed|Netflix|3990|3490"
    payload = json.loads((tmp_path / "out.json.stdin").read_text())
    assert payload["subscription"]["service"] == "Netflix" and payload["old"] == "3490"


def test_hook_failure_and_timeout_do_not_raise(tmp_path):
    cfg = Config.model_validate({"hooks": {"job_failed": ["exit 3", "sleep 5"], "timeout": 1}})
    runs = run_hooks(cfg, "job_failed", None, {"error": "boom"})
    assert runs[0].returncode == 3 and runs[1].timed_out


def test_unknown_event_and_empty_list():
    assert run_hooks(Config(), "nope") == []
    assert run_hooks(Config(), "new_subscription", netflix()) == []


def test_hooks_fire_from_scan(tmp_path):
    marker = tmp_path / "events.log"
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    rows = ["Дата;Сумма;Описание"] + [f"14.{m:02d}.2026;-1 590,00;SPOTIFY" for m in range(6, 11)]
    (inbox / "s.csv").write_text("\n".join(rows), encoding="utf-8")
    write_config(f"""
[sources.statements]
inbox_dir = "{inbox}"
[sources.imap]
enabled = false
[hooks]
new_subscription = ['echo "new $SUBWATCH_SERVICE" >> {marker}']
""")
    ctx = AppContext.load(quiet_logs=True)
    run_job(ctx)
    ctx.close()
    assert "new Spotify" in marker.read_text()


# ---------------------------------------------------------------- plugins


PLUGIN = '''
from datetime import date
from decimal import Decimal
from subwatch.plugins import RawMessage, Source, Transaction, source


@source("mybank_api")
class MyBank(Source):
    kind = "transactions"

    def enabled(self, config):
        return bool(config.plugins.options.get("mybank_api", {}).get("enabled"))

    def fetch(self, ctx):
        assert ctx.options["token_name"] == "mybank"
        for m in range(6, 11):
            yield Transaction(date(2026, m, 9), Decimal("2990"), "KZT", "KINOPOISK HD")


@source("notes_mail")
class Notes(Source):
    def enabled(self, config):
        return True

    def fetch(self, ctx):
        yield RawMessage(source="notes_mail", key="n1", sender="billing@notion.so", sender_name="Notion",
                         subject="Your Notion receipt", text="Notion Plus $10.00 per month. Payment received.")
'''


def test_plugins_are_loaded_and_used(tmp_path):
    pdir = paths.plugins_dir()
    pdir.mkdir(parents=True)
    (pdir / "mybank.py").write_text(textwrap.dedent(PLUGIN), encoding="utf-8")
    (pdir / "broken.py").write_text("raise RuntimeError('nope')\n", encoding="utf-8")
    write_config('[sources.imap]\nenabled = false\n[plugins.options.mybank_api]\nenabled = true\n'
                 'token_name = "mybank"\n')
    ctx = AppContext.load(quiet_logs=True)
    errors = load_plugins(ctx.config)
    assert any("broken.py" in k for k in errors)
    assert "mybank_api" in REGISTRY and not REGISTRY["mybank_api"].builtin
    report = run_job(ctx)
    assert report.stats["mybank_api"]["transactions"] == 5
    assert ctx.store.find_by_service("Кинопоиск")[0].status == "active"
    assert ctx.store.find_by_service("Notion")
    ctx.close()


def test_plugin_can_be_disabled():
    pdir = paths.plugins_dir()
    pdir.mkdir(parents=True)
    (pdir / "mybank.py").write_text(textwrap.dedent(PLUGIN), encoding="utf-8")
    cfg = Config.model_validate({"plugins": {"disabled": ["notes_mail"]}})
    load_plugins(cfg)
    assert "notes_mail" not in available(cfg)
    assert load_plugins(Config.model_validate({"plugins": {"enabled": False}})) == {}


# ----------------------------------------------------------------- export


def test_csv_and_rows():
    rows = subscription_rows([netflix()], Config(), Rates("KZT", {}))
    assert rows[0]["category"] == "Видео" and rows[0]["monthly_base"] == "3990.00"
    text = to_csv(rows)
    assert text.splitlines()[0].startswith("№;Сервис;Сумма;Валюта")
    assert "Netflix;3990;KZT;1m" in text


def test_ics_format():
    ics = build_ics([netflix(), netflix(status="review", service="Okko", id=2)], Config(), today=date(2026, 10, 22))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 12  # 25.10.2026 .. 25.09.2027 (12 months ahead)
    assert "UID:sub-1-20261025@subwatch" in ics and "DTSTART;VALUE=DATE:20261025" in ics
    assert "SUMMARY:Netflix — 3\u00a0990\\,00\u00a0₸" in ics and "Okko" not in ics  # commas escaped
    assert "TRIGGER:-P1D" in ics and "URL:https://www.netflix.com/cancelplan" in ics
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))


def test_ics_options():
    cfg = Config.model_validate({"export": {"ics_months_ahead": 2, "ics_alarm_days": 0, "ics_include_review": True}})
    ics = build_ics([netflix(), netflix(status="review", service="Okko", id=2)], cfg, today=date(2026, 10, 22))
    assert "BEGIN:VALARM" not in ics and "Okko" in ics and ics.count("BEGIN:VEVENT") == 4


def test_ics_auto_written_to_configured_path(tmp_path):
    target = tmp_path / "cal" / "charges.ics"
    write_config(f'[export]\nics_path = "{target}"\n')
    ctx = AppContext.load()
    ctx.store.insert_subscription(netflix())
    ctx.after_change()
    assert target.exists() and "Netflix" in target.read_text(encoding="utf-8")
    ctx.close()
    write_ics([netflix()], Config(), target)
    assert target.stat().st_mode & 0o777 == 0o600
