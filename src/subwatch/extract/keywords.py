"""Keyword lists from resources/keywords.toml, filtered by language."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Iterable


@lru_cache(maxsize=1)
def _raw() -> dict:
    ref = resources.files("subwatch") / "resources" / "keywords.toml"
    return tomllib.loads(ref.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class Hit:
    pos: int
    end: int
    phrase: str


class Keywords:
    def __init__(self, languages: Iterable[str] = ("ru", "en", "kk"), extra: Iterable[str] = ()):
        self.languages = tuple(languages)
        self.extra = tuple(e.casefold() for e in extra if e)
        self._cache: dict[str, tuple[str, ...]] = {}

    def group(self, name: str) -> tuple[str, ...]:
        if name in self._cache:
            return self._cache[name]
        table = _raw().get(name, {})
        words: list[str] = []
        if "words" in table:
            words.extend(table["words"])
        for lang in self.languages:
            words.extend(table.get(lang, []))
        if name == "subscription":
            words.extend(self.extra)
        result = tuple(sorted({w.casefold() for w in words}, key=len, reverse=True))
        self._cache[name] = result
        return result

    def find(self, text_cf: str, name: str) -> list[Hit]:
        """All occurrences of the group's phrases in casefolded text."""
        hits = []
        for phrase in self.group(name):
            start = 0
            while True:
                i = text_cf.find(phrase, start)
                if i < 0:
                    break
                hits.append(Hit(i, i + len(phrase), phrase))
                start = i + len(phrase)
        hits.sort(key=lambda h: h.pos)
        return hits

    def any(self, text_cf: str, name: str) -> bool:
        return any(phrase in text_cf for phrase in self.group(name))


@lru_cache(maxsize=1)
def month_regexes() -> tuple[tuple[int, re.Pattern[str]], ...]:
    table = _raw()["months"]
    out = []
    for key, patterns in table.items():
        for pat in patterns:
            out.append((int(key), re.compile(rf"^(?:{pat})\.?$", re.IGNORECASE)))
    return tuple(out)


@lru_cache(maxsize=1)
def month_alternation() -> str:
    table = _raw()["months"]
    parts = [p for pats in table.values() for p in pats]
    parts.sort(key=len, reverse=True)
    return "(?:" + "|".join(parts) + ")"


def month_number(word: str) -> int | None:
    word = word.strip().rstrip(".")
    for number, rx in month_regexes():
        if rx.match(word):
            return number
    return None
