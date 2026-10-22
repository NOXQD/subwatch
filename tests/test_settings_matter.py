"""Each setting from the "behaviour, not looks" list changes what the
program does. Settings covered elsewhere are listed at the bottom."""

import json
import os
from datetime import date, timedelta
from decimal import Decimal

from conftest import write_config

from subwatch import clock, paths
from subwatch.__main__ import main
from subwatch.app import AppContext
from subwatch.classify import assign_category, assign_tags
from subwatch.config.schema import Config
from subwatch.models import Subscription
from subwatch.period import Period


def run(capsys, *args):
    try:
        main(list(args))
    except SystemExit:
        pass
    return capsys.readouterr()


def add(ctx, service, amount="1000", **kw):
    s = Subscription(service=service, amount=Decimal(amount), currency="KZT", period=Period("month", 1), **kw)
    return ctx.store.insert_subscription(s)


# ---------------------------------------------------------- 1. config


def test_config_edit_validates_after_saving(tmp_path, monkeypatch, capsys):
    editor = tmp_path / "editor.sh"
    editor.write_text('#!/bin/sh\nsed -i \'s/^months_back = 12/months_back = 3/\' "$1"\n')
    editor.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(editor))
    out = run(capsys, "config", "edit").out
    assert "в порядке" in out
    assert AppContext.load().config.scan.months_back == 3


# ------------------------------------------------- 2. reminder actions


def test_cancel_action_opens_cancellation_page(monkeypatch, store):
    from subwatch import reminders

    opened = []
    monkeypatch.setattr(reminders, "open_url", lambda url: opened.append(url) or True)
    s = store.insert_subscription(Subscription(service="Netflix", amount=Decimal(1), currency="KZT",
                                               next_charge=date(2026, 10, 25),
                                               cancel_url="https://www.netflix.com/cancelplan"))
    rid = store.ensure_reminder(s.id, date(2026, 10, 25), 3, "charge", clock.now())
    assert reminders.apply_action(store, Config(), rid, "cancel") == "remind.action.cancelled_opened"
    assert opened == ["https://www.netflix.com/cancelplan"]


def test_snooze_options_shown_in_action_menu(monkeypatch, capsys):
    from subwatch import picker

    write_config('[reminders]\nsnooze_options = ["2h", "5d"]\n')
    ctx = AppContext.load()
    s = add(ctx, "Okko", next_charge=date(2026, 10, 25))
    rid = ctx.store.ensure_reminder(s.id, date(2026, 10, 25), 3, "charge", clock.now())
    ctx.close()
    seen = {}

    def choose(prompt, options, preferred="auto"):
        seen["options"] = [o.value for o in options]
        seen["labels"] = [o.label for o in options]
        return "snooze:5d"

    monkeypatch.setattr(picker, "choose", choose)
    run(capsys, "notify-action", str(rid))
    assert seen["options"] == ["keep", "cancel", "snooze:2h", "snooze:5d"]
    assert "Отложить на 5 дней" in seen["labels"]
    ctx = AppContext.load()
    until = clock.parse_iso(ctx.store.reminder(rid)["snoozed_until"])
    assert until - clock.now() == timedelta(days=5)
    ctx.close()


# -------------------------------------------------- 3. categories, tags


def test_category_rules_beat_dictionary():
    cfg = Config.model_validate({
        "categories": {"work": {"name": "Работа"}, "education": {}, "video": {}},
        "category_rules": [{"category": "work", "services": ["GitHub Copilot"]},
                           {"category": "work", "senders": ["*@jetbrains.com"]},
                           {"category": "education", "keywords": ["курс"]}],
    })
    assert assign_category("GitHub Copilot", cfg, suggested="software") == "work"
    assert assign_category("JetBrains", cfg, sender="sales@jetbrains.com", suggested="software") == "work"
    assert assign_category("Мегадиск", cfg, text_cf="доступ к курсам на месяц") == "education"
    assert assign_category("Netflix", cfg, suggested="video") == "video"
    assert assign_category("Неизвестно", cfg) == "other"


