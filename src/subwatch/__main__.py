"""Entry point.

Two things happen before the CLI is imported:
  * `subwatch bar` is answered from the cache when possible (the bar calls it
    every few minutes; no reason to import half the app for that);
  * the UI language is chosen, because typer reads help texts at import time.
Language priority is the same as for every other setting:
--lang > SUBWATCH_UI__LANGUAGE > ui.language in config.toml > ru.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path


def _config_path(argv: list[str]) -> Path:
    for i, a in enumerate(argv):
        if a in ("--config", "-c") and i + 1 < len(argv):
            return Path(argv[i + 1]).expanduser()
        if a.startswith("--config="):
            return Path(a.split("=", 1)[1]).expanduser()
    from . import paths

    return paths.config_file()


def _fast_bar(argv: list[str]) -> bool:
    if not argv or argv[0] != "bar" or any(a in ("-h", "--help") for a in argv):
        return False
    rest = argv[1:]
    if rest and rest not in (["--format", "waybar"], ["-f", "waybar"], ["--format=waybar"]):
        return False
    from . import barcache

    cfg = _config_path([])
    data = barcache.read(barcache.fast_db_path(cfg), cfg)
    if data is None:
        return False
    import json

    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    return True


def _language(argv: list[str]) -> str:
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    env = os.environ.get("SUBWATCH_UI__LANGUAGE")
    if env:
        return env
    try:
        with _config_path(argv).open("rb") as fh:
            return str((tomllib.load(fh).get("ui") or {}).get("language") or "ru")
    except (OSError, tomllib.TOMLDecodeError):
        return "ru"


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    os.umask(0o077)
    if _fast_bar(argv):
        return
    from .i18n import set_language

    set_language(_language(argv))
    from .cli.main import run

    run(argv)


if __name__ == "__main__":
    main()
