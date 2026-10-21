"""systemd --user units: the scan timer and the reminder timer.

Unit files are generated from config.toml (schedule, nice, io class,
reminder check interval). `subwatch config set scan.schedule ...` rewrites
them and reloads the user manager.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .. import paths
from ..config.schema import Config, parse_duration
from ..i18n import t
from .common import Step, subwatch_exe, write_text

UNITS = ("subwatch-scan.service", "subwatch-scan.timer", "subwatch-remind.service",
         "subwatch-remind.timer")
TIMERS = ("subwatch-scan.timer", "subwatch-remind.timer")


def unit_dir() -> Path:
    return paths.config_home() / "systemd" / "user"


def systemd_available() -> bool:
    if not shutil.which("systemctl"):
        return False
    try:
        out = subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True,
                             text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.stdout.strip() not in ("", "offline")


def _exec(exe: str, args: str) -> str:
    home = str(paths.home())
    if exe.startswith(home + "/"):
        exe = "%h" + exe[len(home):]
    return f"{exe} {args}"


def _timer_schedule(spec: str) -> list[str]:
    """OnCalendar for calendar expressions, monotonic timers for "6h"-style."""
    spec = spec.strip()
    if re.fullmatch(r"\d+\s*[smhdw]", spec):
        return ["OnBootSec=5min", f"OnUnitActiveSec={spec.replace(' ', '')}"]
    return [f"OnCalendar={spec}"]


def _interval_calendar(spec: str) -> list[str]:
    seconds = int(parse_duration(spec).total_seconds())
    minutes = seconds // 60
    if seconds % 60 == 0 and 0 < minutes < 60 and 60 % minutes == 0:
        return [f"OnCalendar=*:0/{minutes}:00"]
    if seconds % 3600 == 0 and 0 < seconds // 3600 < 24 and 24 % (seconds // 3600) == 0:
        return [f"OnCalendar=0/{seconds // 3600}:00:00"]
    return ["OnBootSec=2min", f"OnUnitActiveSec={spec}"]


def render(config: Config) -> dict[str, str]:
    exe = subwatch_exe()
    io = {"idle": "IOSchedulingClass=idle", "best-effort": "IOSchedulingClass=best-effort\nIOSchedulingPriority=7",
          "none": ""}[config.scan.io_class]
    service_lines = [
        "[Unit]",
        f"Description={t('integrate.systemd.scan_desc')}",
        "",
        "[Service]",
        "Type=oneshot",
        f"ExecStart={_exec(exe, 'scan --quiet')}",
        f"Nice={config.scan.nice}",
        *([io] if io else []),
        "NoNewPrivileges=yes",
        "TimeoutStartSec=45min",
        "SyslogIdentifier=subwatch",
    ]
    scan_service = "\n".join(service_lines) + "\n"
    scan_timer = "\n".join([
        "[Unit]",
        f"Description={t('integrate.systemd.scan_timer_desc')}",
        "",
        "[Timer]",
        *_timer_schedule(config.scan.schedule),
        f"RandomizedDelaySec={config.scan.randomized_delay}",
        f"Persistent={'true' if config.scan.persistent else 'false'}",
        "AccuracySec=1min",
        "",
        "[Install]",
        "WantedBy=timers.target",
    ]) + "\n"
    remind_service = "\n".join([
        "[Unit]",
        f"Description={t('integrate.systemd.remind_desc')}",
        "",
        "[Service]",
        "Type=oneshot",
        f"ExecStart={_exec(exe, 'remind --quiet')}",
        "Nice=5",
        "NoNewPrivileges=yes",
        "TimeoutStartSec=5min",
        "SyslogIdentifier=subwatch",
    ]) + "\n"
    remind_timer = "\n".join([
        "[Unit]",
        f"Description={t('integrate.systemd.remind_timer_desc')}",
        "",
        "[Timer]",
        *_interval_calendar(config.reminders.check_interval),
        "Persistent=true",
        "AccuracySec=30s",
        "",
        "[Install]",
        "WantedBy=timers.target",
    ]) + "\n"
    return {
        "subwatch-scan.service": scan_service,
        "subwatch-scan.timer": scan_timer,
        "subwatch-remind.service": remind_service,
        "subwatch-remind.timer": remind_timer,
    }


def _systemctl(*args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None


def validate_calendar(spec: str) -> bool:
    if re.fullmatch(r"\d+\s*[smhdw]", spec.strip()):
        return True
    if not shutil.which("systemd-analyze"):
        return True
    try:
        out = subprocess.run(["systemd-analyze", "calendar", spec], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return True
    return out.returncode == 0


def apply(config: Config, dry_run: bool = False, enable: bool = True) -> list[Step]:
    steps: list[Step] = []
    if not validate_calendar(config.scan.schedule):
        return [Step("systemd", "failed", "integrate.systemd.bad_schedule", {"value": config.scan.schedule})]
    changed = False
    for name, content in render(config).items():
        path = unit_dir() / name
        if path.exists() and path.read_text(encoding="utf-8") == content:
            continue
        changed = True
        if not dry_run:
            write_text(path, content, mode=0o644)
        steps.append(Step("systemd", "planned" if dry_run else "changed", "integrate.file_written", {}, path))
    if dry_run:
        return steps or [Step("systemd", "unchanged", "integrate.systemd.same")]
    if not systemd_available():
        steps.append(Step("systemd", "skipped", "integrate.systemd.unavailable"))
        return steps
    if changed:
        _systemctl("daemon-reload")
    if enable:
        for timer in TIMERS:
            res = _systemctl("enable", "--now", timer)
            if res is None or res.returncode != 0:
                steps.append(Step("systemd", "failed", "integrate.systemd.enable_failed",
                                  {"unit": timer, "detail": (res.stderr.strip() if res else "")}))
            elif changed:
                _systemctl("restart", timer)
    if not steps:
        steps.append(Step("systemd", "unchanged", "integrate.systemd.same"))
    return steps


def remove(dry_run: bool = False) -> list[Step]:
    steps = []
    if not dry_run and systemd_available():
        for timer in TIMERS:
            _systemctl("disable", "--now", timer)
    for name in UNITS:
        path = unit_dir() / name
        if path.exists():
            if not dry_run:
                path.unlink()
            steps.append(Step("systemd", "removed" if not dry_run else "planned", "integrate.removed_file", {}, path))
    if not dry_run and steps and systemd_available():
        _systemctl("daemon-reload")
    return steps


def timer_state(timer: str) -> tuple[bool, bool, str | None]:
    """(enabled, active, next elapse text)."""
    if not systemd_available():
        return False, False, None
    enabled = _systemctl("is-enabled", timer)
    active = _systemctl("is-active", timer)
    nxt = _systemctl("show", timer, "--property=NextElapseUSecRealtime", "--value")
    return (
        bool(enabled and enabled.stdout.strip() == "enabled"),
        bool(active and active.stdout.strip() == "active"),
        (nxt.stdout.strip() or None) if nxt else None,
    )


def units_current(config: Config) -> bool:
    for name, content in render(config).items():
        path = unit_dir() / name
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            return False
    return True
