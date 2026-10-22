"""The Omarchy widget and the settings window: the data they get, the backend
they talk to, the plugin files and how they are installed."""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tomllib
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from subwatch import paths
from subwatch.__main__ import main
from subwatch.app import AppContext
from subwatch.config.loader import LoadedConfig, load_config
from subwatch.config.schema import Config
from subwatch.gui import settings, views
from subwatch.gui.server import Server
from subwatch.integrate import omarchy
from subwatch.models import Subscription
from subwatch.period import Period

PLUGIN = Path(__file__).resolve().parents[1] / "src" / "subwatch" / "resources" / "omarchy" / "plugin"
CATALOGS = Path(__file__).resolve().parents[1] / "src" / "subwatch" / "resources" / "i18n"
CYRILLIC = re.compile(r"[Ѐ-ӿ]")


def catalog(lang: str) -> dict:
    return tomllib.loads((CATALOGS / f"{lang}.toml").read_text(encoding="utf-8"))


def cli(*args: str) -> None:
    try:
        main(list(args))
    except SystemExit as exc:
        assert not exc.code


def seed(ctx: AppContext) -> None:
    def add(service, amount, currency, nxt, category, **kw):
        sub = Subscription(service=service, amount=Decimal(amount), currency=currency, period=Period.parse("1m"),
                           next_charge=date.fromisoformat(nxt), category=category, **kw)
        ctx.store.insert_subscription(sub)

    add("Netflix", "3990", "KZT", "2026-10-23", "video", cancel_url="https://example.com/cancel")
    add("Notion", "10", "USD", "2026-10-25", "software")
    add("Spotify", "1590", "KZT", "2026-11-14", "music")
    add("Tasklane", "4.99", "USD", "2026-11-09", "software", status="review", review_reason="unknown_service",
        confidence=0.6)


@pytest.fixture
def ctx():
    from conftest import write_config

    write_config('# мои настройки\n[currency]\nrates_source = "manual"\n[currency.manual_rates]\nUSD = 520\n'
                 '[budget]\nmonthly_limit = 10000\n')
    app = AppContext.load()
    seed(app)
    yield app
    app.close()


class Client:
    """Talks to the gui-server the way the window does, line by line."""

    def __init__(self):
        self.server = Server(out=io.StringIO())
        self.n = 0

    def __call__(self, cmd, **args):
        self.n += 1
        reply = self.server.handle({"id": self.n, "cmd": cmd, **args})
        assert reply["id"] == self.n
        return reply

    def ok(self, cmd, **args):
        reply = self(cmd, **args)
        assert reply["ok"], reply
        return reply["data"]


@pytest.fixture
def client(ctx):
    c = Client()
    yield c
    c.server.ctx.close()


# ------------------------------------------------------------ dashboard


def test_dashboard_is_formatted_for_display(ctx):
    data = views.dashboard(ctx)
    # 3990 + 10 USD × 520 + 1590; the finding under review is not counted.
    assert data["totals"]["monthly"] == "10\u00a0780\u00a0₸"
    assert data["totals"]["count_text"] == "3 подписки"
    assert data["budget"]["level"] == "over" and data["budget"]["note"].startswith("сверх лимита")
    first = data["upcoming"][0]
    assert first["service"] == "Netflix" and first["relative"] == "завтра" and first["month"] == "окт"
    assert first["amount"] == "3\u00a0990\u00a0₸"   # compact: no ",00" in the popup
    notion = data["upcoming"][1]
    assert notion["converted"] == "5\u00a0200\u00a0₸"
    assert data["widget"]["state"] == "soon" and data["widget"]["alert"] is True
    assert data["widget"]["label"] == "Netflix · завтра"
    assert data["review"]["text"] == "1 находка ждёт проверки"
    assert {c["key"] for c in data["categories"]} == {"video", "software", "music"}
    assert abs(sum(c["share"] for c in data["categories"]) - 1) < 0.01
    assert data["strings"]["per_month"] == "в месяц" and data["strings"]["page_overview"] == "Обзор"
    assert len(data["history"]) == views.HISTORY_MONTHS


