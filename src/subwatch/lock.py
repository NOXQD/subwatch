"""One scanner at a time, at a polite CPU and I/O priority."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager

from . import paths
from .errors import LockedError


@contextmanager
def single_instance(name: str = "scan") -> Iterator[None]:
    lock_dir = paths.ensure_private_dir(paths.runtime_dir())
    path = lock_dir / f"{name}.lock"
    fh = open(path, "a+")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fh.seek(0)
            holder = fh.read().strip() or "?"
            raise LockedError("scan.err.locked", hint="scan.hint.locked", pid=holder) from None
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        finally:
            fh.close()


def is_locked(name: str = "scan") -> bool:
    path = paths.runtime_dir() / f"{name}.lock"
    if not path.exists():
        return False
    with open(path, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
    return False


def lower_priority(nice: int, io_class: str) -> None:
    """Apply scan.nice / scan.io_class to the current process."""
    if nice > 0:
        try:
            current = os.nice(0)
            if current < nice:
                os.nice(nice - current)
        except OSError:
            pass
    if io_class != "none" and shutil.which("ionice"):
        cls = {"idle": "3", "best-effort": "2"}.get(io_class)
        if cls:
            args = ["ionice", "-c", cls]
            if cls == "2":
                args += ["-n", "7"]
            subprocess.run(args + ["-p", str(os.getpid())], capture_output=True, check=False)
