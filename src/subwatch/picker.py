"""Choosing one item from a list via whatever menu the desktop has.

Order for picker = "auto": the Omarchy menu (omarchy-menu-select), Walker,
fuzzel, wofi, rofi, then fzf in a terminal.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Option:
    value: str
    label: str
    icon: str = ""
    detail: str = ""


ORDER = ("omarchy", "walker", "fuzzel", "wofi", "rofi", "fzf")
COMMANDS = {
    "omarchy": "omarchy-menu-select",
    "walker": "walker",
    "fuzzel": "fuzzel",
    "wofi": "wofi",
    "rofi": "rofi",
    "fzf": "fzf",
}


def available(preferred: str = "auto") -> str | None:
    names = ORDER if preferred == "auto" else (preferred,)
    for name in names:
        if name == "fzf" and not sys.stdin.isatty():
            continue
        if shutil.which(COMMANDS[name]):
            return name
    return None


def _line(opt: Option, with_icon: bool) -> str:
    text = opt.label + (f" — {opt.detail}" if opt.detail else "")
    return f"{opt.icon}\t{text}" if with_icon and opt.icon else text


def choose(prompt: str, options: list[Option], preferred: str = "auto") -> str | None:
    if not options:
        return None
    tool = available(preferred)
    if tool is None:
        return None
    lines = [_line(o, tool == "omarchy") for o in options]
    by_line = {}
    for opt, line in zip(options, lines, strict=True):
        by_line[line] = opt.value
        by_line[line.split("\t", 1)[-1]] = opt.value
        by_line[opt.label] = opt.value
    if tool == "omarchy":
        cmd = ["omarchy-menu-select", prompt, *lines, "--", "--width", "560"]
        stdin = None
    elif tool == "walker":
        cmd = ["walker", "--dmenu", "--placeholder", prompt]
        stdin = "\n".join(lines)
    elif tool == "fuzzel":
        cmd = ["fuzzel", "--dmenu", "--prompt", prompt + " "]
        stdin = "\n".join(lines)
    elif tool == "wofi":
        cmd = ["wofi", "--dmenu", "--prompt", prompt]
        stdin = "\n".join(lines)
    elif tool == "rofi":
        cmd = ["rofi", "-dmenu", "-p", prompt]
        stdin = "\n".join(lines)
    else:
        cmd = ["fzf", "--prompt", prompt + " > ", "--height", "40%"]
        stdin = "\n".join(lines)
    try:
        out = subprocess.run(cmd, input=stdin, text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL if tool != "fzf" else None,
                             env=dict(os.environ), timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    picked = out.stdout.strip()
    if not picked:
        return None
    return by_line.get(picked) or by_line.get(picked.split("\t")[0]) or picked