def test_tag_rules():
    cfg = Config.model_validate({"tag_rules": [
        {"tag": "работа", "services": ["JetBrains"]}, {"tag": "развлечения", "categories": ["video"]},
        {"tag": "дорого", "min_amount": 10000}]})
    assert assign_tags("JetBrains", "software", cfg, amount_base=Decimal(150000)) == ["работа", "дорого"]
    assert assign_tags("Netflix", "video", cfg, amount_base=Decimal(3990)) == ["развлечения"]


def test_user_category_in_cli(capsys):
    write_config('[categories.health]\nname = "Здоровье"\nbudget = 5000\n')
    run(capsys, "add", "Fitbit Premium", "--amount", "2000", "--category", "Здоровье", "--next", "+5d")
    data = json.loads(run(capsys, "list", "--json").out)
    assert data[0]["category"] == "Здоровье"


# ------------------------------------------------------- 5. scan depth


def test_imap_folders_option():
    from fixtures.emails import EMAILS
    from mock_imap import Mailbox, MockImapServer, ServerState

    from subwatch import secrets
    from subwatch.scan import run_job

    state = ServerState()
    state.folders["Receipts"] = Mailbox()
    state.folders["Receipts"].append(EMAILS[0].to_bytes())
    with MockImapServer(state) as srv:
        for folders, expected in ((["INBOX"], 0), (["INBOX", "Receipts"], 1)):
            write_config(f"""
[[sources.imap.accounts]]
name = "mock"
host = "127.0.0.1"
port = {srv.port}
ssl = false
username = "user@example.org"
folders = {json.dumps(folders)}
""")
            secrets.put(secrets.imap_password_name("mock"), "app-password")
            ctx = AppContext.load(quiet_logs=True)
            report = run_job(ctx)
            assert report.stats["imap"]["seen"] == expected
            ctx.close()


def test_max_messages_option():
    from fixtures.emails import EMAILS
    from mock_imap import MockImapServer, ServerState

    from subwatch import secrets
    from subwatch.scan import run_job

    state = ServerState()
    for e in EMAILS:
        state.folders["INBOX"].append(e.to_bytes())
    with MockImapServer(state) as srv:
        write_config(f"""
[scan]
max_messages = 10
[[sources.imap.accounts]]
name = "mock"
host = "127.0.0.1"
port = {srv.port}
ssl = false
username = "user@example.org"
""")
        secrets.put(secrets.imap_password_name("mock"), "app-password")
        ctx = AppContext.load(quiet_logs=True)
        report = run_job(ctx)
        assert report.stats["imap"]["seen"] <= 10
        ctx.close()


def test_scan_priority_applied(monkeypatch):
    from subwatch import lock

    calls = []
    monkeypatch.setattr(os, "nice", lambda inc: calls.append(inc) or 0)
    monkeypatch.setattr(lock.subprocess, "run", lambda args, **kw: calls.append(tuple(args[:3])))
    monkeypatch.setattr(lock.shutil, "which", lambda name: "/usr/bin/ionice")
    lock.lower_priority(15, "idle")
    assert 15 in calls and ("ionice", "-c", "3") in calls
    calls.clear()
    lock.lower_priority(0, "none")
    assert calls == []


# ------------------------------------------------------------ 7. hooks


def test_zombie_hook(tmp_path):
    from subwatch.scan import react

    log = tmp_path / "z.log"
    write_config(f"[hooks]\nzombie_found = ['echo \"$SUBWATCH_SERVICE $SUBWATCH_DAYS\" >> {log}']\n")
    ctx = AppContext.load()
    add(ctx, "Coursera Plus", track_usage=True, last_used=clock.today() - timedelta(days=100))
    react(ctx, [])
    assert log.read_text().strip() == "Coursera Plus 45"
    ctx.close()


# ----------------------------------------------------- UI behaviour


def test_list_sort_date_style_decimals_and_cancelled(capsys):
    write_config('[ui]\ndefault_sort = "amount"\nsort_reverse = true\ndate_style = "relative"\n'
                 'money_decimals = 0\n')
    run(capsys, "add", "Cheap", "--amount", "100", "--next", "+3d")
    run(capsys, "add", "Pricey", "--amount", "9000", "--next", "+5d")
    run(capsys, "add", "Gone", "--amount", "500", "--next", "+5d")
    run(capsys, "cancel", "Gone", "--no-open")
    out = run(capsys, "list").out
    assert out.index("Pricey") < out.index("Cheap")
    assert "через 3 дня" in out and "октября" not in out
    assert "9 000 ₸" in out and ",00" not in out
    assert "Gone" not in out
    write_config('[ui]\nshow_cancelled = true\n')
    assert "Gone" in run(capsys, "list").out


