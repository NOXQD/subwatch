"""Every user-facing string comes from the catalog.

* no Cyrillic (Russian or Kazakh) text anywhere in the Python sources;
* nothing that looks like English words is passed straight to an output
  function, widget or help text;
* every key used in code exists in ru.toml and en.toml, with the same
  placeholders, and no key in the catalog is dead.
"""

from __future__ import annotations

import ast
import re
import string
import tomllib
from pathlib import Path

import pytest

from subwatch.i18n import PLURAL_FORMS, _flatten

SRC = Path(__file__).resolve().parents[1] / "src" / "subwatch"
CATALOGS = SRC / "resources" / "i18n"
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
WORD = re.compile(r"[A-Za-z]{2,}")
MARKUP = re.compile(r"\[/?[^\[\]]*\]")
ALLOWED_WORDS = {"Subwatch", "subwatch", "Esc"}

# Callables whose text arguments end up on screen, with the positions of
# those arguments (the rest are styles, ids and the like).
SINKS = {"print": (0,), "echo": (0,), "secho": (0,), "say": (0,), "ok": (0,), "warn": (0,), "Text": (0,),
         "Static": (0,), "Label": (0,), "Button": (0,), "notify": (0,), "Notification": (0, 1),
         "ConfirmScreen": (0,), "Panel": (0,), "confirm": (0,), "ask": (0,), "input": (0,), "status": (0,),
         "choose": (0,), "Checkbox": (0,)}
UI_KEYWORDS = {"help", "short_help", "epilog", "title", "prompt", "placeholder", "label", "description",
               "summary", "body", "message", "tooltip", "text"}
NOT_UI_CALLS = {"run_local_server"}  # OAuth "prompt" parameter
# Placeholders filled in by third-party code, not at our call site.
EXTERNAL_PLACEHOLDERS = {"auth.gmail.prompt_url", "cli.chrome.try_help"}
KEY_FUNCS = {"t", "tn", "tget", "has"}


def py_files():
    return sorted(SRC.rglob("*.py"))


def flat(lang: str) -> dict:
    out: dict = {}
    _flatten(tomllib.loads((CATALOGS / f"{lang}.toml").read_text(encoding="utf-8")), "", out)
    return out


def literal_parts(node) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values if isinstance(v, ast.Constant)]
    if isinstance(node, ast.BinOp):
        return literal_parts(node.left) + literal_parts(node.right)
    return []


def looks_like_text(s: str) -> bool:
    s = MARKUP.sub("", s)
    words = [w for w in WORD.findall(s) if w not in ALLOWED_WORDS]
    return bool(words)


def call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def test_no_cyrillic_in_code():
    bad = []
    for path in py_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if CYRILLIC.search(line):
                bad.append(f"{path.relative_to(SRC)}:{n}: {line.strip()}")
    assert bad == []


def test_no_hardcoded_ui_strings():
    bad = []
    for path in py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = call_name(node)
            if name in NOT_UI_CALLS:
                continue
            candidates = []
            if name in SINKS:
                candidates += [a for i, a in enumerate(node.args) if i in SINKS[name]]
            for kw in node.keywords:
                if kw.arg in UI_KEYWORDS:
                    candidates.append(kw.value)
            for c in candidates:
                for part in literal_parts(c):
                    if looks_like_text(part):
                        bad.append(f"{path.relative_to(SRC)}:{node.lineno}: {name}({part!r})")
    assert bad == []


def collect_usage():
    static: dict[str, list[set[str] | None]] = {}
    dynamic: list[str] = []
    for path in py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = call_name(node)
                first = node.args[0] if node.args else None
                kws = None if any(k.arg is None for k in node.keywords) else \
                    {k.arg for k in node.keywords if k.arg not in ("hint",)}
                if name in KEY_FUNCS | {"SubwatchError", "NotFoundError", "LockedError"} and first is not None:
                    if isinstance(first, ast.Constant) and isinstance(first.value, str):
                        params = None if kws is None else (kws | {"n"} if name == "tn" else kws)
                        static.setdefault(first.value, []).append(params)
                    elif isinstance(first, ast.JoinedStr):
                        dynamic.append(ast.unparse(first))
                    elif isinstance(first, ast.BinOp):
                        left, right = first.left, first.right
                        if isinstance(left, ast.Constant) and isinstance(left.value, str):
                            dynamic.append("^" + re.escape(left.value) + ".*$")
                        if isinstance(right, ast.Constant) and isinstance(right.value, str):
                            dynamic.append("^.*" + re.escape(right.value) + "$")
                if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "log" and first is not None
                        and isinstance(first, ast.Constant)):
                    static.setdefault("log." + first.value, []).append(None)
                for kw in node.keywords:
                    if kw.arg == "hint" and isinstance(kw.value, ast.Constant):
                        static.setdefault(kw.value.value, []).append(kws)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                    re.fullmatch(r"[a-z_]+(\.[a-z0-9_-]+)+", node.value):
                static.setdefault(node.value, [])
    return static, dynamic


