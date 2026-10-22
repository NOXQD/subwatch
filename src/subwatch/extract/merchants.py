"""Known services and merchant name normalisation.

    normalize_descriptor("NETFLIX.COM*123")          -> "Netflix" (via the book)
    book.match_message(sender, subject, body)         -> best MerchantMatch
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from .. import paths
from ..models import service_key
from ..period import Period, PeriodError
from .keywords import _raw as _keywords_raw
from .keywords import regex_group


@dataclass
class Merchant:
    id: str
    name: str
    category: str = "other"
    senders: tuple[str, ...] = ()
    patterns: tuple[re.Pattern[str], ...] = ()
    shared: bool = False
    generic: bool = False
    period: Period | None = None
    cancel_url: str | None = None
    includes: tuple[str, ...] = ()
    user: bool = False

    @property
    def key(self) -> str:
        return service_key(self.name)


@dataclass
class MerchantMatch:
    merchant: Merchant
    score: int
    sender_hit: bool = False
    subject_hit: bool = False
    body_hit: bool = False
    specificity: int = 0
    reasons: list[str] = field(default_factory=list)


def _compile(patterns: list[str]) -> tuple[re.Pattern[str], ...]:
    out = []
    for pat in patterns:
        try:
            out.append(re.compile(pat, re.IGNORECASE))
        except re.error:
            continue
    return tuple(out)


def _merchant_from(mid: str, item: dict[str, Any], user: bool) -> Merchant:
    period = None
    if item.get("period"):
        try:
            period = Period.parse(item["period"])
        except PeriodError:
            period = None
    return Merchant(
        id=mid,
        name=str(item.get("name", mid)),
        category=str(item.get("category", "other")),
        senders=tuple(str(s).lower() for s in item.get("senders", [])),
        patterns=_compile(list(item.get("patterns", []))),
        shared=bool(item.get("shared", False)),
        generic=bool(item.get("generic", False)),
        period=period,
        cancel_url=item.get("cancel_url") or None,
        includes=tuple(item.get("includes", [])),
        user=user,
    )


def _sender_matches(sender: str, domain: str, entry: str) -> bool:
    if "@" in entry:
        return sender == entry
    return domain == entry or domain.endswith("." + entry)


class MerchantBook:
    def __init__(self, merchants: list[Merchant]):
        # User entries first so they win ties.
        self.merchants = sorted(merchants, key=lambda m: (not m.user,))
        self.by_id = {m.id: m for m in merchants}
        self.by_key: dict[str, Merchant] = {}
        for m in self.merchants:
            self.by_key.setdefault(m.key, m)

    @classmethod
    def load(cls, user_file: Path | None = None) -> "MerchantBook":
        ref = resources.files("subwatch") / "resources" / "merchants.toml"
        shipped: dict[str, Any] = tomllib.loads(ref.read_text(encoding="utf-8"))
        user_file = user_file if user_file is not None else paths.user_merchants_file()
        user: dict[str, Any] = {}
        if user_file.is_file():
            try:
                user = tomllib.loads(user_file.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                user = {}
        merchants = []
        for mid, item in shipped.items():
            override = user.get(mid)
            if isinstance(override, dict):
                merged = {**item, **override}
                merchants.append(_merchant_from(mid, merged, True))
            else:
                merchants.append(_merchant_from(mid, item, False))
        for mid, item in user.items():
            if mid not in shipped and isinstance(item, dict):
                merchants.append(_merchant_from(mid, item, True))
        return cls(merchants)

    # ------------------------------------------------------------- lookups

    def get(self, mid: str) -> Merchant | None:
        return self.by_id.get(mid)

    def find_service(self, name: str) -> Merchant | None:
        return self.by_key.get(service_key(name))

    def bundle_partners(self, name: str) -> set[str]:
        """Service keys that are bundled with (or include) this service."""
        m = self.find_service(name)
        if not m:
            return set()
        out = {self.by_id[i].key for i in m.includes if i in self.by_id}
        for other in self.merchants:
            if m.id in other.includes:
                out.add(other.key)
        return out

    # ------------------------------------------------------------ matching

    def match_text(self, text: str) -> Merchant | None:
        """Best pattern hit in a short text such as a statement descriptor."""
        best: tuple[int, int, Merchant] | None = None
        for m in self.merchants:
            for rx in m.patterns:
                hit = rx.search(text)
                if hit:
                    rank = (0 if m.generic else 1, len(hit.group(0)))
                    if best is None or rank > best[:2]:
                        best = (rank[0], rank[1], m)
        return best[2] if best else None

    def match_message(self, sender: str, subject: str, body: str) -> MerchantMatch | None:
        sender = (sender or "").lower().strip("<> ")
        domain = sender.rpartition("@")[2]
        subject_cf = (subject or "").casefold()
        body_cf = (body or "")[:8000].casefold()
        candidates: list[MerchantMatch] = []
        for m in self.merchants:
            sender_hit = bool(domain) and any(_sender_matches(sender, domain, s) for s in m.senders)
            subj = [h for rx in m.patterns if (h := rx.search(subject_cf))]
            body_hits = [h for rx in m.patterns if (h := rx.search(body_cf))]
            subject_hit, body_hit = bool(subj), bool(body_hits)
            if not (sender_hit or subject_hit or body_hit):
                continue
            if (m.shared or m.generic) and not (subject_hit or body_hit) and not m.generic:
                continue
            score = 0
            if sender_hit:
                score += 1 if (m.shared or m.generic) else 3
            if subject_hit:
                score += 2
            if body_hit:
                score += 1
            spec = max((len(h.group(0)) for h in subj + body_hits), default=0)
            candidates.append(MerchantMatch(m, score, sender_hit, subject_hit, body_hit, spec))
        if not candidates:
            return None
        specific = [c for c in candidates if not c.merchant.generic]
        pool = specific or candidates
        pool.sort(key=lambda c: (c.score, c.specificity, c.merchant.user), reverse=True)
        return pool[0]


@lru_cache(maxsize=4)
def _cached_book(user_file: str, mtime: float) -> MerchantBook:
    return MerchantBook.load(Path(user_file))


def default_book() -> MerchantBook:
    user = paths.user_merchants_file()
    mtime = user.stat().st_mtime if user.is_file() else 0.0
    return _cached_book(str(user), mtime)


# ------------------------------------------------------- descriptor cleanup

_PREFIX = re.compile(r"^" + regex_group("descriptor_prefix") + r"\s*[*:\s]\s*", re.IGNORECASE)
_REF = re.compile(r"\*[\w-]*\d[\w-]*|#\s*\d+|\b\d{4,}\b|\b[a-z]*\d{3,}[a-z0-9]*\b", re.IGNORECASE)
_DOMAIN_TAIL = re.compile(r"\.(?:com|net|org|io|ru|kz|co|me|tv|app|ai|so|us|uk|de)\b", re.IGNORECASE)
_COUNTRIES = (
    "KZ", "RU", "US", "CA", "GB", "UK", "NL", "IE", "DE", "FR", "SE", "CZ", "LU", "CY", "AE", "SG",
    "BY", "UA", "KG", "UZ", "AM", "GE", "TR", "CN", "JP", "ES", "IT", "PL", "AU", "CH", "AT", "BE",
    "DK", "FI", "NO", "PT", "IL", "IN", "HK", "KR", "USA", "KAZ", "RUS", "GBR", "NLD", "IRL",
)
_COUNTRY_TAIL = re.compile(r"\s+(?:" + "|".join(_COUNTRIES) + r")$")


def clean_descriptor(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "").strip()
    # Fixed-width statement columns: the merchant comes first.
    text = re.split(r"\s{3,}|\t", text)[0]
    text = _PREFIX.sub("", text)
    text = _REF.sub(" ", text)
    text = _DOMAIN_TAIL.sub("", text)
    text = re.sub(r"^www\.", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[*_]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" -.,:;/")
    text = _COUNTRY_TAIL.sub("", text).strip()
    if text.isupper() and len(text) > 3:
        text = " ".join(w.capitalize() if len(w) > 2 else w for w in text.split())
    return text


def normalize_descriptor(raw: str, book: MerchantBook | None = None) -> tuple[str, Merchant | None]:
    """Canonical service name for a raw merchant string, plus the match."""
    book = book or default_book()
    m = book.match_text(raw or "")
    if m is None:
        cleaned = clean_descriptor(raw)
        m = book.match_text(cleaned) if cleaned else None
        if m is None:
            return cleaned or (raw or "").strip(), None
    return m.name, m


def guess_name_from_sender(sender_name: str, sender: str) -> str:
    noise = {w.casefold() for w in _keywords_raw().get("sender_noise", {}).get("words", [])}
    words = [w for w in re.split(r"[\s|,]+", sender_name or "") if w]
    kept = [w for w in words if w.casefold().strip(".:-") not in noise]
    if kept:
        return " ".join(kept).strip(" -.:")
    domain = (sender or "").rpartition("@")[2]
    parts = [p for p in domain.split(".") if p]
    generic = {"mail", "email", "e", "news", "info", "billing", "noreply", "notify", "notifications",
               "accounts", "account", "payments", "receipts"}
    core = [p for p in parts[:-1] if p not in generic] if len(parts) > 1 else parts
    name = core[-1] if core else (parts[0] if parts else "")
    return name.capitalize()
