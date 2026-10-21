"""Source plugin API.

A source is a class registered with @source("name"). It yields RawMessage
objects (emails) or Transaction objects (bank operations); everything after
that — extraction, deduplication, storage — is shared.

Built-in sources use exactly the same API as user plugins in
~/.config/subwatch/plugins/*.py.
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from .. import paths
from ..config.schema import Config
from ..models import RawMessage, Transaction

REGISTRY: dict[str, type["Source"]] = {}
PLUGIN_ERRORS: dict[str, str] = {}
PLUGIN_FILES: dict[str, str] = {}


@dataclass
class SourceContext:
    config: Config
    store: Any
    since: date
    full: bool = False
    max_messages: int = 5000
    options: dict[str, Any] = field(default_factory=dict)
    prefilter: Callable[[str, str], bool] | None = None
    progress: Callable[[str, int], None] | None = None


class Source:
    """Base class for sources. Subclasses set `name` via the decorator."""

    name: str = ""
    kind: str = "messages"  # "messages" or "transactions"
    builtin: bool = False

    def enabled(self, config: Config) -> bool:
        options = config.plugins.options.get(self.name, {})
        return bool(options.get("enabled", True))

    def fetch(self, ctx: SourceContext) -> Iterator[RawMessage | Transaction]:
        raise NotImplementedError

    def check(self, config: Config) -> Iterable[tuple[bool, str]]:
        """Doctor checks: (ok, catalog_key, params) triples."""
        return ()


def source(name: str, kind: str = "messages") -> Callable[[type[Source]], type[Source]]:
    """Register a source class under `name`."""

    def decorator(cls: type[Source]) -> type[Source]:
        cls.name = name
        cls.kind = kind
        module = getattr(cls, "__module__", "")
        cls.builtin = module.startswith("subwatch.")
        REGISTRY[name] = cls
        if not cls.builtin:
            PLUGIN_FILES[name] = getattr(sys.modules.get(module), "__file__", "") or ""
        return cls

    return decorator


def load_builtin() -> None:
    from . import gmail, imap, manual, statements  # noqa: F401


def load_plugins(config: Config, directory: Path | None = None) -> dict[str, str]:
    """Import every *.py in the plugins dir. Returns {file: error} for failures."""
    PLUGIN_ERRORS.clear()
    if not config.plugins.enabled:
        return {}
    directory = directory or paths.plugins_dir()
    if not directory.is_dir():
        return {}
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module_name = f"subwatch_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(str(path))
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            PLUGIN_ERRORS[str(path)] = traceback.format_exc(limit=3).strip().splitlines()[-1]
    return dict(PLUGIN_ERRORS)


def available(config: Config) -> dict[str, Source]:
    load_builtin()
    out = {}
    for name, cls in REGISTRY.items():
        if name in config.plugins.disabled:
            continue
        out[name] = cls()
    return out
