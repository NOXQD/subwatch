"""Desktop integration edits only Subwatch's own blocks and files."""

import json
import re
import subprocess
from pathlib import Path

import pytest

from subwatch import paths
from subwatch.config.schema import Config
from subwatch.integrate import apply_all, completion_source, hyprland, launchers, omarchy, remove_all, systemd

BINDS = [
    {"modmask": 64 | 4, "key": "S", "description": "Share"},
    {"modmask": 64, "key": "SPACE", "description": "Omarchy menu"},
    {"modmask": 64 | 4 | 8, "key": "D", "description": "Calendar"},
]

HYPR_LUA = """-- user config
dofile((os.getenv("OMARCHY_PATH") or "/usr/share/omarchy") .. "/default/hypr/bootstrap.lua")
require("default.hypr.omarchy")
require("hypr.bindings")
"""

MENU = """{
  // Extend the Quickshell Omarchy menu with JSONC.
  "personal": {"icon":"","label":"Personal"},
  "personal.notes": {"icon":"","label":"Notes","action":"omarchy-launch-editor ~/notes"}
}
"""

SHELL = {"version": 1, "bar": {"position": "top", "layout": {
    "left": [{"id": "omarchy.menu"}], "center": [{"id": "omarchy.clock", "format": "HH:mm"}],
    "right": [{"id": "omarchy.audio"}, {"id": "omarchy.power"}]}}, "idle": {"lock": 600}}


def omarchy_parser_ok(text: str) -> bool:
    """The exact rules of MenuModel.stripJsonc in the Omarchy shell."""
    stripped = re.sub(r"^\s*//[^\n]*(\n|$)", "", text, flags=re.M)
    stripped = re.sub(r",(\s*[}\]])", r"\1", stripped)
    json.loads(stripped)
    return True


@pytest.fixture
def desktop(monkeypatch, tmp_path):
    hypr = paths.config_home() / "hypr"
    hypr.mkdir(parents=True)
    (hypr / "hyprland.lua").write_text(HYPR_LUA, encoding="utf-8")
    ext = paths.config_home() / "omarchy" / "extensions"
    ext.mkdir(parents=True)
    (ext / "omarchy-menu.jsonc").write_text(MENU, encoding="utf-8")
    (paths.config_home() / "omarchy" / "shell.json").write_text(json.dumps(SHELL, indent=2), encoding="utf-8")
    fake_root = tmp_path / "omarchy-root"
    (fake_root / "shell").mkdir(parents=True)
    monkeypatch.setenv("OMARCHY_PATH", str(fake_root))
    monkeypatch.setattr(systemd, "systemd_available", lambda: False)
    monkeypatch.setattr(hyprland, "current_binds", lambda: BINDS)
    return hypr


def test_parse_combo():
    c = hyprland.parse_combo("super + ctrl + u")
    assert c.mods == 64 | 4 and c.key == "U" and str(c) == "SUPER + CTRL + U"
    with pytest.raises(hyprland.KeyError_):
        hyprland.parse_combo("HYPER + U")


def test_conflicts_are_skipped_or_overridden(desktop):
    cfg = Config.model_validate({"keybinds": {"open_tui": "SUPER + CTRL + S", "menu": "SUPER + CTRL + SHIFT + U"}})
    steps = hyprland.apply(cfg, reload=False)
    lua = (desktop / "subwatch.lua").read_text(encoding="utf-8")
    assert '"SUPER + CTRL + S"' not in lua and '"SUPER + CTRL + SHIFT + U"' in lua
    assert any(s.key == "integrate.keys.conflict" and "Share" in s.params["what"] for s in steps)
    forced = Config.model_validate({"keybinds": {"open_tui": "SUPER + CTRL + S", "override_conflicts": True}})
    hyprland.apply(forced, reload=False)
    lua = (desktop / "subwatch.lua").read_text(encoding="utf-8")
    assert 'hl.unbind("SUPER + CTRL + S")' in lua and 'o.bind("SUPER + CTRL + S", "Subwatch: открыть"' in lua


