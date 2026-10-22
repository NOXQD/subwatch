"""SQLite storage.

Only extracted facts are stored: service, amount, dates, where it came from.
Message ids are hashed, email bodies are never written (unless the user turns
on extraction.store_snippets, and then only a short fragment).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import clock, paths
from .config.schema import Config
from .models import Charge, Subscription, Transaction, service_key
from .period import Period

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    service TEXT NOT NULL,
    plan TEXT,
    amount TEXT,
    currency TEXT,
    period TEXT NOT NULL DEFAULT '1m',
    next_charge TEXT,
    last_charge TEXT,
    anchor_day INTEGER,
    category TEXT NOT NULL DEFAULT 'other',
    tags TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'active',
    trial_until TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL,
    source_account TEXT,
    sender TEXT,
    cancel_url TEXT,
    notes TEXT,
    snippet TEXT,
    review_reason TEXT,
    track_usage INTEGER NOT NULL DEFAULT 0,
    last_used TEXT,
    previous_amount TEXT,
    price_changed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cancelled_at TEXT
);
CREATE INDEX IF NOT EXISTS subscriptions_status ON subscriptions(status);

CREATE TABLE IF NOT EXISTS charges (
    id INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    source TEXT NOT NULL,
    source_ref TEXT,
    kind TEXT NOT NULL DEFAULT 'charge',
    created_at TEXT NOT NULL,
    UNIQUE (subscription_id, date, amount, currency)
);
CREATE INDEX IF NOT EXISTS charges_date ON charges(date);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    pattern TEXT NOT NULL,
    value TEXT,
    origin TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    UNIQUE (kind, pattern)
);

CREATE TABLE IF NOT EXISTS scan_state (
    source TEXT NOT NULL,
    account TEXT NOT NULL,
    scope TEXT NOT NULL,
    cursor TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, account, scope)
);

CREATE TABLE IF NOT EXISTS processed (
    source TEXT NOT NULL,
    key TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    PRIMARY KEY (source, key)
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    charge_date TEXT NOT NULL,
    days_before INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'charge',
    due_at TEXT NOT NULL,
    sent_count INTEGER NOT NULL DEFAULT 0,
    first_sent_at TEXT,
    last_sent_at TEXT,
    acked_at TEXT,
    action TEXT,
    snoozed_until TEXT,
    UNIQUE (subscription_id, charge_date, days_before, kind)
);
CREATE INDEX IF NOT EXISTS reminders_due ON reminders(due_at);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    subscription_id INTEGER,
    payload TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind, subscription_id);

CREATE TABLE IF NOT EXISTS fx_rates (
    base TEXT NOT NULL,
    currency TEXT NOT NULL,
    rate TEXT NOT NULL,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (base, currency)
);

CREATE TABLE IF NOT EXISTS ai_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    is_local INTEGER NOT NULL,
    message_key TEXT,
    sender_domain TEXT,
    chars INTEGER NOT NULL,
    payload_sha256 TEXT NOT NULL,
    payload TEXT,
    outcome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    date TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    merchant TEXT NOT NULL,
    merchant_key TEXT NOT NULL,
    file_sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS transactions_merchant ON transactions(merchant_key, date);

CREATE TABLE IF NOT EXISTS imported_files (
    sha256 TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    bank TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    rows INTEGER NOT NULL,
    found INTEGER NOT NULL
);
"""

MIGRATIONS: dict[int, str] = {1: _SCHEMA_V1}


def hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()[:32]


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _dt(value: str | None) -> datetime | None:
    return clock.parse_iso(value)


def _dec(value: str | None) -> Decimal | None:
    return Decimal(value) if value not in (None, "") else None