def test_dashboard_follows_settings(ctx):
    from conftest import write_config

    write_config('[ui]\nlanguage = "en"\n[bar]\nmode = "total"\n[currency]\nrates_source = "manual"\n'
                 '[currency.manual_rates]\nUSD = 520\n')
    app = AppContext.load()
    try:
        data = views.dashboard(app)
        assert data["widget"]["state"] == "total" and data["widget"]["label"] == data["totals"]["monthly"]
        assert data["budget"] is None
        assert data["strings"]["per_month"] == "a month"
    finally:
        app.close()
        from subwatch.i18n import set_language

        set_language("ru")


def test_panel_format_is_cached(ctx, capsys):
    ctx.close()
    cli("bar", "--format", "panel")
    first = json.loads(capsys.readouterr().out)
    assert first["widget"]["label"] == "Netflix · завтра"
    assert (paths.cache_dir() / "panel.json").exists()
    cli("bar", "--format", "panel")   # answered by the fast path in __main__
    assert json.loads(capsys.readouterr().out) == first


def test_changes_touch_the_stamp_the_widget_watches(ctx):
    from subwatch import barcache, ops

    stamp = barcache.stamp_file()
    stamp.unlink(missing_ok=True)
    ops.mark_used(ctx, ctx.store.find_by_service("Spotify")[0])
    assert stamp.exists()


# ---------------------------------------------------------- the backend


def test_server_speaks_json_lines(ctx):
    ctx.close()
    out = io.StringIO()
    server = Server(out=out)
    server.serve(io.StringIO('{"id": 1, "cmd": "hello"}\nnot json\n{"id": 2, "cmd": "nope"}\n'))
    lines = [json.loads(x) for x in out.getvalue().splitlines()]
    assert lines[0]["event"] == "ready"
    assert lines[1]["id"] == 1 and lines[1]["ok"] and lines[1]["data"]["strings"]["save"] == "Сохранить"
    assert [p["id"] for p in lines[1]["data"]["pages"]][:3] == ["reminders", "notifications", "budget"]
    assert lines[2] == {"id": 2, "ok": False, "error": "Неизвестная команда: nope"}


def test_settings_are_saved_validated_and_reset(client):
    page = client.ok("page", page="reminders")
    fields = {f["path"]: f for g in page["groups"] for f in g["fields"]}
    assert fields["reminders.time"]["value"] == "10:00" and fields["reminders.time"]["kind"] == "text"
    assert fields["reminders.days_before"]["kind"] == "numbers"
    assert fields["reminders.rules"]["kind"] == "records"
    assert fields["reminders.amount_basis"]["options"][0] == {"value": "charge", "label": "по сумме списания"}

    data = client.ok("set", path="reminders.time", value="09:30")
    assert data["field"]["value"] == "09:30" and data["field"]["changed"]
    assert load_config().config.reminders.time == "09:30"
    assert "# мои настройки" in paths.config_file().read_text(encoding="utf-8")   # comments survive

    bad = client("set", path="reminders.time", value="25:99")
    assert not bad["ok"] and "25:99" in bad["error"]
    assert load_config().config.reminders.time == "09:30"

    rules = [{"name": "дорогие", "min_amount": 5000, "days_before": [7, 1]}]
    client.ok("set", path="reminders.rules", value=rules)
    assert load_config().config.reminders.rules[0].days_before == [7, 1]

    data = client.ok("reset", path="reminders.time")
    assert data["field"]["value"] == "10:00" and not data["field"]["changed"]


def test_env_overrides_are_shown_locked(client, monkeypatch):
    monkeypatch.setenv("SUBWATCH_REMINDERS__TIME", "07:00")
    client.server.reload_config()
    field = settings.field("reminders.time", client.server.ctx.loaded)
    assert field["locked"] and field["value"] == "07:00" and field["origin_text"]


