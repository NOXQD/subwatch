"""What Subwatch keeps, what it has sent out, and wiping all of it."""

from __future__ import annotations

import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths, secrets
from .config.schema import Config
from .db import Store, db_path_for


@dataclass
class FileInfo:
    path: Path
    exists: bool
    size: int = 0
    mode: str = ""


@dataclass
class PrivacyReport:
    files: list[FileInfo] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    snippets: int = 0
    store_snippets: bool = False
    encrypted: bool = False
    secrets: list[tuple[str, bool]] = field(default_factory=list)
    ai_total: int = 0
    ai_cloud: int = 0
    ai_by_model: dict[str, int] = field(default_factory=dict)
    ai_recent: list[dict[str, Any]] = field(default_factory=list)


def _info(path: Path) -> FileInfo:
    if not path.exists():
        return FileInfo(path, False)
    st = path.stat()
    return FileInfo(path, True, st.st_size, oct(stat.S_IMODE(st.st_mode)))


def known_secret_names(config: Config) -> list[str]:
    names = {secrets.gmail_token_name(config.sources.gmail.account),
             secrets.gmail_client_name(config.sources.gmail.account),
             secrets.ai_key_name(config.ai.provider), secrets.DB_KEY_NAME}
    names.update(secrets.imap_password_name(a.name) for a in config.sources.imap.accounts)
    return sorted(names | set(secrets.index()))


def report(config: Config, show_payloads: bool = False) -> PrivacyReport:
    from .export import ics_path

    db = db_path_for(config)
    rep = PrivacyReport(store_snippets=config.extraction.store_snippets, encrypted=config.storage.encrypt)
    for p in (db, Path(str(db) + ".enc"), Path(str(db) + "-wal"), ics_path(config),
              paths.bar_cache_file(), paths.secrets_index_file(), paths.config_file()):
        info = _info(p)
        if info.exists or p in (db, paths.config_file()):
            rep.files.append(info)
    if db.exists() or Path(str(db) + ".enc").exists():
        with Store.open(config) as store:
            rep.counts = store.table_counts()
            rep.snippets = store.snippet_count()
            for row in store.ai_log(limit=10_000):
                rep.ai_total += 1
                if not row["is_local"]:
                    rep.ai_cloud += 1
                label = f"{row['provider']}/{row['model']}"
                rep.ai_by_model[label] = rep.ai_by_model.get(label, 0) + 1
            for row in store.ai_log(limit=10):
                item = dict(row)
                if not show_payloads:
                    item.pop("payload", None)
                rep.ai_recent.append(item)
    for name in known_secret_names(config):
        rep.secrets.append((name, secrets.exists(name)))
    return rep


def purge(config: Config, include_config: bool = False) -> list[str]:
    """Delete the database, caches, calendar, state and keyring entries."""
    from .crypto import EncryptedFile
    from .export import ics_path

    removed: list[str] = []
    db = db_path_for(config)
    for p in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm"), Path(str(db) + ".enc"), ics_path(config)):
        if p.exists():
            p.unlink()
            removed.append(paths.contract_home(p))
    for p in db.parent.glob(db.name + ".v*.bak"):
        p.unlink()
        removed.append(paths.contract_home(p))
    EncryptedFile(Path(str(db) + ".enc")).wipe_working()
    for d in (paths.cache_dir(), paths.runtime_dir()):
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed.append(paths.contract_home(d))
    for name in secrets.purge_all(known_secret_names(config)):
        removed.append(f"keyring:{name}")
    state = paths.state_dir()
    if state.exists():
        shutil.rmtree(state, ignore_errors=True)
        removed.append(paths.contract_home(state))
    if include_config and paths.config_dir().exists():
        shutil.rmtree(paths.config_dir(), ignore_errors=True)
        removed.append(paths.contract_home(paths.config_dir()))
    return removed
