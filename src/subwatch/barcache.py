"""Bar output cache. Standard library only, so `subwatch bar` can answer from
the cache without importing pydantic, typer or SQLite."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any

from . import clock, paths

MAX_AGE = 3600


def _stamp(path: Path) -> float:
    best = 0.0
    for p in (path, Path(str(path) + "-wal"), Path(str(path) + ".enc")):
        try:
            best = max(best, p.stat().st_mtime)
        except OSError:
            pass
    return best


def key_for(db_path: Path, config_path: Path) -> dict[str, Any]:
    return {"db": _stamp(db_path), "config": _stamp(config_path), "date": clock.today().isoformat()}


def read(db_path: Path, config_path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(paths.bar_cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if raw.get("key") != key_for(db_path, config_path):
        return None
    if clock.now().timestamp() - float(raw.get("generated", 0)) > MAX_AGE:
        return None
    return raw.get("data")


def write(data: dict[str, Any], db_path: Path, config_path: Path) -> None:
    target = paths.bar_cache_file()
    try:
        paths.ensure_private_dir(target.parent)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps({"generated": clock.now().timestamp(),
                                   "key": key_for(db_path, config_path), "data": data},
                                  ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        pass


def invalidate() -> None:
    try:
        paths.bar_cache_file().unlink()
    except OSError:
        pass


def fast_db_path(config_path: Path) -> Path:
    """DB location without loading the full config schema."""
    try:
        with config_path.open("rb") as fh:
            data = tomllib.load(fh)
        custom = (data.get("storage") or {}).get("db_path") or ""
    except (OSError, tomllib.TOMLDecodeError):
        custom = ""
    env = os.environ.get("SUBWATCH_STORAGE__DB_PATH", "")
    custom = env or custom
    return paths.expand(custom) if custom else paths.db_file()
