"""Backend of the settings window: `subwatch gui-server`.

One JSON object per line in each direction. Requests look like
{"id": 7, "cmd": "set", "path": "reminders.time", "value": "09:00"}; replies are
{"id": 7, "ok": true, "data": ...} or {"id": 7, "ok": false, "error": "...",
"hint": "..."}. Lines without an id are events: {"event": "changed"} when the
database or config.toml changed behind the window's back, and
{"event": "scan", "state": "running" | "done", ...} while a scan runs.

The process lives exactly as long as the window and never prompts: anything
that needs a terminal (the Gmail wizard) is started in one.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from .. import __version__, paths
from ..app import AppContext
from ..config.loader import ConfigError, load_config
from ..errors import SubwatchError
from ..i18n import t
from . import settings, views

POLL_SECONDS = 1.5

Handler = Callable[["Server", dict[str, Any]], Any]
HANDLERS: dict[str, Handler] = {}


def command(name: str) -> Callable[[Handler], Handler]:
    def wrap(fn: Handler) -> Handler:
        HANDLERS[name] = fn
        return fn
    return wrap


class Reply(Exception):
    """Raised by a handler to fail with a catalog message."""

    def __init__(self, key: str, **params: Any):
        super().__init__(key)
        self.text = t(key, **params)


class Server:
    def __init__(self, out: TextIO | None = None):
        self.out = out or sys.stdout
        self.lock = threading.Lock()
        self.ctx = AppContext(load_config(), quiet_logs=True)
        self._stamps = self._current_stamps()
        self._stop = threading.Event()
        self.scanning = False

    # ------------------------------------------------------------ plumbing

    def send(self, message: dict[str, Any]) -> None:
        line = json.dumps(message, ensure_ascii=False, default=str)
        with self.lock:
            self.out.write(line + "\n")
            self.out.flush()

    def event(self, name: str, **data: Any) -> None:
        self.send({"event": name, **data})

    def _current_stamps(self) -> tuple[float, float]:
        def mtime(p: Path) -> float:
            best = 0.0
            for candidate in (p, Path(str(p) + "-wal"), Path(str(p) + ".enc")):
                try:
                    best = max(best, candidate.stat().st_mtime)
                except OSError:
                    pass
            return best

        return mtime(self.ctx.db_path), mtime(self.ctx.loaded.path)

    def mark_seen(self) -> None:
        """Our own writes are not news for the window."""
        self._stamps = self._current_stamps()

    def reload_config(self) -> None:
        fresh = load_config(self.ctx.loaded.path)
        self.ctx.reload(fresh)
        self.ctx.close()

    def watch(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            stamps = self._current_stamps()
            if stamps != self._stamps:
                config_changed = stamps[1] != self._stamps[1]
                self._stamps = stamps
                if config_changed:
                    try:
                        self.reload_config()
                    except ConfigError:
                        pass
                self.event("changed", config=config_changed)

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        rid = request.get("id")
        name = str(request.get("cmd", ""))
        fn = HANDLERS.get(name)
        if fn is None:
            return {"id": rid, "ok": False, "error": t("gui.err.unknown_command", name=name)}
        try:
            data = fn(self, request)
            return {"id": rid, "ok": True, "data": data}
        except Reply as exc:
            return {"id": rid, "ok": False, "error": exc.text}
        except SubwatchError as exc:
            return {"id": rid, "ok": False, "error": exc.message, "hint": exc.hint_text or ""}
        except ConfigError as exc:
            problems = [msg for _, msg in exc.problems] or [t("gui.err.config")]
            return {"id": rid, "ok": False, "error": "\n".join(problems)}
        except Exception as exc:  # the window must survive anything
            from .. import log

            log.error("gui_failed", command=name, error=repr(exc))
            return {"id": rid, "ok": False, "error": t("gui.err.internal", detail=str(exc))}

    def serve(self, inp: TextIO | None = None) -> None:
        inp = inp or sys.stdin
        watcher = threading.Thread(target=self.watch, daemon=True)
        watcher.start()
        self.event("ready", version=__version__)
        for line in inp:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                continue
            if not isinstance(request, dict):
                continue
            self.send(self.handle(request))
        self._stop.set()
        self.ctx.close()


def _sub(server: Server, request: dict[str, Any]):
    sub = server.ctx.store.get_subscription(int(request.get("sub_id") or 0))
    if sub is None:
        raise Reply("gui.err.no_subscription")
    return sub


def _run_detached(args: list[str]) -> None:
    subprocess.Popen(args, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _exe() -> str:
    from ..integrate.common import subwatch_exe

    return subwatch_exe()


# ----------------------------------------------------------------- reading


@command("hello")
def _hello(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": __version__,
        "strings": views.strings(),
        "pages": [{"id": pid, "title": t(f"gui.page.{pid}.title")} for pid in settings.page_ids()],
        "config_path": paths.contract_home(server.ctx.loaded.path),
    }


@command("overview")
def _overview(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    return views.overview(server.ctx)


@command("subscriptions")
def _subscriptions(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    return views.subscriptions(server.ctx)


@command("review")
def _review(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    return views.review(server.ctx)


@command("categories")
def _categories(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    return views.categories(server.ctx)


@command("sources")
def _sources(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    data = views.sources(server.ctx)
    data["scanning"] = server.scanning
    return data


@command("rates")
def _rates(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    return views.rates(server.ctx)


@command("health")
def _health(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    return views.health(server.ctx)


@command("page")
def _page(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    page_id = str(request.get("page", ""))
    if page_id not in settings.page_ids():
        raise Reply("gui.err.unknown_page", page=page_id)
    return settings.page(page_id, server.ctx.loaded)


@command("search")
def _search(server: Server, request: dict[str, Any]) -> list[dict[str, Any]]:
    return settings.search(str(request.get("query", "")), server.ctx.loaded)


# ---------------------------------------------------------------- settings


def _apply_config_change(server: Server, change: Callable[[Path], Any]) -> list[str]:
    from ..config.editor import ensure_config_file
    from ..config.effects import apply_side_effects

    old = server.ctx.config
    path, _ = ensure_config_file(server.ctx.loaded.path)
    change(path)
    server.reload_config()
    steps = apply_side_effects(old, server.ctx.config)
    server.ctx.after_change()
    server.mark_seen()
    return [t(step.key, **step.params) for step in steps]


@command("set")
def _set(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from ..config.editor import set_python

    path = str(request.get("path", ""))
    value = request.get("value")
    effects = _apply_config_change(server, lambda p: set_python(path, value, p))
    return {"field": settings.field(path, server.ctx.loaded), "effects": effects}


@command("reset")
def _reset(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from ..config.editor import unset_value

    path = str(request.get("path", ""))
    effects = _apply_config_change(server, lambda p: unset_value(path, p))
    return {"field": settings.field(path, server.ctx.loaded), "effects": effects}


# ----------------------------------------------------------- subscriptions


@command("subscription_save")
def _subscription_save(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from .. import clock, ops

    values = dict(request.get("values") or {})
    if request.get("sub_id"):
        sub = ops.update(server.ctx, _sub(server, request), values)
        message = t("cli.edit.done", service=sub.service)
    else:
        sub = ops.create(server.ctx, values, "gui")
        message = t("gui.toast.added", service=sub.service)
    server.mark_seen()
    return {"item": views.subscription_row(server.ctx, sub, server.ctx.rates(), clock.today()),
            "message": message}


@command("subscription_action")
def _subscription_action(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from .. import ops
    from ..reminders import open_url

    sub = _sub(server, request)
    action = str(request.get("action", ""))
    if action == "remove":
        ops.remove(server.ctx, sub)
        message = t("cli.remove.done", service=sub.service)
    elif action == "cancel":
        opened = ops.cancel(server.ctx, sub, "gui", open_page=bool(request.get("open_page", True)))
        message = t("gui.toast.cancelled_opened" if opened else "cli.cancel.done", service=sub.service)
    elif action == "pause":
        ops.pause(server.ctx, sub)
        message = t("cli.pause.done", service=sub.service)
    elif action == "resume":
        ops.resume(server.ctx, sub)
        message = t("cli.resume.done", service=sub.service)
    elif action == "used":
        ops.mark_used(server.ctx, sub)
        message = t("cli.used.done", service=sub.service)
    elif action == "open_cancel_page":
        if not sub.cancel_url:
            raise Reply("cli.cancel.no_url", service=sub.service)
        open_url(sub.cancel_url)
        message = t("gui.toast.page_opened")
    else:
        raise Reply("gui.err.unknown_command", name=action)
    server.mark_seen()
    return {"message": message}


@command("review_decide")
def _review_decide(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from .. import ops

    sub = _sub(server, request)
    accepted = bool(request.get("accept"))
    ops.decide(server.ctx, sub, accepted)
    server.mark_seen()
    key = "cli.review.confirmed" if accepted else "cli.review.rejected"
    return {"message": t(key, service=sub.service)}


# -------------------------------------------------------------- categories


def _category_key(name: str, existing: set[str]) -> str:
    import re
    import unicodedata

    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")[:24] or "custom"
    key, n = base, 2
    while key in existing:
        key = f"{base}_{n}"
        n += 1
    return key


@command("category_save")
def _category_save(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from decimal import Decimal, InvalidOperation

    from ..config.editor import materialize, set_python
    from ..money import parse_number

    name = str(request.get("name", "")).strip()
    if not name:
        raise Reply("gui.err.category_name")
    raw_budget = str(request.get("budget", "") or "0").strip() or "0"
    budget = parse_number(raw_budget)
    if budget is None:
        try:
            budget = Decimal(raw_budget)
        except InvalidOperation:
            raise Reply("gui.err.budget", value=raw_budget) from None
    key = str(request.get("key", "") or "")
    cats = server.ctx.config.categories
    if not key:
        key = _category_key(name, set(cats))
    value = {"name": name, "icon": str(request.get("icon", "") or ""), "budget": float(budget)}

    def change(path: Path) -> None:
        materialize("categories", server.ctx.config, path)
        set_python(f"categories.{key}", value, path)

    _apply_config_change(server, change)
    return {"key": key, "message": t("gui.toast.category_saved", name=name)}


@command("category_remove")
def _category_remove(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from ..config.editor import materialize, unset_value

    key = str(request.get("key", ""))
    cats = server.ctx.config.categories
    if key not in cats or key == "other":
        raise Reply("gui.err.category_keep")
    name = cats[key].name
    if any(rule.category == key for rule in server.ctx.config.category_rules):
        raise Reply("gui.err.category_in_rules", name=name)
    moved = 0
    for sub in server.ctx.store.subscriptions():
        if sub.category == key:
            sub.category = "other"
            server.ctx.store.update_subscription(sub)
            moved += 1

    def change(path: Path) -> None:
        materialize("categories", server.ctx.config, path)
        unset_value(f"categories.{key}", path)

    _apply_config_change(server, change)
    return {"message": t("gui.toast.category_removed", name=name, moved=moved)}


# ----------------------------------------------------------------- sources


@command("scan")
def _scan(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from ..integrate.systemd import unit_dir

    if server.scanning:
        return {"message": t("gui.toast.scan_running")}
    server.scanning = True
    server.event("scan", state="running")
    unit = unit_dir() / "subwatch-scan.service"
    if unit.exists() and shutil.which("systemctl"):
        subprocess.run(["systemctl", "--user", "start", "--no-block", "subwatch-scan.service"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        threading.Thread(target=_wait_for_unit, args=(server,), daemon=True).start()
    else:
        threading.Thread(target=_scan_inline, args=(server,), daemon=True).start()
    return {"message": t("tui.rescan_started")}


def _wait_for_unit(server: Server) -> None:
    time.sleep(1.0)
    for _ in range(1800):
        state = subprocess.run(["systemctl", "--user", "is-active", "subwatch-scan.service"],
                               capture_output=True, text=True, check=False).stdout.strip()
        if state not in ("active", "activating", "reloading"):
            break
        time.sleep(1.0)
    _scan_done(server, None)


def _scan_inline(server: Server) -> None:
    from ..scan import run_job

    ctx = AppContext(server.ctx.loaded, quiet_logs=True)
    error = None
    try:
        run_job(ctx)
    except SubwatchError as exc:
        error = exc.message
    except Exception as exc:  # reported to the window, not raised
        error = str(exc)
    finally:
        ctx.close()
    _scan_done(server, error)


def _scan_done(server: Server, error: str | None) -> None:
    server.scanning = False
    ctx = AppContext(server.ctx.loaded, quiet_logs=True)
    try:
        last = views.last_scan(ctx)
    finally:
        ctx.close()
    server.event("scan", state="done", text=error or last["text"], error=bool(error or last["errors"]))
    server.event("changed", config=False)


@command("imap_connect")
def _imap_connect(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    """Add or update an IMAP account and keep its app password in the keyring."""
    from .. import secrets
    from ..cli.tomledit import upsert_imap_account
    from ..config.schema import ImapAccount
    from ..sources.imap import test_login

    name = str(request.get("name", "")).strip()
    password = str(request.get("password", ""))
    folders = [f.strip() for f in str(request.get("folders", "") or "INBOX").split(",") if f.strip()]
    account = ImapAccount(name=name, host=str(request.get("host", "")).strip(),
                          username=str(request.get("username", "")).strip(),
                          port=int(request.get("port") or 993), folders=folders or ["INBOX"])
    if not password:
        raise Reply("gui.err.password")
    available = test_login(account, password)
    secrets.put(secrets.imap_password_name(account.name), password)

    def change(path: Path) -> None:
        upsert_imap_account(path, account)

    _apply_config_change(server, change)
    missing = [f for f in account.folders if f not in available]
    message = t("cli.auth.imap_saved", name=account.name)
    if missing:
        message += "\n" + t("cli.auth.imap_missing_folders", folders=", ".join(missing),
                            available=", ".join(available[:15]))
    return {"message": message}


@command("imap_remove")
def _imap_remove(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from .. import secrets
    from ..config.editor import plain as plain_value
    from ..config.editor import set_python

    name = str(request.get("name", ""))
    accounts = [plain_value(a) for a in server.ctx.config.sources.imap.accounts if a.name != name]
    _apply_config_change(server, lambda p: set_python("sources.imap.accounts", accounts, p))
    secrets.delete(secrets.imap_password_name(name))
    return {"message": t("gui.toast.account_removed", name=name)}


@command("gmail_connect")
def _gmail_connect(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    """The Gmail wizard needs a terminal and a browser; start it in one."""
    _open_terminal([_exe(), "auth", "gmail"], server)
    return {"message": t("gui.toast.terminal_opened")}


@command("gmail_disconnect")
def _gmail_disconnect(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from .. import secrets
    from ..config.editor import set_python
    from ..sources.gmail import revoke

    account = server.ctx.config.sources.gmail.account
    try:
        revoke(account)
    except Exception:  # offline: still forget the token locally
        secrets.delete(secrets.gmail_token_name(account))
    _apply_config_change(server, lambda p: set_python("sources.gmail.enabled", False, p))
    return {"message": t("gui.toast.gmail_disconnected")}


@command("ai_key")
def _ai_key(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from .. import secrets

    key = str(request.get("key", "")).strip()
    provider = server.ctx.config.ai.provider
    if key:
        secrets.put(secrets.ai_key_name(provider), key)
        return {"message": t("cli.auth.ai_saved", provider=provider)}
    secrets.delete(secrets.ai_key_name(provider))
    return {"message": t("gui.toast.ai_key_removed", provider=provider)}


@command("rates_update")
def _rates_update(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    server.ctx.rates(allow_network=True, force=True)
    server.ctx.after_change()
    server.mark_seen()
    return views.rates(server.ctx)


@command("health_fix")
def _health_fix(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from ..doctor import run_checks

    fixed = 0
    for check in run_checks():
        if check.fix is not None and check.status in ("warn", "fail"):
            try:
                fixed += 1 if check.fix() else 0
            except Exception:
                pass
    server.mark_seen()
    return {"message": t("gui.toast.fixed", count=fixed), "health": views.health(server.ctx)}


# -------------------------------------------------------------------- misc


def _open_terminal(args: list[str], server: Server) -> None:
    term = server.ctx.config.ui.terminal
    import shlex

    if term != "auto":
        command_line = shlex.split(term) + args
    elif shutil.which("omarchy-launch-floating-terminal-with-presentation"):
        command_line = ["omarchy-launch-floating-terminal-with-presentation", shlex.join(args)]
    elif shutil.which("xdg-terminal-exec"):
        command_line = ["xdg-terminal-exec", *args]
    else:
        raise SubwatchError("cli.err.no_terminal", hint="cli.hint.terminal")
    _run_detached(command_line)


@command("open")
def _open(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    target = str(request.get("target", ""))
    if target == "config":
        from ..config.editor import ensure_config_file

        path, _ = ensure_config_file(server.ctx.loaded.path)
        if shutil.which("omarchy-launch-editor"):
            _run_detached(["omarchy-launch-editor", str(path)])
        else:
            _run_detached(["xdg-open", str(path)])
    elif target == "tui":
        _run_detached([_exe(), "open"])
    elif target == "logs":
        _open_terminal([_exe(), "logs", "-f"], server)
    elif target == "url":
        from ..reminders import open_url

        open_url(str(request.get("url", "")))
    elif target == "import":
        path = Path(str(request.get("path", ""))).expanduser()
        if not path.is_file():
            raise Reply("gui.err.no_file", path=str(path))
        _open_terminal([_exe(), "import", str(path)], server)
    else:
        raise Reply("gui.err.unknown_command", name=target)
    return {"message": ""}


@command("export")
def _export(server: Server, request: dict[str, Any]) -> dict[str, Any]:
    from ..export import subscription_rows, to_csv, to_json, write_ics

    fmt = str(request.get("format", "csv"))
    ctx = server.ctx
    subs = ctx.store.subscriptions()
    target_dir = _downloads()
    if fmt == "ics":
        path = write_ics(subs, ctx.config, target_dir / "subwatch.ics")
    else:
        rows = subscription_rows(subs, ctx.config, ctx.rates())
        text = to_csv(rows) if fmt == "csv" else to_json(rows, ctx.config)
        path = target_dir / f"subwatch.{'csv' if fmt == 'csv' else 'json'}"
        path.write_text(text, encoding="utf-8")
    return {"message": t("gui.toast.exported", path=paths.contract_home(path))}


def _downloads() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, check=False)
        folder = Path(out.stdout.strip()) if out.stdout.strip() else None
    except OSError:
        folder = None
    if not folder or not folder.is_dir() or folder == Path.home():
        folder = Path.home()
    return folder


def main() -> None:
    Server().serve()
