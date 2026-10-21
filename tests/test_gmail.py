"""Gmail source against a fake API object (no network, no Google libs)."""

import base64
import json
from datetime import date

import pytest

from conftest import write_config
from fixtures.emails import EMAILS
from subwatch import secrets
from subwatch.app import AppContext
from subwatch.config.schema import Config
from subwatch.scan import Scanner
from subwatch.sources import gmail as gmail_mod
from subwatch.sources.base import SourceContext
from subwatch.sources.gmail import GmailSource, build_queries, message_from_full, payload_text


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def full_item(mid: str, e) -> dict:
    parts = []
    if e.text:
        parts.append({"mimeType": "text/plain", "body": {"data": b64(e.text)}})
    if e.html:
        parts.append({"mimeType": "text/html", "body": {"data": b64(e.html)}})
    return {
        "id": mid, "internalDate": "1792000000000", "labelIds": ["INBOX"],
        "payload": {"mimeType": "multipart/alternative", "headers": [
            {"name": "From", "value": f"{e.sender_name} <{e.sender}>"},
            {"name": "Subject", "value": e.subject},
        ], "parts": parts},
    }


class Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self, num_retries=0):
        return self.fn()


class FakeGmail:
    def __init__(self, emails, history_id="1000"):
        self.items = {f"m{i}": e for i, e in enumerate(emails)}
        self.history_id = history_id
        self.calls = []
        self.added: list[str] = []
        self.history_gone = False

    def users(self):
        return self

    def getProfile(self, userId):
        return Req(lambda: {"historyId": self.history_id, "emailAddress": "me@gmail.com"})

    def messages(self):
        return self

    def history(self):
        return HistoryApi(self)

    def list(self, userId, q, pageToken=None, maxResults=500, includeSpamTrash=False, fields=None):
        self.calls.append(("list", q, pageToken))
        ids = sorted(self.items)
        if pageToken is None:
            return Req(lambda: {"messages": [{"id": i} for i in ids[:20]], "nextPageToken": "p2"})
        return Req(lambda: {"messages": [{"id": i} for i in ids[20:]]})

    def get(self, userId, id, format, fields=None, metadataHeaders=None):
        self.calls.append(("get", id, format))
        e = self.items[id]
        if format == "metadata":
            return Req(lambda: {"id": id, "labelIds": ["INBOX"], "payload": {"headers": [
                {"name": "From", "value": f"{e.sender_name} <{e.sender}>"},
                {"name": "Subject", "value": e.subject}]}})
        return Req(lambda: full_item(id, e))


class HistoryApi:
    def __init__(self, fake):
        self.fake = fake

    def list(self, userId, startHistoryId, historyTypes, pageToken=None, fields=None):
        self.fake.calls.append(("history", startHistoryId))
        if self.fake.history_gone:
            class Gone(Exception):
                class resp:
                    status = 404
            def boom():
                raise Gone()
            return Req(boom)
        return Req(lambda: {"history": [{"messagesAdded": [{"message": {"id": i}}]} for i in self.fake.added],
                            "historyId": self.fake.history_id})


def gmail_app():
    write_config('[sources.gmail]\nenabled = true\naccount = "me"\n[sources.imap]\nenabled = false\n')
    return AppContext.load(quiet_logs=True)


def run_gmail(app, fake, full=False):
    scanner = Scanner(app)
    src = GmailSource(service_factory=lambda account: fake)
    import subwatch.sources.base as base

    stats = {}
    from collections import Counter

    c = Counter()
    sctx = SourceContext(config=app.config, store=app.store, since=date(2025, 10, 22), full=full,
                         max_messages=1000, prefilter=None)
    for msg in src.fetch(sctx):
        scanner.process_message(msg, c)
    stats["gmail"] = c
    assert base  # keep import used
    return c


def test_query_building():
    cfg = Config.model_validate({"sources": {"gmail": {"labels": ["Receipts"], "query": "-category:promotions"}},
                                 "filters": {"exclude_senders": ["*@spam.example"]}})
    qs = build_queries(cfg.sources.gmail, cfg, None, ["netflix.com", "spotify.com"], 6)
    q = qs[0]
    assert "newer_than:6m" in q and "-in:spam" in q and "-in:trash" in q
    assert "label:Receipts" in q and "-category:promotions" in q and "-from:spam.example" in q
    assert "from:netflix.com" in q and "подписка" in q and "receipt" in q and "жазылым" in q
    since = build_queries(cfg.sources.gmail, cfg, date(2026, 10, 1), ["netflix.com"], 6)[0]
    assert "after:2026/10/01" in since and "newer_than" not in since


def test_long_query_is_split():
    cfg = Config()
    domains = [f"service{i}.example.com" for i in range(200)]
    qs = build_queries(cfg.sources.gmail, cfg, None, domains, 12)
    assert len(qs) > 1 and all(len(q) <= gmail_mod.MAX_QUERY + 50 for q in qs)
    assert sum(q.count("from:") for q in qs) == 200