def _s(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return clock.iso(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def db_path_for(config: Config) -> Path:
    if config.storage.db_path:
        return paths.expand(config.storage.db_path)
    return paths.db_file()


class Store:
    def __init__(self, conn: sqlite3.Connection, path: Path, encrypted=None):
        self.conn = conn
        self.path = path
        self._encrypted = encrypted
        self._depth = 0
        self._changes_at_sync = conn.total_changes

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def open(cls, config: Config, path: Path | None = None) -> "Store":
        plain_path = path or db_path_for(config)
        paths.ensure_private_dir(plain_path.parent)
        encrypted = None
        work_path = plain_path
        if config.storage.encrypt:
            from .crypto import EncryptedFile

            encrypted = EncryptedFile(Path(str(plain_path) + ".enc"), plain_source=plain_path)
            work_path = encrypted.open()
        else:
            enc = Path(str(plain_path) + ".enc")
            if enc.exists() and not plain_path.exists():
                from .crypto import EncryptedFile, decrypt_bytes, load_or_create_key

                # Encryption was switched off: decrypt once and keep plain.
                data = decrypt_bytes(load_or_create_key(create=False), enc.read_bytes())
                plain_path.write_bytes(data)
                os.chmod(plain_path, 0o600)
                enc.unlink()
                EncryptedFile(enc).wipe_working()
        old_umask = os.umask(0o077)
        try:
            existed = work_path.exists()
            conn = sqlite3.connect(work_path, timeout=10, isolation_level=None)
        finally:
            os.umask(old_umask)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        if not config.storage.encrypt:
            conn.execute("PRAGMA journal_mode = WAL")
        store = cls(conn, work_path, encrypted)
        store._migrate(existed and config.storage.backup_before_migrate)
        try:
            os.chmod(work_path, 0o600)
        except OSError:
            pass
        return store

    @classmethod
    def memory(cls) -> "Store":
        conn = sqlite3.connect(":memory:", isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        store = cls(conn, Path(":memory:"))
        store._migrate(False)
        return store

    def _migrate(self, backup: bool) -> None:
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        current = int(row["value"]) if row else 0
        if current >= SCHEMA_VERSION:
            return
        if backup and current > 0 and self.path.exists():
            shutil.copy2(self.path, self.path.with_name(self.path.name + f".v{current}.bak"))
        for version in range(current + 1, SCHEMA_VERSION + 1):
            self.conn.executescript("BEGIN;" + MIGRATIONS[version] + "COMMIT;")
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )

    def close(self) -> None:
        self.sync()
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def sync(self) -> None:
        if self._encrypted is not None and self.conn.total_changes != self._changes_at_sync:
            self._encrypted.sync(self.conn)
            self._changes_at_sync = self.conn.total_changes

    @contextmanager
    def transaction(self) -> Iterator["Store"]:
        if self._depth == 0:
            self.conn.execute("BEGIN IMMEDIATE")
        self._depth += 1
        try:
            yield self
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self.conn.execute("ROLLBACK")
            raise
        self._depth -= 1
        if self._depth == 0:
            self.conn.execute("COMMIT")
            self.sync()

    def _after_write(self) -> None:
        if self._depth == 0:
            self.sync()

    def schema_version(self) -> int:
        row = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row["value"]) if row else 0

    def integrity_ok(self) -> bool:
        row = self.conn.execute("PRAGMA quick_check").fetchone()
        return bool(row) and row[0] == "ok"

    # -------------------------------------------------------- subscriptions

    def _row_to_sub(self, row: sqlite3.Row) -> Subscription:
        return Subscription(
            id=row["id"],
            key=row["key"],
            service=row["service"],
            plan=row["plan"],
            amount=_dec(row["amount"]),
            currency=row["currency"],
            period=Period.parse(row["period"]),
            next_charge=_d(row["next_charge"]),
            last_charge=_d(row["last_charge"]),
            anchor_day=row["anchor_day"],
            category=row["category"],
            tags=json.loads(row["tags"] or "[]"),
            status=row["status"],
            trial_until=_d(row["trial_until"]),
            confidence=row["confidence"],
            source=row["source"],
            source_account=row["source_account"],
            sender=row["sender"],
            cancel_url=row["cancel_url"],
            notes=row["notes"],
            snippet=row["snippet"],
            review_reason=row["review_reason"],
            track_usage=bool(row["track_usage"]),
            last_used=_d(row["last_used"]),
            previous_amount=_dec(row["previous_amount"]),
            price_changed_at=_d(row["price_changed_at"]),
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            cancelled_at=_dt(row["cancelled_at"]),
        )

    _SUB_COLUMNS = (
        "key", "service", "plan", "amount", "currency", "period", "next_charge",
        "last_charge", "anchor_day", "category", "tags", "status", "trial_until",
        "confidence", "source", "source_account", "sender", "cancel_url", "notes",
        "snippet", "review_reason", "track_usage", "last_used", "previous_amount",
        "price_changed_at", "created_at", "updated_at", "cancelled_at",
    )

    def _sub_values(self, sub: Subscription) -> list[Any]:
        return [
            sub.key, sub.service, sub.plan, _s(sub.amount), sub.currency, sub.period.code,
            _s(sub.next_charge), _s(sub.last_charge), sub.anchor_day, sub.category,
            json.dumps(sub.tags, ensure_ascii=False), sub.status, _s(sub.trial_until),
            float(sub.confidence), sub.source, sub.source_account, sub.sender, sub.cancel_url,
            sub.notes, sub.snippet, sub.review_reason, int(sub.track_usage), _s(sub.last_used),
            _s(sub.previous_amount), _s(sub.price_changed_at), _s(sub.created_at),
            _s(sub.updated_at), _s(sub.cancelled_at),
        ]

    def insert_subscription(self, sub: Subscription) -> Subscription:
        now = clock.now()
        sub.created_at = sub.created_at or now
        sub.updated_at = now
        sub.key = sub.key or sub.make_key()
        cols = ", ".join(self._SUB_COLUMNS)
        marks = ", ".join("?" for _ in self._SUB_COLUMNS)
        cur = self.conn.execute(
            f"INSERT INTO subscriptions ({cols}) VALUES ({marks})", self._sub_values(sub)
        )
        sub.id = cur.lastrowid
        self._after_write()
        return sub

    def update_subscription(self, sub: Subscription) -> Subscription:
        sub.updated_at = clock.now()
        assignments = ", ".join(f"{c} = ?" for c in self._SUB_COLUMNS)
        self.conn.execute(
            f"UPDATE subscriptions SET {assignments} WHERE id = ?",
            [*self._sub_values(sub), sub.id],
        )
        self._after_write()
        return sub

    def delete_subscription(self, sub_id: int) -> None:
        self.conn.execute("DELETE FROM subscriptions WHERE id = ?", (sub_id,))
        self._after_write()

    def get_subscription(self, sub_id: int) -> Subscription | None:
        row = self.conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        return self._row_to_sub(row) if row else None

    def find_by_key(self, key: str) -> Subscription | None:
        row = self.conn.execute("SELECT * FROM subscriptions WHERE key = ?", (key,)).fetchone()
        return self._row_to_sub(row) if row else None

    def find_by_service(self, name: str) -> list[Subscription]:
        wanted = service_key(name)
        return [s for s in self.subscriptions(include_cancelled=True) if s.key.split("|")[0] == wanted]

    def resolve(self, ref: str) -> Subscription | None:
        """Look up by numeric id or by service name."""
        ref = ref.strip()
        if ref.isdigit():
            return self.get_subscription(int(ref))
        found = self.find_by_service(ref)
        if len(found) == 1:
            return found[0]
        active = [s for s in found if s.status != "cancelled"]
        return active[0] if len(active) == 1 else None

    def subscriptions(
        self,
        statuses: Iterable[str] | None = None,
        include_cancelled: bool = False,
    ) -> list[Subscription]:
        sql = "SELECT * FROM subscriptions"
        args: list[Any] = []
        if statuses is not None:
            wanted = list(statuses)
            sql += f" WHERE status IN ({', '.join('?' for _ in wanted)})"
            args.extend(wanted)
        elif not include_cancelled:
            sql += " WHERE status != 'cancelled'"
        sql += " ORDER BY service COLLATE NOCASE"
        return [self._row_to_sub(r) for r in self.conn.execute(sql, args)]

    def active_subscriptions(self) -> list[Subscription]:
        return self.subscriptions(statuses=("active", "paused"))

    def review_queue(self) -> list[Subscription]:
        return self.subscriptions(statuses=("review",))

    # -------------------------------------------------------------- charges

    def add_charge(self, charge: Charge) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO charges (subscription_id, date, amount, currency, source,"
            " source_ref, kind, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                charge.subscription_id, charge.date.isoformat(), str(charge.amount),
                charge.currency, charge.source,
                hash_key(charge.source_ref) if charge.source_ref else None, charge.kind,
                clock.iso(clock.now()),
            ),
        )
        self._after_write()
        return cur.rowcount > 0

    def charges(self, sub_id: int | None = None, since: date | None = None) -> list[Charge]:
        sql = "SELECT * FROM charges WHERE 1=1"
        args: list[Any] = []
        if sub_id is not None:
            sql += " AND subscription_id = ?"
            args.append(sub_id)
        if since is not None:
            sql += " AND date >= ?"
            args.append(since.isoformat())
        sql += " ORDER BY date"
        return [
            Charge(
                id=r["id"], subscription_id=r["subscription_id"], date=date.fromisoformat(r["date"]),
                amount=Decimal(r["amount"]), currency=r["currency"], source=r["source"],
                source_ref=r["source_ref"], kind=r["kind"],
            )
            for r in self.conn.execute(sql, args)
        ]

    def move_charges(self, from_id: int, to_id: int) -> None:
        self.conn.execute(
            "UPDATE OR IGNORE charges SET subscription_id = ? WHERE subscription_id = ?",
            (to_id, from_id),
        )
        self._after_write()

    # ---------------------------------------------------------------- rules

    def add_rule(self, kind: str, pattern: str, value: str | None = None, origin: str = "user") -> bool:
        cur = self.conn.execute(
            "INSERT OR REPLACE INTO rules (kind, pattern, value, origin, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (kind, pattern, value, origin, clock.iso(clock.now())),
        )
        self._after_write()
        return cur.rowcount > 0

    def rules(self, kind: str | None = None) -> list[sqlite3.Row]:
        if kind:
            return list(self.conn.execute("SELECT * FROM rules WHERE kind = ? ORDER BY id", (kind,)))
        return list(self.conn.execute("SELECT * FROM rules ORDER BY kind, id"))

    def has_rule(self, kind: str, pattern: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM rules WHERE kind = ? AND pattern = ?", (kind, pattern)
        ).fetchone()
        return row is not None

    def remove_rule(self, rule_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
        self._after_write()
        return cur.rowcount > 0

    # ----------------------------------------------------------- scan state

    def get_cursor(self, source: str, account: str, scope: str = "") -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT cursor FROM scan_state WHERE source = ? AND account = ? AND scope = ?",
            (source, account, scope),
        ).fetchone()
        return json.loads(row["cursor"]) if row else None

    def set_cursor(self, source: str, account: str, scope: str, cursor: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO scan_state (source, account, scope, cursor, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (source, account, scope, json.dumps(cursor), clock.iso(clock.now())),
        )
        self._after_write()

    def clear_cursors(self, source: str | None = None) -> None:
        if source:
            self.conn.execute("DELETE FROM scan_state WHERE source = ?", (source,))
        else:
            self.conn.execute("DELETE FROM scan_state")
        self._after_write()

    def cursors(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM scan_state ORDER BY source, account, scope"))

    def is_processed(self, source: str, key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM processed WHERE source = ? AND key = ?", (source, hash_key(key))
        ).fetchone()
        return row is not None

    def mark_processed(self, source: str, key: str, outcome: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO processed (source, key, processed_at, outcome) VALUES (?, ?, ?, ?)",
            (source, hash_key(key), clock.iso(clock.now()), outcome),
        )
        self._after_write()

    def forget_processed(self, source: str | None = None) -> None:
        if source:
            self.conn.execute("DELETE FROM processed WHERE source = ?", (source,))
        else:
            self.conn.execute("DELETE FROM processed")
        self._after_write()

    # ------------------------------------------------------------ reminders

    def ensure_reminder(
        self, sub_id: int, charge_date: date, days_before: int, kind: str, due_at: datetime
    ) -> int:
        self.conn.execute(
            "INSERT INTO reminders (subscription_id, charge_date, days_before, kind, due_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (subscription_id, charge_date, days_before, kind)"
            " DO UPDATE SET due_at = excluded.due_at WHERE reminders.sent_count = 0",
            (sub_id, charge_date.isoformat(), days_before, kind, clock.iso(due_at)),
        )
        row = self.conn.execute(
            "SELECT id FROM reminders WHERE subscription_id = ? AND charge_date = ?"
            " AND days_before = ? AND kind = ?",
            (sub_id, charge_date.isoformat(), days_before, kind),
        ).fetchone()
        self._after_write()
        return int(row["id"])

    def reminder(self, reminder_id: int) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()

    def reminders_for(self, sub_id: int) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM reminders WHERE subscription_id = ? ORDER BY due_at", (sub_id,)
            )
        )

    def open_reminders(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute("SELECT * FROM reminders WHERE acked_at IS NULL ORDER BY due_at")
        )

    def mark_reminder_sent(self, reminder_id: int, when: datetime) -> None:
        self.conn.execute(
            "UPDATE reminders SET sent_count = sent_count + 1, last_sent_at = ?,"
            " first_sent_at = COALESCE(first_sent_at, ?) WHERE id = ?",
            (clock.iso(when), clock.iso(when), reminder_id),
        )
        self._after_write()

    def ack_reminder(self, reminder_id: int, action: str, snoozed_until: datetime | None = None) -> None:
        if action == "snooze":
            self.conn.execute(
                "UPDATE reminders SET action = ?, snoozed_until = ? WHERE id = ?",
                (action, _s(snoozed_until), reminder_id),
            )
        else:
            self.conn.execute(
                "UPDATE reminders SET action = ?, acked_at = ?, snoozed_until = NULL WHERE id = ?",
                (action, clock.iso(clock.now()), reminder_id),
            )
        self._after_write()

    def ack_all_for_charge(self, sub_id: int, charge_date: date, action: str) -> None:
        self.conn.execute(
            "UPDATE reminders SET action = ?, acked_at = ? WHERE subscription_id = ?"
            " AND charge_date = ? AND acked_at IS NULL",
            (action, clock.iso(clock.now()), sub_id, charge_date.isoformat()),
        )
        self._after_write()

    def drop_stale_reminders(self, sub_id: int, keep_dates: Iterable[date]) -> None:
        keep = [d.isoformat() for d in keep_dates]
        sql = "DELETE FROM reminders WHERE subscription_id = ? AND sent_count = 0"
        args: list[Any] = [sub_id]
        if keep:
            sql += f" AND charge_date NOT IN ({', '.join('?' for _ in keep)})"
            args.extend(keep)
        self.conn.execute(sql, args)
        self._after_write()

    # --------------------------------------------------------------- events

    def add_event(self, kind: str, sub_id: int | None = None, payload: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "INSERT INTO events (ts, kind, subscription_id, payload) VALUES (?, ?, ?, ?)",
            (clock.iso(clock.now()), kind, sub_id, json.dumps(payload or {}, ensure_ascii=False,
                                                              default=str)),
        )
        self._after_write()

    def last_event(self, kind: str, sub_id: int | None = None) -> sqlite3.Row | None:
        if sub_id is None:
            return self.conn.execute(
                "SELECT * FROM events WHERE kind = ? ORDER BY id DESC LIMIT 1", (kind,)
            ).fetchone()
        return self.conn.execute(
            "SELECT * FROM events WHERE kind = ? AND subscription_id = ? ORDER BY id DESC LIMIT 1",
            (kind, sub_id),
        ).fetchone()

    def events(self, kind: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
        if kind:
            return list(self.conn.execute(
                "SELECT * FROM events WHERE kind = ? ORDER BY id DESC LIMIT ?", (kind, limit)))
        return list(self.conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)))

    # ------------------------------------------------------------- fx rates

    def save_rates(self, base: str, rates: dict[str, Decimal], source: str) -> None:
        now = clock.iso(clock.now())
        with self.transaction():
            for code, rate in rates.items():
                self.conn.execute(
                    "INSERT OR REPLACE INTO fx_rates (base, currency, rate, source, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (base, code, str(rate), source, now),
                )

    def load_rates(self, base: str) -> tuple[dict[str, Decimal], datetime | None, str | None]:
        rows = list(self.conn.execute("SELECT * FROM fx_rates WHERE base = ?", (base,)))
        if not rows:
            return {}, None, None
        fetched = max(clock.parse_iso(r["fetched_at"]) for r in rows)
        return {r["currency"]: Decimal(r["rate"]) for r in rows}, fetched, rows[0]["source"]

    # --------------------------------------------------------------- ai log

    def log_ai(self, *, provider: str, model: str, is_local: bool, message_key: str | None,
               sender_domain: str | None, payload: str, outcome: str, keep_payload: bool) -> None:
        self.conn.execute(
            "INSERT INTO ai_log (ts, provider, model, is_local, message_key, sender_domain, chars,"
            " payload_sha256, payload, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                clock.iso(clock.now()), provider, model, int(is_local),
                hash_key(message_key) if message_key else None, sender_domain, len(payload),
                hashlib.sha256(payload.encode()).hexdigest(), payload if keep_payload else None,
                outcome,
            ),
        )
        self._after_write()

    def ai_log(self, limit: int = 50) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM ai_log ORDER BY id DESC LIMIT ?", (limit,)))

    def ai_requests_since(self, since: datetime) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM ai_log WHERE ts >= ? AND outcome != 'dry_run'",
            (clock.iso(since),),
        ).fetchone()
        return int(row["n"])

    # --------------------------------------------------------- transactions

    def add_transactions(self, items: Iterable[Transaction]) -> int:
        inserted = 0
        with self.transaction():
            for tx in items:
                fp = hash_key(
                    f"{tx.date.isoformat()}|{tx.amount}|{tx.currency}|{tx.merchant_key}|{tx.seq}"
                )
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO transactions (fingerprint, date, amount, currency,"
                    " merchant, merchant_key, file_sha256) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (fp, tx.date.isoformat(), str(tx.amount), tx.currency, tx.merchant,
                     tx.merchant_key, tx.file_sha256),
                )
                inserted += cur.rowcount
        return inserted

    def transactions(self, since: date | None = None) -> list[Transaction]:
        sql = "SELECT * FROM transactions"
        args: list[Any] = []
        if since:
            sql += " WHERE date >= ?"
            args.append(since.isoformat())
        sql += " ORDER BY date"
        return [
            Transaction(
                date=date.fromisoformat(r["date"]), amount=Decimal(r["amount"]),
                currency=r["currency"], merchant=r["merchant"], merchant_key=r["merchant_key"],
                file_sha256=r["file_sha256"],
            )
            for r in self.conn.execute(sql, args)
        ]

    def purge_transactions_older_than(self, days: int) -> int:
        cutoff = (clock.today() - timedelta(days=days)).isoformat()
        cur = self.conn.execute("DELETE FROM transactions WHERE date < ?", (cutoff,))
        self._after_write()
        return cur.rowcount

    def is_imported(self, sha: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM imported_files WHERE sha256 = ?", (sha,)
        ).fetchone() is not None

    def mark_imported(self, sha: str, name: str, bank: str, rows: int, found: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO imported_files (sha256, name, bank, imported_at, rows, found)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (sha, name, bank, clock.iso(clock.now()), rows, found),
        )
        self._after_write()

    # ---------------------------------------------------------------- stats

    def table_counts(self) -> dict[str, int]:
        tables = [
            "subscriptions", "charges", "rules", "scan_state", "processed", "reminders",
            "events", "fx_rates", "ai_log", "transactions", "imported_files",
        ]
        return {
            name: int(self.conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
            for name in tables
        }

    def snippet_count(self) -> int:
        return int(self.conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE snippet IS NOT NULL AND snippet != ''"
        ).fetchone()[0])
