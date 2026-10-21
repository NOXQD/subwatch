"""Structured logging.

Each record is an event name plus fields. The human-readable MESSAGE comes
from the catalog (log.<event>), the fields go to journald as
SUBWATCH_<FIELD>=value so they can be filtered:

    journalctl --user -t subwatch SUBWATCH_EVENT=scan_finished

When the journal socket is not available (or logging.journal = false) the
record goes to stderr as one line.
"""

from __future__ import annotations

import os
import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .i18n import has, t

JOURNAL_SOCKET = "/run/systemd/journal/socket"
IDENTIFIER = "subwatch"
LEVELS = {"debug": 7, "info": 6, "warning": 4, "error": 3}

_state: dict[str, Any] = {"level": "info", "journal": True, "file": None, "quiet": False}


def configure(level: str = "info", journal: bool = True, file: str | None = None,
              quiet: bool = False) -> None:
    _state.update(level=level, journal=journal, file=file or None, quiet=quiet)


def _journal_send(fields: dict[str, str]) -> bool:
    if not os.path.exists(JOURNAL_SOCKET):
        return False
    payload = bytearray()
    for key, value in fields.items():
        data = value.encode("utf-8", "replace")
        if b"\n" in data:
            payload += key.encode() + b"\n" + len(data).to_bytes(8, "little") + data + b"\n"
        else:
            payload += key.encode() + b"=" + data + b"\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.sendto(bytes(payload), JOURNAL_SOCKET)
        return True
    except OSError:
        return False


def _field_name(name: str) -> str:
    clean = "".join(ch if ch.isalnum() else "_" for ch in name.upper())
    return "SUBWATCH_" + clean


def event(name: str, level: str = "info", **fields: Any) -> str:
    """Log an event; returns the rendered message."""
    key = f"log.{name}"
    message = t(key, **fields) if has(key) else name
    if LEVELS.get(level, 6) > LEVELS.get(_state["level"], 6):
        return message
    record = {
        "MESSAGE": message,
        "PRIORITY": str(LEVELS.get(level, 6)),
        "SYSLOG_IDENTIFIER": IDENTIFIER,
        "SUBWATCH_EVENT": name,
    }
    for k, v in fields.items():
        if v is not None:
            record[_field_name(k)] = str(v)
    sent = _state["journal"] and _journal_send(record)
    under_systemd = bool(os.environ.get("INVOCATION_ID"))
    if not sent and (under_systemd or level in ("warning", "error")) and not _state["quiet"]:
        print(f"subwatch[{level}]: {message}", file=sys.stderr)
    if _state["file"]:
        try:
            path = Path(os.path.expanduser(_state["file"]))
            path.parent.mkdir(parents=True, exist_ok=True)
            extra = " ".join(f"{k}={v}" for k, v in fields.items() if v is not None)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().isoformat(timespec='seconds')} {level} {name} "
                         f"{extra} | {message}\n")
        except OSError:
            pass
    return message


def debug(name: str, **fields: Any) -> str:
    return event(name, "debug", **fields)


def info(name: str, **fields: Any) -> str:
    return event(name, "info", **fields)


def warning(name: str, **fields: Any) -> str:
    return event(name, "warning", **fields)


def error(name: str, **fields: Any) -> str:
    return event(name, "error", **fields)