def test_keybinds_from_config_and_empty_means_none(desktop):
    cfg = Config.model_validate({"keybinds": {"open_tui": "SUPER + ALT + Y", "upcoming": "", "menu": "",
                                              "rescan": "SUPER + ALT + SHIFT + Y"}})
    hyprland.apply(cfg, reload=False)
    lua = (desktop / "subwatch.lua").read_text(encoding="utf-8")
    assert lua.count("o.bind(") == 2 and "subwatch-scan.service" in lua and "upcoming" not in lua


def test_include_block_is_idempotent_and_removable(desktop):
    apply_all(Config(), only=["keybinds"])
    apply_all(Config(), only=["keybinds"])
    text = (desktop / "hyprland.lua").read_text(encoding="utf-8")
    assert text.count(">>> subwatch >>>") == 1
    assert 'require("hypr.subwatch")' in text and 'package.searchpath("hypr.subwatch"' in text
    assert text.startswith(HYPR_LUA.rstrip("\n"))
    remove_all(only=["keybinds"])
    assert (desktop / "hyprland.lua").read_text(encoding="utf-8").strip() == HYPR_LUA.strip()
    assert not (desktop / "subwatch.lua").exists()


def test_lua_is_syntactically_sane(desktop):
    apply_all(Config(), only=["keybinds"])
    lua = (desktop / "subwatch.lua").read_text(encoding="utf-8")
    for line in lua.splitlines():
        if line.startswith("o.bind("):
            assert re.fullmatch(r'o\.bind\("[^"]+", "[^"]+", "[^"]+"\)', line), line


def test_legacy_hyprland_conf(desktop):
    (desktop / "hyprland.lua").unlink()
    (desktop / "hyprland.conf").write_text("source = ~/.config/hypr/bindings.conf\n", encoding="utf-8")
    hyprland.apply(Config(), reload=False)
    conf = (desktop / "subwatch.conf").read_text(encoding="utf-8")
    assert "bindd = SUPER CTRL, U, Subwatch: открыть, exec," in conf
    assert "source = ~/.config/hypr/subwatch.conf" in (desktop / "hyprland.conf").read_text(encoding="utf-8")


def test_menu_block(desktop):
    menu = paths.config_home() / "omarchy" / "extensions" / "omarchy-menu.jsonc"
    step = omarchy.apply_menu(Config())
    assert step.status == "changed"
    text = menu.read_text(encoding="utf-8")
    assert omarchy_parser_ok(text)
    data = json.loads(re.sub(r",(\s*[}\]])", r"\1", re.sub(r"^\s*//[^\n]*(\n|$)", "", text, flags=re.M)))
    assert data["subwatch.upcoming"]["label"] == "Ближайшие списания"
    assert data["personal.notes"]["label"] == "Notes"
    assert omarchy.apply_menu(Config()).status == "unchanged"
    omarchy.remove_menu()
    assert omarchy_parser_ok(menu.read_text(encoding="utf-8"))
    assert "subwatch" not in menu.read_text(encoding="utf-8")


def test_menu_created_when_missing(desktop):
    menu = paths.config_home() / "omarchy" / "extensions" / "omarchy-menu.jsonc"
    menu.unlink()
    omarchy.apply_menu(Config())
    assert omarchy_parser_ok(menu.read_text(encoding="utf-8"))


def test_menu_disabled_in_config(desktop):
    omarchy.apply_menu(Config())
    omarchy.apply_menu(Config.model_validate({"menu": {"enabled": False}}))
    assert not omarchy.menu_installed()


