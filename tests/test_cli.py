"""CLI behaviour through the real entry point (subwatch.__main__.main)."""

import json
import re

import pytest

from conftest import write_config
from subwatch.__main__ import main


def run(capsys, *args, code=0):
    try:
        main(list(args))
        rc = 0
    except SystemExit as exc:
        rc = exc.code or 0
    out = capsys.readouterr()
    assert rc == code, out.out + out.err
    return out.out, out.err


def test_help_is_russian(capsys):
    out, _ = run(capsys, "--help")
    assert "Использование:" in out and "Параметры" in out and "Команды" in out
    assert "Показать эту справку и выйти" in out
    assert "Usage" not in out and "Show this message" not in out
    out, _ = run(capsys, "scan", "--help")
    assert "Найти подписки в почте" in out and "--dry-run" in out


def test_errors_are_russian(capsys):
    _, err = run(capsys, "no-such-command", code=2)
    assert "Нет такой команды" in err
    _, err = run(capsys, "show", code=2)
    assert "Не указан аргумент" in err
    _, err = run(capsys, "list", "--bogus", code=2)
    assert "Нет такого параметра" in err
    _, err = run(capsys, "upcoming", "--days", "abc", code=2)
    assert "не целое число" in err


def test_add_list_show_edit_remove(capsys):
    out, _ = run(capsys, "add", "Netflix", "--amount", "3 990 ₸", "--next", "2026-10-25")
    assert "Добавлено: Netflix" in out
    run(capsys, "add", "Spotify", "--amount", "4.99 USD", "--next", "1 ноября", "--tag", "семья")
    run(capsys, "rates", "set", "USD", "520")
    out, _ = run(capsys, "list")
    assert "Netflix" in out and "25 октября, через 3 дня" in out.replace("\n", " ").replace("  ", " ") or "через 3" in out
    assert "Итого:" in out
    out, _ = run(capsys, "list", "--json")
    data = json.loads(out)
    assert {r["service"] for r in data} == {"Netflix", "Spotify"}
    assert next(r for r in data if r["service"] == "Netflix")["category"] == "Видео"
    out, _ = run(capsys, "show", "Netflix")
    assert "netflix.com/cancelplan" in out
    run(capsys, "edit", "Netflix", "--amount", "4490", "--category", "Прочее")
    out, _ = run(capsys, "show", "1", "--json")
    assert json.loads(out)["amount"] == "4490" and json.loads(out)["category"] == "Прочее"
    _, err = run(capsys, "add", "Netflix", "--amount", "1", code=1)
    assert "уже есть" in err
    run(capsys, "remove", "Spotify", "--yes")
    out, _ = run(capsys, "list", "--json")
    assert [r["service"] for r in json.loads(out)] == ["Netflix"]


def test_not_found_has_hint(capsys):
    _, err = run(capsys, "show", "Nope", code=2)
    assert "не найдена" in err and "subwatch list" in err


def test_upcoming_and_spend(capsys):
    run(capsys, "add", "Netflix", "--amount", "3990", "--next", "+3d")
    run(capsys, "add", "iCloud", "--amount", "1490", "--next", "+20d", "--category", "cloud")
    out, _ = run(capsys, "upcoming", "--days", "7")
    assert "Netflix" in out and "iCloud" not in out and "через 3 дня" in out
    out, _ = run(capsys, "spend")
    assert "5 480,00 ₸ в месяц" in out
    out, _ = run(capsys, "spend", "--json")
    assert json.loads(out)["monthly"] == "5480.00"


def test_upcoming_notify_records_notification(capsys, notifications):
    run(capsys, "add", "Netflix", "--amount", "3990", "--next", "+3d")
    run(capsys, "upcoming", "--notify")
    notes = notifications()
    assert notes and "Netflix" in notes[-1]["body"]


