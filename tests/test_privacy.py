import stat

from conftest import write_config
from fixtures.emails import EMAILS

from subwatch import paths, secrets
from subwatch.__main__ import main
from subwatch.app import AppContext
from subwatch.config.schema import Config
from subwatch.db import Store, db_path_for
from subwatch.extract.engine import Context, analyse
from subwatch.extract.merchants import MerchantBook
from subwatch.extract.text import parse_email
from subwatch.ingest import Ingestor


def run(capsys, *args):
    try:
        main(list(args))
    except SystemExit:
        pass
    return capsys.readouterr()


def ingest_all(config):
    store = Store.open(config)
    ctx = Context.build(config, MerchantBook.load())
    ing = Ingestor(store, config)
    for e in EMAILS:
        msg = parse_email(e.to_bytes(), "imap", e.id)
        det = analyse(msg, ctx).detection
        if det:
            ing.ingest(det)
        store.mark_processed("imap", msg.key, "x")
    store.close()


def db_bytes(config) -> bytes:
    path = db_path_for(config)
    data = b""
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + ".enc")):
        if p.exists():
            data += p.read_bytes()
    return data


def test_permissions():
    cfg = Config()
    Store.open(cfg).close()
    assert stat.S_IMODE(db_path_for(cfg).stat().st_mode) == 0o600
    assert stat.S_IMODE(paths.data_dir().stat().st_mode) == 0o700


def test_no_email_bodies_or_message_ids_are_stored():
    cfg = Config()
    ingest_all(cfg)
    raw = db_bytes(cfg)
    assert "Спасибо за оплату подписки".encode() not in raw
    assert b"4417" not in raw  # card digits from the Netflix email
    assert b"ru_netflix_receipt" not in raw  # message keys are hashed
    assert b"Netflix" in raw


def test_snippets_only_when_enabled():
    cfg = Config.model_validate({"extraction": {"store_snippets": True}})
    ingest_all(cfg)
    store = Store.open(cfg)
    assert store.snippet_count() > 0
    assert all("•••• 4417" not in (s.snippet or "") for s in store.subscriptions(include_cancelled=True))
    store.close()


def test_encrypted_database():
    cfg = Config.model_validate({"storage": {"encrypt": True}})
    ingest_all(cfg)
    enc = db_path_for(cfg).with_name("subwatch.db.enc")
    assert enc.exists() and not db_path_for(cfg).exists()
    assert b"Netflix" not in enc.read_bytes() and b"SQLite format" not in enc.read_bytes()
    assert secrets.get(secrets.DB_KEY_NAME)
    working = paths.runtime_dir() / "subwatch.db"
    working.unlink()  # e.g. after a logout tmpfs is empty again
    store = Store.open(cfg)
    assert {s.service for s in store.subscriptions()} >= {"Spotify"}
    store.close()


def test_switching_encryption_on_and_off_keeps_data():
    plain = Config()
    ingest_all(plain)
    on = Config.model_validate({"storage": {"encrypt": True}})
    with Store.open(on) as store:
        assert store.find_by_service("Spotify")
    assert not db_path_for(plain).exists()
    with Store.open(plain) as store:
        assert store.find_by_service("Spotify")
    assert not db_path_for(plain).with_name("subwatch.db.enc").exists()


def test_privacy_report_and_purge(capsys):
    secrets.put(secrets.imap_password_name("work"), "pw")
    secrets.put(secrets.gmail_token_name("default"), "{}")
    ingest_all(Config())
    out = " ".join(run(capsys, "privacy").out.split())
    assert "Тексты писем не сохраняются" in out and "imap:work" in out and "pw" not in out
    assert "Ничего не отправлялось" in out
    out = run(capsys, "purge", "--yes").out
    assert "Все данные Subwatch удалены" in out
    assert not db_path_for(Config()).exists()
    assert secrets.get(secrets.imap_password_name("work")) is None
    assert secrets.get(secrets.gmail_token_name("default")) is None


def test_purge_all_removes_config(capsys):
    write_config("[scan]\nmonths_back = 3\n")
    run(capsys, "purge", "--yes", "--all")
    assert not paths.config_file().exists()


def test_privacy_lists_ai_requests(capsys, store):
    cfg = Config()
    with Store.open(cfg) as s:
        s.log_ai(provider="openai", model="gpt-4o-mini", is_local=False, message_key="k", sender_domain="x.com",
                 payload="From: x.com\n990 ₸", outcome="detected", keep_payload=True)
    out = run(capsys, "privacy", "--payloads").out
    assert "в облако: 1" in out and "openai/gpt-4o-mini" in out and "990 ₸" in out


def test_auth_revoke_imap(capsys):
    write_config('[[sources.imap.accounts]]\nname = "work"\nhost = "imap.example.org"\nusername = "me"\n')
    secrets.put(secrets.imap_password_name("work"), "pw")
    out = run(capsys, "auth", "revoke", "imap", "--yes").out
    assert "imap.example.org" in out and secrets.get(secrets.imap_password_name("work")) is None


def test_secrets_never_in_config(capsys):
    from io import StringIO

    import subwatch.cli.groups  # noqa: F401

    write_config("")
    import sys

    sys.stdin = StringIO("super-secret\n")
    try:
        run(capsys, "auth", "imap", "--name", "x", "--host", "h", "--user", "u", "--no-test", "--password-stdin")
    finally:
        sys.stdin = sys.__stdin__
    assert secrets.get(secrets.imap_password_name("x")) == "super-secret"
    assert "super-secret" not in paths.config_file().read_text(encoding="utf-8")
    assert 'host = "h"' in paths.config_file().read_text(encoding="utf-8")
    AppContext.load().close()
