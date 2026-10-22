"""Shared pieces of desktop integration.

Subwatch never edits files owned by the Omarchy package. In user config
files it only writes a block between `>>> subwatch >>>` and
`<<< subwatch <<<` markers; everything outside is left byte for byte.
Every change is backed up first and validated afterwards.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import paths

BEGIN = ">>> subwatch >>>"
END = "<<< subwatch <<<"


@dataclass
class Step:
    """Result of one integration action, rendered by the CLI via the catalog."""

    name: str
    status: str  # changed | unchanged | skipped | removed | failed | planned
    key: str
    params: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None


def subwatch_exe() -> str:
    """Absolute path of the subwatch command to put into generated configs."""
    found = shutil.which("subwatch")
    if found:
        return found
    candidate = paths.home() / ".local" / "bin" / "subwatch"
    return str(candidate)


def backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.subwatch-bak.{stamp}")
    shutil.copy2(path, target)
    return target


def write_text(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".subwatch-", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    if mode is not None:
        os.chmod(tmp, mode)
    elif path.exists():
        os.chmod(tmp, path.stat().st_mode & 0o777)
    else:
        os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def block_pattern(comment: str) -> re.Pattern[str]:
    c = re.escape(comment)
    return re.compile(rf"\n?[ \t]*{c} {re.escape(BEGIN)}.*?{c} {re.escape(END)}[ \t]*\n?", re.S)


def has_block(text: str, comment: str) -> bool:
    return bool(block_pattern(comment).search(text))


def strip_block(text: str, comment: str) -> str:
    return block_pattern(comment).sub("\n", text).rstrip("\n") + "\n" if text.strip() else ""


def replace_block(text: str, comment: str, block: str) -> str:
    """Put a new version of our block where the old one stands.

    Other tools append their own blocks after ours, so moving ours to the
    end on every run would rewrite the file each time. Blank lines right
    before the block are squeezed to one.
    """
    c = re.escape(comment)
    pattern = re.compile(rf"\n*[ \t]*{c} {re.escape(BEGIN)}.*?{c} {re.escape(END)}[ \t]*\n?", re.S)
    return pattern.sub(lambda m: ("\n\n" if m.start() > 0 else "") + block, text, count=1)


def make_block(lines: list[str], comment: str, indent: str = "") -> str:
    body = "\n".join(indent + line if line else line for line in lines)
    return f"{indent}{comment} {BEGIN}\n{body}\n{indent}{comment} {END}\n"


def update_file(
    path: Path,
    transform: Callable[[str], str],
    validate: Callable[[str], bool] | None = None,
    dry_run: bool = False,
    create: bool = True,
) -> str:
    """Apply transform; returns changed / unchanged / planned / invalid / missing."""
    if not path.exists() and not create:
        return "missing"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    new = transform(old)
    if new == old:
        return "unchanged"
    if validate is not None and not validate(new):
        return "invalid"
    if dry_run:
        return "planned"
    backup_file(path)
    write_text(path, new)
    return "changed"


def strip_jsonc(text: str) -> str:
    """Comments (// and /* */) and trailing commas removed, strings kept."""
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        else:
            out.append(ch)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))
