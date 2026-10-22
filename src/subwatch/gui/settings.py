"""Description of config.toml for the settings window.

Pages and groups are listed here; fields, types, limits, defaults and
current values come from the schema, so a new option shows up in the
window as soon as it is added to `config/schema.py` and given a label.
Help texts are the comments of the commented default config.toml.
"""

from __future__ import annotations

import re
import types
from decimal import Decimal
from functools import lru_cache
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from ..config.editor import default_template, plain
from ..config.loader import LoadedConfig, get_dotted
from ..config.schema import Config
from ..i18n import get_language, has, t

# page id -> [(group id, [paths])]. A path names a field or a whole section.
PAGES: list[tuple[str, list[tuple[str, list[str]]]]] = [
    ("reminders", [
        ("reminders", ["reminders.enabled", "reminders.days_before", "reminders.time",
                       "reminders.trial_days_before", "reminders.check_interval"]),
        ("quiet", ["reminders.quiet_hours"]),
        ("repeat", ["reminders.repeat_unacknowledged", "reminders.repeat_every", "reminders.max_repeats",
                    "reminders.snooze", "reminders.snooze_options"]),
        ("rules", ["reminders.amount_basis", "reminders.rules"]),
    ]),
    ("notifications", [("notifications", ["notifications"])]),
    ("budget", [("budget", ["budget"])]),
    ("currency", [
        ("currency", ["currency.base", "currency.rates_source", "currency.cache_ttl_hours", "currency.timeout"]),
        ("manual_rates", ["currency.manual_rates"]),
    ]),
    ("sources", [
        ("scan", ["scan"]),
        ("gmail", ["sources.gmail"]),
        ("imap", ["sources.imap"]),
        ("statements", ["sources.statements"]),
    ]),
    ("detection", [
        ("extraction", ["extraction"]),
        ("recurrence", ["recurrence"]),
        ("detection", ["detection"]),
        ("filters", ["filters"]),
        ("category_rules", ["category_rules"]),
        ("tag_rules", ["tag_rules"]),
    ]),
    ("appearance", [
        ("general", ["ui.language", "general.timezone"]),
        ("bar", ["bar"]),
        ("menu", ["menu"]),
        ("tui", ["ui.theme", "ui.default_sort", "ui.sort_reverse", "ui.show_cancelled", "ui.date_style",
                 "ui.money_decimals", "ui.terminal", "ui.reload_interval"]),
        ("colors", ["ui.colors"]),
    ]),
    ("keys", [("keybinds", ["keybinds"]), ("tui_keys", ["ui.keys"])]),
    ("ai", [("ai", ["ai"])]),
    ("privacy", [("storage", ["storage"]), ("export", ["export"]), ("logging", ["logging"])]),
    ("hooks", [("hooks", ["hooks"]), ("plugins", ["plugins.enabled", "plugins.disabled"])]),
]

# Edited on their own pages, not as plain fields.
SPECIAL = {"categories", "plugins.options"}

FORMATS = {
    "time": re.compile(r"(^|\.)(time|start|end)$"),
    "duration": re.compile(r"(repeat_every|snooze|check_interval|randomized_delay)$"),
    "keybind": re.compile(r"^keybinds\.(open_tui|upcoming|menu|rescan|add|settings)$"),
    "color": re.compile(r"^ui\.colors\."),
    "glyph": re.compile(r"(\.icon|\.glyph)$"),
    "path": re.compile(r"(inbox_dir|ics_path|db_path|logging\.file)$"),
}


def _strip_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _limits(info: FieldInfo) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in info.metadata:
        for attr, key in (("ge", "min"), ("gt", "min"), ("le", "max"), ("lt", "max")):
            value = getattr(item, attr, None)
            if value is not None:
                out[key] = float(value) if isinstance(value, (Decimal, float)) else value
    return out


def _model_fields(model: type[BaseModel]) -> dict[str, FieldInfo]:
    return dict(model.model_fields)


def label(path: str) -> str:
    if has(f"gui.field.{path}"):
        return t(f"gui.field.{path}")
    return path.rsplit(".", 1)[-1].replace("_", " ")


