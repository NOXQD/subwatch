"""Omarchy 4: menu entries, bar module, post-update hook.

Menu:  ~/.config/omarchy/extensions/omarchy-menu.jsonc (hot-reloaded by the
       shell). Its parser only understands whole-line // comments and
       trailing commas, so the block uses nothing else.
Bar:   a `type: command` module in ~/.config/omarchy/shell.json.
Hook:  ~/.config/omarchy/hooks/post-update.d/subwatch re-applies the
       integration in case an update or `omarchy refresh` reset a file.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .. import paths
from ..config.schema import Config
from ..i18n import t
from .common import (
    Step, backup_file, has_block, make_block, strip_block, strip_jsonc, subwatch_exe, update_file,
    write_text,
)

MODULE_ID = "subwatch"
SCAN_UNIT_START = "systemctl --user start --no-block subwatch-scan.service"


def omarchy_root() -> Path:
    return Path(os.environ.get("OMARCHY_PATH") or "/usr/share/omarchy")


def is_omarchy() -> bool:
    return (omarchy_root() / "shell").is_dir() or shutil.which("omarchy") is not None


def omarchy_config() -> Path:
    return paths.config_home() / "omarchy"


def menu_file() -> Path:
    return omarchy_config() / "extensions" / "omarchy-menu.jsonc"


def shell_file() -> Path:
    return omarchy_config() / "shell.json"


def hook_file() -> Path:
    return omarchy_config() / "hooks" / "post-update.d" / "subwatch"


# ------------------------------------------------------------------ menu


def menu_entries(config: Config) -> list[tuple[str, dict[str, str]]]:
    exe = subwatch_exe()
    cfg = paths.contract_home(paths.config_file())
    return [
        ("subwatch", {"icon": "", "label": "Subwatch", "description": t("integrate.menu.root_desc")}),
        ("subwatch.upcoming", {"icon": "\U000f00f0", "label": t("integrate.menu.upcoming"),
                               "action": f"{exe} menu upcoming"}),
        ("subwatch.list", {"icon": "\U000f0279", "label": t("integrate.menu.list"), "action": f"{exe} open"}),
        ("subwatch.add", {"icon": "\U000f0415", "label": t("integrate.menu.add"), "action": f"{exe} open --add"}),
        ("subwatch.review", {"icon": "\uf046", "label": t("integrate.menu.review"),
                             "action": f"{exe} open --review"}),
        ("subwatch.spend", {"icon": "\uf080", "label": t("integrate.menu.spend"),
                            "action": f"{exe} spend --notify"}),
        ("subwatch.rescan", {"icon": "\U000f0450", "label": t("integrate.menu.rescan"),
                             "action": SCAN_UNIT_START}),
        ("subwatch.config", {"icon": "\U000f0493", "label": t("integrate.menu.config"),
                             "action": f"omarchy-launch-editor {cfg}"}),
    ]


def _menu_block(config: Config) -> str:
    lines = [f"// {t('integrate.menu.comment')}"]
    for key, value in menu_entries(config):
        lines.append(f"{json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)},")
    return make_block(lines, "//", indent="  ")


def _insert_after_first_brace(text: str, block: str) -> str:
    """Put our block first inside the root object.

    Every line of the block ends with a comma, so whatever follows (the
    user's entries or the closing brace) stays valid and untouched.
    """
    brace = text.find("{")
    if brace < 0:
        return "{\n" + block + "}\n"
    return text[: brace + 1] + "\n" + block.rstrip("\n") + text[brace + 1:]


def _menu_valid(text: str) -> bool:
    # Mirror the shell's parser: whole-line comments and trailing commas only.
    import re

    stripped = re.sub(r"^\s*//[^\n]*(\n|$)", "", text, flags=re.M)
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
    try:
        return isinstance(json.loads(stripped), dict)
    except ValueError:
        return False


def apply_menu(config: Config, dry_run: bool = False) -> Step:
    path = menu_file()
    if not config.menu.enabled:
        return remove_menu(dry_run)

    def transform(old: str) -> str:
        base = strip_block(old, "//") if has_block(old, "//") else old
        if not base.strip():
            base = "{\n}\n"
        return _insert_after_first_brace(base, _menu_block(config))

    status = update_file(path, transform, validate=_menu_valid, dry_run=dry_run)
    key = {"changed": "integrate.menu.written", "unchanged": "integrate.menu.same",
           "planned": "integrate.menu.would", "invalid": "integrate.menu.invalid"}[status]
    return Step("menu", "failed" if status == "invalid" else status, key, {}, path)


def remove_menu(dry_run: bool = False) -> Step:
    path = menu_file()
    if not path.exists():
        return Step("menu", "unchanged", "integrate.not_installed", {}, path)
    status = update_file(path, lambda s: strip_block(s, "//") if has_block(s, "//") else s,
                         validate=_menu_valid, dry_run=dry_run, create=False)
    return Step("menu", "removed" if status == "changed" else status, "integrate.menu.removed", {}, path)


def menu_installed() -> bool:
    p = menu_file()
    return p.exists() and has_block(p.read_text(encoding="utf-8"), "//")


# ------------------------------------------------------------------- bar


def bar_entry(config: Config) -> dict[str, Any]:
    exe = subwatch_exe()
    return {
        "id": MODULE_ID,
        "type": "command",
        "exec": f"{exe} bar",
        "interval": config.bar.interval,
        "tooltip": "Subwatch",
        "onClick": f"{exe} open",
        "onRightClick": f"{exe} menu",
        "onMiddleClick": SCAN_UNIT_START,
    }


def _load_shell_json() -> tuple[dict[str, Any] | None, bool]:
    path = shell_file()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8")), True
        except ValueError:
            return None, True
    default = omarchy_root() / "config" / "omarchy" / "shell.json"
    if default.exists():
        try:
            return json.loads(strip_jsonc(default.read_text(encoding="utf-8"))), False
        except ValueError:
            return None, False
    return None, False


def _find_entry(layout: dict[str, Any]) -> tuple[str, int] | None:
    for section, items in layout.items():
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            ident = item.get("id") if isinstance(item, dict) else item
            if ident == MODULE_ID:
                return section, i
    return None


def apply_bar(config: Config, dry_run: bool = False) -> Step:
    path = shell_file()
    data, existed = _load_shell_json()
    if data is None:
        return Step("bar", "failed", "integrate.bar.unreadable", {}, path)
    bar = data.setdefault("bar", {})
    layout = bar.setdefault("layout", {})
    entry = bar_entry(config)
    found = _find_entry(layout)
    if found:
        section, index = found
        current = layout[section][index]
        merged = {**current, **{k: entry[k] for k in ("type", "exec", "interval", "onClick",
                                                     "onRightClick", "onMiddleClick")}}
        if merged == current and existed:
            return Step("bar", "unchanged", "integrate.bar.same", {}, path)
        layout[section][index] = merged
    else:
        layout.setdefault(config.bar.section, []).insert(0, entry)
    if dry_run:
        return Step("bar", "planned", "integrate.bar.would", {"section": config.bar.section}, path)
    if existed:
        backup_file(path)
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return Step("bar", "changed", "integrate.bar.written", {"section": config.bar.section}, path)


def remove_bar(dry_run: bool = False) -> Step:
    path = shell_file()
    if not path.exists():
        return Step("bar", "unchanged", "integrate.not_installed", {}, path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return Step("bar", "failed", "integrate.bar.unreadable", {}, path)
    layout = (data.get("bar") or {}).get("layout") or {}
    found = _find_entry(layout)
    if not found:
        return Step("bar", "unchanged", "integrate.not_installed", {}, path)
    if dry_run:
        return Step("bar", "planned", "integrate.bar.removed", {}, path)
    section, index = found
    del layout[section][index]
    backup_file(path)
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return Step("bar", "removed", "integrate.bar.removed", {}, path)


def bar_installed() -> bool:
    path = shell_file()
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return _find_entry((data.get("bar") or {}).get("layout") or {}) is not None


# ------------------------------------------------------------------ hook


def hook_script() -> str:
    exe = subwatch_exe()
    return (
        "#!/bin/bash\n"
        f"# {t('integrate.hook.comment')}\n"
        f"[[ -x {exe} ]] && {exe} integrate apply --quiet || true\n"
    )


def apply_hook(dry_run: bool = False) -> Step:
    path = hook_file()
    content = hook_script()
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return Step("hook", "unchanged", "integrate.hook.same", {}, path)
    if dry_run:
        return Step("hook", "planned", "integrate.hook.would", {}, path)
    write_text(path, content, mode=0o755)
    return Step("hook", "changed", "integrate.hook.written", {}, path)


def remove_hook(dry_run: bool = False) -> Step:
    path = hook_file()
    if not path.exists():
        return Step("hook", "unchanged", "integrate.not_installed", {}, path)
    if not dry_run:
        path.unlink()
    return Step("hook", "removed" if not dry_run else "planned", "integrate.removed_file", {}, path)
