"""User-facing errors carry a catalog key, not a hardcoded message."""

from __future__ import annotations

from typing import Any

from .i18n import t


class SubwatchError(Exception):
    """An error meant to be shown to the user as is.

    key   - catalog key of the message
    hint  - optional catalog key of a "what to do" line
    """

    exit_code = 1

    def __init__(self, key: str, hint: str | None = None, **params: Any):
        self.key = key
        self.hint = hint
        self.params = params
        super().__init__(key)

    @property
    def message(self) -> str:
        return t(self.key, **self.params)

    @property
    def hint_text(self) -> str | None:
        return t(self.hint, **self.params) if self.hint else None

    def __str__(self) -> str:
        return self.message


class LockedError(SubwatchError):
    exit_code = 75  # EX_TEMPFAIL


class NotFoundError(SubwatchError):
    exit_code = 2
