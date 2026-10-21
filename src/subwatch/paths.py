"""Filesystem locations.

Everything follows the XDG base directory spec, so tests (and people who keep
their dotfiles elsewhere) can relocate the whole app with the usual
XDG_* variables. SUBWATCH_CONFIG points at an alternative config file.
"""

from __future__ import annotations

import os
from pathlib import Path

APP = "subwatch"


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var, "")
    if value and os.path.isabs(value):
        return Path(value)
    return Path.home() / fallback


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def state_home() -> Path:
    return _xdg("XDG_STATE_HOME", ".local/state")


def cache_home() -> Path:
    return _xdg("XDG_CACHE_HOME", ".cache")


def config_dir() -> Path:
    return config_home() / APP


def config_file() -> Path:
    override = os.environ.get("SUBWATCH_CONFIG", "")
    if override:
        return Path(override).expanduser()
    return config_dir() / "config.toml"


def data_dir() -> Path:
    return data_home() / APP


def state_dir() -> Path:
    return state_home() / APP


def cache_dir() -> Path:
    return cache_home() / APP


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR", "")
    if base and os.path.isdir(base):
        return Path(base) / APP
    # No runtime dir (e.g. a cron job without a session): fall back to the
    # state dir, which is private to the user as well.
    return state_dir() / "run"


def banks_dir() -> Path:
    return config_dir() / "banks"


def plugins_dir() -> Path:
    return config_dir() / "plugins"


def user_merchants_file() -> Path:
    return config_dir() / "merchants.toml"


def user_i18n_dir() -> Path:
    return config_dir() / "i18n"


def db_file() -> Path:
    return data_dir() / "subwatch.db"


def bar_cache_file() -> Path:
    return cache_dir() / "bar.json"


def secrets_index_file() -> Path:
    return state_dir() / "secrets.json"


def ensure_private_dir(path: Path) -> Path:
    """Create a directory readable only by the owner."""
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        if path.stat().st_mode & 0o077:
            path.chmod(0o700)
    except OSError:
        pass
    return path


def contract_home(path: Path | str) -> str:
    """Render a path with ~ instead of the home directory, for display."""
    text = str(path)
    h = str(home())
    if text == h:
        return "~"
    if text.startswith(h + os.sep):
        return "~" + text[len(h):]
    return text


def expand(path: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(path)))
