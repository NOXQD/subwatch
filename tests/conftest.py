"""Shared fixtures. Every test runs in its own XDG tree with an in-memory
keyring, a frozen clock and no access to the real desktop, network or
systemd."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

sys.path.insert(0, str(Path(__file__).parent))

NOW = "2026-10-22T12:00:00"


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.data.get((service, username))

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.data:
            raise PasswordDeleteError(username)
        del self.data[(service, username)]


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        d = tmp_path / var.lower()
        d.mkdir()
        monkeypatch.setenv(var, str(d))
    run = tmp_path / "runtime"
    run.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(run))
    monkeypatch.setenv("SUBWATCH_NOW", NOW)
    monkeypatch.setenv("SUBWATCH_NOTIFY_RECORD", str(tmp_path / "notifications.jsonl"))
    monkeypatch.setenv("SUBWATCH_LOGGING__JOURNAL", "false")
    for var in list(os.environ):
        if var.startswith("SUBWATCH_") and var not in ("SUBWATCH_NOW", "SUBWATCH_NOTIFY_RECORD",
                                                        "SUBWATCH_LOGGING__JOURNAL"):
            monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)
    monkeypatch.delenv("OMARCHY_PATH", raising=False)
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    from subwatch import clock, i18n, log

    i18n.reset_cache()
    i18n.set_language("ru")
    clock.set_timezone("Asia/Almaty")
    log.configure("debug", journal=False, quiet=True)
    from subwatch.cli.common import State

    State.app = None
    State.overrides = []
    State.config_path = None
    State.quiet = False
    yield tmp_path
    clock.set_timezone("local")
    i18n.set_language("ru")


@pytest.fixture
def keyring_backend():
    return keyring.get_keyring()


@pytest.fixture
def notifications(sandbox):
    path = sandbox / "notifications.jsonl"

    def read():
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    return read


@pytest.fixture
def config():
    from subwatch.config.schema import Config

    return Config()


@pytest.fixture
def store():
    from subwatch.db import Store

    s = Store.memory()
    yield s
    s.conn.close()


@pytest.fixture
def app_ctx():
    from subwatch.app import AppContext

    ctx = AppContext.load()
    yield ctx
    ctx.close()


def write_config(text: str) -> Path:
    from subwatch import paths

    path = paths.config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
