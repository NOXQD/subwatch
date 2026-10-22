"""Bank statements: CSV and PDF, described by bank templates.

Templates live in resources/banks/*.toml (shipped) and
~/.config/subwatch/banks/*.toml (yours, same name wins). A file is matched to
a template by its headers (CSV) or by marker text (PDF); `--bank` forces
one, `--map` describes the columns by hand ("universal mode").

Only debits are kept, and of them only date, amount, currency and the
normalised merchant name — enough to find recurring charges.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any

from .. import paths
from ..config.schema import Config
from ..errors import SubwatchError
from ..extract.merchants import normalize_descriptor
from ..i18n import t
from ..models import Transaction
from ..money import currency_token_pattern, is_valid_code, parse_number, resolve_currency
from .base import Source, SourceContext, source

COMMON_DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y %H:%M:%S",
                       "%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")


@dataclass
class BankTemplate:
    name: str
    title: str = ""
    format: str = "csv"
    currency: str = ""
    encoding: str = "auto"
    delimiter: str = "auto"
    skip_rows: int = 0
    detect_headers: list[str] = field(default_factory=list)
    detect_text: list[str] = field(default_factory=list)
    date: str = ""
    amount: str = ""
    description: str = ""
    currency_column: str = ""
    debit: str = ""
    credit: str = ""
    type_column: str = ""
    date_format: str = ""
    debit_negative: bool = True
    include_types: list[str] = field(default_factory=list)
    exclude_types: list[str] = field(default_factory=list)
    line_regex: str = ""
    user: bool = False

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any], user: bool = False) -> "BankTemplate":
        cols = data.get("columns", {})
        pdf = data.get("pdf", {})
        return cls(
            name=name,
            title=data.get("title", name),
            format=data.get("format", "csv"),
            currency=data.get("currency", ""),
            encoding=data.get("encoding", "auto"),
            delimiter=data.get("delimiter", "auto"),
            skip_rows=int(data.get("skip_rows", 0)),
            detect_headers=list(data.get("detect_headers", [])),
            detect_text=list(pdf.get("detect_text", data.get("detect_text", []))),
            date=cols.get("date", ""),
            amount=cols.get("amount", ""),
            description=cols.get("description", ""),
            currency_column=cols.get("currency", ""),
            debit=cols.get("debit", ""),
            credit=cols.get("credit", ""),
            type_column=cols.get("type", ""),
            date_format=data.get("date_format", ""),
            debit_negative=bool(data.get("debit_negative", True)),
            include_types=list(data.get("include_types", [])),
            exclude_types=list(data.get("exclude_types", [])),
            line_regex=pdf.get("line_regex", ""),
            user=user,
        )

    def to_toml(self) -> str:
        import tomlkit

        doc = tomlkit.document()
        doc["title"] = self.title or self.name
        doc["format"] = self.format
        if self.currency:
            doc["currency"] = self.currency
        doc["encoding"] = self.encoding
        doc["delimiter"] = self.delimiter
        doc["skip_rows"] = self.skip_rows
        if self.date_format:
            doc["date_format"] = self.date_format
        doc["debit_negative"] = self.debit_negative
        if self.detect_headers:
            doc["detect_headers"] = self.detect_headers
        cols = tomlkit.table()
        for key, attr in (("date", "date"), ("amount", "amount"), ("description", "description"),
                          ("currency", "currency_column"), ("debit", "debit"), ("credit", "credit"),
                          ("type", "type_column")):
            if getattr(self, attr):
                cols[key] = getattr(self, attr)
        doc["columns"] = cols
        return tomlkit.dumps(doc)


def load_templates() -> dict[str, BankTemplate]:
    out: dict[str, BankTemplate] = {}
    base = resources.files("subwatch") / "resources" / "banks"
    for entry in sorted(base.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".toml"):
            name = entry.name[:-5]
            out[name] = BankTemplate.from_dict(name, tomllib.loads(entry.read_text(encoding="utf-8")))
    user_dir = paths.banks_dir()
    if user_dir.is_dir():
        for p in sorted(user_dir.glob("*.toml")):
            try:
                out[p.stem] = BankTemplate.from_dict(p.stem, tomllib.loads(p.read_text(encoding="utf-8")), True)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                raise SubwatchError("statements.err.template", path=str(p), detail=str(exc)) from None
    return out


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _decode(raw: bytes, encoding: str) -> str:
    if encoding and encoding != "auto":
        return raw.decode(encoding)
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _sniff(text: str, delimiter: str) -> str:
    if delimiter and delimiter != "auto":
        return "\t" if delimiter in ("tab", "\\t") else delimiter
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t|").delimiter
    except csv.Error:
        return ";" if sample.count(";") > sample.count(",") else ","


def parse_date(value: str, fmt: str = "") -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    formats = [fmt] if fmt else []
    formats += [f for f in COMMON_DATE_FORMATS if f != fmt]
    for f in formats:
        try:
            return datetime.strptime(value, f).date()
        except ValueError:
            continue
    m = re.match(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})", value)
    if m:
        y = int(m.group(3))
        y += 2000 if y < 100 else 0
        try:
            return date(y, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


@dataclass
class ParseResult:
    template: BankTemplate
    rows: int
    transactions: list[Transaction]
    skipped: int = 0


def _amount_and_currency(raw: str, default_currency: str) -> tuple[Decimal | None, str]:
    raw = (raw or "").strip()
    currency = default_currency
    m = re.search(r"[A-Za-z]{3}|" + currency_token_pattern(), raw, re.IGNORECASE)
    if m:
        code = resolve_currency(m.group(0)) or (m.group(0).upper() if is_valid_code(m.group(0).upper()) else None)
        if code:
            currency = code
        raw = (raw[: m.start()] + raw[m.end():]).strip()
    return parse_number(raw), currency


def parse_csv(text: str, tpl: BankTemplate, default_currency: str, sha: str) -> ParseResult:
    delim = _sniff(text, tpl.delimiter)
    lines = text.splitlines()[tpl.skip_rows:]
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delim)
    headers = [h.strip() for h in (reader.fieldnames or [])]
    reader.fieldnames = headers
    needed = [c for c in (tpl.date, tpl.description) if c]
    missing = [c for c in needed + ([tpl.amount] if tpl.amount else [tpl.debit]) if c and c not in headers]
    if missing:
        raise SubwatchError("statements.err.columns", hint="statements.hint.map",
                            columns=", ".join(missing), headers=", ".join(headers))
    out: list[Transaction] = []
    rows = skipped = 0
    seq: dict[tuple, int] = {}
    for row in reader:
        rows += 1
        day = parse_date(row.get(tpl.date, ""), tpl.date_format)
        desc = (row.get(tpl.description) or "").strip()
        kind = (row.get(tpl.type_column) or "").strip() if tpl.type_column else ""
        if kind and tpl.exclude_types and any(x.casefold() in kind.casefold() for x in tpl.exclude_types):
            skipped += 1
            continue
        if kind and tpl.include_types and not any(x.casefold() in kind.casefold() for x in tpl.include_types):
            skipped += 1
            continue
        currency = default_currency
        if tpl.currency_column and row.get(tpl.currency_column):
            code = row[tpl.currency_column].strip().upper()
            currency = resolve_currency(code) or (code if is_valid_code(code) else currency)
        if tpl.amount:
            amount, currency = _amount_and_currency(row.get(tpl.amount, ""), currency)
            if amount is None:
                skipped += 1
                continue
            if tpl.debit_negative:
                if amount >= 0:
                    skipped += 1
                    continue
                amount = -amount
            elif amount <= 0:
                skipped += 1
                continue
        else:
            amount, currency = _amount_and_currency(row.get(tpl.debit, ""), currency)
            if amount is None or amount == 0:
                skipped += 1
                continue
            amount = abs(amount)
        if day is None or not desc:
            skipped += 1
            continue
        name, _ = normalize_descriptor(desc)
        key = (day, amount, currency, name)
        seq[key] = seq.get(key, 0) + 1
        out.append(Transaction(day, amount, currency, name, description="", file_sha256=sha, seq=seq[key]))
    return ParseResult(tpl, rows, out, skipped)


def pdf_text(path: Path) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise SubwatchError("statements.err.no_pdf") from None
    try:
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:  # pdfminer raises a zoo of errors
        raise SubwatchError("statements.err.pdf", path=str(path), detail=str(exc)) from None


def parse_pdf_text(text: str, tpl: BankTemplate, default_currency: str, sha: str) -> ParseResult:
    if not tpl.line_regex:
        raise SubwatchError("statements.err.no_regex", name=tpl.name)
    rx = re.compile(tpl.line_regex)
    out: list[Transaction] = []
    rows = skipped = 0
    seq: dict[tuple, int] = {}
    for line in text.splitlines():
        m = rx.search(line.strip())
        if not m:
            continue
        rows += 1
        g = m.groupdict()
        kind = (g.get("type") or "").strip()
        if kind and tpl.exclude_types and any(x.casefold() in kind.casefold() for x in tpl.exclude_types):
            skipped += 1
            continue
        if kind and tpl.include_types and not any(x.casefold() in kind.casefold() for x in tpl.include_types):
            skipped += 1
            continue
        cur_raw = (g.get("currency") or "").strip()
        cur = resolve_currency(cur_raw) if cur_raw else None
        amount, currency = _amount_and_currency(g.get("amount", ""), cur or default_currency)
        if amount is None:
            skipped += 1
            continue
        if "sign" in rx.groupindex:
            sign = (g.get("sign") or "").strip()
            if sign == "+" or (not sign and tpl.debit_negative):
                skipped += 1
                continue
        elif (tpl.debit_negative and amount >= 0) or (not tpl.debit_negative and amount <= 0):
            skipped += 1
            continue
        amount = abs(amount)
        day = parse_date(g.get("date", ""), tpl.date_format)
        desc = (g.get("description") or "").strip()
        if day is None or not desc or amount == 0:
            skipped += 1
            continue
        name, _ = normalize_descriptor(desc)
        key = (day, amount, currency, name)
        seq[key] = seq.get(key, 0) + 1
        out.append(Transaction(day, amount, currency, name, file_sha256=sha, seq=seq[key]))
    return ParseResult(tpl, rows, out, skipped)


def detect_template(path: Path, text: str | None, templates: dict[str, BankTemplate]) -> BankTemplate | None:
    if path.suffix.lower() == ".pdf":
        if text is None:
            return None
        cf = text.casefold()
        for tpl in templates.values():
            if tpl.format == "pdf" and tpl.detect_text and all(m.casefold() in cf for m in tpl.detect_text):
                return tpl
        return None
    if text is None:
        return None
    # Most specific template first: more required headers, user templates win ties.
    candidates = sorted((t for t in templates.values() if t.format == "csv" and t.detect_headers),
                        key=lambda t: (len(t.detect_headers), t.user), reverse=True)
    lines = text.splitlines()
    for skip in range(0, min(15, len(lines))):
        header = lines[skip]
        delim = _sniff(header, "auto")
        cells = {c.strip().strip('"').strip() for c in next(csv.reader([header], delimiter=delim), [])}
        for tpl in candidates:
            if all(h in cells for h in tpl.detect_headers):
                if tpl.skip_rows != skip:
                    tpl = BankTemplate(**{**tpl.__dict__, "skip_rows": skip})
                return tpl
    return None


def template_from_mapping(mapping: str, base: BankTemplate | None = None, **overrides: Any) -> BankTemplate:
    tpl = BankTemplate(name="custom", title=t("statements.custom_title")) if base is None \
        else BankTemplate(**base.__dict__)
    for part in mapping.split(","):
        key, sep, value = part.partition("=")
        if not sep:
            raise SubwatchError("statements.err.map_syntax", hint="statements.hint.map", value=part)
        key = key.strip().lower()
        attr = {"date": "date", "amount": "amount", "description": "description", "desc": "description",
                "currency": "currency_column", "debit": "debit", "credit": "credit", "type": "type_column"}.get(key)
        if attr is None:
            raise SubwatchError("statements.err.map_key", hint="statements.hint.map", value=key)
        setattr(tpl, attr, value.strip())
    for k, v in overrides.items():
        if v is not None:
            setattr(tpl, k, v)
    return tpl


def read_statement(path: Path, config: Config, template: BankTemplate | None = None,
                   templates: dict[str, BankTemplate] | None = None) -> ParseResult:
    templates = templates or load_templates()
    sha = file_sha256(path)
    raw_text = pdf_text(path) if path.suffix.lower() == ".pdf" else _decode(
        path.read_bytes(), template.encoding if template else "auto")
    tpl = template or detect_template(path, raw_text, templates)
    if tpl is None:
        raise SubwatchError("statements.err.unknown_format", hint="statements.hint.bank", path=str(path))
    currency = tpl.currency or config.currency.base
    if tpl.format == "pdf" or path.suffix.lower() == ".pdf":
        return parse_pdf_text(raw_text, tpl, currency, sha)
    if template is not None and template.encoding not in ("", "auto"):
        raw_text = _decode(path.read_bytes(), template.encoding)
    return parse_csv(raw_text, tpl, currency, sha)


def csv_headers(path: Path, encoding: str = "auto", delimiter: str = "auto", skip: int = 0) -> list[str]:
    text = _decode(path.read_bytes(), encoding)
    delim = _sniff(text, delimiter)
    lines = text.splitlines()[skip:]
    if not lines:
        return []
    return [h.strip() for h in next(csv.reader([lines[0]], delimiter=delim))]


@source("statements", kind="transactions")
class StatementsSource(Source):
    """Auto-import of statements dropped into sources.statements.inbox_dir."""

    def enabled(self, config: Config) -> bool:
        return bool(config.sources.statements.inbox_dir)

    def fetch(self, ctx: SourceContext) -> Iterator[Transaction]:
        cfg = ctx.config.sources.statements
        folder = paths.expand(cfg.inbox_dir)
        if not folder.is_dir():
            raise SubwatchError("statements.err.inbox", hint="statements.hint.inbox", path=str(folder))
        templates = load_templates()
        forced = templates.get(cfg.default_bank) if cfg.default_bank != "auto" else None
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in (".csv", ".pdf", ".txt"):
                continue
            sha = file_sha256(path)
            if ctx.store.is_imported(sha):
                continue
            result = read_statement(path, ctx.config, forced, templates)
            yield from result.transactions
            ctx.store.mark_imported(sha, path.name, result.template.name, result.rows, len(result.transactions))
