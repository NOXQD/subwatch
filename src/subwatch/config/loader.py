"""Loading the effective configuration.

Priority, highest first:

    1. command line (--set key=value and command specific flags)
    2. environment: SUBWATCH_<SECTION>__<KEY>=value, e.g.
       SUBWATCH_CURRENCY__BASE=USD, SUBWATCH_REMINDERS__DAYS_BEFORE=7,3,1
    3. ~/.config/subwatch/config.toml
    4. defaults from the schema

Values from the environment and --set are parsed as TOML literals when
possible ("12", "true", "[1, 2]") and kept as plain strings otherwise.
"""

from __future__ import annotations

import copy
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, get_args, get_origin

from pydantic import BaseModel, ValidationError

from .. import paths
from ..i18n import t
from .schema import Config

ENV_PREFIX = "SUBWATCH_"


class ConfigError(Exception):
    """Configuration could not be read or validated."""

    def __init__(self, path: Path | None, problems: list[tuple[str, str]]):
        self.path = path
        self.problems = problems
        super().__init__("; ".join(f"{k}: {m}" for k, m in problems))

    def render(self) -> str:
        if self.path:
            lines = [t("config.err.header", path=paths.contract_home(self.path))]
        else:
            lines = [t("config.err.header_value")]
        for key, message in self.problems:
            lines.append(t("config.err.line", key=key or "—", message=message))
        return "\n".join(lines)


@dataclass
class LoadedConfig:
    config: Config
    path: Path
    exists: bool
    file_data: dict[str, Any] = field(default_factory=dict)
    env_data: dict[str, Any] = field(default_factory=dict)
    cli_data: dict[str, Any] = field(default_factory=dict)
    mtime: float | None = None

    def origin(self, dotted: str) -> str:
        for name, layer in (("cli", self.cli_data), ("env", self.env_data), ("file", self.file_data)):
            if _has_path(layer, dotted.split(".")):
                return name
        return "default"


# ---------------------------------------------------------------- utilities


def parse_scalar(text: str) -> Any:
    """Interpret a string the way TOML would, falling back to the raw text."""
    try:
        return tomllib.loads(f"v = {text}")["v"]
    except tomllib.TOMLDecodeError:
        return text


def set_dotted(target: dict[str, Any], parts: list[str], value: Any) -> None:
    node = target
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value


def _has_path(data: Mapping[str, Any], parts: list[str]) -> bool:
    node: Any = data
    for part in parts:
        if not isinstance(node, Mapping) or part not in node:
            return False
        node = node[part]
    return True


def get_dotted(data: Any, parts: list[str]) -> Any:
    node = data
    for part in parts:
        if isinstance(node, BaseModel):
            if part not in type(node).model_fields:
                raise KeyError(part)
            node = getattr(node, part)
        elif isinstance(node, Mapping):
            node = node[part]
        elif isinstance(node, list) and part.isdigit():
            node = node[int(part)]
        else:
            raise KeyError(part)
    return node


