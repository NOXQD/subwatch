"""A small IMAP4rev1 server for tests.

Implements what imapclient needs for Subwatch: CAPABILITY, LOGIN, LIST,
SELECT/EXAMINE, UID SEARCH (UID ranges, SINCE, ALL), UID FETCH (header
fields, partial BODY[], RFC822.SIZE), NOOP and LOGOUT. Every command is
recorded, so tests can assert that nothing was written (no STORE, COPY,
EXPUNGE, APPEND, and folders opened with EXAMINE).
"""

from __future__ import annotations

import re
import socketserver
import threading
from dataclasses import dataclass, field
from datetime import date, datetime
from email import message_from_bytes, policy
from email.utils import parsedate_to_datetime


@dataclass
class Mailbox:
    uidvalidity: int = 1
    messages: dict[int, bytes] = field(default_factory=dict)
    next_uid: int = 1

    def append(self, raw: bytes) -> int:
        uid = self.next_uid
        self.messages[uid] = raw
        self.next_uid += 1
        return uid


@dataclass
class ServerState:
    user: str = "user@example.org"
    password: str = "app-password"
    folders: dict[str, Mailbox] = field(default_factory=lambda: {"INBOX": Mailbox()})
    log: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def writes(self) -> list[str]:
        bad = ("STORE", "COPY", "MOVE", "EXPUNGE", "APPEND", "DELETE", "CREATE", "RENAME", "SELECT ")
        return [c for c in self.log if any(f" {b}" in f" {c.upper()}" for b in bad)]


MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep",
                                       "oct", "nov", "dec"], 1)}


def _msg_date(raw: bytes) -> date:
    msg = message_from_bytes(raw, policy=policy.default)
    try:
        return parsedate_to_datetime(str(msg["Date"])).date()
    except (TypeError, ValueError):
        return date(1970, 1, 1)


def _headers(raw: bytes, names: list[str]) -> bytes:
    head = raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
    lines = head.replace(b"\r\n", b"\n").split(b"\n")
    out, keep = [], False
    wanted = {n.lower() for n in names}
    for line in lines:
        if line[:1] in (b" ", b"\t"):
            if keep:
                out.append(line)
            continue
        name = line.split(b":", 1)[0].decode("ascii", "replace").lower()
        keep = name in wanted
        if keep:
            out.append(line)
    return b"\r\n".join(out) + b"\r\n\r\n"


