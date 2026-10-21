"""Hyprland keybindings from [keybinds] in config.toml.

Omarchy 4 configures Hyprland in Lua: we write ~/.config/hypr/subwatch.lua
and add a guarded `require("hypr.subwatch")` block to hyprland.lua. Older
setups with hyprland.conf get subwatch.conf plus a `source = ...` line.

Before writing, every combination is checked against `hyprctl binds -j`.
A taken combination is skipped (with a warning) unless
keybinds.override_conflicts = true, in which case we unbind it first.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from ..config.schema import Config
from ..i18n import t
from .common import Step, backup_file, has_block, make_block, strip_block, subwatch_exe, update_file, write_text

MODS = {"SHIFT": 1, "CAPS": 2, "CTRL": 4, "CONTROL": 4, "ALT": 8, "MOD2": 16, "MOD3": 32,
        "SUPER": 64, "WIN": 64, "LOGO": 64, "MOD4": 64, "MOD5": 128}

ACTIONS = ("open_tui", "upcoming", "menu", "rescan", "add")


@dataclass(frozen=True)
class Combo:
    mods: int
    key: str

    def __str__(self) -> str:
        names = [n for n, v in (("SUPER", 64), ("CTRL", 4), ("ALT", 8), ("SHIFT", 1)) if self.mods & v]
        return " + ".join(names + [self.key])


class KeyError_(ValueError):
    pass


def parse_combo(text: str) -> Combo:
    parts = [p.strip() for p in re.split(r"[+\s]+", text.strip()) if p.strip()]
    if not parts:
        raise KeyError_(text)
    mods = 0
    for p in parts[:-1]:
        up = p.upper()
        if up not in MODS:
            raise KeyError_(text)
        mods |= MODS[up]
    key = parts[-1]
    if key.upper() in MODS:
        raise KeyError_(text)
    return Combo(mods, key.upper())


def hypr_dir() -> Path:
    return paths.config_home() / "hypr"


def mode() -> str:
    """"lua" for Omarchy 4, "conf" for classic hyprland.conf setups."""
    d = hypr_dir()
    if (d / "hyprland.lua").exists():
        return "lua"
    if (d / "hyprland.conf").exists():
        return "conf"
    return "lua"


def hyprland_running() -> bool:
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and shutil.which("hyprctl") is not None


def current_binds() -> list[dict] | None:
    if not hyprland_running():
        return None
    try:
        out = subprocess.run(["hyprctl", "binds", "-j"], capture_output=True, text=True, timeout=5)
        return json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def commands(config: Config) -> dict[str, str]:
    exe = subwatch_exe()
    return {
        "open_tui": f"{exe} open",
        "upcoming": f"{exe} upcoming --notify",
        "menu": f"{exe} menu",
        "rescan": "systemctl --user start --no-block subwatch-scan.service",
        "add": f"{exe} open --add",
    }


@dataclass
class Planned:
    action: str
    combo: Combo
    description: str
    command: str
    conflict: str | None = None


def plan(config: Config, binds: list[dict] | None = None) -> tuple[list[Planned], list[Step]]:
    """Which binds to write, with conflicts against the running Hyprland."""
    steps: list[Step] = []
    out: list[Planned] = []
    if binds is None:
        binds = current_binds() or []
    taken: dict[Combo, str] = {}
    for b in binds:
        desc = b.get("description") or b.get("arg") or ""
        if str(desc).startswith("Subwatch"):
            continue
        key = str(b.get("key", ""))
        combo = Combo(int(b.get("modmask", 0)), key.upper())
        taken[combo] = str(desc)
    cmds = commands(config)
    seen: set[Combo] = set()
    for action in ACTIONS:
        value = getattr(config.keybinds, action)
        if not value:
            continue
        try:
            combo = parse_combo(value)
        except KeyError_:
            steps.append(Step("keybinds", "failed", "integrate.keys.bad_combo", {"combo": value, "action": action}))
            continue
        if combo in seen:
            steps.append(Step("keybinds", "failed", "integrate.keys.duplicate", {"combo": str(combo)}))
            continue
        seen.add(combo)
        desc = t(f"integrate.keys.desc.{action}")
        out.append(Planned(action, combo, desc, cmds[action], taken.get(combo)))
    return out, steps


def _lua_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_lua(items: list[Planned], override: bool) -> str:
    lines = [f"-- {t('integrate.keys.generated')}", f"-- {t('integrate.keys.edit_hint')}", ""]
    for item in items:
        if item.conflict and not override:
            continue
        if item.conflict:
            lines.append(f"-- {t('integrate.keys.was', combo=str(item.combo), what=item.conflict)}")
            lines.append(f"hl.unbind({_lua_string(str(item.combo))})")
        lines.append(f"o.bind({_lua_string(str(item.combo))}, {_lua_string(item.description)}, "
                     f"{_lua_string(item.command)})")
    return "\n".join(lines) + "\n"


def _conf_combo(c: Combo) -> tuple[str, str]:
    mods = " ".join(n for n, v in (("SUPER", 64), ("CTRL", 4), ("ALT", 8), ("SHIFT", 1)) if c.mods & v)
    return mods, c.key


def render_conf(items: list[Planned], override: bool) -> str:
    lines = [f"# {t('integrate.keys.generated')}", f"# {t('integrate.keys.edit_hint')}", ""]
    for item in items:
        if item.conflict and not override:
            continue
        mods, key = _conf_combo(item.combo)
        if item.conflict:
            lines.append(f"unbind = {mods}, {key}")
        lines.append(f"bindd = {mods}, {key}, {item.description}, exec, {item.command}")
    return "\n".join(lines) + "\n"


LUA_INCLUDE = 'if package.searchpath("hypr.subwatch", package.path) then require("hypr.subwatch") end'


def _include_transform(old: str, kind: str) -> str:
    comment = "--" if kind == "lua" else "#"
    text = strip_block(old, comment) if has_block(old, comment) else old
    line = LUA_INCLUDE if kind == "lua" else "source = ~/.config/hypr/subwatch.conf"
    block = make_block([f"{comment} {t('integrate.keys.include_comment')}", line], comment)
    return text.rstrip("\n") + "\n\n" + block


def validate_reload() -> list[str]:
    """Reload Hyprland and return config errors (empty list = fine)."""
    if not hyprland_running():
        return []
    try:
        subprocess.run(["hyprctl", "reload"], capture_output=True, timeout=10)
        out = subprocess.run(["hyprctl", "configerrors"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    text = (out.stdout or "").strip()
    if not text or text.lower().startswith("no errors"):
        return []
    return [line for line in text.splitlines() if line.strip()]


def apply(config: Config, dry_run: bool = False, binds: list[dict] | None = None,
          reload: bool = True) -> list[Step]:
    kind = mode()
    d = hypr_dir()
    main = d / ("hyprland.lua" if kind == "lua" else "hyprland.conf")
    target = d / ("subwatch.lua" if kind == "lua" else "subwatch.conf")
    if not config.keybinds.enabled:
        return remove(dry_run)
    items, steps = plan(config, binds)
    override = config.keybinds.override_conflicts
    for item in items:
        if item.conflict and not override:
            steps.append(Step("keybinds", "skipped", "integrate.keys.conflict",
                              {"combo": str(item.combo), "what": item.conflict,
                               "action": t(f"integrate.keys.desc.{item.action}")}))
        elif item.conflict:
            steps.append(Step("keybinds", "changed", "integrate.keys.overridden",
                              {"combo": str(item.combo), "what": item.conflict}))
    content = render_lua(items, override) if kind == "lua" else render_conf(items, override)
    old = target.read_text(encoding="utf-8") if target.exists() else None
    if old != content:
        if dry_run:
            steps.append(Step("keybinds", "planned", "integrate.keys.would_write", {}, target))
        else:
            if old is not None:
                backup_file(target)
            write_text(target, content)
            steps.append(Step("keybinds", "changed", "integrate.keys.written",
                              {"count": sum(1 for i in items if not i.conflict or override)}, target))
    else:
        steps.append(Step("keybinds", "unchanged", "integrate.keys.same", {}, target))
    if not main.exists():
        steps.append(Step("keybinds", "skipped", "integrate.keys.no_main", {}, main))
        return steps
    status = update_file(main, lambda s: _include_transform(s, kind), dry_run=dry_run, create=False)
    if status == "changed":
        steps.append(Step("keybinds", "changed", "integrate.keys.include_added", {}, main))
    elif status == "planned":
        steps.append(Step("keybinds", "planned", "integrate.keys.would_include", {}, main))
    if not dry_run and reload:
        errors = validate_reload()
        related = [e for e in errors if "subwatch" in e.lower()]
        if related:
            steps.append(Step("keybinds", "failed", "integrate.keys.reload_errors",
                              {"errors": "; ".join(related[:3])}, target))
    return steps


def remove(dry_run: bool = False) -> list[Step]:
    steps: list[Step] = []
    d = hypr_dir()
    for main, comment in ((d / "hyprland.lua", "--"), (d / "hyprland.conf", "#")):
        if not main.exists():
            continue
        status = update_file(main, lambda s, c=comment: strip_block(s, c) if has_block(s, c) else s,
                             dry_run=dry_run, create=False)
        if status in ("changed", "planned"):
            steps.append(Step("keybinds", "removed" if status == "changed" else "planned",
                              "integrate.keys.include_removed", {}, main))
    for name in ("subwatch.lua", "subwatch.conf"):
        p = d / name
        if p.exists():
            if not dry_run:
                p.unlink()
            steps.append(Step("keybinds", "removed" if not dry_run else "planned",
                              "integrate.removed_file", {}, p))
    if not dry_run and steps:
        validate_reload()
    return steps


def status(config: Config) -> list[Step]:
    kind = mode()
    d = hypr_dir()
    main = d / ("hyprland.lua" if kind == "lua" else "hyprland.conf")
    target = d / ("subwatch.lua" if kind == "lua" else "subwatch.conf")
    steps = []
    comment = "--" if kind == "lua" else "#"
    included = main.exists() and has_block(main.read_text(encoding="utf-8"), comment)
    steps.append(Step("keybinds", "unchanged" if included and target.exists() else "failed",
                      "integrate.keys.status_ok" if included and target.exists() else "integrate.keys.status_missing",
                      {}, target))
    if included:
        errors = []
        if hyprland_running():
            try:
                out = subprocess.run(["hyprctl", "configerrors"], capture_output=True, text=True, timeout=5)
                text = (out.stdout or "").strip()
                if text and not text.lower().startswith("no errors"):
                    errors = [e for e in text.splitlines() if "subwatch" in e.lower()]
            except (OSError, subprocess.TimeoutExpired):
                pass
        if errors:
            steps.append(Step("keybinds", "failed", "integrate.keys.reload_errors",
                              {"errors": "; ".join(errors[:3])}, target))
        items, _ = plan(config)
        for item in items:
            if item.conflict:
                steps.append(Step("keybinds", "skipped", "integrate.keys.conflict",
                                  {"combo": str(item.combo), "what": item.conflict,
                                   "action": t(f"integrate.keys.desc.{item.action}")}))
    return steps
