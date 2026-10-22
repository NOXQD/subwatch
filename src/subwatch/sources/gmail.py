"""Gmail source (OAuth, scope gmail.readonly only).

First run: a search query limited to receipts/billing words and known
service senders, newer_than:<months_back>m. Later runs: the History API from
the stored historyId, so only new messages are looked at; their headers are
checked first and the body is downloaded only for candidates. If the stored
historyId is too old (HTTP 404) we fall back to a search with after:<date>.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from .. import clock, log, secrets
from ..config.schema import Config, GmailConfig
from ..errors import SubwatchError
from ..models import RawMessage
from ..retry import RateLimiter, retry
from .base import Source, SourceContext, source

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
REVOKE_URI = "https://oauth2.googleapis.com/revoke"

MAX_QUERY = 1500


def _quote(term: str) -> str:
    return f'"{term}"' if " " in term else term


def build_queries(cfg: GmailConfig, config: Config, since: date | None, sender_domains: list[str],
                  months_back: int) -> list[str]:
    """Search queries; split in two when one would get too long."""
    scope = []
    if since is not None:
        scope.append(f"after:{since:%Y/%m/%d}")
    else:
        scope.append(f"newer_than:{months_back}m")
    for label in cfg.exclude_labels:
        low = label.lower()
        scope.append(f"-in:{low}" if low in ("spam", "trash") else f"-label:{_quote(label)}")
    if cfg.labels:
        scope.append("{" + " ".join(f"label:{_quote(lbl)}" for lbl in cfg.labels) + "}")
    for pattern in config.filters.exclude_senders:
        if "*" not in pattern or pattern.startswith("*@"):
            scope.append(f"-from:{pattern.lstrip('*@') if pattern.startswith('*@') else pattern}")
    if cfg.query:
        scope.append(cfg.query)
    from ..extract.keywords import Keywords

    words = Keywords(config.extraction.languages).group("gmail_query")
    terms = [_quote(t) for t in list(words) + list(config.extraction.extra_keywords)]
    senders = [f"from:{d}" for d in sender_domains]
    base = " ".join(scope)
    combined = f"{base} {{{' '.join(terms + senders)}}}"
    if len(combined) <= MAX_QUERY:
        return [combined]
    out = [f"{base} {{{' '.join(terms)}}}"]
    chunk: list[str] = []
    for s in senders:
        if len(base) + len(" ".join(chunk + [s])) + 4 > MAX_QUERY:
            out.append(f"{base} {{{' '.join(chunk)}}}")
            chunk = []
        chunk.append(s)
    if chunk:
        out.append(f"{base} {{{' '.join(chunk)}}}")
    return out


def load_credentials(account: str):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    raw = secrets.get(secrets.gmail_token_name(account))
    if not raw:
        raise SubwatchError("gmail.err.no_token", hint="gmail.hint.auth", account=account)
    info = json.loads(raw)
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if not creds.valid:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            raise SubwatchError("gmail.err.refresh", hint="gmail.hint.refresh", account=account,
                                detail=str(exc)) from None
    return creds


def save_credentials(account: str, creds) -> None:
    info = {
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "token_uri": creds.token_uri or TOKEN_URI,
        "scopes": list(creds.scopes or SCOPES),
    }
    secrets.put(secrets.gmail_token_name(account), json.dumps(info))


def build_service(creds):
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode_b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def payload_text(payload: dict[str, Any]) -> tuple[str, str]:
    """(plain, html) from a format=full payload tree."""
    plain, html = "", ""
    stack = [payload]
    while stack:
        part = stack.pop(0)
        mime = part.get("mimeType", "")
        data = (part.get("body") or {}).get("data")
        if data and mime == "text/plain" and not plain:
            plain = _decode_b64(data).decode("utf-8", "replace")
        elif data and mime == "text/html" and not html:
            html = _decode_b64(data).decode("utf-8", "replace")
        stack.extend(part.get("parts") or [])
    return plain, html


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    return {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers") or []}


def message_from_full(item: dict[str, Any], account: str) -> RawMessage:
    payload = item.get("payload") or {}
    hdr = _headers(payload)
    name, address = parseaddr(hdr.get("from", ""))
    when: datetime | None = None
    if item.get("internalDate"):
        when = datetime.fromtimestamp(int(item["internalDate"]) / 1000, tz=clock.local_tz())
    elif hdr.get("date"):
        try:
            when = parsedate_to_datetime(hdr["date"])
        except (TypeError, ValueError):
            when = None
    plain, html = payload_text(payload)
    headers = {}
    if hdr.get("list-unsubscribe"):
        headers["List-Unsubscribe"] = hdr["list-unsubscribe"]
    return RawMessage(
        source="gmail",
        key=f"gmail:{account}:{item['id']}",
        sender=address.lower(),
        sender_name=name,
        subject=hdr.get("subject", ""),
        date=when,
        text=plain,
        html=html,
        account=account,
        headers=headers,
    )


FULL_FIELDS = (
    "id,internalDate,labelIds,payload(mimeType,headers,body/data,"
    "parts(mimeType,body/data,parts(mimeType,body/data,parts(mimeType,body/data))))"
)
META_FIELDS = "id,labelIds,payload/headers"


def _http_status(exc: BaseException) -> int | None:
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    return int(status) if status is not None else None


@source("gmail")
class GmailSource(Source):
    kind = "messages"

    def __init__(self, service_factory=None):
        # Tests inject a fake service; normal runs build the real client.
        self._factory = service_factory

    def enabled(self, config: Config) -> bool:
        return config.sources.gmail.enabled

    def check(self, config: Config):
        account = config.sources.gmail.account
        has = secrets.exists(secrets.gmail_token_name(account))
        yield has, ("gmail.check.ok" if has else "gmail.check.no_token"), {"account": account}

    def _service(self, account: str):
        if self._factory is not None:
            return self._factory(account)
        return build_service(load_credentials(account))

    def fetch(self, ctx: SourceContext) -> Iterator[RawMessage]:
        cfg = ctx.config.sources.gmail
        account = cfg.account
        service = self._service(account)
        limiter = RateLimiter(cfg.rate_limit)

        def call(request):
            limiter.acquire()

            def run():
                return request.execute(num_retries=cfg.max_retries)

            return retry(run, attempts=2, retry_on=(OSError, TimeoutError))

        profile = call(service.users().getProfile(userId="me"))
        current_history = str(profile.get("historyId", ""))
        cursor = ctx.store.get_cursor("gmail", account, "") or {}
        from ..extract.merchants import default_book

        domains = sorted({s for m in default_book().merchants for s in m.senders if "@" not in s})

        ids: list[str] = []
        via_history = False
        if cursor.get("history_id") and not ctx.full:
            try:
                ids = self._history_ids(service, call, cursor["history_id"], cfg)
                via_history = True
            except Exception as exc:  # googleapiclient.errors.HttpError
                if _http_status(exc) != 404:
                    raise
                log.info("gmail_history_expired", account=account)
                last = cursor.get("last_scan")
                since = date.fromisoformat(last) - timedelta(days=1) if last else None
                ids = self._search_ids(service, call, cfg, ctx, since, domains)
        else:
            ids = self._search_ids(service, call, cfg, ctx, None, domains)

        ids = ids[: ctx.max_messages]
        log.debug("gmail_candidates", account=account, count=len(ids), history=via_history)
        for mid in ids:
            key = f"gmail:{account}:{mid}"
            if ctx.store.is_processed("gmail", key):
                continue
            if via_history:
                meta = call(service.users().messages().get(
                    userId="me", id=mid, format="metadata",
                    metadataHeaders=["From", "Subject", "Date"], fields=META_FIELDS))
                labels = set(meta.get("labelIds") or [])
                if labels & {lbl.upper() for lbl in cfg.exclude_labels}:
                    ctx.store.mark_processed("gmail", key, "excluded_label")
                    continue
                if cfg.labels and not labels & set(cfg.labels):
                    ctx.store.mark_processed("gmail", key, "excluded_label")
                    continue
                hdr = _headers(meta.get("payload") or {})
                _, sender = parseaddr(hdr.get("from", ""))
                if ctx.prefilter and not ctx.prefilter(sender.lower(), hdr.get("subject", "")):
                    ctx.store.mark_processed("gmail", key, "prefiltered")
                    continue
            item = call(service.users().messages().get(userId="me", id=mid, format="full",
                                                      fields=FULL_FIELDS))
            yield message_from_full(item, account)

        ctx.store.set_cursor("gmail", account, "", {
            "history_id": current_history or cursor.get("history_id"),
            "last_scan": clock.today().isoformat(),
        })

    def _search_ids(self, service, call, cfg: GmailConfig, ctx: SourceContext, since: date | None,
                    domains: list[str]) -> list[str]:
        seen: dict[str, None] = {}
        for query in build_queries(cfg, ctx.config, since, domains, ctx.config.scan.months_back):
            token = None
            while True:
                resp = call(service.users().messages().list(
                    userId="me", q=query, pageToken=token, maxResults=500,
                    includeSpamTrash=False, fields="messages/id,nextPageToken"))
                for m in resp.get("messages") or []:
                    seen.setdefault(m["id"], None)
                token = resp.get("nextPageToken")
                if not token or len(seen) >= ctx.max_messages:
                    break
        return list(seen)

    def _history_ids(self, service, call, start: str, cfg: GmailConfig) -> list[str]:
        seen: dict[str, None] = {}
        token = None
        while True:
            resp = call(service.users().history().list(
                userId="me", startHistoryId=start, historyTypes=["messageAdded"], pageToken=token,
                fields="history/messagesAdded/message/id,nextPageToken,historyId"))
            for h in resp.get("history") or []:
                for added in h.get("messagesAdded") or []:
                    seen.setdefault(added["message"]["id"], None)
            token = resp.get("nextPageToken")
            if not token:
                break
        return list(seen)


def revoke(account: str) -> bool:
    """Revoke the refresh token at Google and forget it locally."""
    import urllib.parse
    import urllib.request

    raw = secrets.get(secrets.gmail_token_name(account))
    revoked = False
    if raw:
        token = json.loads(raw).get("refresh_token")
        if token:
            data = urllib.parse.urlencode({"token": token}).encode()
            req = urllib.request.Request(REVOKE_URI, data=data, method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded"})
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    revoked = resp.status == 200
            except OSError:
                revoked = False
    secrets.delete(secrets.gmail_token_name(account))
    secrets.delete(secrets.gmail_client_name(account))
    return revoked