def _uid_set(spec: str, max_uid: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        if ":" in part:
            a, b = part.split(":")
            lo = int(a)
            hi = max_uid if b == "*" else int(b)
            if lo > hi:
                lo, hi = hi, lo
            out.update(range(lo, hi + 1))
        else:
            out.add(max_uid if part == "*" else int(part))
    return out


class Handler(socketserver.StreamRequestHandler):
    state: ServerState

    def send(self, data: bytes | str) -> None:
        if isinstance(data, str):
            data = data.encode()
        self.wfile.write(data)

    def handle(self) -> None:
        st = self.server.state  # type: ignore[attr-defined]
        selected: Mailbox | None = None
        self.send("* OK [CAPABILITY IMAP4rev1 AUTH=PLAIN] mock ready\r\n")
        while True:
            line = self.rfile.readline()
            if not line:
                return
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            # Literal arguments ({n}) are not used by imapclient for our commands.
            with st.lock:
                st.log.append(text)
            tag, _, rest = text.partition(" ")
            cmd, _, args = rest.partition(" ")
            cmd = cmd.upper()
            if cmd == "CAPABILITY":
                self.send("* CAPABILITY IMAP4rev1 AUTH=PLAIN UIDPLUS\r\n")
                self.send(f"{tag} OK CAPABILITY completed\r\n")
            elif cmd == "LOGIN":
                parts = re.findall(r'"((?:[^"\\]|\\.)*)"|(\S+)', args)
                values = [a or b for a, b in parts]
                if len(values) >= 2 and values[0] == st.user and values[1] == st.password:
                    self.send(f"{tag} OK LOGIN completed\r\n")
                else:
                    self.send(f"{tag} NO [AUTHENTICATIONFAILED] Invalid credentials\r\n")
            elif cmd == "NOOP":
                self.send(f"{tag} OK NOOP completed\r\n")
            elif cmd == "LIST":
                for name in st.folders:
                    self.send(f'* LIST (\\HasNoChildren) "/" "{name}"\r\n')
                self.send(f"{tag} OK LIST completed\r\n")
            elif cmd in ("SELECT", "EXAMINE"):
                name = args.strip().strip('"')
                box = st.folders.get(name)
                if box is None:
                    self.send(f"{tag} NO no such folder\r\n")
                    continue
                selected = box
                self.send(f"* {len(box.messages)} EXISTS\r\n* 0 RECENT\r\n")
                self.send(f"* OK [UIDVALIDITY {box.uidvalidity}] UIDs valid\r\n")
                self.send(f"* OK [UIDNEXT {box.next_uid}] next UID\r\n")
                self.send("* FLAGS (\\Seen \\Answered \\Flagged \\Deleted \\Draft)\r\n")
                mode = "READ-ONLY" if cmd == "EXAMINE" else "READ-WRITE"
                self.send(f"{tag} OK [{mode}] {cmd} completed\r\n")
            elif cmd == "UID":
                sub, _, sargs = args.partition(" ")
                sub = sub.upper()
                if selected is None:
                    self.send(f"{tag} BAD no folder selected\r\n")
                    continue
                uids = sorted(selected.messages)
                max_uid = uids[-1] if uids else 0
                if sub == "SEARCH":
                    crit = sargs.strip()
                    found = set(uids)
                    m = re.search(r"UID (\S+)", crit, re.I)
                    if m:
                        found &= _uid_set(m.group(1), max_uid) if max_uid else set()
                    m = re.search(r"SINCE (\d{1,2})-(\w{3})-(\d{4})", crit, re.I)
                    if m:
                        since = date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
                        found = {u for u in found if _msg_date(selected.messages[u]) >= since}
                    self.send("* SEARCH" + "".join(f" {u}" for u in sorted(found)) + "\r\n")
                    self.send(f"{tag} OK SEARCH completed\r\n")
                elif sub == "FETCH":
                    spec, _, items = sargs.partition(" ")
                    wanted = _uid_set(spec, max_uid) if max_uid else set()
                    items_up = items.upper()
                    for seq, uid in enumerate(uids, 1):
                        if uid not in wanted:
                            continue
                        raw = selected.messages[uid]
                        parts = [f"UID {uid}".encode()]
                        if "RFC822.SIZE" in items_up:
                            parts.append(f"RFC822.SIZE {len(raw)}".encode())
                        hm = re.search(r"BODY\.PEEK\[HEADER\.FIELDS \(([^)]*)\)\]", items, re.I)
                        if hm:
                            names = hm.group(1).split()
                            data = _headers(raw, names)
                            key = f"BODY[HEADER.FIELDS ({hm.group(1).upper()})]"
                            parts.append(f"{key} {{{len(data)}}}\r\n".encode() + data)
                        bm = re.search(r"BODY\.PEEK\[\]<(\d+)\.(\d+)>", items, re.I)
                        if bm:
                            start, size = int(bm.group(1)), int(bm.group(2))
                            data = raw[start: start + size]
                            parts.append(f"BODY[]<{start}> {{{len(data)}}}\r\n".encode() + data)
                        elif re.search(r"BODY\.PEEK\[\](?!<)", items, re.I):
                            parts.append(f"BODY[] {{{len(raw)}}}\r\n".encode() + raw)
                        self.send(f"* {seq} FETCH (".encode() + b" ".join(parts) + b")\r\n")
                    self.send(f"{tag} OK FETCH completed\r\n")
                else:
                    self.send(f"{tag} NO not supported in mock\r\n")
            elif cmd == "LOGOUT":
                self.send("* BYE logging out\r\n")
                self.send(f"{tag} OK LOGOUT completed\r\n")
                return
            elif cmd in ("ID", "ENABLE"):
                self.send(f"{tag} OK {cmd} completed\r\n")
            else:
                self.send(f"{tag} BAD unknown command\r\n")


class MockImapServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, state: ServerState | None = None):
        super().__init__(("127.0.0.1", 0), Handler)
        self.state = state or ServerState()
        self.thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.server_address[1]

    def __enter__(self) -> "MockImapServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.shutdown()
        self.server_close()


def internal_date(raw: bytes) -> datetime:
    msg = message_from_bytes(raw, policy=policy.default)
    return parsedate_to_datetime(str(msg["Date"]))
