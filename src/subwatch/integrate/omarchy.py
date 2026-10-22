"""Omarchy 4: menu entries, bar module, post-update hook.

Menu:  ~/.config/omarchy/extensions/omarchy-menu.jsonc (hot-reloaded by the
       shell). Its parser only understands whole-line // comments and
       trailing commas, so the block uses nothing else.
Bar:   the noxqd.subwatch shell plugin (bar widget with a popup and the
       settings window), copied to ~/.config/omarchy/plugins/ and placed in
       ~/.config/omarchy/shell.json. Shells without plugin support get a
       plain `type: command` module instead.
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
    Step,
    backup_file,
    has_block,
    make_block,
    strip_block,
    strip_jsonc,
    subwatch_exe,
    update_file,
    write_text,
)

MODULE_ID = "subwatch"
PLUGIN_ID = "noxqd.subwatch"
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


def plugin_dir() -> Path:
    return omarchy_config() / "plugins" / PLUGIN_ID


def plugins_supported() -> bool:
    """Omarchy 4 shells load QML plugins from ~/.config/omarchy/plugins."""
    return (omarchy_root() / "shell" / "services" / "PluginRegistry.qml").exists()


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


def _find_entry(layout: dict[str, Any], ident: str = MODULE_ID) -> tuple[str, int] | None:
    for section, items in layout.items():
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            current = item.get("id") if isinstance(item, dict) else item
            if current == ident:
                return section, i
    return None


# ---------------------------------------------------------------- plugin


def env_js() -> str:
    return (
        ".pragma library\n"
        f"// {t('integrate.plugin.env_comment')}\n"
        f"var exe = {json.dumps(subwatch_exe())}\n"
        f"var cacheDir = {json.dumps(str(paths.cache_dir()))}\n"
    )


def plugin_files() -> dict[str, bytes]:
    """Everything that goes into the plugin directory, by relative path."""
    from importlib import resources

    out: dict[str, bytes] = {}

    def walk(node: Any, prefix: str) -> None:
        for child in node.iterdir():
            name = prefix + child.name
            if child.is_dir():
                if child.name != "__pycache__":
                    walk(child, name + "/")
            elif child.name not in ("Env.js", ".gitignore"):
                out[name] = child.read_bytes()

    walk(resources.files("subwatch") / "resources" / "omarchy" / "plugin", "")
    out["Env.js"] = env_js().encode()
    return out


def _plugin_changes() -> tuple[dict[str, bytes], list[str]]:
    """(files to write, files to delete) to bring the plugin up to date."""
    target = plugin_dir()
    wanted = plugin_files()
    write = {rel: data for rel, data in wanted.items()
             if not (target / rel).is_file() or (target / rel).read_bytes() != data}
    stale = []
    if target.is_dir():
        stale = sorted(p.relative_to(target).as_posix() for p in target.rglob("*")
                       if p.is_file() and p.relative_to(target).as_posix() not in wanted)
    return write, stale


def plugin_current() -> bool:
    write, stale = _plugin_changes()
    return not write and not stale


def _ours(path: Path) -> bool:
    try:
        return json.loads((path / "manifest.json").read_text(encoding="utf-8")).get("id") == PLUGIN_ID
    except (OSError, ValueError):
        return False


def _shell_ipc(*args: str) -> None:
    import subprocess

    # Only inside a running Hyprland session: the shell is not ours to poke otherwise.
    if shutil.which("omarchy-shell") and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        subprocess.run(["omarchy-shell", "-q", *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=10, check=False)


def _sync_plugin(dry_run: bool) -> bool:
    write, stale = _plugin_changes()
    if dry_run or (not write and not stale):
        return bool(write or stale)
    target = plugin_dir()
    if target.exists() and not _ours(target) and (target / "manifest.json").exists():
        raise OSError(str(target))
    for rel, data in write.items():
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for rel in stale:
        (target / rel).unlink()
    for folder in sorted((p for p in target.rglob("*") if p.is_dir()), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()
    return True


def _apply_plugin(config: Config, dry_run: bool) -> Step:
    from .. import barcache

    path = shell_file()
    data, existed = _load_shell_json()
    if data is None:
        return Step("bar", "failed", "integrate.bar.unreadable", {}, path)
    try:
        files_changed = _sync_plugin(dry_run)
    except OSError:
        return Step("bar", "failed", "integrate.plugin.foreign", {"path": paths.contract_home(plugin_dir())},
                    plugin_dir())
    if files_changed and not dry_run:
        _shell_ipc("shell", "rescanPlugins")
    layout = data.setdefault("bar", {}).setdefault("layout", {})
    plugin_at = _find_entry(layout, PLUGIN_ID)
    legacy_at = _find_entry(layout, MODULE_ID)
    section = plugin_at[0] if plugin_at else config.bar.section
    layout_changed = False
    if legacy_at:
        # The old text-only module gives its place to the widget.
        legacy_section, index = legacy_at
        if plugin_at:
            del layout[legacy_section][index]
        else:
            layout[legacy_section][index] = {"id": PLUGIN_ID}
            section = legacy_section
        layout_changed = True
    elif not plugin_at:
        layout.setdefault(config.bar.section, []).insert(0, {"id": PLUGIN_ID})
        layout_changed = True
    if not layout_changed and not files_changed and existed:
        return Step("bar", "unchanged", "integrate.bar.same", {}, path)
    if dry_run:
        return Step("bar", "planned", "integrate.plugin.would", {"section": section}, path)
    if layout_changed:
        if existed:
            backup_file(path)
        write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    barcache.invalidate()
    key = "integrate.plugin.written" if layout_changed else "integrate.plugin.updated"
    return Step("bar", "changed", key, {"section": section}, path)


def apply_bar(config: Config, dry_run: bool = False) -> Step:
    if plugins_supported():
        return _apply_plugin(config, dry_run)
    return _apply_command(config, dry_run)


def _apply_command(config: Config, dry_run: bool = False) -> Step:
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
    found = [f for f in (_find_entry(layout, PLUGIN_ID), _find_entry(layout, MODULE_ID)) if f]
    has_dir = plugin_dir().exists() and _ours(plugin_dir())
    if not found and not has_dir:
        return Step("bar", "unchanged", "integrate.not_installed", {}, path)
    if dry_run:
        return Step("bar", "planned", "integrate.bar.removed", {}, path)
    if found:
        for section, index in sorted(found, key=lambda f: -f[1]):
            del layout[section][index]
        backup_file(path)
        write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if has_dir:
        shutil.rmtree(plugin_dir())
        _shell_ipc("shell", "rescanPlugins")
    return Step("bar", "removed", "integrate.bar.removed", {}, path)


def _layout() -> dict[str, Any]:
    path = shell_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return (data.get("bar") or {}).get("layout") or {}


def bar_installed() -> bool:
    layout = _layout()
    return _find_entry(layout, PLUGIN_ID) is not None or _find_entry(layout, MODULE_ID) is not None


def plugin_installed() -> bool:
    """The widget is on the bar, so the shell has the window loaded too."""
    return _ours(plugin_dir()) and _find_entry(_layout(), PLUGIN_ID) is not None


# ------------------------------------------------------------------ hook


def hook_script() -> str:
    exe = subwatch_exe()
    return (
        "#!/bin/bash\n"
        f"# {t('integrate.hook.comment')}\n"
        f"[[ -x {exe} ]] && {exe} --quiet integrate apply || true\n"
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
