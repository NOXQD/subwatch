import json
import stat
import subprocess

import pytest
from conftest import write_config

from subwatch import doctor, paths, secrets
from subwatch.__main__ import main
from subwatch.config.schema import Config
from subwatch.db import Store, db_path_for
from subwatch.integrate import hyprland, systemd


@pytest.fixture
def fake_desktop(monkeypatch, tmp_path):
    import os
    import sys
    from pathlib import Path

    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setattr(systemd, "systemd_available", lambda: True)
    monkeypatch.setattr(systemd, "_systemctl", lambda *a: subprocess.CompletedProcess(a, 0, "enabled\n" if a[0] == "is-enabled" else ("active\n" if a[0] == "is-active" else ""), ""))
    monkeypatch.setattr(hyprland, "current_binds", lambda: [])
    monkeypatch.setattr("subwatch.notify.server_name", lambda: "quickshell")
    root = tmp_path / "omarchy"
    (root / "shell").mkdir(parents=True)
    monkeypatch.setenv("OMARCHY_PATH", str(root))
    hypr = paths.config_home() / "hypr"
    hypr.mkdir(parents=True)
    (hypr / "hyprland.lua").write_text("-- user\n", encoding="utf-8")
    (paths.config_home() / "omarchy").mkdir(parents=True, exist_ok=True)
    (paths.config_home() / "omarchy" / "shell.json").write_text('{"bar": {"layout": {"right": []}}}', encoding="utf-8")


def run_doctor(capsys, *args):
    try:
        main(["doctor", *args])
        code = 0
    except SystemExit as exc:
        code = exc.code or 0
    return code, capsys.readouterr().out


def statuses(checks):
    return {c.key: c.status for c in checks}


def test_doctor_reports_and_fix_makes_it_green(fake_desktop, capsys, monkeypatch):
    write_config("[scan]\nmonths_back = 6\n")
    paths.config_file().chmod(0o644)
    Store.open(Config()).close()
    db_path_for(Config()).chmod(0o644)
    code, out = run_doctor(capsys)
    assert code == 1
    assert "база доступна другим пользователям" in out and "subwatch doctor --fix" in out
    assert "модуля нет в панели Omarchy" in out
    code, out = run_doctor(capsys, "--fix")
    assert stat.S_IMODE(db_path_for(Config()).stat().st_mode) == 0o600
    checks = doctor.run_checks()
    bad = [(c.key, c.params) for c in checks if c.status in ("fail", "warn")]
    assert bad == [], bad
    code, out = run_doctor(capsys)
    assert code == 0 and "Всё в порядке" in out


def test_doctor_json(fake_desktop, capsys):
    code, out = run_doctor(capsys, "--json")
    data = json.loads(out)
    assert {"group", "status", "message", "hint"} <= set(data[0])
    assert all(isinstance(d["message"], str) and "doctor." not in d["message"] for d in data)


def test_missing_tokens_are_failures(fake_desktop):
    write_config('[sources.gmail]\nenabled = true\n[[sources.imap.accounts]]\nname = "w"\nhost = "h"\nusername = "u"\n')
    st = statuses(doctor.check_secrets(Config.model_validate({
        "sources": {"gmail": {"enabled": True}, "imap": {"accounts": [{"name": "w", "host": "h", "username": "u"}]}}})))
    assert st["doctor.secrets.gmail_missing"] == "fail" and st["doctor.secrets.imap_missing"] == "fail"
    secrets.put(secrets.imap_password_name("w"), "x")
    st = statuses(doctor.check_secrets(Config.model_validate({"sources": {"imap": {"accounts": [
        {"name": "w", "host": "h", "username": "u"}]}}})))
    assert st["doctor.secrets.imap_ok"] == "ok"


def test_insecure_keyring_detected(monkeypatch):
    import keyring
    from keyring.backends import fail

    keyring.set_keyring(fail.Keyring())
    st = statuses(doctor.check_secrets(Config()))
    assert st["doctor.secrets.bad_backend"] == "fail"


def test_invalid_config(capsys):
    write_config("[scan]\nmonths_back = -1\n")
    checks = doctor.run_checks()
    assert statuses(checks)["doctor.config.invalid"] == "fail"


def test_keybind_conflict_is_warned(fake_desktop, monkeypatch):
    monkeypatch.setattr(hyprland, "current_binds", lambda: [{"modmask": 68, "key": "U", "description": "Other"}])
    from subwatch.integrate import apply_all

    apply_all(Config(), only=["keybinds"])
    st = statuses(doctor.check_integration(Config()))
    assert st["doctor.int.keys_conflict"] == "warn"
