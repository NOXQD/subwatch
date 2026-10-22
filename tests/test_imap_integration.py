"""Full cycle against a mock IMAP server: scan -> subscriptions -> reminder
-> notification. Also checks incremental scanning and that the mailbox is
never modified."""

from datetime import date

import pytest
from conftest import write_config
from fixtures.emails import EMAILS, Email
from mock_imap import MockImapServer, ServerState

from subwatch import secrets
from subwatch.app import AppContext
from subwatch.scan import run_job


def imap_config(port: int, extra: str = "") -> None:
    write_config(f"""
[sources.imap]
enabled = true

[[sources.imap.accounts]]
name = "mock"
host = "127.0.0.1"
port = {port}
ssl = false
username = "user@example.org"
folders = ["INBOX"]

[notifications]
backend = "auto"
{extra}
""")


@pytest.fixture
def server():
    state = ServerState()
    for e in EMAILS:
        state.folders["INBOX"].append(e.to_bytes())
    with MockImapServer(state) as srv:
        yield srv


def scan(**kw):
    app = AppContext.load(quiet_logs=True)
    try:
        return app, run_job(app, **kw)
    finally:
        pass


def test_full_cycle(server, notifications):
    imap_config(server.port)
    secrets.put(secrets.imap_password_name("mock"), "app-password")
    app, report = scan()
    try:
        assert report.errors == []
        stats = report.stats["imap"]
        assert stats["seen"] >= 20
        active = {s.service for s in app.store.subscriptions(statuses=["active"])}
        review = {s.service for s in app.store.review_queue()}
        assert {"Spotify", "Яндекс Плюс", "iCloud+", "GitHub Copilot", "Beeline", "Dropbox"} <= active
        assert {"Мегадиск", "Tasklane"} <= review
        assert "Ozon" not in active | review
        okko = app.store.find_by_service("Okko")
        assert okko == [] or okko[0].status == "cancelled"
        # The Kazakh cancellation email cancels Netflix in both currencies.
        assert {s.status for s in app.store.find_by_service("Netflix")} == {"cancelled"}
        assert len(app.store.find_by_service("Netflix")) == 2
        spotify = app.store.find_by_key("spotify|USD")
        assert spotify.next_charge == date(2026, 11, 14) and spotify.category == "music"
        # A reminder for something due within 3 days went out (Notion trial ends on the 25th).
        notes = notifications()
        reminders = [n for n in notes if n["kind"] == "reminder"]
        assert any("Notion" in n["summary"] for n in reminders)
        assert all(n["click"][-2] == "notify-action" for n in reminders)
        assert any(n["kind"] == "summary" for n in notes)
        # The mailbox was opened read-only and nothing was written.
        log = server.state.log
        assert any(" EXAMINE " in f" {line} " for line in log)
        assert server.state.writes() == []
        assert not any("BODY[" in line and "PEEK" not in line for line in log if "FETCH" in line)
    finally:
        app.close()


def test_incremental_scan_reads_only_new_mail(server):
    imap_config(server.port)
    secrets.put(secrets.imap_password_name("mock"), "app-password")
    app, first = scan()
    app.close()
    server.state.log.clear()
    app, second = scan()
    assert second.stats["imap"]["seen"] == 0
    fetches = [line for line in server.state.log if "FETCH" in line]
    assert fetches == []
    app.close()
    new = Email("new_okko", "ru", "noreply@okko.tv", "Okko", "Чек об оплате подписки Okko",
                "2026-10-22T09:00:00+03:00", text="Оплата подписки Okko: 399 ₽ в месяц.")
    server.state.folders["INBOX"].append(new.to_bytes())
    server.state.log.clear()
    app, third = scan()
    assert third.stats["imap"]["seen"] == 1
    assert app.store.find_by_key("okko|RUB") is not None
    app.close()


def test_uidvalidity_change_rescans_folder(server):
    imap_config(server.port)
    secrets.put(secrets.imap_password_name("mock"), "app-password")
    app, _ = scan()
    app.close()
    server.state.folders["INBOX"].uidvalidity = 2
    app, again = scan()
    # New UIDVALIDITY means new UIDs: the folder is searched by date again,
    # but messages are recognised by key and nothing is duplicated.
    assert again.stats["imap"]["seen"] > 0
    assert again.stats["imap"]["created"] == 0
    app.close()


def test_months_back_limits_first_scan(server):
    old = Email("old_netflix", "ru", "info@account.netflix.com", "Netflix", "Ваш платёж прошёл успешно",
                "2024-01-01T09:00:00+05:00", text="Сумма: 2 990,00 ₸")
    server.state.folders["INBOX"].append(old.to_bytes())
    imap_config(server.port, '\n[scan]\nmonths_back = 1\n')
    secrets.put(secrets.imap_password_name("mock"), "app-password")
    app, report = scan()
    searches = [line for line in server.state.log if "SEARCH" in line]
    assert any("SINCE" in s for s in searches)
    assert report.stats["imap"]["seen"] < len(EMAILS)
    app.close()


def test_wrong_password_is_reported(server, notifications):
    imap_config(server.port)
    secrets.put(secrets.imap_password_name("mock"), "wrong")
    app, report = scan()
    assert report.errors and "пароль" in report.errors[0][1]
    assert any(n["kind"] == "error" for n in notifications())
    app.close()


def test_missing_password(server):
    imap_config(server.port)
    app, report = scan()
    assert report.errors and "mock" in report.errors[0][1]
    app.close()


def test_folder_and_sender_filters(server):
    imap_config(server.port, '\n[filters]\nexclude_senders = ["*netflix.com"]\n')
    secrets.put(secrets.imap_password_name("mock"), "app-password")
    app, _ = scan()
    netflix = app.store.find_by_service("Netflix")
    # Only the bank notification is left; nothing from netflix.com was read.
    assert netflix and all("netflix" not in (s.sender or "") for s in netflix)
    app.close()


def test_scan_lock_prevents_parallel_runs(server):
    from subwatch.errors import LockedError
    from subwatch.lock import single_instance

    imap_config(server.port)
    with single_instance("scan"):
        app = AppContext.load(quiet_logs=True)
        with pytest.raises(LockedError):
            run_job(app)
        app.close()