def choice_label(path: str, value: Any) -> str:
    return t(f"gui.choice.{path}.{value}") if has(f"gui.choice.{path}.{value}") else str(value)


@lru_cache(maxsize=4)
def _help_for(language: str) -> dict[str, str]:
    return parse_template_help(default_template())


def _same(a: str, b: str) -> bool:
    def norm(x: str) -> str:
        return re.sub(r"[\W_]+", " ", x).strip().casefold()
    return norm(a) == norm(b) or norm(a).startswith(norm(b) + " ") and len(norm(a)) - len(norm(b)) < 12


def help_text(path: str) -> str:
    text = _help_for(get_language()).get(path, "")
    # A help line that only repeats the label ("At." under "At") says nothing new.
    if text and (" " not in text.strip() or _same(text, label(path)) or _same(label(path), text)):
        return ""
    return text


def _clean(paragraph: list[str]) -> str:
    lines = [ln for ln in paragraph if not ln.startswith("  ")]
    if len(lines) != len(paragraph) and lines and lines[-1].rstrip().endswith(":"):
        last = lines[-1].rstrip()
        cut = max(last.rfind(". "), last.rfind("; "))
        lines[-1] = last[:cut + 1] if cut >= 0 else ""
    return " ".join(ln.strip() for ln in lines if ln.strip())


def parse_template_help(text: str) -> dict[str, str]:
    """{dotted key: the comment right above it} for keys and tables."""
    out: dict[str, str] = {}
    table = ""
    pending: list[str] = []

    def flush() -> str:
        paragraphs: list[list[str]] = [[]]
        for line in pending:
            if not line.strip():
                paragraphs.append([])
            else:
                paragraphs[-1].append(line)
        parts = [_clean(p) for p in paragraphs if p]
        return "\n\n".join(p for p in parts if p)

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            body = line[1:]
            body = body[1:] if body.startswith(" ") else body
            if body.strip() and set(body.strip()) == {"-"}:
                pending = []
                continue
            pending.append(body)
            continue
        if not line:
            if pending and not any(p.strip() for p in pending):
                pending = []
            continue
        header = re.match(r"^\[\[?\s*([^\]]+?)\s*\]\]?$", line)
        if header:
            table = header.group(1)
            if pending:
                out.setdefault(table, flush())
            pending = []
            continue
        key = re.match(r'^"?([A-Za-z0-9_-]+)"?\s*=', line)
        if key and pending:
            out.setdefault(f"{table}.{key.group(1)}" if table else key.group(1), flush())
        pending = []
    return {k: v for k, v in out.items() if v}


def _kind(path: str, annotation: Any) -> dict[str, Any]:
    if path == "ui.language":
        from ..i18n import available_languages

        return {"nullable": False, "kind": "choice",
                "options": [{"value": code, "label": name} for code, name in available_languages().items()]}
    base, nullable = _strip_optional(annotation)
    origin = get_origin(base)
    spec: dict[str, Any] = {"nullable": nullable}
    if base is bool:
        spec["kind"] = "bool"
    elif origin is Literal:
        spec["kind"] = "choice"
        spec["options"] = [{"value": v, "label": choice_label(path, v)} for v in get_args(base)]
    elif base is int:
        spec["kind"] = "int"
    elif base in (float, Decimal):
        spec["kind"] = "number"
    elif base is str:
        spec["kind"] = "text"
        for name, rx in FORMATS.items():
            if rx.search(path):
                spec["format"] = name
                break
    elif origin is list:
        inner = get_args(base)[0] if get_args(base) else str
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            spec["kind"] = "records"
            spec["item_fields"] = [_field(f"{path}.{name}", info, None, None)
                                   for name, info in _model_fields(inner).items()]
        elif get_origin(inner) is Literal:
            spec["kind"] = "multichoice"
            spec["options"] = [{"value": v, "label": choice_label(path, v)} for v in get_args(inner)]
        elif inner is int:
            spec["kind"] = "numbers"
        else:
            spec["kind"] = "tags"
    elif origin is dict:
        value_type = get_args(base)[1] if len(get_args(base)) == 2 else Any
        spec["kind"] = "map_number" if value_type in (Decimal, float, int) else "raw"
    else:
        spec["kind"] = "raw"
    return spec