def test_payload_text_and_message():
    e = next(x for x in EMAILS if x.html)
    item = full_item("x1", e)
    plain, html = payload_text(item["payload"])
    assert "VK Музыка" in html
    msg = message_from_full(item, "me")
    assert msg.sender == "admin@vk.com" and msg.key == "gmail:me:x1"


def test_first_scan_uses_search_then_history():
    app = gmail_app()
    fake = FakeGmail(EMAILS)
    c = run_gmail(app, fake)
    assert c["seen"] == len(EMAILS)
    assert any(call[0] == "list" for call in fake.calls)
    assert {s.service for s in app.store.subscriptions(statuses=["active"])} >= {"Spotify", "Яндекс Плюс"}
    cursor = app.store.get_cursor("gmail", "me", "")
    assert cursor["history_id"] == "1000"
    # Second run: only the history API, metadata first, full body only for candidates.
    fake.calls.clear()
    fake.history_id = "1005"
    fake.added = ["m0", "m9"]  # m0 already processed, m9 is the Yandex ID code (filtered by prefilter)
    from subwatch.extract.engine import Context
    from subwatch.scan import make_prefilter

    scanner = Scanner(app)
    src = GmailSource(service_factory=lambda account: fake)
    from collections import Counter

    c2 = Counter()
    sctx = SourceContext(config=app.config, store=app.store, since=date(2025, 10, 22),
                         prefilter=make_prefilter(Context.build(app.config, app.book)))
    for msg in src.fetch(sctx):
        scanner.process_message(msg, c2)
    kinds = [call[0] for call in fake.calls]
    assert "list" not in kinds and "history" in kinds
    assert ("get", "m0", "full") not in fake.calls
    assert app.store.get_cursor("gmail", "me", "")["history_id"] == "1005"
    app.close()


def test_expired_history_falls_back_to_search():
    app = gmail_app()
    app.store.set_cursor("gmail", "me", "", {"history_id": "5", "last_scan": "2026-10-01"})
    fake = FakeGmail(EMAILS[:3])
    fake.history_gone = True
    run_gmail(app, fake)
    lists = [call for call in fake.calls if call[0] == "list"]
    assert lists and "after:2026/09/30" in lists[0][1]
    app.close()


def test_credentials_only_in_keyring(monkeypatch):
    class Creds:
        refresh_token = "1//refresh"
        client_id = "cid.apps.googleusercontent.com"
        client_secret = "secret"
        token_uri = gmail_mod.TOKEN_URI
        scopes = gmail_mod.SCOPES

    gmail_mod.save_credentials("me", Creds())
    stored = json.loads(secrets.get(secrets.gmail_token_name("me")))
    assert stored["refresh_token"] == "1//refresh" and stored["scopes"] == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert secrets.gmail_token_name("me") in secrets.index()
    from subwatch import paths

    for root in (paths.config_dir(), paths.data_dir()):
        if root.exists():
            for f in root.rglob("*"):
                if f.is_file():
                    assert b"1//refresh" not in f.read_bytes()


def test_no_token_error_is_helpful():
    from subwatch.errors import SubwatchError

    with pytest.raises(SubwatchError) as err:
        gmail_mod.load_credentials("me")
    assert "subwatch auth gmail" in err.value.hint_text


def test_revoke_deletes_token(monkeypatch):
    secrets.put(secrets.gmail_token_name("me"), json.dumps({"refresh_token": "x"}))
    calls = []

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: calls.append(req.full_url) or Resp())
    assert gmail_mod.revoke("me") is True
    assert calls == [gmail_mod.REVOKE_URI]
    assert secrets.get(secrets.gmail_token_name("me")) is None


def test_wizard_with_fake_flow(tmp_path, monkeypatch):
    from subwatch.cli.auth_gmail import run_wizard

    client = tmp_path / "client.json"
    client.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "s",
                                                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                                                "token_uri": gmail_mod.TOKEN_URI}}))

    class Creds:
        refresh_token = "1//r"
        client_id = "cid"
        client_secret = "s"
        token_uri = gmail_mod.TOKEN_URI
        scopes = gmail_mod.SCOPES

    class Flow:
        def run_local_server(self, **kw):
            assert kw["access_type"] == "offline" and kw["prompt"] == "consent"
            return Creds()

    monkeypatch.setattr(gmail_mod, "build_service", lambda creds: FakeGmail([]))
    app = AppContext.load(quiet_logs=True)
    run_wizard(app, "me", client, no_browser=True, flow_factory=lambda cfg: Flow())
    assert secrets.get(secrets.gmail_token_name("me"))
    cfg = AppContext.load().config
    assert cfg.sources.gmail.enabled and cfg.sources.gmail.account == "me"
    app.close()
