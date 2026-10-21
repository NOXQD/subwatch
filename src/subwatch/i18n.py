"""Translation catalog.

All user-facing text lives in resources/i18n/<lang>.toml. Russian is the
reference catalog and the fallback for keys a translation does not have yet.
A file with the same name in ~/.config/subwatch/i18n/ overrides or extends
the shipped one, so a new language needs no code changes.

    t("scan.done", count=3)      -> plain string with {placeholders} filled
    tn("units.day", 5)           -> plural-aware string, {n} is the number
    tget("months.genitive")      -> raw value (lists, tables)
"""

from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

from . import paths

DEFAULT_LANGUAGE = "ru"
PLURAL_FORMS = {"zero", "one", "two", "few", "many", "other"}

_catalogs: dict[str, dict[str, Any]] = {}
_current = DEFAULT_LANGUAGE


def _plural_slavic(n: int) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return "one"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "few"
    return "many"


def _plural_one_other(n: int) -> str:
    return "one" if abs(n) == 1 else "other"


def _plural_none(n: int) -> str:
    return "other"


PLURAL_RULES = {
    "slavic": _plural_slavic,
    "one_other": _plural_one_other,
    "none": _plural_none,
}


class _SafeFormat(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _flatten(data: dict[str, Any], prefix: str, out: dict[str, Any]) -> None:
    for key, value in data.items():
        full = f"{prefix}{key}"
        if isinstance(value, dict) and value and not set(value) <= PLURAL_FORMS:
            _flatten(value, full + ".", out)
        else:
            out[full] = value


def _shipped_file(lang: str) -> Path | None:
    ref = resources.files("subwatch") / "resources" / "i18n" / f"{lang}.toml"
    try:
        with resources.as_file(ref) as p:
            return p if p.is_file() else None
    except (FileNotFoundError, OSError):
        return None


def _read(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    flat: dict[str, Any] = {}
    _flatten(raw, "", flat)
    return flat


def load_catalog(lang: str) -> dict[str, Any]:
    if lang in _catalogs:
        return _catalogs[lang]
    merged: dict[str, Any] = {}
    shipped = _shipped_file(lang)
    if shipped is not None:
        merged.update(_read(shipped))
    user = paths.user_i18n_dir() / f"{lang}.toml"
    if user.is_file():
        try:
            merged.update(_read(user))
        except (OSError, tomllib.TOMLDecodeError):
            pass
    _catalogs[lang] = merged
    return merged


def available_languages() -> dict[str, str]:
    """Language code -> its own name, from shipped and user catalogs."""
    codes: set[str] = set()
    base = resources.files("subwatch") / "resources" / "i18n"
    for entry in base.iterdir():
        if entry.name.endswith(".toml"):
            codes.add(entry.name[:-5])
    user_dir = paths.user_i18n_dir()
    if user_dir.is_dir():
        codes.update(p.stem for p in user_dir.glob("*.toml"))
    result = {}
    for code in sorted(codes):
        cat = load_catalog(code)
        result[code] = str(cat.get("meta.name", code))
    return result


def set_language(lang: str | None) -> str:
    """Switch the active language; unknown codes fall back to Russian."""
    global _current
    lang = (lang or DEFAULT_LANGUAGE).strip().lower()
    if lang != DEFAULT_LANGUAGE and not load_catalog(lang):
        lang = DEFAULT_LANGUAGE
    _current = lang
    load_catalog(DEFAULT_LANGUAGE)
    return _current


def get_language() -> str:
    return _current


def reset_cache() -> None:
    _catalogs.clear()


def _lookup(key: str) -> Any:
    value = load_catalog(_current).get(key)
    if value is None and _current != DEFAULT_LANGUAGE:
        value = load_catalog(DEFAULT_LANGUAGE).get(key)
    return value


def has(key: str) -> bool:
    return _lookup(key) is not None


def tget(key: str, default: Any = None) -> Any:
    value = _lookup(key)
    if value is None:
        # A table: rebuild it from the flattened keys.
        prefix = key + "."
        merged: dict[str, Any] = {}
        for lang in (DEFAULT_LANGUAGE, _current):
            for k, v in load_catalog(lang).items():
                if k.startswith(prefix):
                    merged[k[len(prefix):]] = v
        value = merged or None
    return default if value is None else value


def t(key: str, /, **kwargs: Any) -> str:
    value = _lookup(key)
    if value is None:
        return key
    if isinstance(value, dict):
        value = value.get("other") or value.get("many") or next(iter(value.values()))
    text = str(value)
    if kwargs:
        text = text.format_map(_SafeFormat(kwargs))
    return text


def plural_category(n: int, lang: str | None = None) -> str:
    cat = load_catalog(lang or _current)
    rule = PLURAL_RULES.get(str(cat.get("meta.plural", "one_other")), _plural_one_other)
    return rule(int(n))


def tn(key: str, n: int, /, **kwargs: Any) -> str:
    value = _lookup(key)
    if value is None:
        return key
    if isinstance(value, dict):
        form = plural_category(n)
        text = value.get(form) or value.get("other") or value.get("many")
        if text is None:
            text = next(iter(value.values()))
    else:
        text = value
    return str(text).format_map(_SafeFormat({"n": n, **kwargs}))


set_language(DEFAULT_LANGUAGE)
