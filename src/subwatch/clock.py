"""Single source of "now".

SUBWATCH_NOW (ISO datetime) freezes time; tests and the demo script use it so
results don't depend on the day they run.
"""

from __future__ import annotations

import os
from datetime import date, datetime, tzinfo
from zoneinfo import ZoneInfo

_tz: tzinfo | None = None


def set_timezone(name: str) -> None:
    global _tz
    if not name or name == "local":
        _tz = None
    else:
        _tz = ZoneInfo(name)


def local_tz() -> tzinfo:
    if _tz is not None:
        return _tz
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def now() -> datetime:
    frozen = os.environ.get("SUBWATCH_NOW", "")
    if frozen:
        value = datetime.fromisoformat(frozen)
        if value.tzinfo is None:
            value = value.replace(tzinfo=local_tz())
        return value.astimezone(local_tz())
    return datetime.now(local_tz())


def today() -> date:
    return now().date()


def to_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=local_tz())
    return value.astimezone(local_tz())


def iso(value: datetime) -> str:
    return to_local(value).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return to_local(datetime.fromisoformat(value))
