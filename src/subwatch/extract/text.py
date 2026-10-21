"""Turning email bodies into plain text the extractor can read."""

from __future__ import annotations

import email
import email.policy
import html
import re
import unicodedata
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from ..models import RawMessage

_BLOCK_TAGS = {
    "p", "div", "br", "tr", "li", "ul", "ol", "table", "tbody", "thead", "h1", "h2", "h3",
    "h4", "h5", "h6", "section", "article", "header", "footer", "blockquote", "hr", "td",
    "th", "dd", "dt",
}
_SKIP_TAGS = {"script", "style", "head", "title", "noscript", "template"}

MAX_TEXT = 40_000


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n" if tag not in ("td", "th") else " ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n" if tag not in ("td", "th") else " ")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:
        return normalize(re.sub(r"<[^>]+>", " ", html.unescape(markup)))
    return normalize("".join(parser.parts))


_SPACE_RUN = re.compile(r"[ \t\f\v   ​]+")


def normalize(text: str) -> str:
    """NFKC, unify spaces and dashes, drop empty lines, keep line structure."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("­", "").replace("\r", "")
    text = re.sub(r"[‐-―−]", "-", text)
    lines = []
    for line in text.split("\n"):
        line = _SPACE_RUN.sub(" ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)[:MAX_TEXT]


def message_text(msg: RawMessage) -> str:
    if msg.text.strip():
        return normalize(msg.text)
    if msg.html:
        return html_to_text(msg.html)
    return ""


def _part_text(part: EmailMessage) -> str:
    try:
        return part.get_content()
    except (LookupError, UnicodeDecodeError, AssertionError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", "replace")


def parse_email(raw: bytes, source: str, key: str, account: str | None = None) -> RawMessage:
    """Build a RawMessage from RFC 822 bytes, keeping only what we need."""
    parsed = email.message_from_bytes(raw, policy=email.policy.default)
    assert isinstance(parsed, EmailMessage)
    name, address = parseaddr(str(parsed.get("From", "")))
    date: datetime | None = None
    if parsed.get("Date"):
        try:
            date = parsedate_to_datetime(str(parsed["Date"]))
        except (TypeError, ValueError):
            date = None
    plain = ""
    markup = ""
    for part in parsed.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain" and not plain:
            plain = _part_text(part)
        elif ctype == "text/html" and not markup:
            markup = _part_text(part)
    headers = {}
    for h in ("Message-ID", "List-Id", "List-Unsubscribe"):
        if parsed.get(h):
            headers[h] = str(parsed[h])
    return RawMessage(
        source=source,
        key=key,
        sender=address.lower(),
        sender_name=name,
        subject=str(parsed.get("Subject", "")),
        date=date,
        text=plain,
        html=markup,
        account=account,
        headers=headers,
    )