def test_search_finds_settings_on_any_page(client):
    hits = client.ok("search", query="тихие")
    assert {h["path"] for h in hits} >= {"reminders.quiet_hours.enabled"}
    assert all(h["page_title"] for h in hits)
    assert client.ok("search", query="   ") == []


def test_subscriptions_are_edited_through_the_window(client):
    data = client.ok("subscriptions")
    assert data["counts"]["active"] == 3 and all(r["status"] != "review" for r in data["items"])
    assert data["form"]["categories"][0]["value"] == ""   # "detect from the service"

    added = client.ok("subscription_save", values={"service": "youtube premium", "amount": "2 490 ₸",
                                                   "period": "1m", "next": "+1m", "category": ""})
    item = added["item"]
    assert item["service"] == "YouTube Premium" and item["category"]["key"] == "video"
    assert item["amount_raw"] == "2490"

    dup = client("subscription_save", values={"service": "Netflix", "amount": "3990"})
    assert not dup["ok"] and "Netflix" in dup["error"]

    netflix = next(r for r in data["items"] if r["service"] == "Netflix")
    client.ok("subscription_save", sub_id=netflix["id"], values={"amount": "9.99 USD", "tags": ["семья"]})
    sub = client.server.ctx.store.get_subscription(netflix["id"])
    assert sub.currency == "USD" and sub.amount == Decimal("9.99") and sub.tags == ["семья"]

    bad = client("subscription_save", sub_id=netflix["id"], values={"next": "когда-нибудь"})
    assert not bad["ok"] and bad["hint"]

    for action, status in (("pause", "paused"), ("resume", "active"), ("used", "active")):
        client.ok("subscription_action", sub_id=netflix["id"], action=action)
        assert client.server.ctx.store.get_subscription(netflix["id"]).status == status
    cancelled = client.ok("subscription_action", sub_id=netflix["id"], action="cancel", open_page=False)
    assert "Netflix" in cancelled["message"]
    assert client.server.ctx.store.get_subscription(netflix["id"]).status == "cancelled"
    client.ok("subscription_action", sub_id=netflix["id"], action="remove")
    assert client.server.ctx.store.get_subscription(netflix["id"]) is None
    gone = client("subscription_action", sub_id=netflix["id"], action="pause")
    assert not gone["ok"]


def test_review_decisions_become_rules(client):
    item = client.ok("review")["items"][0]
    assert item["service"] == "Tasklane" and item["review_reason"] == "сервис не из справочника"
    client.ok("review_decide", sub_id=item["id"], accept=True)
    assert client.server.ctx.store.get_subscription(item["id"]).status == "active"
    assert client.ok("review")["items"] == []
    assert client.server.ctx.store.has_rule("accept_service", "tasklane")


def test_categories_are_added_renamed_and_removed(client):
    data = client.ok("category_save", name="Здоровье", icon="", budget="5 000")
    key = data["key"]
    assert key == "custom" or re.fullmatch(r"[a-z0-9_]+", key)
    cats = load_config().config.categories
    assert cats[key].name == "Здоровье" and cats[key].budget == Decimal(5000)
    assert list(cats)[:2] == ["music", "video"]   # the rest keep their order

    netflix = client.server.ctx.store.find_by_service("Netflix")[0]
    client.ok("subscription_save", sub_id=netflix.id, values={"category": key})
    removed = client.ok("category_remove", key=key)
    assert key not in load_config().config.categories and "1" in removed["message"]
    assert client.server.ctx.store.get_subscription(netflix.id).category == "other"
    assert not client("category_remove", key="other")["ok"]


def test_overview_and_health_pages(client):
    data = client.ok("overview")
    assert len(data["history_long"]) == 12 and data["history_long"][-1]["forecast"]
    health = client.ok("health")
    assert health["groups"] and health["worst"] in ("ok", "warn", "fail")


