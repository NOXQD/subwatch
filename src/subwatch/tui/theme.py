"""TUI colours from the current Omarchy theme.

Omarchy keeps the active theme in ~/.local/state/omarchy/current/theme/ with
the palette in colors.toml (accent, background, foreground, red, yellow,
green...). ui.colors in config.toml overrides single colours.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from textual.theme import Theme

from .. import paths
from ..config.schema import Config

THEME_NAME = "subwatch-omarchy"


def omarchy_colors_file() -> Path:
    candidates = [
        paths.state_home() / "omarchy" / "current" / "theme" / "colors.toml",
        paths.config_home() / "omarchy" / "current" / "theme" / "colors.toml",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def read_palette(path: Path | None = None) -> dict[str, str] | None:
    path = path or omarchy_colors_file()
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return {k: str(v) for k, v in data.items() if isinstance(v, str)}


def palette_mtime() -> float:
    try:
        return omarchy_colors_file().stat().st_mtime
    except OSError:
        return 0.0


def _pick(p: dict[str, str], *names: str, default: str) -> str:
    for n in names:
        v = p.get(n)
        if v and v.startswith("#"):
            return v
    return default


def build_theme(config: Config) -> tuple[Theme | None, str]:
    """(theme to register or None, name to activate)."""
    choice = config.ui.theme
    palette = read_palette() if choice in ("auto", "omarchy") else None
    overrides = {k: v for k, v in config.ui.colors.model_dump().items() if v}
    if palette is None:
        if choice in ("auto", "omarchy"):
            base_name = "textual-dark"
        else:
            base_name = choice
        if not overrides:
            return None, base_name
        palette = {}
    dark = palette.get("mode", "dark") != "light"
    colors = {
        "primary": _pick(palette, "accent", "blue", default="#7aa2f7"),
        "secondary": _pick(palette, "blue", "cyan", default="#7dcfff"),
        "accent": _pick(palette, "magenta", "accent", default="#bb9af7"),
        "foreground": _pick(palette, "foreground", default="#c0caf5" if dark else "#1a1b26"),
        "background": _pick(palette, "background", default="#1a1b26" if dark else "#f5f5f5"),
        "surface": _pick(palette, "dark_background", "lighter_background", "background",
                         default="#1f2335" if dark else "#e8e8e8"),
        "panel": _pick(palette, "lighter_background", "selection", default="#24283b" if dark else "#dddddd"),
        "success": _pick(palette, "green", default="#9ece6a"),
        "warning": _pick(palette, "yellow", "orange", default="#e0af68"),
        "error": _pick(palette, "red", default="#f7768e"),
    }
    colors.update(overrides)
    theme = Theme(name=THEME_NAME, dark=dark, **colors)
    return theme, THEME_NAME


def in_omarchy() -> bool:
    return bool(os.environ.get("OMARCHY_PATH")) or omarchy_colors_file().exists()