def _field(path: str, info: FieldInfo, value: Any, loaded: LoadedConfig | None) -> dict[str, Any]:
    spec = _kind(path, info.annotation)
    default = info.get_default(call_default_factory=True)
    spec.update(_limits(info))
    spec.update({
        "path": path,
        "label": label(path),
        "help": help_text(path),
        "value": plain(value),
        "default": plain(default),
    })
    if loaded is not None:
        origin = loaded.origin(path)
        spec["origin"] = origin
        spec["origin_text"] = t(f"config.origin.{origin}") if origin in ("env", "cli") else ""
        spec["locked"] = origin in ("env", "cli")
        spec["changed"] = plain(value) != plain(default)
    return spec


def _expand(model: type[BaseModel], prefix: str, config: Any, loaded: LoadedConfig) -> list[dict[str, Any]]:
    out = []
    for name, info in _model_fields(model).items():
        path = f"{prefix}.{name}" if prefix else name
        if path in SPECIAL:
            continue
        value = getattr(config, name)
        base, _ = _strip_optional(info.annotation)
        if isinstance(base, type) and issubclass(base, BaseModel):
            out.extend(_expand(base, path, value, loaded))
        else:
            out.append(_field(path, info, value, loaded))
    return out


def _resolve(path: str) -> tuple[type[BaseModel], str, FieldInfo]:
    parts = path.split(".")
    model: type[BaseModel] = Config
    for part in parts[:-1]:
        annotation, _ = _strip_optional(model.model_fields[part].annotation)
        model = annotation
    return model, parts[-1], model.model_fields[parts[-1]]


def fields_for(path: str, loaded: LoadedConfig) -> list[dict[str, Any]]:
    model, name, info = _resolve(path)
    value = get_dotted(loaded.config, path.split("."))
    base, _ = _strip_optional(info.annotation)
    if isinstance(base, type) and issubclass(base, BaseModel):
        return _expand(base, path, value, loaded)
    return [_field(path, info, value, loaded)]


def field(path: str, loaded: LoadedConfig) -> dict[str, Any]:
    return fields_for(path, loaded)[0]


def page_ids() -> list[str]:
    return [pid for pid, _ in PAGES]


def page(page_id: str, loaded: LoadedConfig) -> dict[str, Any]:
    groups = dict(PAGES)[page_id]
    out = []
    for group_id, paths in groups:
        fields: list[dict[str, Any]] = []
        for path in paths:
            fields.extend(fields_for(path, loaded))
        if has(f"gui.group.{group_id}.help"):
            group_help = t(f"gui.group.{group_id}.help")
        elif len(paths) == 1 and len(fields) > 1:
            group_help = help_text(paths[0])
        else:
            group_help = ""
        out.append({
            "id": group_id,
            "title": t(f"gui.group.{group_id}.title"),
            "help": group_help,
            "fields": fields,
        })
    return {"id": page_id, "title": t(f"gui.page.{page_id}.title"), "subtitle": t(f"gui.page.{page_id}.subtitle"),
            "groups": out}


def all_paths() -> list[str]:
    """Every editable leaf of the schema, as the pages see them."""
    loaded = LoadedConfig(Config(), path=None, exists=False)  # type: ignore[arg-type]
    out = []
    for _, groups in PAGES:
        for _, paths in groups:
            for path in paths:
                out.extend(f["path"] for f in fields_for(path, loaded))
    return out


def search(query: str, loaded: LoadedConfig) -> list[dict[str, Any]]:
    """Fields whose label, help or key match; each carries its page."""
    q = query.casefold().strip()
    if not q:
        return []
    hits = []
    for page_id, groups in PAGES:
        for _, paths in groups:
            for path in paths:
                for f in fields_for(path, loaded):
                    hay = " ".join([f["label"], f["help"], f["path"]]).casefold()
                    if q in hay:
                        hits.append({**f, "page": page_id, "page_title": t(f"gui.page.{page_id}.title")})
    return hits[:60]
