"""User hooks: shell commands run on events.

Each command gets the event in environment variables and the full payload
as JSON on stdin. A failing or hanging hook is logged and never breaks the
scan or the reminder run.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from . import log
from .config.schema import HOOK_EVENTS, Config
from .models import Subscription


@dataclass
class HookRun:
    event: str
    command: str
    returncode: int | None
    timed_out: bool = False


def subscription_payload(sub: Subscription | None) -> dict[str, Any]:
    if sub is None:
        return {}
    return {
        "id": sub.id,
        "service": sub.service,
        "amount": str(sub.amount) if sub.amount is not None else None,
        "currency": sub.currency,
        "period": sub.period.code,
        "next_charge": sub.next_charge.isoformat() if sub.next_charge else None,
        "category": sub.category,
        "tags": sub.tags,
        "status": sub.status,
        "source": sub.source,
        "cancel_url": sub.cancel_url,
    }


def _env_for(event: str, sub: Subscription | None, data: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    env["SUBWATCH_EVENT"] = event
    if sub is not None:
        env["SUBWATCH_SUBSCRIPTION_ID"] = str(sub.id or "")
        env["SUBWATCH_SERVICE"] = sub.service
        env["SUBWATCH_AMOUNT"] = str(sub.amount) if sub.amount is not None else ""
        env["SUBWATCH_CURRENCY"] = sub.currency or ""
        env["SUBWATCH_DATE"] = sub.next_charge.isoformat() if sub.next_charge else ""
        env["SUBWATCH_CATEGORY"] = sub.category
    for key, value in data.items():
        if isinstance(value, (str, int, float, Decimal)):
            env["SUBWATCH_" + key.upper()] = str(value)
    return env


def run_hooks(config: Config, event: str, sub: Subscription | None = None,
              data: dict[str, Any] | None = None) -> list[HookRun]:
    if event not in HOOK_EVENTS:
        return []
    commands = list(getattr(config.hooks, event, []))
    if not commands:
        return []
    data = data or {}
    payload = json.dumps({"event": event, "subscription": subscription_payload(sub), **data},
                         ensure_ascii=False, default=str)
    env = _env_for(event, sub, data)
    runs = []
    for command in commands:
        try:
            proc = subprocess.run(
                [config.hooks.shell, "-c", command], input=payload, text=True, env=env,
                capture_output=True, timeout=config.hooks.timeout,
            )
            runs.append(HookRun(event, command, proc.returncode))
            if proc.returncode != 0:
                log.warning("hook_failed", hook_event=event, command=command, code=proc.returncode,
                            stderr=(proc.stderr or "").strip()[:300])
            else:
                log.debug("hook_ok", hook_event=event, command=command)
        except subprocess.TimeoutExpired:
            runs.append(HookRun(event, command, None, timed_out=True))
            log.warning("hook_timeout", hook_event=event, command=command, timeout=config.hooks.timeout)
        except OSError as exc:
            runs.append(HookRun(event, command, None))
            log.warning("hook_failed", hook_event=event, command=command, code=-1, stderr=str(exc))
    return runs
