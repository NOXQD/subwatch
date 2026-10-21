"""Optional at-rest encryption of the database (storage.encrypt).

On disk: subwatch.db.enc = MAGIC + 12 byte nonce + AES-256-GCM ciphertext.
The key (32 random bytes) lives in the keyring. While the app runs, SQLite
works on a plain copy in $XDG_RUNTIME_DIR, which is tmpfs owned by the user
and wiped at logout. Every write is synced back to the encrypted file.
"""

from __future__ import annotations

import base64
import fcntl
import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import paths, secrets
from .errors import SubwatchError

MAGIC = b"SWDB1\n"


def load_or_create_key(create: bool = True) -> bytes:
    stored = secrets.get(secrets.DB_KEY_NAME)
    if stored:
        return base64.b64decode(stored)
    if not create:
        raise SubwatchError("crypto.err.no_key", hint="crypto.hint.no_key")
    key = AESGCM.generate_key(bit_length=256)
    secrets.put(secrets.DB_KEY_NAME, base64.b64encode(key).decode("ascii"))
    return key


def encrypt_bytes(key: bytes, data: bytes) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(key).encrypt(nonce, data, MAGIC)


def decrypt_bytes(key: bytes, blob: bytes) -> bytes:
    if not blob.startswith(MAGIC):
        raise SubwatchError("crypto.err.format")
    nonce = blob[len(MAGIC): len(MAGIC) + 12]
    try:
        return AESGCM(key).decrypt(nonce, blob[len(MAGIC) + 12:], MAGIC)
    except Exception:
        raise SubwatchError("crypto.err.decrypt", hint="crypto.hint.decrypt") from None


@contextmanager
def _locked(lock_path: Path):
    paths.ensure_private_dir(lock_path.parent)
    with open(lock_path, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write_private(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class EncryptedFile:
    """Pairs an encrypted file on disk with a working copy in tmpfs."""

    def __init__(self, encrypted: Path, plain_source: Path | None = None):
        self.encrypted = encrypted
        self.plain_source = plain_source
        work_dir = paths.ensure_private_dir(paths.runtime_dir())
        self.working = work_dir / (encrypted.name.removesuffix(".enc") or "subwatch.db")
        self.state = work_dir / (self.working.name + ".state")
        self.lock = work_dir / (self.working.name + ".lock")

    def _enc_stamp(self) -> dict[str, int] | None:
        try:
            st = self.encrypted.stat()
        except FileNotFoundError:
            return None
        return {"mtime_ns": st.st_mtime_ns, "size": st.st_size}

    def open(self) -> Path:
        """Make sure the working copy is current and return its path."""
        with _locked(self.lock):
            stamp = self._enc_stamp()
            if stamp is None:
                # First run with encryption: migrate the plain database if any.
                if self.plain_source and self.plain_source.exists():
                    data = self.plain_source.read_bytes()
                    paths.ensure_private_dir(self.encrypted.parent)
                    _write_private(self.encrypted, encrypt_bytes(load_or_create_key(), data))
                    _write_private(self.working, data)
                    for suffix in ("", "-wal", "-shm"):
                        p = Path(str(self.plain_source) + suffix)
                        if p.exists():
                            p.unlink()
                else:
                    load_or_create_key()
                    if self.working.exists():
                        self.working.unlink()
                self._save_state(self._enc_stamp())
                return self.working
            known = self._load_state()
            if self.working.exists() and known == stamp:
                return self.working
            key = load_or_create_key(create=False)
            data = decrypt_bytes(key, self.encrypted.read_bytes())
            _write_private(self.working, data)
            for suffix in ("-wal", "-shm"):
                p = Path(str(self.working) + suffix)
                if p.exists():
                    p.unlink()
            self._save_state(stamp)
            return self.working

    def sync(self, conn: sqlite3.Connection) -> None:
        """Snapshot the live database and replace the encrypted file."""
        with _locked(self.lock):
            fd, tmp = tempfile.mkstemp(prefix=".snap-", dir=self.working.parent)
            os.close(fd)
            try:
                dest = sqlite3.connect(tmp)
                with dest:
                    conn.backup(dest)
                dest.close()
                data = Path(tmp).read_bytes()
            finally:
                os.unlink(tmp)
            paths.ensure_private_dir(self.encrypted.parent)
            _write_private(self.encrypted, encrypt_bytes(load_or_create_key(), data))
            self._save_state(self._enc_stamp())

    def _load_state(self) -> dict[str, int] | None:
        try:
            return json.loads(self.state.read_text())
        except (OSError, ValueError):
            return None

    def _save_state(self, stamp: dict[str, int] | None) -> None:
        _write_private(self.state, json.dumps(stamp or {}).encode())

    def wipe_working(self) -> None:
        for p in (self.working, self.state, Path(str(self.working) + "-wal"),
                  Path(str(self.working) + "-shm")):
            if p.exists():
                p.unlink()
