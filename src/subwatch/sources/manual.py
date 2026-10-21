"""Manual entries. They are written straight to the database by the CLI and
the TUI; the source exists so manual records show up in `subwatch plugins
list` and in statistics like every other origin."""

from __future__ import annotations

from typing import Iterator

from ..config.schema import Config
from ..models import RawMessage
from .base import Source, SourceContext, source


@source("manual")
class ManualSource(Source):
    kind = "manual"

    def enabled(self, config: Config) -> bool:
        return False  # nothing to fetch

    def fetch(self, ctx: SourceContext) -> Iterator[RawMessage]:
        return iter(())
