"""Launcher integration that works with any menu: a .desktop entry with
actions (picked up by the Omarchy Apps menu, Walker, fuzzel, rofi...) and,
when Walker/Elephant is installed (Omarchy 3.x), an Elephant menu file."""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import paths
from ..i18n import t
from .common import Step, strip_jsonc, subwatch_exe, write_text
from .omarchy import SCAN_UNIT_START


def desktop_file() -> Path:
    return paths.data_home() / "applications" / "subwatch.desktop"


def elephant_file() -> Path:
    return paths.config_home() / "elephant" / "menus" / "subwatch.toml"


def desktop_entry() -> str:
    exe = subwatch_exe()
    actions = [
        ("upcoming", t("integrate.menu.upcoming"), f"{exe} menu upcoming"),
        ("add", t("integrate.menu.add"), f"{exe} open --add"),
        ("review", t("integrate.menu.review"), f"{exe} open --review"),
        ("spend", t("integrate.menu.spend"), f"{exe} spend --notify"),
        ("rescan", t("integrate.menu.rescan"), SCAN_UNIT_START),
    ]
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=Subwatch",
        f"GenericName={t('integrate.desktop.generic')}",
        f"Comment={t('integrate.desktop.comment')}",
        f"Exec={exe} open",
        "Icon=wallet",
        "Terminal=false",
        "Categories=Office;Finance;",
        f"Keywords={t('integrate.desktop.keywords')}",
        "Actions=" + ";".join(a for a, _, _ in actions) + ";",
        "",
    ]
    for action, name, command in actions:
        lines += [f"[Desktop Action {action}]", f"Name={name}", f"Exec={command}", ""]
    return "\n".join(lines)


def elephant_menu() -> str:
    exe = subwatch_exe()

    def q(s: str) -> str:
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'

    entries = [
        (t("integrate.menu.upcoming"), f"{exe} menu upcoming"),
        (t("integrate.menu.list"), f"{exe} open"),
        (t("integrate.menu.add"), f"{exe} open --add"),
        (t("integrate.menu.spend"), f"{exe} spend --notify"),
        (t("integrate.menu.rescan"), SCAN_UNIT_START),
        (t("integrate.menu.config"), f"omarchy-launch-editor {paths.contract_home(paths.config_file())}"),
    ]
    lines = [f"# {t('integrate.menu.comment')}", 'name = "subwatch"', 'name_pretty = "Subwatch"',
             'icon = "wallet"', "global_search = true", ""]
    for text, command in entries:
        lines += ["[[entries]]", f"text = {q(text)}", f"keywords = [{q('subwatch')}]",
                  f"actions = {{ \"run\" = {q(command)} }}", ""]
    return "\n".join(lines)


def walker_present() -> bool:
    return shutil.which("walker") is not None and shutil.which("elephant") is not None


def apply(dry_run: bool = False) -> list[Step]:
    steps = []
    for name, path, content, wanted in (
        ("desktop", desktop_file(), desktop_entry(), True),
        ("walker", elephant_file(), elephant_menu(), walker_present()),
    ):
        if not wanted:
            steps.append(Step(name, "skipped", "integrate.walker.absent", {}, path))
            continue
        if path.exists() and path.read_text(encoding="utf-8") == content:
            steps.append(Step(name, "unchanged", "integrate.file_same", {}, path))
            continue
        if dry_run:
            steps.append(Step(name, "planned", "integrate.file_would", {}, path))
            continue
        write_text(path, content)
        steps.append(Step(name, "changed", "integrate.file_written", {}, path))
    return steps


def remove(dry_run: bool = False) -> list[Step]:
    steps = []
    for name, path in (("desktop", desktop_file()), ("walker", elephant_file())):
        if path.exists():
            if not dry_run:
                path.unlink()
            steps.append(Step(name, "removed" if not dry_run else "planned", "integrate.removed_file", {}, path))
    return steps


# ---------------------------------------------------------------- waybar


def waybar_dir() -> Path:
    return paths.config_home() / "waybar"


