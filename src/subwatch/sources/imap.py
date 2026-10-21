"""IMAP source: any mail provider with an app password.

Read-only by construction: folders are opened with EXAMINE (select_folder
readonly=True) and bodies are fetched with BODY.PEEK so nothing is marked as
read. Incremental: the last seen UID per folder is stored together with
UIDVALIDITY; if the server resets UIDVALIDITY the folder is rescanned by date.
"""

from __future__ import annotations

import socket
import ssl
from datetime import date
from email import message_from_bytes, policy
from email.utils import parseaddr
from typing import Iterator

from .. import log, secrets
from ..config.schema import Config, ImapAccount
from ..errors import SubwatchError
from ..extract.text import parse_email
from ..models import RawMessage
from ..retry import retry
from .base import Source, SourceContext, source

HEADER_FIELDS = "BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID LIST-UNSUBSCRIBE)]"
HEADER_KEY = b"BODY[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID LIST-UNSUBSCRIBE)]"

TRANSIENT = (OSError, socket.timeout, ssl.SSLError, EOFError)


def _imapclient():
    import imapclient

    return imapclient


def connect(account: ImapAccount, password: str):
    imapclient = _imapclient()
    context = ssl.create_default_context() if (account.ssl or account.starttls) else None
    client = imapclient.IMAPClient(
        account.host, port=account.port, ssl=account.ssl, ssl_context=context if account.ssl else None,
        timeout=account.timeout,
    )
    if account.starttls and not account.ssl:
        client.starttls(context)
    try:
        client.login(account.username, password)
    except imapclient.exceptions.LoginError as exc:
        client.shutdown()
        raise SubwatchError("imap.err.login", hint="imap.hint.login", account=account.name,
                            detail=str(exc)) from None
    return client


def _header_value(raw: bytes, name: str) -> str:
    msg = message_from_bytes(raw, policy=policy.default)
    return str(msg.get(name, "") or "")


def _chunks(items: list[int], size: int) -> Iterator[list[int]]:
    for i in range(0, len(items), size):
        yield items[i: i + size]


@source("imap")
class ImapSource(Source):
    kind = "messages"

    def enabled(self, config: Config) -> bool:
        imap = config.sources.imap
        return imap.enabled and any(a.enabled for a in imap.accounts)

    def check(self, config: Config):
        for account in config.sources.imap.accounts:
            if not account.enabled:
                continue
            has = secrets.exists(secrets.imap_password_name(account.name))
            yield has, ("imap.check.ok" if has else "imap.check.no_password"), {"account": account.name}

    def fetch(self, ctx: SourceContext) -> Iterator[RawMessage]:
        cfg = ctx.config.sources.imap
        for account in cfg.accounts:
            if not account.enabled:
                continue
            password = secrets.get(secrets.imap_password_name(account.name))
            if not password:
                raise SubwatchError("imap.err.no_password", hint="imap.hint.no_password",
                                    account=account.name)
            yield from self._fetch_account(ctx, account, password)

    def _fetch_account(self, ctx: SourceContext, account: ImapAccount, password: str) -> Iterator[RawMessage]:
        cfg = ctx.config.sources.imap

        def open_client():
            return retry(lambda: connect(account, password), attempts=cfg.max_retries + 1,
                         retry_on=TRANSIENT)

        client = open_client()
        budget = ctx.max_messages
        try:
            for folder in account.folders:
                if budget <= 0:
                    break
                try:
                    info = client.select_folder(folder, readonly=True)
                except Exception as exc:  # folder missing or not selectable
                    log.warning("imap_folder_failed", account=account.name, folder=folder, error=str(exc))
                    continue
                uidvalidity = int(info.get(b"UIDVALIDITY", 0))
                cursor = ctx.store.get_cursor("imap", account.name, folder)
                last_uid = 0
                if cursor and not ctx.full and cursor.get("uidvalidity") == uidvalidity:
                    last_uid = int(cursor.get("last_uid", 0))
                    uids = client.search(["UID", f"{last_uid + 1}:*"])
                else:
                    uids = client.search(["SINCE", ctx.since])
                uids = sorted(u for u in uids if u > last_uid)
                if len(uids) > budget:
                    uids = uids[-budget:]
                budget -= len(uids)
                log.debug("imap_folder", account=account.name, folder=folder, new=len(uids))
                for batch in _chunks(uids, cfg.batch_size):
                    headers = retry(lambda b=batch: client.fetch(b, [HEADER_FIELDS, "RFC822.SIZE"]),
                                    attempts=cfg.max_retries + 1, retry_on=TRANSIENT)
                    for uid in batch:
                        data = headers.get(uid) or {}
                        raw_headers = data.get(HEADER_KEY) or b""
                        key = f"imap:{account.name}:{folder}:{uidvalidity}:{uid}"
                        if ctx.store.is_processed("imap", key):
                            continue
                        _, sender = parseaddr(_header_value(raw_headers, "From"))
                        subject = _header_value(raw_headers, "Subject")
                        if ctx.prefilter and not ctx.prefilter(sender.lower(), subject):
                            ctx.store.mark_processed("imap", key, "prefiltered")
                            continue
                        body_key = b"BODY[]<0>"
                        fetched = retry(
                            lambda u=uid: client.fetch([u], [f"BODY.PEEK[]<0.{cfg.fetch_max_bytes}>"]),
                            attempts=cfg.max_retries + 1, retry_on=TRANSIENT,
                        )
                        item = fetched.get(uid) or {}
                        raw = item.get(body_key) or item.get(b"BODY[]") or b""
                        if not raw:
                            continue
                        msg = parse_email(raw, "imap", key, account=account.name)
                        yield msg
                    ctx.store.set_cursor("imap", account.name, folder,
                                         {"uidvalidity": uidvalidity, "last_uid": max(batch)})
                if not uids and (cursor is None or cursor.get("uidvalidity") != uidvalidity):
                    ctx.store.set_cursor("imap", account.name, folder,
                                         {"uidvalidity": uidvalidity, "last_uid": last_uid})
        finally:
            try:
                client.logout()
            except Exception:
                pass


def test_login(account: ImapAccount, password: str) -> list[str]:
    """Log in and list folders; used by `subwatch auth imap`."""
    client = connect(account, password)
    try:
        return [name for _flags, _delim, name in client.list_folders()]
    finally:
        try:
            client.logout()
        except Exception:
            pass


def since_date(ctx: SourceContext) -> date:
    return ctx.since