def test_config_commands(capsys, monkeypatch):
    out, _ = run(capsys, "config", "get", "reminders.days_before", "--source")
    assert "[3, 1]" in out and "по умолчанию" in out
    out, _ = run(capsys, "config", "set", "reminders.days_before", "7,3,1")
    assert "[7, 3, 1]" in out
    out, _ = run(capsys, "config", "get", "reminders.days_before", "--source")
    assert "из config.toml" in out
    monkeypatch.setenv("SUBWATCH_REMINDERS__DAYS_BEFORE", "[2]")
    out, _ = run(capsys, "config", "get", "reminders.days_before", "--source")
    assert "[2]" in out and "из переменной окружения" in out
    out, _ = run(capsys, "--set", "reminders.days_before=[5]", "config", "get", "reminders.days_before", "--source")
    assert "[5]" in out and "из командной строки" in out
    monkeypatch.delenv("SUBWATCH_REMINDERS__DAYS_BEFORE")
    out, _ = run(capsys, "config", "diff")
    assert "reminders.days_before" in out
    _, err = run(capsys, "config", "set", "scan.months_back", "много", code=78)
    assert "ожидается целое число" in err
    out, _ = run(capsys, "config", "check")
    assert "в порядке" in out


def test_broken_config_is_explained(capsys):
    write_config("[reminders]\ntime = '25:99'\n")
    _, err = run(capsys, "list", code=78)
    assert "не время суток" in err and "subwatch config check" in err


def test_bar_output_and_fast_path(capsys):
    run(capsys, "add", "Netflix", "--amount", "3990", "--next", "+2d")
    out, _ = run(capsys, "bar")
    data = json.loads(out)
    assert "Netflix" in data["text"] and "через 2 дня" in data["text"]
    assert "Ближайшие списания" in data["tooltip"]
    assert "subwatch" in data["class"]
    out2, _ = run(capsys, "bar")
    assert out2 == out  # served from cache
    out, _ = run(capsys, "bar", "--format", "text")
    assert "Netflix" in out and not out.startswith("{")


def test_bar_shows_total_when_nothing_soon(capsys):
    run(capsys, "add", "iCloud", "--amount", "1490", "--next", "+20d")
    data = json.loads(run(capsys, "bar")[0])
    assert "1 490" in data["text"]


def test_bar_over_budget_class(capsys):
    write_config("[budget]\nmonthly_limit = 1000\n")
    run(capsys, "add", "iCloud", "--amount", "1490", "--next", "+20d")
    data = json.loads(run(capsys, "bar")[0])
    assert "over-budget" in data["class"] and "active" in data["class"]
    assert "превышен" in data["tooltip"]


def test_export(capsys, tmp_path):
    run(capsys, "add", "Netflix", "--amount", "3990", "--next", "2026-10-25")
    out, _ = run(capsys, "export", "csv")
    assert out.splitlines()[0].startswith("№;Сервис;Сумма")
    out, _ = run(capsys, "export", "json")
    assert json.loads(out)["subscriptions"][0]["service"] == "Netflix"
    target = tmp_path / "c.ics"
    run(capsys, "export", "ics", "--output", str(target))
    ics = target.read_text(encoding="utf-8")
    assert "BEGIN:VCALENDAR" in ics and "DTSTART;VALUE=DATE:20261025" in ics and "TRIGGER:-P1D" in ics


def test_version(capsys):
    out, _ = run(capsys, "--version")
    assert re.match(r"Subwatch \d+\.\d+\.\d+", out)


def test_language_switch_from_config(capsys):
    write_config('[ui]\nlanguage = "en"\n')
    out, _ = run(capsys, "upcoming")
    assert "No charges" in out or "charges" in out.lower()


@pytest.mark.parametrize("cmd", [["doctor", "--help"], ["review", "--help"], ["import", "--help"],
                                 ["config", "set", "--help"], ["auth", "gmail", "--help"]])
def test_subcommand_help_has_no_english_chrome(capsys, cmd):
    out, _ = run(capsys, *cmd)
    assert "Usage:" not in out and "Options" not in out and "Arguments" not in out