def test_bar_module(desktop):
    shell = paths.config_home() / "omarchy" / "shell.json"
    cfg = Config.model_validate({"bar": {"interval": 120, "section": "center"}})
    assert omarchy.apply_bar(cfg).status == "changed"
    data = json.loads(shell.read_text(encoding="utf-8"))
    entry = data["bar"]["layout"]["center"][0]
    assert entry["type"] == "command" and entry["exec"].endswith("subwatch bar") and entry["interval"] == 120
    assert data["idle"] == {"lock": 600} and data["bar"]["layout"]["right"] == SHELL["bar"]["layout"]["right"]
    assert omarchy.apply_bar(cfg).status == "unchanged"
    data["bar"]["layout"]["center"][0]["custom"] = "kept"
    shell.write_text(json.dumps(data), encoding="utf-8")
    omarchy.apply_bar(Config.model_validate({"bar": {"interval": 60}}))
    entry = json.loads(shell.read_text(encoding="utf-8"))["bar"]["layout"]["center"][0]
    assert entry["interval"] == 60 and entry["custom"] == "kept"
    omarchy.remove_bar()
    assert json.loads(shell.read_text(encoding="utf-8")) == SHELL


def test_backups_are_made(desktop):
    omarchy.apply_bar(Config())
    backups = list((paths.config_home() / "omarchy").glob("shell.json.subwatch-bak.*"))
    assert backups


def test_systemd_units_follow_config(tmp_path):
    cfg = Config.model_validate({"scan": {"schedule": "*-*-* 07:30", "nice": 15, "io_class": "best-effort",
                                          "randomized_delay": "2m", "persistent": False},
                                 "reminders": {"check_interval": "5m"}})
    units = systemd.render(cfg)
    assert "OnCalendar=*-*-* 07:30" in units["subwatch-scan.timer"]
    assert "RandomizedDelaySec=2m" in units["subwatch-scan.timer"] and "Persistent=false" in units["subwatch-scan.timer"]
    assert "Nice=15" in units["subwatch-scan.service"] and "IOSchedulingClass=best-effort" in units["subwatch-scan.service"]
    assert "OnCalendar=*:0/5:00" in units["subwatch-remind.timer"]
    hourly = systemd.render(Config.model_validate({"scan": {"schedule": "6h"}, "reminders": {"check_interval": "2h"}}))
    assert "OnUnitActiveSec=6h" in hourly["subwatch-scan.timer"]
    assert "OnCalendar=0/2:00:00" in hourly["subwatch-remind.timer"]
    assert "ExecStart=" in units["subwatch-scan.service"] and "--quiet scan" in units["subwatch-scan.service"]


