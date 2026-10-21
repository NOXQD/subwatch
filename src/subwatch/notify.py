"""Desktop notifications.

Backends:
  omarchy      Omarchy 4 shell. No buttons, but a click runs a command
               (omarchy-notification-send --exec), which opens the action menu.
  notify-send  mako, dunst, swaync... Real action buttons via -A; a detached
               helper process waits for the answer.
  none         nothing is shown (logged only).

"auto" asks the running daemon for its name over D-Bus.
SUBWATCH_NOTIFY_RECORD=<file> writes notifications to a JSON-lines file
instead of showing them (used by the demo script and integration tests).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field

from . import log
from .config.schema import NotificationsConfig

APP_NAME = "Subwatch"


@dataclass
class Notification:
    summary: str
    body: str = ""
    urgency: str = "normal"
    kind: str = "info"
    reminder_id: int | None = None
    actions: list[tuple[str, str]] = field(default_factory=list)
    click: list[str] = field(default_factory=list)


def server_name() -> str | None:
    """Name of the running notification daemon, or None."""
    if shutil.which("busctl"):
        try:
            out = subprocess.run(
                ["busctl", "--user", "--json=short", "call", "org.freedesktop.Notifications",
                 "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                 "GetServerInformation"],
                capture_output=True, text=True, timeout=3,
            )
            if out.returncode == 0:
                data = json.loads(out.stdout).get("data") or []
                return str(data[0]).lower() if data else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None
    return None


def resolve_backend(cfg: NotificationsConfig) -> str:
    if os.environ.get("SUBWATCH_NOTIFY_RECORD"):
        return "record"
    if cfg.backend != "auto":
        return cfg.backend
    name = server_name()
    if name and "quickshell" in name and shutil.which("omarchy-notification-send"):
        return "omarchy"
    if shutil.which("notify-send") and name:
        return "notify-send"
    if shutil.which("omarchy-notification-send"):
        return "omarchy"
    return "notify-send" if shutil.which("notify-send") else "none"


def self_command() -> list[str]:
    """How to call this program again from a detached process."""
    exe = shutil.which("subwatch")
    if exe:
        return [exe]
    return [sys.executable, "-m", "subwatch"]


def _record(note: Notification) -> None:
    path = os.environ["SUBWATCH_NOTIFY_RECORD"]
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(note), ensure_ascii=False) + "\n")


def send(note: Notification, cfg: NotificationsConfig) -> str:
    """Show a notification; returns the backend that was used."""
    backend = resolve_backend(cfg)
    urgency = note.urgency or cfg.urgency
    try:
        if backend == "record":
            _record(note)
        elif backend == "omarchy":
            args = ["omarchy-notification-send", "--app-name", APP_NAME, "-u", urgency]
            if cfg.glyph:
                args += ["-g", cfg.glyph]
            if cfg.timeout_ms:
                args += ["-t", str(cfg.timeout_ms)]
            args += [note.summary, note.body or " "]
            if note.click:
                args += ["--exec", *note.click]
            subprocess.run(args, capture_output=True, timeout=10, check=False)
        elif backend == "notify-send":
            base = ["notify-send", "-a", APP_NAME, "-u", urgency]
            if cfg.timeout_ms:
                base += ["-t", str(cfg.timeout_ms)]
            if note.actions and note.reminder_id is not None:
                payload = json.dumps({"reminder_id": note.reminder_id, "summary": note.summary,
                                      "body": note.body, "urgency": urgency,
                                      "actions": note.actions}, ensure_ascii=False)
                subprocess.Popen(self_command() + ["notify-wait", payload],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            else:
                subprocess.run(base + ["--", note.summary, note.body], capture_output=True,
                               timeout=10, check=False)
        else:
            log.info("notification_suppressed", summary=note.summary)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("notification_failed", backend=backend, error=str(exc))
    log.debug("notification_sent", backend=backend, kind=note.kind, summary=note.summary)
    return backend


def wait_for_action(payload: str) -> str | None:
    """Body of `subwatch notify-wait`: show buttons and wait for a click."""
    data = json.loads(payload)
    args = ["notify-send", "-a", APP_NAME, "-u", data.get("urgency", "normal"), "--wait"]
    for action_id, label in data.get("actions", []):
        args += ["-A", f"{action_id}={label}"]
    args += ["--", data.get("summary", ""), data.get("body", "")]
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=24 * 3600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    chosen = (out.stdout or "").strip().splitlines()
    return chosen[-1] if chosen else None
