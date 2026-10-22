"""What has to happen outside config.toml when a setting changes.

Only components that are already installed are touched: changing a key
never installs integration the user did not ask for.
"""

from __future__ import annotations

from .schema import Config


def _changed(old: Config, new: Config, *dotted: str) -> bool:
    from .loader import get_dotted

    for key in dotted:
        parts = key.split(".")
        if get_dotted(old, parts) != get_dotted(new, parts):
            return True
    return False


def apply_side_effects(old: Config, new: Config):
    from .. import bar
    from ..integrate import hyprland, launchers, omarchy, systemd
    from ..integrate.common import Step

    steps: list[Step] = []
    bar.invalidate_cache()
    language = _changed(old, new, "ui.language")
    units_installed = (systemd.unit_dir() / "subwatch-scan.timer").exists()
    if units_installed and (language or _changed(
        old, new, "scan.schedule", "scan.randomized_delay", "scan.persistent", "scan.nice",
        "scan.io_class", "reminders.check_interval",
    )):
        steps += systemd.apply(new)
    binds_installed = any((hyprland.hypr_dir() / n).exists() for n in ("subwatch.lua", "subwatch.conf"))
    if binds_installed and new.keybinds.auto_apply and (language or _changed(old, new, "keybinds")):
        steps += hyprland.apply(new)
    if omarchy.bar_installed() and _changed(old, new, "bar.interval"):
        steps.append(omarchy.apply_bar(new))
    menu_changed = _changed(old, new, "menu.enabled")
    if (omarchy.menu_installed() or (omarchy.is_omarchy() and menu_changed)) and (language or menu_changed):
        steps.append(omarchy.apply_menu(new) if new.menu.enabled else omarchy.remove_menu())
    if language and launchers.desktop_file().exists():
        steps += launchers.apply()
    return [s for s in steps if s.status not in ("unchanged",)]
