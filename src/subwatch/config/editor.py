"""Editing config.toml without losing the user's comments (tomlkit)."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any, get_args, get_origin

import tomlkit
from pydantic import BaseModel
from tomlkit.items import AoT, Table

from .. import paths
from ..i18n import get_language, t
from .loader import ConfigError, field_annotation, flatten, get_dotted, parse_scalar, validate
from .schema import Config


def default_template() -> str:
    """The commented default config for the current UI language."""
    base = resources.files("subwatch") / "resources"
    localized = base / f"config.default.{get_language()}.toml"
    if localized.is_file():
        return localized.read_text(encoding="utf-8")
    return (base / "config.default.toml").read_text(encoding="utf-8")


def write_atomic(path: Path, text: str, mode: int = 0o600) -> None:
    paths.ensure_private_dir(path.parent)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.bak.{stamp}")
    n = 1
    while target.exists():
        target = path.with_name(f"{path.name}.bak.{stamp}-{n}")
        n += 1
    shutil.copy2(path, target)
    return target


def ensure_config_file(path: Path | None = None) -> tuple[Path, bool]:
    """Create config.toml from the template if missing. Returns (path, created)."""
    path = path or paths.config_file()
    if path.exists():
        return path, False
    write_atomic(path, default_template())
    return path, True


def _load_doc(path: Path) -> tomlkit.TOMLDocument:
    if not path.exists():
        return tomlkit.parse(default_template())
    try:
        return tomlkit.parse(path.read_text(encoding="utf-8"))
    except Exception as exc:  # tomlkit raises its own ParseError subclasses
        raise ConfigError(path, [("", t("config.err.toml", detail=str(exc)))]) from None


def coerce_for_field(dotted: str, raw: str) -> Any:
    """Turn a command-line string into the type the schema expects."""
    try:
        annotation = field_annotation(dotted)
    except KeyError:
        raise ConfigError(None, [(dotted, t("config.err.unknown_key"))]) from None
    base = _strip_optional(annotation)
    origin = get_origin(base)
    if base is str:
        value = parse_scalar(raw)
        return value if isinstance(value, str) else raw
    if origin is list:
        value = parse_scalar(raw)
        if isinstance(value, list):
            return value
        items = [item.strip() for item in raw.split(",") if item.strip()]
        inner = get_args(base)[0] if get_args(base) else str
        if inner is int:
            return [int(i) for i in items] if all(i.lstrip("-").isdigit() for i in items) else items
        return items
    if base is bool:
        low = raw.strip().lower()
        if low in ("true", "yes", "on", "1"):
            return True
        if low in ("false", "no", "off", "0"):
            return False
        return raw
    value = parse_scalar(raw)
    if base is Decimal and isinstance(value, (int, float)):
        return value
    return value


def _strip_optional(annotation: Any) -> Any:
    args = [a for a in get_args(annotation) if a is not type(None)]
    if get_origin(annotation) is not None and len(args) == 1 and get_origin(annotation) is not list:
        return args[0]
    return annotation


def _to_toml_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value) if value != value.to_integral_value() else int(value)
    if isinstance(value, list):
        return [_to_toml_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_toml_value(v) for k, v in value.items()}
    return value


def set_value(dotted: str, raw: str, path: Path | None = None) -> tuple[Any, Any]:
    """Set a key, validate the whole file, then write. Returns (old, new)."""
    path = path or paths.config_file()
    value = coerce_for_field(dotted, raw)
    doc = _load_doc(path)
    parts = dotted.split(".")
    node: Any = doc
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], (Table, dict)):
            node[part] = tomlkit.table()
        node = node[part]
    old = node.get(parts[-1])
    old_plain = old.unwrap() if hasattr(old, "unwrap") else old
    node[parts[-1]] = _to_toml_value(value)
    text = tomlkit.dumps(doc)
    validate(tomlkit.parse(text).unwrap(), path)
    write_atomic(path, text)
    return old_plain, value


def _toml_item(value: Any) -> Any:
    """Lists of tables become [[arrays of tables]], dicts become tables."""
    if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        aot = tomlkit.aot()
        for item in value:
            table = tomlkit.table()
            for k, v in item.items():
                if v is not None:
                    table[k] = _toml_item(v)
            aot.append(table)
        return aot
    if isinstance(value, dict):
        table = tomlkit.table()
        for k, v in value.items():
            if v is not None:
                table[k] = _toml_item(v)
        return table
    return _to_toml_value(value)


def set_python(dotted: str, value: Any, path: Path | None = None) -> tuple[Any, Any]:
    """Like set_value, but takes an already typed value (from the settings
    window): lists of tables and whole tables are written as such."""
    try:
        field_annotation(dotted)
    except KeyError:
        raise ConfigError(None, [(dotted, t("config.err.unknown_key"))]) from None
    path = path or paths.config_file()
    doc = _load_doc(path)
    parts = dotted.split(".")
    node: Any = doc
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], (Table, dict)):
            node[part] = tomlkit.table()
        node = node[part]
    old = node.get(parts[-1])
    old_plain = old.unwrap() if hasattr(old, "unwrap") else old
    item = _toml_item(value) if value is not None else None
    if isinstance(old, Table) and isinstance(value, dict):
        # Update a table in place, so it keeps its spot and comments.
        for key in [k for k in old if k not in value or value[k] is None]:
            del old[key]
        for key, v in value.items():
            if v is not None:
                old[key] = _toml_item(v)
    else:
        structured = isinstance(item, (AoT, Table)) or isinstance(old, (AoT, Table))
        if parts[-1] in node and (item is None or structured):
            del node[parts[-1]]
        if item is not None:
            node[parts[-1]] = item
    text = tomlkit.dumps(doc)
    validate(tomlkit.parse(text).unwrap(), path)
    write_atomic(path, text)
    return old_plain, value


def materialize(dotted: str, effective: Config, path: Path | None = None) -> None:
    """Write the effective value of a table into the file if the file has
    no such table yet, so that editing one entry keeps the others."""
    path = path or paths.config_file()
    doc = _load_doc(path)
    node: Any = doc
    for part in dotted.split("."):
        if part not in node:
            set_python(dotted, plain(get_dotted(effective, dotted.split("."))), path)
            return
        node = node[part]


def unset_value(dotted: str, path: Path | None = None) -> bool:
    path = path or paths.config_file()
    if not path.exists():
        return False
    doc = _load_doc(path)
    parts = dotted.split(".")
    node: Any = doc
    for part in parts[:-1]:
        if part not in node:
            return False
        node = node[part]
    if parts[-1] not in node:
        return False
    del node[parts[-1]]
    text = tomlkit.dumps(doc)
    validate(tomlkit.parse(text).unwrap(), path)
    write_atomic(path, text)
    return True


def reset_file(path: Path | None = None) -> Path | None:
    path = path or paths.config_file()
    saved = backup(path)
    write_atomic(path, default_template())
    return saved


def plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return {k: plain(getattr(value, k)) for k in type(value).model_fields}
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, Decimal):
        return _to_toml_value(value)
    return value


def diff(effective: Config) -> list[tuple[str, Any, Any]]:
    """(key, default, effective) for every value that differs from defaults."""
    defaults = flatten(plain(Config()))
    current = flatten(plain(effective))
    out = []
    for key in sorted(set(defaults) | set(current)):
        a, b = defaults.get(key), current.get(key)
        if (a == {} and b is None) or (b == {} and a is None):
            continue
        if a != b:
            out.append((key, a, b))
    return out


def get_value(effective: Config, dotted: str) -> Any:
    try:
        return plain(get_dotted(effective, dotted.split(".")))
    except (KeyError, IndexError):
        raise ConfigError(None, [(dotted, t("config.err.unknown_key"))]) from None


def render_value(value: Any) -> str:
    """Show a value the way it would be written in TOML."""
    import json

    if value is None:
        return "—"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Decimal):
        return str(_to_toml_value(value))
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(render_value(v) for v in value) + "]"
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{ " + ", ".join(f"{k} = {render_value(v)}" for k, v in value.items()) + " }"
    return str(value)
