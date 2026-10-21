"""Shared runtime context for the CLI, the TUI and background jobs."""

from __future__ import annotations

from functools import cached_property
from typing import Any

from . import bar, clock, log
from .config.loader import LoadedConfig, load_config
from .config.schema import Config
from .db import Store, db_path_for
from .extract.engine import Learned
from .extract.merchants import MerchantBook, default_book
from .fx import Rates, get_rates
from .i18n import set_language


class AppContext:
    def __init__(self, loaded: LoadedConfig, quiet_logs: bool = False):
        self.loaded = loaded
        self._store: Store | None = None
        self.apply_runtime(quiet_logs)

    @classmethod
    def load(cls, cli: dict[str, Any] | None = None, **kw: Any) -> "AppContext":
        return cls(load_config(cli=cli), **kw)

    def apply_runtime(self, quiet_logs: bool = False) -> None:
        cfg = self.loaded.config
        set_language(cfg.ui.language)
        clock.set_timezone(cfg.general.timezone)
        log.configure(cfg.logging.level, cfg.logging.journal, cfg.logging.file, quiet_logs)

    def reload(self, loaded: LoadedConfig) -> None:
        self.loaded = loaded
        self.__dict__.pop("book", None)
        self.apply_runtime()

    @property
    def config(self) -> Config:
        return self.loaded.config

    @property
    def store(self) -> Store:
        if self._store is None:
            self._store = Store.open(self.config)
        return self._store

    @property
    def db_path(self):
        return db_path_for(self.config)

    @cached_property
    def book(self) -> MerchantBook:
        return default_book()

    def learned(self) -> Learned:
        return Learned.from_store(self.store)

    def rates(self, allow_network: bool = False, force: bool = False) -> Rates:
        return get_rates(self.store, self.config, allow_network=allow_network, force=force)

    def after_change(self) -> None:
        """Cheap follow-ups after any data change: bar cache and calendar."""
        bar.invalidate_cache()
        if self.config.export.ics_auto:
            from .export import write_ics

            try:
                write_ics(self.store.subscriptions(), self.config)
            except OSError as exc:
                log.warning("ics_failed", error=str(exc))

    def close(self) -> None:
        if self._store is not None:
            self._store.close()
            self._store = None