def waybar_config() -> Path | None:
    for name in ("config.jsonc", "config"):
        p = waybar_dir() / name
        if p.exists():
            return p
    return None


def waybar_present() -> bool:
    return shutil.which("waybar") is not None and waybar_config() is not None


def waybar_module() -> str:
    exe = subwatch_exe()
    return (
        "{\n"
        f"  // {t('integrate.waybar.comment')}\n"
        '  "custom/subwatch": {\n'
        f'    "exec": "{exe} bar",\n'
        '    "return-type": "json",\n'
        '    "interval": 300,\n'
        '    "tooltip": true,\n'
        f'    "on-click": "{exe} open",\n'
        f'    "on-click-right": "{exe} menu",\n'
        f'    "on-click-middle": "{SCAN_UNIT_START}"\n'
        "  }\n"
        "}\n"
    )


def apply_waybar(dry_run: bool = False, edit_config: bool = True) -> list[Step]:
    """Write the module file and wire it into the Waybar config."""
    if not waybar_present():
        return [Step("waybar", "skipped", "integrate.waybar.absent", {}, waybar_dir())]
    import json
    import re

    steps = []
    module_path = waybar_dir() / "subwatch.jsonc"
    content = waybar_module()
    if not module_path.exists() or module_path.read_text(encoding="utf-8") != content:
        if not dry_run:
            write_text(module_path, content)
        steps.append(Step("waybar", "planned" if dry_run else "changed", "integrate.file_written", {}, module_path))
    cfg = waybar_config()
    if not edit_config or cfg is None:
        return steps
    text = cfg.read_text(encoding="utf-8")
    if "custom/subwatch" in text:
        steps.append(Step("waybar", "unchanged", "integrate.waybar.same", {}, cfg))
        return steps
    try:
        parsed = json.loads(strip_jsonc(text))
    except ValueError:
        steps.append(Step("waybar", "failed", "integrate.waybar.unparsable", {}, cfg))
        return steps
    if not isinstance(parsed, dict) or "modules-right" not in parsed:
        steps.append(Step("waybar", "skipped", "integrate.waybar.manual", {}, cfg))
        return steps
    new = re.sub(r'("modules-right"\s*:\s*\[)', r'\1"custom/subwatch", ', text, count=1)
    include_line = '"~/.config/waybar/subwatch.jsonc"'
    if '"include"' in text:
        new = re.sub(r'("include"\s*:\s*\[)', r'\1' + include_line + ", ", new, count=1)
    else:
        brace = new.find("{")
        new = new[: brace + 1] + f'\n  "include": [{include_line}],' + new[brace + 1:]
    try:
        json.loads(strip_jsonc(new))
    except ValueError:
        steps.append(Step("waybar", "failed", "integrate.waybar.unparsable", {}, cfg))
        return steps
    if not dry_run:
        from .common import backup_file

        backup_file(cfg)
        write_text(cfg, new)
    steps.append(Step("waybar", "planned" if dry_run else "changed", "integrate.waybar.written", {}, cfg))
    return steps


def remove_waybar(dry_run: bool = False) -> list[Step]:
    import re

    steps = []
    module_path = waybar_dir() / "subwatch.jsonc"
    if module_path.exists():
        if not dry_run:
            module_path.unlink()
        steps.append(Step("waybar", "removed", "integrate.removed_file", {}, module_path))
    cfg = waybar_config()
    if cfg is not None:
        text = cfg.read_text(encoding="utf-8")
        new = re.sub(r'"custom/subwatch",\s*', "", text)
        new = re.sub(r'\n[ \t]*"include": \["~/\.config/waybar/subwatch\.jsonc"\],?', "", new)
        new = re.sub(r'"~/\.config/waybar/subwatch\.jsonc",\s*|,\s*"~/\.config/waybar/subwatch\.jsonc"', "", new)
        if new != text:
            if not dry_run:
                from .common import backup_file

                backup_file(cfg)
                write_text(cfg, new)
            steps.append(Step("waybar", "removed", "integrate.waybar.removed", {}, cfg))
    return steps