def test_notifications_backend_none(monkeypatch, capsys, notifications):
    monkeypatch.delenv("SUBWATCH_NOTIFY_RECORD")
    write_config('[notifications]\nbackend = "none"\n')
    calls = []
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: calls.append(a))
    run(capsys, "add", "Netflix", "--amount", "1", "--next", "+1d")
    run(capsys, "upcoming", "--notify")
    assert calls == []


def test_notification_urgency(capsys, notifications):
    write_config('[notifications]\nurgency = "critical"\n[reminders]\ndays_before = [3]\n')
    run(capsys, "add", "Netflix", "--amount", "1", "--next", "+3d")
    run(capsys, "remind")
    assert [n["urgency"] for n in notifications() if n["kind"] == "reminder"] == ["critical"]


def test_bar_modes(capsys):
    run(capsys, "add", "Netflix", "--amount", "3990", "--next", "+5d")
    assert "Netflix" in json.loads(run(capsys, "bar").out)["text"]
    write_config('[bar]\nnext_within_days = 2\n')
    assert "3 990" in json.loads(run(capsys, "bar").out)["text"]
    write_config('[bar]\nmode = "next"\nnext_within_days = 0\n')
    assert "Netflix" in json.loads(run(capsys, "bar").out)["text"]
    write_config('[bar]\nmode = "total"\nicon = "$"\n')
    assert json.loads(run(capsys, "bar").out)["text"].startswith("$ 3")


def test_bar_hide_when_empty(capsys):
    write_config('[bar]\nhide_when_empty = true\n')
    assert json.loads(run(capsys, "bar").out)["text"] == ""


def test_logging_file(tmp_path, capsys):
    log = tmp_path / "subwatch.log"
    write_config(f'[logging]\nfile = "{log}"\nlevel = "debug"\n')
    run(capsys, "add", "Netflix", "--amount", "1", "--next", "+1d")
    run(capsys, "remind")
    assert "reminder_sent" in log.read_text()


def test_timezone_setting(capsys):
    write_config('[general]\ntimezone = "America/New_York"\n[reminders]\ndays_before = [0]\ntime = "09:00"\n')
    ctx = AppContext.load()
    assert str(clock.local_tz()) == "America/New_York"
    ctx.close()


COVERED_ELSEWHERE = {
    "priority cli > env > file > default": "test_config.py::test_priority_cli_over_env_over_file_over_default",
    "config set/unset/reset/diff/check": "test_config.py, test_cli.py::test_config_commands",
    "hot reload": "test_config.py::test_hot_reload_watcher, test_tui.py::test_hot_reload_rebinds_keys",
    "reminder days/time/rules/quiet/repeat/actions": "test_reminders.py",
    "budgets and monthly limit": "test_analysis.py::test_budgets_levels, test_reactions.py",
    "multi-currency": "test_fx.py, test_analysis.py",
    "scan schedule": "test_integration_files.py::test_systemd_units_follow_config",
    "months_back": "test_imap_integration.py::test_months_back_limits_first_scan",
    "gmail labels/query": "test_gmail.py::test_query_building",
    "exclusion filters": "test_imap_integration.py::test_folder_and_sender_filters, test_ingest.py",
    "not a subscription forever": "test_ingest.py::test_learned_rules, test_tui.py",
    "hooks": "test_hooks_plugins_export.py, test_reactions.py",
    "price/duplicates/zombies": "test_ingest.py, test_analysis.py, test_reactions.py",
    "export csv/json/ics": "test_cli.py::test_export, test_hooks_plugins_export.py",
    "keybinds": "test_integration_files.py",
    "ai settings": "test_ai.py",
}


def test_index_points_to_existing_tests():
    here = paths.Path(__file__).parent
    for where in COVERED_ELSEWHERE.values():
        for ref in where.split(", "):
            assert (here / ref.split("::")[0]).exists(), ref
