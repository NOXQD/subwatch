"""Amounts and currencies. Money is always Decimal, never float."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from importlib import resources
from typing import Any


@dataclass(frozen=True)
class CurrencyInfo:
    code: str
    symbol: str
    aliases: tuple[str, ...]
    decimals: int


@lru_cache(maxsize=1)
def currencies() -> dict[str, CurrencyInfo]:
    ref = resources.files("subwatch") / "resources" / "currencies.toml"
    data: dict[str, Any] = tomllib.loads(ref.read_text(encoding="utf-8"))
    out = {}
    for code, item in data.items():
        out[code] = CurrencyInfo(
            code=code,
            symbol=item.get("symbol", code),
            aliases=tuple(a.lower() for a in item.get("aliases", [])),
            decimals=int(item.get("decimals", 2)),
        )
    return out


WORDLIKE_CODES = frozenset({"TRY", "AMD", "GEL"})


@lru_cache(maxsize=1)
def _alias_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for code, info in currencies().items():
        # Codes that are also common words ("try", "gel") only match in
        # upper case, see iso_code_pattern().
        if code not in WORDLIKE_CODES:
            out[code.lower()] = code
        for alias in info.aliases:
            out.setdefault(alias, code)
    return out


def is_known_currency(code: str) -> bool:
    return code.upper() in currencies()


def is_valid_code(code: str) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}", code or ""))


def currency_symbol(code: str) -> str:
    info = currencies().get((code or "").upper())
    return info.symbol if info else (code or "").upper()


def currency_decimals(code: str) -> int:
    info = currencies().get((code or "").upper())
    return info.decimals if info else 2


def resolve_currency(token: str) -> str | None:
    """Map a symbol/word found in text ("тг", "$", "руб.") to an ISO code."""
    if not token:
        return None
    key = token.strip().lower()
    hit = _alias_map().get(key)
    if hit:
        return hit
    key = key.rstrip(".")
    return _alias_map().get(key) or _alias_map().get(key + ".")


@lru_cache(maxsize=1)
def currency_token_pattern() -> str:
    """Regex alternation matching any known currency token, longest first."""
    tokens = sorted(_alias_map(), key=len, reverse=True)
    parts = []
    for tok in tokens:
        escaped = re.escape(tok)
        if tok[-1].isalpha():
            escaped += r"(?![\w])"
        if tok[0].isalpha():
            escaped = r"(?<![\w])" + escaped
        parts.append(escaped)
    return "(?:" + "|".join(parts) + ")"


ISO_CODE_PATTERN = r"(?<![A-Za-z])[A-Z]{3}(?![A-Za-z])"


def to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, int):
        return Decimal(value)
    parsed = parse_number(str(value))
    if parsed is None:
        raise InvalidOperation(str(value))
    return parsed


def quantize(amount: Decimal, places: int = 2) -> Decimal:
    exp = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return amount.quantize(exp, rounding=ROUND_HALF_UP)


_SPACES = "     '’"


def parse_number(text: str) -> Decimal | None:
    """Parse "1 299,00", "1,299.00", "1.299,00", "9.99", "-2 990" etc."""
    if text is None:
        return None
    s = text.strip()
    if not s:
        return None
    negative = s.startswith(("-", "−", "–"))
    s = s.lstrip("+-−– ")
    for ch in _SPACES:
        s = s.replace(ch, "")
    if not s or not re.fullmatch(r"[\d.,]+", s) or not s[0].isdigit():
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        if s.count(",") == 1 and len(tail) in (1, 2):
            s = head + "." + tail
        elif len(tail) == 3:
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    elif "." in s:
        head, _, tail = s.rpartition(".")
        if s.count(".") > 1 or (len(tail) == 3 and head and len(head) <= 3):
            s = s.replace(".", "")
    try:
        value = Decimal(s)
    except InvalidOperation:
        return None
    return -value if negative else value


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "amount", to_decimal(self.amount))
        object.__setattr__(self, "currency", self.currency.upper())