def deep_merge(base: dict[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, Mapping) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def flatten(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        full = f"{prefix}{key}"
        if isinstance(value, Mapping) and value:
            out.update(flatten(value, full + "."))
        else:
            out[full] = value
    return out


def env_overrides(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    out: dict[str, Any] = {}
    for name, value in environ.items():
        if not name.startswith(ENV_PREFIX) or "__" not in name[len(ENV_PREFIX):]:
            continue
        parts = [p.lower() for p in name[len(ENV_PREFIX):].split("__") if p]
        if parts:
            set_dotted(out, parts, parse_scalar(value))
    return out


def cli_overrides(pairs: list[str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise ConfigError(None, [(pair, t("config.err.set_syntax"))])
        set_dotted(out, key.strip().split("."), parse_scalar(value.strip()))
    return out


def field_annotation(dotted: str) -> Any:
    """Schema annotation for a dotted key, or raise KeyError."""
    model: Any = Config
    annotation: Any = Config
    parts = dotted.split(".")
    i = 0
    while i < len(parts):
        part = parts[i]
        if isinstance(model, type) and issubclass(model, BaseModel):
            if part not in model.model_fields:
                raise KeyError(dotted)
            annotation = model.model_fields[part].annotation
            model = _unwrap_model(annotation)
        elif get_origin(model) is dict:
            annotation = get_args(model)[1]
            model = _unwrap_model(annotation)
        else:
            raise KeyError(dotted)
        i += 1
    return annotation


def _unwrap_model(annotation: Any) -> Any:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    if get_origin(annotation) is dict:
        return annotation
    for arg in get_args(annotation):
        if isinstance(arg, type) and issubclass(arg, BaseModel):
            return arg
    return annotation


def describe_validation_error(exc: ValidationError) -> list[tuple[str, str]]:
    problems = []
    for err in exc.errors(include_url=False):
        loc_parts = []
        for item in err.get("loc", ()):
            if isinstance(item, int):
                loc_parts.append(f"[{item}]")
            else:
                loc_parts.append(("." if loc_parts else "") + str(item))
        loc = "".join(loc_parts)
        problems.append((loc, _error_message(err)))
    return problems


_ERROR_KEYS = {
    "missing": "config.err.missing",
    "extra_forbidden": "config.err.unknown_key",
    "int_parsing": "config.err.int",
    "int_type": "config.err.int",
    "int_from_float": "config.err.int",
    "float_parsing": "config.err.float",
    "float_type": "config.err.float",
    "bool_parsing": "config.err.bool",
    "bool_type": "config.err.bool",
    "string_type": "config.err.string",
    "list_type": "config.err.list",
    "dict_type": "config.err.table",
    "model_type": "config.err.table",
    "model_attributes_type": "config.err.table",
    "decimal_parsing": "config.err.number",
    "decimal_type": "config.err.number",
    "greater_than_equal": "config.err.ge",
    "less_than_equal": "config.err.le",
    "greater_than": "config.err.gt",
    "less_than": "config.err.lt",
    "literal_error": "config.err.literal",
}


def _error_message(err: dict[str, Any]) -> str:
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    if kind == "value_error":
        return str(ctx.get("error", err.get("msg", "")))
    key = _ERROR_KEYS.get(kind)
    if key is None:
        return t("config.err.generic", detail=err.get("msg", kind))
    params = {k: str(v) for k, v in ctx.items()}
    if "expected" in params:
        params["expected"] = params["expected"].replace("' or '", "'" + t("config.err.or") + "'")
    return t(key, **params)


_TOML_POS = re.compile(r"\(at line (\d+), column (\d+)\)")


def read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        m = _TOML_POS.search(str(exc))
        if m:
            msg = t("config.err.toml_at", line=m.group(1), column=m.group(2))
        else:
            msg = t("config.err.toml", detail=str(exc))
        raise ConfigError(path, [("", msg)]) from None
    except OSError as exc:
        raise ConfigError(path, [("", t("config.err.read", detail=exc.strerror or str(exc)))]) from None


def validate(data: Mapping[str, Any], path: Path | None = None) -> Config:
    try:
        return Config.model_validate(dict(data))
    except ValidationError as exc:
        raise ConfigError(path, describe_validation_error(exc)) from None


def load_config(
    path: Path | None = None,
    cli: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> LoadedConfig:
    path = path or paths.config_file()
    exists = path.is_file()
    file_data = read_toml(path) if exists else {}
    env_data = env_overrides(environ)
    cli_data = dict(cli or {})
    merged = deep_merge(deep_merge(file_data, env_data), cli_data)
    config = validate(merged, path)
    mtime = path.stat().st_mtime if exists else None
    return LoadedConfig(config, path, exists, file_data, env_data, cli_data, mtime)


class ConfigWatcher:
    """Polls the config file and returns a fresh config when it changes.

    An invalid edit keeps the previous config and reports the error once, so
    a half-saved file in an editor never takes the TUI down.
    """

    def __init__(self, loaded: LoadedConfig):
        self.loaded = loaded
        self.last_error: ConfigError | None = None
        self._mtime = loaded.mtime

    def poll(self) -> LoadedConfig | None:
        path = self.loaded.path
        try:
            mtime = path.stat().st_mtime if path.is_file() else None
        except OSError:
            return None
        if mtime == self._mtime:
            return None
        self._mtime = mtime
        try:
            fresh = load_config(path, self.loaded.cli_data)
        except ConfigError as exc:
            self.last_error = exc
            return None
        self.last_error = None
        self.loaded = fresh
        return fresh
