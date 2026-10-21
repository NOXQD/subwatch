"""Desktop integration as one operation: apply, remove, status."""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import paths
from ..config.schema import Config
from . import hyprland, launchers, omarchy, systemd
from .common import Step, write_text

COMPONENTS = ("systemd", "bar", "menu", "keybinds", "launchers", "waybar", "hook", "completion")


def completion_targets() -> dict[str, Path]:
    targets = {"bash": paths.data_home() / "bash-completion" / "completions" / "subwatch"}
    if shutil.which("zsh"):
        targets["zsh"] = paths.data_home() / "zsh" / "site-functions" / "_subwatch"
    if shutil.which("fish"):
        targets["fish"] = paths.config_home() / "fish" / "completions" / "subwatch.fish"
    return targets


def completion_source(shell: str) -> str:
    from typer._click.shell_completion import get_completion_class
    from typer._completion_classes import completion_init

    from ..cli.main import click_command

    completion_init()
    cls = get_completion_class(shell)
    if cls is None:
        raise ValueError(shell)
    return cls(click_command(), {}, "subwatch", "_SUBWATCH_COMPLETE").source()


def apply_completion(dry_run: bool = False) -> list[Step]:
    steps = []
    for shell, path in completion_targets().items():
        content = completion_source(shell)
        if path.exists() and path.read_text(encoding="utf-8") == content:
            steps.append(Step("completion", "unchanged", "integrate.file_same", {"shell": shell}, path))
            continue
        if not dry_run:
            write_text(path, content, mode=0o644)
        steps.append(Step("completion", "planned" if dry_run else "changed", "integrate.file_written",
                          {"shell": shell}, path))
    return steps


def remove_completion(dry_run: bool = False) -> list[Step]:
    steps = []
    for shell, path in completion_targets().items():
        if path.exists():
            if not dry_run:
                path.unlink()
            steps.append(Step("completion", "removed", "integrate.removed_file", {"shell": shell}, path))
    return steps


def apply_all(config: Config, only: list[str] | None = None, dry_run: bool = False) -> list[Step]:
    want = set(only or COMPONENTS)
    steps: list[Step] = []
    if "systemd" in want:
        steps += systemd.apply(config, dry_run)
    on_omarchy = omarchy.is_omarchy()
    if "bar" in want:
        steps.append(omarchy.apply_bar(config, dry_run) if on_omarchy
                     else Step("bar", "skipped", "integrate.omarchy_absent"))
    if "menu" in want:
        steps.append(omarchy.apply_menu(config, dry_run) if on_omarchy
                     else Step("menu", "skipped", "integrate.omarchy_absent"))
    if "hook" in want:
        steps.append(omarchy.apply_hook(dry_run) if on_omarchy
                     else Step("hook", "skipped", "integrate.omarchy_absent"))
    if "keybinds" in want:
        steps += hyprland.apply(config, dry_run)
    if "launchers" in want:
        steps += launchers.apply(dry_run)
    if "waybar" in want:
        steps += launchers.apply_waybar(dry_run)
    if "completion" in want:
        steps += apply_completion(dry_run)
    return steps


def remove_all(only: list[str] | None = None, dry_run: bool = False) -> list[Step]:
    want = set(only or COMPONENTS)
    steps: list[Step] = []
    if "systemd" in want:
        steps += systemd.remove(dry_run)
    if "bar" in want:
        steps.append(omarchy.remove_bar(dry_run))
    if "menu" in want:
        steps.append(omarchy.remove_menu(dry_run))
    if "hook" in want:
        steps.append(omarchy.remove_hook(dry_run))
    if "keybinds" in want:
        steps += hyprland.remove(dry_run)
    if "launchers" in want:
        steps += launchers.remove(dry_run)
    if "waybar" in want:
        steps += launchers.remove_waybar(dry_run)
    if "completion" in want:
        steps += remove_completion(dry_run)
    return steps
