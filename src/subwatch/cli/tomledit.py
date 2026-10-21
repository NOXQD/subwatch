"""Structured edits of config.toml that `config set` cannot express."""

from __future__ import annotations

from pathlib import Path

import tomlkit

from ..config.editor import ensure_config_file, write_atomic
from ..config.loader import validate
from ..config.schema import ImapAccount


def upsert_imap_account(path: Path, account: ImapAccount) -> None:
    path, _ = ensure_config_file(path)
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    sources = doc.setdefault("sources", tomlkit.table())
    imap = sources.setdefault("imap", tomlkit.table())
    accounts = imap.get("accounts")
    entry = tomlkit.table()
    for key in ("name", "host", "username", "port", "ssl", "starttls", "folders", "enabled", "timeout"):
        entry[key] = getattr(account, key)
    if accounts is None or not isinstance(accounts, tomlkit.items.AoT):
        aot = tomlkit.aot()
        for item in (accounts or []):
            t_ = tomlkit.table()
            t_.update(item)
            aot.append(t_)
        if "accounts" in imap:
            del imap["accounts"]
        imap["accounts"] = aot
        accounts = imap["accounts"]
    for i, item in enumerate(accounts):
        if item.get("name") == account.name:
            accounts[i] = entry
            break
    else:
        accounts.append(entry)
    imap["enabled"] = True
    text = tomlkit.dumps(doc)
    validate(tomlkit.parse(text).unwrap(), path)
    write_atomic(path, text)