def test_imap_account_is_checked_before_saving(client, monkeypatch):
    from subwatch import secrets
    from subwatch.sources import imap

    monkeypatch.setattr(imap, "test_login", lambda account, password: ["INBOX", "Receipts"])
    data = client.ok("imap_connect", name="fm", host="imap.fastmail.com", username="me@example.com",
                     password="app-pass", folders="INBOX, Чеки")
    assert "Чеки" in data["message"]   # a folder the server does not have is reported
    acc = load_config().config.sources.imap.accounts[0]
    assert acc.host == "imap.fastmail.com" and acc.folders == ["INBOX", "Чеки"]
    assert secrets.get(secrets.imap_password_name("fm")) == "app-pass"
    assert "app-pass" not in paths.config_file().read_text(encoding="utf-8")
    assert not client("imap_connect", name="x", host="h", username="u", password="")["ok"]
    client.ok("imap_remove", name="fm")
    assert load_config().config.sources.imap.accounts == []
    assert secrets.get(secrets.imap_password_name("fm")) is None


def test_external_changes_are_announced(client):
    out = client.server.out
    client.server._stamps = (0.0, 0.0)
    stamps = client.server._current_stamps()
    assert stamps != (0.0, 0.0)
    client.server._stop.set()
    # One poll by hand: the watcher thread would do exactly this.
    if stamps != client.server._stamps:
        client.server._stamps = stamps
        client.server.event("changed", config=True)
    assert json.loads(out.getvalue().splitlines()[-1]) == {"event": "changed", "config": True}


# -------------------------------------------------------- settings schema


def every_field() -> list[dict]:
    loaded = LoadedConfig(Config(), path=None, exists=False)  # type: ignore[arg-type]
    out = []
    for page_id in settings.page_ids():
        for group in settings.page(page_id, loaded)["groups"]:
            for f in group["fields"]:
                out.append(f)
                out.extend(f.get("item_fields") or [])
    return out


def test_every_setting_is_on_exactly_one_page():
    loaded = LoadedConfig(Config(), path=None, exists=False)  # type: ignore[arg-type]
    shown = [p for p in settings.all_paths()]
    assert len(shown) == len(set(shown))

    def leaves(model, prefix=""):
        for name, info in model.model_fields.items():
            path = f"{prefix}{name}"
            ann, _ = settings._strip_optional(info.annotation)
            if path in settings.SPECIAL:
                continue
            if isinstance(ann, type) and hasattr(ann, "model_fields"):
                yield from leaves(ann, path + ".")
            else:
                yield path

    assert set(leaves(Config)) == set(shown)
    assert settings.page("reminders", loaded)["title"] == "Напоминания"


@pytest.mark.parametrize("lang", ["ru", "en"])
def test_every_setting_has_a_label(lang):
    fields = catalog(lang)["gui"]["field"]
    missing = [f["path"] for f in every_field() if f["path"] not in fields]
    assert missing == []
    choices = catalog(lang)["gui"]["choice"]
    no_label = [f"{f['path']}.{o['value']}" for f in every_field() if f["kind"] in ("choice", "multichoice")
                and f["path"] != "ui.language" for o in f["options"] if f"{f['path']}.{o['value']}" not in choices]
    assert no_label == []


def test_help_comes_from_the_config_template():
    assert "0 — в день списания" in settings.help_text("reminders.days_before")
    assert settings.help_text("reminders.time") == ""            # "Во сколько." only repeats the label
    parsed = settings.parse_template_help("# Header.\n[a]\n# Explains x:\n#   x = 1\nx = 2\n# ---\ny = 1\n")
    assert parsed == {"a": "Header."}   # an explanation made only of an example is dropped


def test_language_is_a_choice_of_installed_catalogs():
    field = settings.field("ui.language", LoadedConfig(Config(), path=None, exists=False))  # type: ignore[arg-type]
    assert field["kind"] == "choice" and {o["value"] for o in field["options"]} >= {"ru", "en"}


# ------------------------------------------------------------ QML plugin