def test_systemd_apply_with_fake_systemctl(monkeypatch):
    calls = []
    monkeypatch.setattr(systemd, "systemd_available", lambda: True)
    monkeypatch.setattr(systemd, "_systemctl", lambda *a: calls.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    systemd.apply(Config())
    assert ("daemon-reload",) in calls and ("enable", "--now", "subwatch-scan.timer") in calls
    for name in systemd.UNITS:
        assert (systemd.unit_dir() / name).exists()
    calls.clear()
    systemd.apply(Config())
    assert ("daemon-reload",) not in calls
    systemd.remove()
    assert ("disable", "--now", "subwatch-remind.timer") in calls
    assert not any((systemd.unit_dir() / n).exists() for n in systemd.UNITS)


def test_config_set_rewrites_timer(monkeypatch, capsys):
    from subwatch.__main__ import main

    monkeypatch.setattr(systemd, "systemd_available", lambda: False)
    systemd.apply(Config())
    try:
        main(["config", "set", "scan.schedule", "Mon..Fri 08:30"])
    except SystemExit:
        pass
    assert "OnCalendar=Mon..Fri 08:30" in (systemd.unit_dir() / "subwatch-scan.timer").read_text()


def test_desktop_entry_and_elephant(monkeypatch):
    launchers.apply()
    entry = launchers.desktop_file().read_text(encoding="utf-8")
    assert "Name=Subwatch" in entry and "[Desktop Action upcoming]" in entry and "Name=Ближайшие списания" in entry
    assert not launchers.elephant_file().exists()
    monkeypatch.setattr(launchers, "walker_present", lambda: True)
    launchers.apply()
    import tomllib

    data = tomllib.loads(launchers.elephant_file().read_text(encoding="utf-8"))
    assert data["name"] == "subwatch" and data["entries"][0]["text"] == "Ближайшие списания"


def test_waybar_insertion(monkeypatch):
    wb = paths.config_home() / "waybar"
    wb.mkdir(parents=True)
    cfg = wb / "config.jsonc"
    cfg.write_text('{\n  // my bar\n  "layer": "top",\n  "modules-right": ["clock", "battery"],\n}\n', encoding="utf-8")
    monkeypatch.setattr(launchers, "waybar_present", lambda: True)
    launchers.apply_waybar()
    text = cfg.read_text(encoding="utf-8")
    assert '"modules-right": ["custom/subwatch", "clock", "battery"]' in text
    assert '"include": ["~/.config/waybar/subwatch.jsonc"]' in text and "// my bar" in text
    module = (wb / "subwatch.jsonc").read_text(encoding="utf-8")
    assert '"return-type": "json"' in module
    launchers.apply_waybar()
    assert cfg.read_text(encoding="utf-8").count("custom/subwatch") == 1
    launchers.remove_waybar()
    assert "subwatch" not in cfg.read_text(encoding="utf-8")


def test_completion_scripts():
    bash = completion_source("bash")
    assert "_SUBWATCH_COMPLETE" in bash and "complete" in bash
    assert "compdef" in completion_source("zsh")
    assert "complete" in completion_source("fish")


def test_post_update_hook_script(desktop):
    omarchy.apply_hook()
    script = omarchy.hook_file()
    assert script.stat().st_mode & 0o111
    assert "--quiet integrate apply" in script.read_text(encoding="utf-8")


def test_full_apply_and_remove_leave_user_files_intact(desktop):
    before = {p: p.read_text(encoding="utf-8") for p in (desktop / "hyprland.lua",
                                                         paths.config_home() / "omarchy" / "extensions" / "omarchy-menu.jsonc")}
    steps = apply_all(Config())
    assert not [s for s in steps if s.status == "failed"]
    remove_all()
    for p, text in before.items():
        assert Path(p).read_text(encoding="utf-8").strip() == text.strip()


def _run_cli(args):
    from subwatch.__main__ import main

    try:
        main(args)
    except SystemExit as exc:
        return exc.code or 0
    return 0


def test_generated_commands_actually_run(monkeypatch):
    """Every command line we put into units and hooks must parse and succeed."""
    import shlex

    monkeypatch.setattr(systemd, "systemd_available", lambda: False)
    units = systemd.render(Config())
    commands = []
    for name in ("subwatch-scan.service", "subwatch-remind.service"):
        line = next(x for x in units[name].splitlines() if x.startswith("ExecStart="))
        commands.append(shlex.split(line.split("=", 1)[1])[1:])
    hook = omarchy.hook_script().splitlines()[-1]
    commands.append(shlex.split(hook.split("&&", 1)[1].split("||")[0])[1:])
    for args in commands:
        assert _run_cli(args) == 0, args


def test_block_stays_put_when_other_tools_add_theirs(desktop):
    """Another installer appends its block after ours: re-applying must not
    move ours to the end or pile up blank lines."""
    main = desktop / "hyprland.lua"
    hyprland.apply(Config(), binds=BINDS, reload=False)
    other = "\n-- >>> altscape >>>\nrequire(\"hypr.altscape\")\n-- <<< altscape <<<\n"
    main.write_text(main.read_text(encoding="utf-8") + other, encoding="utf-8")
    once = main.read_text(encoding="utf-8")
    for _ in range(3):
        steps = hyprland.apply(Config(), binds=BINDS, reload=False)
        assert all(s.key != "integrate.keys.include_added" for s in steps)
    assert main.read_text(encoding="utf-8") == once
    assert once.index(">>> subwatch >>>") < once.index(">>> altscape >>>")
    # Blank lines a previous version left above the block are tidied up.
    main.write_text(once.replace("\n-- >>> subwatch", "\n\n\n\n-- >>> subwatch"), encoding="utf-8")
    hyprland.apply(Config(), binds=BINDS, reload=False)
    assert "\n\n\n-- >>> subwatch" not in main.read_text(encoding="utf-8")
