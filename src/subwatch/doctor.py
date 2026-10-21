"""`subwatch doctor`: environment, secrets, permissions, timers, integration."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable

from . import clock, paths, secrets
from .config.loader import ConfigError, load_config
from .config.schema import Config


@dataclass
class Check:
    group: str
    status: str  # ok | warn | fail | info
    key: str
    params: dict[str, Any] = field(default_factory=dict)
    hint: str | None = None
    fix: Callable[[], bool] | None = None


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _chmod(path: Path, mode: int) -> Callable[[], bool]:
    def run() -> bool:
        path.chmod(mode)
        return True

    return run


def check_environment() -> list[Check]:
    out = []
    v = sys.version_info
    out.append(Check("env", "ok" if v >= (3, 12) else "fail", "doctor.env.python",
                     {"version": f"{v.major}.{v.minor}.{v.micro}"}, None if v >= (3, 12) else "doctor.hint.python"))
    exe = shutil.which("subwatch")
    out.append(Check("env", "ok" if exe else "warn", "doctor.env.on_path" if exe else "doctor.env.not_on_path",
                     {"path": paths.contract_home(exe or "")}, None if exe else "doctor.hint.install"))
    if shutil.which("fc-list"):
        try:
            fonts = subprocess.run(["fc-list", ":lang=ru", "family"], capture_output=True, text=True, timeout=10)
            has = bool(fonts.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            has = True
        out.append(Check("env", "ok" if has else "warn", "doctor.env.fonts" if has else "doctor.env.no_fonts",
                         {}, None if has else "doctor.hint.fonts"))
    return out


def check_config() -> tuple[list[Check], Config | None]:
    path = paths.config_file()
    out = []
    config = None
    if not path.exists():
        out.append(Check("config", "warn", "doctor.config.missing", {"path": paths.contract_home(path)},
                         "doctor.hint.config_missing", fix=_create_config))
        try:
            config = load_config(path).config
        except ConfigError:
            config = Config()
        return out, config
    try:
        config = load_config(path).config
        out.append(Check("config", "ok", "doctor.config.valid", {"path": paths.contract_home(path)}))
    except ConfigError as exc:
        out.append(Check("config", "fail", "doctor.config.invalid",
                         {"path": paths.contract_home(path), "errors": "; ".join(f"{k}: {m}" for k, m in exc.problems)},
                         "doctor.hint.config_invalid"))
        return out, None
    if _mode(path) & 0o077:
        out.append(Check("config", "warn", "doctor.config.perms", {"mode": oct(_mode(path))},
                         "doctor.hint.chmod", fix=_chmod(path, 0o600)))
    return out, config


def _create_config() -> bool:
    from .config.editor import ensure_config_file

    ensure_config_file()
    return True


def check_storage(config: Config) -> list[Check]:
    from .db import Store, db_path_for

    out = []
    data = paths.data_dir()
    if data.exists() and _mode(data) & 0o077:
        out.append(Check("storage", "warn", "doctor.storage.dir_perms", {"path": paths.contract_home(data),
                                                                          "mode": oct(_mode(data))},
                         "doctor.hint.chmod", fix=_chmod(data, 0o700)))
    db = db_path_for(config)
    target = Path(str(db) + ".enc") if config.storage.encrypt else db
    if not target.exists():
        out.append(Check("storage", "info", "doctor.storage.no_db", {"path": paths.contract_home(target)}))
        return out
    mode = _mode(target)
    if mode & 0o077:
        out.append(Check("storage", "fail", "doctor.storage.db_perms", {"mode": oct(mode)},
                         "doctor.hint.chmod", fix=_chmod(target, 0o600)))
    else:
        out.append(Check("storage", "ok", "doctor.storage.db_ok",
                         {"path": paths.contract_home(target), "mode": oct(mode)}))
    try:
        with Store.open(config) as store:
            ok = store.integrity_ok()
            out.append(Check("storage", "ok" if ok else "fail",
                             "doctor.storage.integrity" if ok else "doctor.storage.corrupt",
                             {"version": store.schema_version()}, None if ok else "doctor.hint.corrupt"))
    except Exception as exc:
        out.append(Check("storage", "fail", "doctor.storage.open_failed", {"detail": str(exc)},
                         "doctor.hint.corrupt"))
    if config.storage.encrypt:
        has_key = secrets.exists(secrets.DB_KEY_NAME)
        out.append(Check("storage", "ok" if has_key else "fail",
                         "doctor.storage.key_ok" if has_key else "doctor.storage.no_key", {},
                         None if has_key else "crypto.hint.no_key"))
    return out


def check_secrets(config: Config, online: bool = False) -> list[Check]:
    out = []
    ok, backend = secrets.backend_ok()
    out.append(Check("secrets", "ok" if ok else "fail", "doctor.secrets.backend" if ok else "doctor.secrets.bad_backend",
                     {"backend": backend}, None if ok else "doctor.hint.keyring"))
    if not ok:
        return out
    gm = config.sources.gmail
    if gm.enabled:
        has = secrets.exists(secrets.gmail_token_name(gm.account))
        out.append(Check("secrets", "ok" if has else "fail", "doctor.secrets.gmail_ok" if has else "doctor.secrets.gmail_missing",
                         {"account": gm.account}, None if has else "gmail.hint.auth"))
        if has and online:
            from .errors import SubwatchError
            from .sources.gmail import load_credentials

            try:
                load_credentials(gm.account)
                out.append(Check("secrets", "ok", "doctor.secrets.gmail_refresh_ok", {"account": gm.account}))
            except SubwatchError as exc:
                out.append(Check("secrets", "fail", "doctor.secrets.gmail_refresh_failed",
                                 {"account": gm.account, "detail": exc.message}, "gmail.hint.refresh"))
    if config.sources.imap.enabled:
        for acc in config.sources.imap.accounts:
            if not acc.enabled:
                continue
            has = secrets.exists(secrets.imap_password_name(acc.name))
            out.append(Check("secrets", "ok" if has else "fail",
                             "doctor.secrets.imap_ok" if has else "doctor.secrets.imap_missing",
                             {"account": acc.name}, None if has else "imap.hint.no_password"))
    if config.ai.enabled:
        from .ai import needs_key

        if needs_key(config.ai):
            has = secrets.exists(secrets.ai_key_name(config.ai.provider))
            out.append(Check("secrets", "ok" if has else "fail",
                             "doctor.secrets.ai_ok" if has else "doctor.secrets.ai_missing",
                             {"provider": config.ai.provider}, None if has else "ai.hint.key"))
    if not gm.enabled and not config.sources.imap.accounts and not config.sources.statements.inbox_dir:
        out.append(Check("secrets", "info", "doctor.secrets.no_sources", {}, "doctor.hint.add_source"))
    return out


def check_notifications(config: Config) -> list[Check]:
    from .notify import resolve_backend, server_name

    name = server_name()
    backend = resolve_backend(config.notifications)
    if backend == "none":
        return [Check("notify", "warn", "doctor.notify.disabled", {}, "doctor.hint.notify_backend")]
    if name is None:
        return [Check("notify", "warn", "doctor.notify.no_daemon", {"backend": backend}, "doctor.hint.notify")]
    return [Check("notify", "ok", "doctor.notify.ok", {"daemon": name, "backend": backend})]


def check_systemd(config: Config) -> list[Check]:
    from .integrate import systemd

    if not systemd.systemd_available():
        return [Check("systemd", "warn", "doctor.systemd.unavailable", {}, "doctor.hint.systemd")]
    out = []
    current = systemd.units_current(config)
    out.append(Check("systemd", "ok" if current else "fail",
                     "doctor.systemd.units_ok" if current else "doctor.systemd.units_stale",
                     {}, None if current else "doctor.hint.integrate",
                     fix=None if current else (lambda: _integrate(config, ["systemd"]))))
    for timer in systemd.TIMERS:
        enabled, active, nxt = systemd.timer_state(timer)
        good = enabled and active
        out.append(Check("systemd", "ok" if good else "fail",
                         "doctor.systemd.timer_ok" if good else "doctor.systemd.timer_off",
                         {"timer": timer, "next": _usec_text(nxt)}, None if good else "doctor.hint.integrate",
                         fix=None if good else (lambda: _integrate(config, ["systemd"]))))
    result = subprocess.run(["systemctl", "--user", "show", "subwatch-scan.service", "--property=Result",
                             "--value"], capture_output=True, text=True, timeout=5) if shutil.which("systemctl") else None
    if result is not None and result.stdout.strip() not in ("", "success"):
        out.append(Check("systemd", "warn", "doctor.systemd.last_failed", {"result": result.stdout.strip()},
                         "doctor.hint.logs"))
    return out


def _usec_text(value: str | None) -> str:
    return value or "—"


def _integrate(config: Config, only: list[str]) -> bool:
    from .integrate import apply_all

    steps = apply_all(config, only=only)
    return not any(s.status == "failed" for s in steps)


def check_integration(config: Config) -> list[Check]:
    from .integrate import completion_targets, hyprland, launchers, omarchy

    out = []
    if omarchy.is_omarchy():
        bar_ok = omarchy.bar_installed()
        out.append(Check("integration", "ok" if bar_ok else "fail",
                         "doctor.int.bar_ok" if bar_ok else "doctor.int.bar_missing",
                         {"path": paths.contract_home(omarchy.shell_file())}, None if bar_ok else "doctor.hint.integrate",
                         fix=None if bar_ok else (lambda: _integrate(config, ["bar"]))))
        if config.menu.enabled:
            menu_ok = omarchy.menu_installed()
            out.append(Check("integration", "ok" if menu_ok else "fail",
                             "doctor.int.menu_ok" if menu_ok else "doctor.int.menu_missing",
                             {"path": paths.contract_home(omarchy.menu_file())},
                             None if menu_ok else "doctor.hint.integrate",
                             fix=None if menu_ok else (lambda: _integrate(config, ["menu"]))))
        hook_ok = omarchy.hook_file().exists()
        out.append(Check("integration", "ok" if hook_ok else "warn",
                         "doctor.int.hook_ok" if hook_ok else "doctor.int.hook_missing", {},
                         None if hook_ok else "doctor.hint.integrate",
                         fix=None if hook_ok else (lambda: _integrate(config, ["hook"]))))
    else:
        out.append(Check("integration", "info", "doctor.int.not_omarchy", {}))
    desktop_ok = launchers.desktop_file().exists()
    out.append(Check("integration", "ok" if desktop_ok else "warn",
                     "doctor.int.desktop_ok" if desktop_ok else "doctor.int.desktop_missing", {},
                     None if desktop_ok else "doctor.hint.integrate",
                     fix=None if desktop_ok else (lambda: _integrate(config, ["launchers"]))))
    if config.keybinds.enabled:
        for step in hyprland.status(config):
            status = {"unchanged": "ok", "failed": "fail", "skipped": "warn"}.get(step.status, "info")
            key = {"integrate.keys.status_ok": "doctor.int.keys_ok",
                   "integrate.keys.status_missing": "doctor.int.keys_missing",
                   "integrate.keys.reload_errors": "doctor.int.keys_errors",
                   "integrate.keys.conflict": "doctor.int.keys_conflict"}.get(step.key, step.key)
            hint = None
            fix = None
            if status == "fail":
                hint = "doctor.hint.integrate"
                fix = lambda: _integrate(config, ["keybinds"])  # noqa: E731
            elif status == "warn":
                hint = "doctor.hint.keys_conflict"
            out.append(Check("integration", status, key, step.params, hint, fix))
    if launchers.waybar_present():
        wired = "custom/subwatch" in (launchers.waybar_config() or Path("/dev/null")).read_text(encoding="utf-8")
        out.append(Check("integration", "ok" if wired else "warn",
                         "doctor.int.waybar_ok" if wired else "doctor.int.waybar_missing", {},
                         None if wired else "doctor.hint.waybar"))
    if launchers.walker_present():
        ok = launchers.elephant_file().exists()
        out.append(Check("integration", "ok" if ok else "warn",
                         "doctor.int.walker_ok" if ok else "doctor.int.walker_missing", {},
                         None if ok else "doctor.hint.integrate"))
    comp = completion_targets()
    missing = [s for s, p in comp.items() if not p.exists()]
    out.append(Check("integration", "ok" if not missing else "warn",
                     "doctor.int.completion_ok" if not missing else "doctor.int.completion_missing",
                     {"shells": ", ".join(missing or comp)}, None if not missing else "doctor.hint.integrate",
                     fix=None if not missing else (lambda: _integrate(config, ["completion"]))))
    return out


def check_data(config: Config) -> list[Check]:
    from .db import Store, db_path_for
    from .fx import get_rates
    from .sources.base import PLUGIN_ERRORS, load_plugins

    out = []
    load_plugins(config)
    for path, error in PLUGIN_ERRORS.items():
        out.append(Check("plugins", "warn", "doctor.plugins.error", {"path": paths.contract_home(path),
                                                                      "detail": error}, "doctor.hint.plugin"))
    db = db_path_for(config)
    if not (db.exists() or Path(str(db) + ".enc").exists()):
        return out
    with Store.open(config) as store:
        subs = store.active_subscriptions()
        foreign = sorted({s.currency for s in subs if s.currency and s.currency != config.currency.base})
        if foreign:
            rates = get_rates(store, config)
            missing = [c for c in foreign if not rates.has(c)]
            if missing:
                out.append(Check("rates", "warn", "doctor.rates.missing", {"codes": ", ".join(missing)},
                                 "doctor.hint.rates"))
            elif rates.fetched_at is None:
                out.append(Check("rates", "ok", "doctor.rates.manual_only", {}))
            elif rates.stale and config.currency.rates_source != "manual":
                out.append(Check("rates", "warn", "doctor.rates.stale",
                                 {"when": clock.iso(rates.fetched_at) if rates.fetched_at else "—"},
                                 "doctor.hint.rates"))
            else:
                out.append(Check("rates", "ok", "doctor.rates.ok", {"source": rates.source}))
        cursors = store.cursors()
        if cursors:
            last = max(clock.parse_iso(r["updated_at"]) for r in cursors)
            old = clock.now() - last > timedelta(days=3)
            out.append(Check("scan", "warn" if old else "ok",
                             "doctor.scan.old" if old else "doctor.scan.recent",
                             {"when": clock.iso(last)}, "doctor.hint.logs" if old else None))
        review = len(store.review_queue())
        if review:
            out.append(Check("scan", "info", "doctor.scan.review", {"count": review}))
    return out


def run_checks(online: bool = False) -> list[Check]:
    checks = check_environment()
    cfg_checks, config = check_config()
    checks += cfg_checks
    if config is None:
        return checks
    checks += check_storage(config)
    checks += check_secrets(config, online)
    checks += check_notifications(config)
    checks += check_systemd(config)
    checks += check_integration(config)
    checks += check_data(config)
    return checks


def summary(checks: list[Check]) -> dict[str, int]:
    out = {"ok": 0, "warn": 0, "fail": 0, "info": 0}
    for c in checks:
        out[c.status] += 1
    return out


def exit_code(checks: list[Check]) -> int:
    s = summary(checks)
    return 1 if s["fail"] else 0


def in_session() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))