def qml_files() -> list[Path]:
    return sorted(p for p in PLUGIN.rglob("*") if p.suffix in (".qml", ".js") and p.name != "Env.js")


def test_plugin_has_no_hardcoded_text():
    bad = [f"{p.relative_to(PLUGIN)}:{n}" for p in qml_files()
           for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if CYRILLIC.search(line)]
    assert bad == []


def test_plugin_strings_exist_and_are_used():
    used = set()
    dynamic = ("page_", "sub_", "filter_", "nav_")
    for path in qml_files():
        used |= set(re.findall(r'\btr\("([a-z_]+)"\)', path.read_text(encoding="utf-8")))
    for lang in ("ru", "en"):
        ui = catalog(lang)["gui"]["ui"]
        assert sorted(k for k in used if k not in ui) == [], lang
    ui = catalog("ru")["gui"]["ui"]
    text = "\n".join(p.read_text(encoding="utf-8") for p in qml_files())
    unused = [k for k in ui if k not in used and not k.startswith(dynamic) and f'"{k}"' not in text]
    assert unused == []


def test_manifest_points_at_real_files():
    manifest = json.loads((PLUGIN / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == omarchy.PLUGIN_ID
    assert set(manifest["kinds"]) == {"bar-widget", "panel"}
    for entry in manifest["entryPoints"].values():
        assert (PLUGIN / entry).is_file()


SHELL_QML = """import QtQuick
import Quickshell
ShellRoot {
  Component.onCompleted: {
    var files = @FILES@
    for (var i = 0; i < files.length; i++) {
      var c = Qt.createComponent("file://@PLUGIN@/" + files[i])
      console.log("COMPILED", files[i], c.status === Component.Ready ? "ok" : c.errorString())
    }
    done.start()
  }
  Timer { id: done; interval: 50; onTriggered: Qt.quit() }
}
"""


@pytest.mark.skipif(not shutil.which("quickshell") or not Path("/usr/share/omarchy/shell/Ui").is_dir(),
                    reason="needs Quickshell and the Omarchy shell")
def test_every_qml_file_compiles(tmp_path):
    root = tmp_path / "shell"
    root.mkdir()
    for name in ("Commons", "Ui"):
        (root / name).symlink_to(Path("/usr/share/omarchy/shell") / name)
    plugin = tmp_path / "plugin"
    shutil.copytree(PLUGIN, plugin)
    (plugin / "Env.js").write_text('.pragma library\nvar exe = "true"\nvar cacheDir = "/nonexistent"\n',
                                   encoding="utf-8")
    files = [p.relative_to(plugin).as_posix() for p in plugin.rglob("*.qml")]
    (root / "shell.qml").write_text(SHELL_QML.replace("@FILES@", json.dumps(files)).replace("@PLUGIN@", str(plugin)),
                                    encoding="utf-8")

    env = {"QT_QPA_PLATFORM": "offscreen", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
           "XDG_RUNTIME_DIR": str(tmp_path)}
    proc = subprocess.run(["quickshell", "-p", str(root / "shell.qml")], capture_output=True, text=True,
                          timeout=90, env=env)
    out = proc.stdout + proc.stderr
    results = dict(re.findall(r"COMPILED (\S+) (.+)", out))
    assert set(results) == set(files), out[-2000:]
    # KeyboardPanel is a Wayland layer-shell surface; offscreen it cannot exist.
    wayland_only = "Type KeyboardPanel unavailable"
    assert {k: v for k, v in results.items() if v != "ok" and not v.endswith(wayland_only)} == {}


# --------------------------------------------------------- installation


@pytest.fixture
def plugin_shell(tmp_path, monkeypatch):
    fake_root = tmp_path / "omarchy-root"
    (fake_root / "shell" / "services").mkdir(parents=True)
    (fake_root / "shell" / "services" / "PluginRegistry.qml").write_text("// stub\n", encoding="utf-8")
    monkeypatch.setenv("OMARCHY_PATH", str(fake_root))
    shell = paths.config_home() / "omarchy" / "shell.json"
    shell.parent.mkdir(parents=True)
    layout = {"left": [{"id": "omarchy.menu"}],
              "center": [{"id": "omarchy.clock"}, {"id": "subwatch", "type": "command", "exec": "x"}],
              "right": [{"id": "omarchy.audio"}]}
    shell.write_text(json.dumps({"version": 1, "bar": {"layout": layout}}, indent=2), encoding="utf-8")
    return shell


def test_widget_replaces_the_old_module_in_place(plugin_shell):
    step = omarchy.apply_bar(Config())
    assert step.status == "changed" and step.params["section"] == "center"
    layout = json.loads(plugin_shell.read_text(encoding="utf-8"))["bar"]["layout"]
    assert layout["center"] == [{"id": "omarchy.clock"}, {"id": "noxqd.subwatch"}]
    target = omarchy.plugin_dir()
    assert (target / "manifest.json").is_file() and (target / "pages" / "SettingsPage.qml").is_file()
    env = (target / "Env.js").read_text(encoding="utf-8")
    assert "var exe = " in env and str(paths.cache_dir()) in env
    assert omarchy.plugin_installed() and omarchy.plugin_current()
    assert omarchy.apply_bar(Config()).status == "unchanged"


def test_widget_files_are_kept_current(plugin_shell):
    omarchy.apply_bar(Config())
    target = omarchy.plugin_dir()
    (target / "PopupContent.qml").write_text("// edited\n", encoding="utf-8")
    (target / "Leftover.qml").write_text("// old\n", encoding="utf-8")
    assert not omarchy.plugin_current()
    step = omarchy.apply_bar(Config())
    assert step.status == "changed" and step.key == "integrate.plugin.updated"
    assert not (target / "Leftover.qml").exists() and omarchy.plugin_current()


def test_widget_goes_to_the_configured_section_and_comes_off_cleanly(plugin_shell):
    data = json.loads(plugin_shell.read_text(encoding="utf-8"))
    data["bar"]["layout"]["center"].pop()
    plugin_shell.write_text(json.dumps(data, indent=2), encoding="utf-8")
    original = json.loads(plugin_shell.read_text(encoding="utf-8"))
    omarchy.apply_bar(Config.model_validate({"bar": {"section": "left"}}))
    layout = json.loads(plugin_shell.read_text(encoding="utf-8"))["bar"]["layout"]
    assert layout["left"][0] == {"id": "noxqd.subwatch"}
    assert omarchy.remove_bar().status == "removed"
    assert json.loads(plugin_shell.read_text(encoding="utf-8")) == original
    assert not omarchy.plugin_dir().exists()


def test_someone_elses_plugin_is_not_overwritten(plugin_shell):
    target = omarchy.plugin_dir()
    target.mkdir(parents=True)
    (target / "manifest.json").write_text('{"id": "someone.else"}', encoding="utf-8")
    assert omarchy.apply_bar(Config()).status == "failed"
    assert json.loads((target / "manifest.json").read_text(encoding="utf-8"))["id"] == "someone.else"


def test_doctor_checks_the_widget(plugin_shell):
    from subwatch.doctor import check_integration

    def status():
        return next(c for c in check_integration(Config()) if c.key.startswith("doctor.int.plugin"))

    assert status().key == "doctor.int.plugin_missing" and status().fix is not None
    assert status().fix()
    assert status().key == "doctor.int.plugin_ok"
    (omarchy.plugin_dir() / "Popup.qml").write_text("// stale\n", encoding="utf-8")
    assert status().key == "doctor.int.plugin_stale"


def test_settings_command_falls_back_to_the_tui(monkeypatch, ctx):
    calls = []
    monkeypatch.setattr(omarchy, "plugin_installed", lambda: False)
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: calls.append(args))
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/" + name if name == "xdg-terminal-exec" else None)
    ctx.close()
    cli("settings", "reminders")
    assert calls and calls[0][0] == "xdg-terminal-exec" and calls[0][-1] == "tui"