def dynamic_patterns(dynamic: list[str]) -> list[re.Pattern]:
    pats = []
    for expr in dynamic:
        if expr.startswith("^"):
            pats.append(re.compile(expr))
            continue
        text = re.sub(r"^f?['\"]|['\"]$", "", expr)
        text = re.sub(r"\{[^}]*\}", "\0", text)
        text = re.sub(r"['\"]\s*\+.*$", "", text)
        rx = "^" + re.escape(text).replace("\\\0", "\0").replace("\0", r"[^.]+") + r"(\..+)?$"
        pats.append(re.compile(rx))
    return pats


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_used_keys_exist(lang):
    cat = flat(lang)
    static, _ = collect_usage()
    prefixes = ("cli.", "config.", "doctor.", "integrate.", "tui.", "bar.", "remind.", "notify.", "privacy.",
                "gmail.", "imap.", "ai.", "crypto.", "secrets.", "scan.", "statements.", "fmt.", "log.", "auth.",
                "status.", "source.", "kind.", "details.", "table.", "export.", "input.", "action.", "category.",
                "review.")
    missing = []
    for key, uses in static.items():
        if not key.startswith(prefixes) or key.endswith((".lua", ".conf", ".toml", ".json", ".py")):
            continue
        # Used through t() or an error must exist in the catalog.
        if key not in cat and not any(k.startswith(key + ".") for k in cat) and uses:
            missing.append(key)
    assert missing == []


def placeholders(value) -> set[str]:
    texts = value.values() if isinstance(value, dict) else [value]
    out = set()
    for text in texts:
        if isinstance(text, str):
            out |= {f[1].split("!")[0].split(":")[0] for f in string.Formatter().parse(text) if f[1]}
    return out


def test_placeholders_match_call_sites():
    ru = flat("ru")
    static, _ = collect_usage()
    bad = []
    for key, uses in static.items():
        if key not in ru or key in EXTERNAL_PLACEHOLDERS:
            continue
        need = placeholders(ru[key])
        for given in uses:
            if given is None:
                continue
            if need - given:
                bad.append(f"{key}: needs {sorted(need)}, given {sorted(given)}")
    assert bad == []


def test_catalog_parity_and_placeholders():
    # input.period holds words people type, which naturally differ per language.
    ru = {k: v for k, v in flat("ru").items() if not k.startswith("input.period.")}
    en = {k: v for k, v in flat("en").items() if not k.startswith("input.period.")}
    assert set(ru) == set(en)
    diff = [k for k in ru if placeholders(ru[k]) != placeholders(en[k])]
    assert diff == []


def test_plural_tables():
    ru, en = flat("ru"), flat("en")
    for key, value in ru.items():
        if isinstance(value, dict):
            assert set(value) == {"one", "few", "many"}, key
            assert set(en[key]) == {"one", "other"}, key
            assert set(value) <= PLURAL_FORMS


def test_no_dead_keys():
    ru = flat("ru")
    static, dynamic = collect_usage()
    pats = dynamic_patterns(dynamic)
    dead = []
    for key in ru:
        if key.startswith(("meta.", "input.period.")):
            continue
        if key in static or any(key.startswith(s + ".") for s in static):
            continue
        if any(p.match(key) for p in pats):
            continue
        dead.append(key)
    assert dead == []


def test_language_is_configurable_without_code(tmp_path, monkeypatch):
    from subwatch import i18n

    user = tmp_path / "xdg_config_home" / "subwatch" / "i18n"
    user.mkdir(parents=True)
    (user / "kk.toml").write_text('[meta]\nname = "Қазақша"\nplural = "none"\n\n[fmt.rel]\ntoday = "бүгін"\n'
                                  'in_days = { other = "{n} күннен кейін" }\n', encoding="utf-8")
    i18n.reset_cache()
    assert "kk" in i18n.available_languages()
    i18n.set_language("kk")
    from subwatch.fmt import format_relative_days

    assert format_relative_days(0) == "бүгін"
    assert format_relative_days(5) == "5 күннен кейін"
    assert format_relative_days(-1) == "вчера"  # missing keys fall back to Russian
    i18n.set_language("ru")
