"""Removing personal data before text leaves the extractor.

Used for stored snippets and for everything sent to an AI model. The goal is
"send the minimum": addresses, card and phone numbers, account numbers and
greeting/address lines go away, then only lines that look relevant are kept.
"""

from __future__ import annotations

import re

from .keywords import Keywords, regex_group

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"https?://([^/\s?#]+)[^\s]*", re.IGNORECASE)
IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
MASKED_CARD = re.compile(
    r"(?:[*•xX]{2,}[\s-]?){1,3}\d{4}\b|\*\d{4}\b|" + regex_group("redact_card_tail") + r"\s*\d{4}",
    re.IGNORECASE,
)
DIGIT_RUN = re.compile(r"(?<![\w.,])\+?\(?\d[\d \-().]{6,}\d(?![\w])")
GREETING = re.compile(r"^\s*" + regex_group("redact_greeting") + r"(?!\w)", re.IGNORECASE)
# "your verification code is 4417": up to two words between the word and the digits.
CODE = re.compile(r"(?<!\w)(" + regex_group("redact_code_word") + r")((?:[\s:—-]+[^\s\d]{1,20}){0,2}[\s:—-]+)"
                  r"\d{3,8}(?!\d)", re.IGNORECASE)
ADDRESS = re.compile(r"(?<!\w)" + regex_group("redact_address") + r"(?!\w)", re.IGNORECASE)


def _digits(s: str) -> int:
    return sum(ch.isdigit() for ch in s)


def _replace_runs(match: re.Match[str]) -> str:
    chunk = match.group(0)
    n = _digits(chunk)
    stripped = chunk.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", stripped):
        return chunk
    if 13 <= n <= 19 and "+" not in chunk and "(" not in chunk:
        return "[card]"
    if 10 <= n <= 15:
        return "[phone]"
    if n >= 8 and not re.search(r"[.,]\d{2}$", chunk):
        return "[number]"
    return chunk


def redact(text: str) -> str:
    out = []
    for line in (text or "").split("\n"):
        if GREETING.match(line) or ADDRESS.search(line):
            continue
        line = EMAIL.sub("[email]", line)
        line = URL.sub(lambda m: m.group(1).lower(), line)
        line = IBAN.sub("[account]", line)
        line = MASKED_CARD.sub("[card]", line)
        line = CODE.sub(lambda m: m.group(1) + m.group(2) + "[code]", line)
        line = DIGIT_RUN.sub(_replace_runs, line)
        out.append(line)
    return "\n".join(out)


def minimize(text: str, subject: str, kw: Keywords, max_chars: int) -> str:
    """Redact, then keep only lines that can help identify a subscription."""
    clean = redact(text)
    groups = ("subscription", "paid", "renewal", "cancellation", "trial", "price_change",
              "period_month", "period_year", "period_week", "next_date", "amount_label")
    keep: list[str] = []
    for line in clean.split("\n"):
        cf = line.casefold()
        if any(ch.isdigit() for ch in line) or any(kw.any(cf, g) for g in groups):
            keep.append(line.strip())
    body = "\n".join(dict.fromkeys(k for k in keep if k))
    head = redact(subject).strip()
    payload = (head + "\n" + body).strip() if head else body
    if len(payload) > max_chars:
        payload = payload[:max_chars].rsplit("\n", 1)[0] if "\n" in payload[:max_chars] else payload[:max_chars]
    return payload
