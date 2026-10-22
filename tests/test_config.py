import os
import time
import tomllib
from importlib import resources

import pytest
from conftest import write_config

from subwatch import paths
from subwatch.config import editor
from subwatch.config.loader import (
    ConfigError,
    ConfigWatcher,
    cli_overrides,
    env_overrides,
    field_annotation,
    flatten,
    load_config,
)
from subwatch.config.schema import Config


def test_defaults_without_file():
    loaded = load_config()
    assert not loaded.exists
    assert loaded.config.currency.base == "KZT"
    assert loaded.origin("currency.base") == "default"


def test_priority_cli_over_env_over_file_over_default(monkeypatch):
    write_config('[currency]\nbase = "RUB"\n[reminders]\ntime = "09:00"\n')
    assert load_config().config.currency.base == "RUB"
    monkeypatch.setenv("SUBWATCH_CURRENCY__BASE", "USD")
    loaded = load_config()
    assert loaded.config.currency.base == "USD" and loaded.origin("currency.base") == "env"
    loaded = load_config(cli=cli_overrides(["currency.base=EUR"]))
    assert loaded.config.currency.base == "EUR" and loaded.origin("currency.base") == "cli"
    assert loaded.origin("reminders.time") == "file"
    assert loaded.origin("reminders.days_before") == "default"


def test_env_parsing():
    env = {
        "SUBWATCH_REMINDERS__DAYS_BEFORE": "7,3,1",
        "SUBWATCH_SCAN__MONTHS_BACK": "6",
        "SUBWATCH_AI__ENABLED": "true",
        "SUBWATCH_REMINDERS__QUIET_HOURS__START": "23:00",
        "SUBWATCH_NOW": "ignored, no double underscore",
    }
    data = env_overrides(env)
    assert data["scan"]["months_back"] == 6 and data["ai"]["enabled"] is True
    cfg = load_config(environ=env).config
    assert cfg.reminders.days_before == [7, 3, 1]
    assert cfg.reminders.quiet_hours.start == "23:00"
    assert cfg.scan.months_back == 6


def test_validation_messages_are_russian():
    write_config('[scan]\nmonths_back = "много"\nunknown = 1\n[reminders]\ntime = "25:00"\n'
                 '[ui]\ndate_style = "x"\n')
    with pytest.raises(ConfigError) as err:
        load_config()
    text = err.value.render()
    assert "ожидается целое число" in text
    assert "неизвестный параметр" in text
    assert "не время суток" in text
    assert "допустимые значения" in text and " или " in text


def test_toml_syntax_error_has_position():
    write_config("[scan\nmonths_back = 1\n")
    with pytest.raises(ConfigError) as err:
        load_config()
    assert "строке 1" in err.value.render()


def test_template_is_valid_and_matches_defaults():
    text = (resources.files("subwatch") / "resources" / "config.default.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    cfg = Config.model_validate(data)
    assert editor.diff(cfg) == []


def test_template_documents_every_option():
    text = (resources.files("subwatch") / "resources" / "config.default.toml").read_text(encoding="utf-8")
    flat = flatten(editor.plain(Config()))
    missing = []
    for key in flat:
        leaf = key.split(".")[-1]
        if key.startswith("categories."):
            continue
        if not any(line.lstrip("# ").startswith(leaf + " =") or line.lstrip("# ").startswith(f"[[{key}") or
                   line.startswith(f"[{key}]") or
                   line.lstrip("# ").startswith(leaf) for line in text.splitlines()):
            missing.append(key)
    for section in ("category_rules", "tag_rules", "reminders.rules", "sources.imap.accounts"):
        assert section.split(".")[-1] in text
    assert missing == []
    # Every option line is preceded by a comment.
    # Every option line is preceded by a comment; category tables share one
    # header comment that describes name/icon/budget.
    lines = text.splitlines()
    section = ""
    for i, line in enumerate(lines):
        if line.startswith("["):
            section = line
        if section.startswith("[categories."):
            continue
        if line and not line.startswith(("#", "[")) and "=" in line and not line.startswith(" "):
            assert lines[i - 1].startswith("#") or lines[i - 1].startswith("["), line
    assert "budget — месячный лимит" in text


def test_set_preserves_comments_and_validates():
    path, created = editor.ensure_config_file()
    assert created and path.stat().st_mode & 0o777 == 0o600
    old, new = editor.set_value("reminders.days_before", "7,3,1", path)
    assert new == [7, 3, 1]
    text = path.read_text(encoding="utf-8")
    assert "days_before = [7, 3, 1]" in text
    assert "# За сколько дней до списания напоминать" in text
    editor.set_value("ui.language", "en", path)
    assert load_config(path).config.ui.language == "en"
    with pytest.raises(ConfigError):
        editor.set_value("reminders.time", "завтра", path)
    assert load_config(path).config.reminders.time == "10:00"
    with pytest.raises(ConfigError):
        editor.set_value("no.such.key", "1", path)
    editor.set_value("currency.manual_rates.USD", "520.5", path)
    assert str(load_config(path).config.currency.manual_rates["USD"]) == "520.5"


def test_unset_reset_and_diff():
    path, _ = editor.ensure_config_file()
    editor.set_value("scan.months_back", "6", path)
    diff = {k: (a, b) for k, a, b in editor.diff(load_config(path).config)}
    assert diff["scan.months_back"] == (12, 6)
    assert editor.unset_value("scan.months_back", path)
    assert load_config(path).config.scan.months_back == 12
    editor.set_value("scan.months_back", "3", path)
    saved = editor.reset_file(path)
    assert saved is not None and saved.exists()
    assert load_config(path).config.scan.months_back == 12


def test_hot_reload_watcher():
    path, _ = editor.ensure_config_file()
    watcher = ConfigWatcher(load_config(path))
    assert watcher.poll() is None
    time.sleep(0.01)
    editor.set_value("ui.keys.down", "ctrl+n", path)
    os.utime(path, (time.time() + 2, time.time() + 2))
    fresh = watcher.poll()
    assert fresh is not None and fresh.config.ui.keys.down == "ctrl+n"
    path.write_text(path.read_text(encoding="utf-8") + "\n[broken\n", encoding="utf-8")
    os.utime(path, (time.time() + 4, time.time() + 4))
    assert watcher.poll() is None and watcher.last_error is not None
    assert watcher.loaded.config.ui.keys.down == "ctrl+n"


def test_field_annotation_lookup():
    assert field_annotation("reminders.days_before") == list[int]
    assert field_annotation("categories.music.budget").__name__ == "Decimal"
    with pytest.raises(KeyError):
        field_annotation("nope")


def test_categories_always_have_other_and_names():
    cfg = Config.model_validate({"categories": {"health": {"icon": "x"}}})
    assert "other" in cfg.categories and cfg.categories["health"].name == "health"
    assert Config().categories["video"].name == "Видео"
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Config.model_validate({"category_rules": [{"category": "missing"}]})


def test_config_file_location_override(monkeypatch, tmp_path):
    custom = tmp_path / "other.toml"
    custom.write_text('[currency]\nbase = "GEL"\n', encoding="utf-8")
    monkeypatch.setenv("SUBWATCH_CONFIG", str(custom))
    assert paths.config_file() == custom
    assert load_config().config.currency.base == "GEL"
