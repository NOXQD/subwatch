"""Secrets in the system keyring (Secret Service / KWallet).

Nothing secret is ever written to config, logs or the database. To be able
to purge everything later we keep a list of entry *names* (never values) in
~/.local/state/subwatch/secrets.json.
"""

from __future__ import annotations

import json
import os

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from . import paths
from .errors import SubwatchError

SERVICE = "subwatch"

def backend_name() -> str:
    kr = keyring.get_keyring()
    return f"{type(kr).__module__}.{type(kr).__name__}"


def backend_ok() -> tuple[bool, str]:
    """False for backends that would lose or leak secrets."""
    kr = keyring.get_keyring()
    name = backend_name()
    lowered = name.lower()
    if "fail" in lowered or "plaintext" in lowered or ".null." in lowered:
        return False, name
    if "chainer" in lowered and not getattr(kr, "backends", None):
        return False, name
    return True, name


def _read_index() -> list[str]:
    path = paths.secrets_index_file()
    try:
        return list(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return []


def _write_index(names: list[str]) -> None:
    path = paths.secrets_index_file()
    paths.ensure_private_dir(path.parent)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(set(names)), ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def index() -> list[str]:
    return sorted(set(_read_index()))


def get(name: str) -> str | None:
    try:
        return keyring.get_password(SERVICE, name)
    except KeyringError as exc:
        raise SubwatchError("secrets.err.read", name=name, detail=str(exc)) from None


def put(name: str, value: str) -> None:
    ok, backend = backend_ok()
    if not ok:
        raise SubwatchError("secrets.err.no_backend", backend=backend)
    try:
        keyring.set_password(SERVICE, name, value)
    except KeyringError as exc:
        raise SubwatchError("secrets.err.write", name=name, detail=str(exc)) from None
    names = _read_index()
    if name not in names:
        names.append(name)
        _write_index(names)


def delete(name: str) -> bool:
    removed = False
    try:
        keyring.delete_password(SERVICE, name)
        removed = True
    except PasswordDeleteError:
        removed = False
    except KeyringError:
        removed = False
    names = [n for n in _read_index() if n != name]
    _write_index(names)
    return removed


def exists(name: str) -> bool:
    try:
        return get(name) is not None
    except SubwatchError:
        return False


def purge_all(extra: list[str] | None = None) -> list[str]:
    removed = []
    for name in sorted(set(_read_index()) | set(extra or [])):
        if delete(name):
            removed.append(name)
    path = paths.secrets_index_file()
    if path.exists():
        path.unlink()
    return removed


# Entry names used across the app, in one place.


def gmail_token_name(account: str) -> str:
    return f"gmail:{account}:token"


def gmail_client_name(account: str) -> str:
    return f"gmail:{account}:client"


def imap_password_name(account: str) -> str:
    return f"imap:{account}"


def ai_key_name(provider: str) -> str:
    return f"ai:{provider}"


DB_KEY_NAME = "db:key"
