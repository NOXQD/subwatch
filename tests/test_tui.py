"""TUI through Textual's pilot."""

import asyncio
import os
import time
from datetime import date
from decimal import Decimal

from conftest import write_config
from subwatch.app import AppContext
from subwatch.models import Subscription
from subwatch.period import Period
from subwatch.tui.app import SubwatchApp


def seed(ctx):
    for name, amount, nxt, status in (("Netflix", "3990", "2026-10-25", "active"),
                                      ("iCloud+", "1490", "2026-11-01", "active"),
                                      ("Мегадиск", "590", "2026-11-07", "review")):
        ctx.store.insert_subscription(Subscription(service=name, amount=Decimal(amount), currency="KZT",
                                                   period=Period("month", 1), next_charge=date.fromisoformat(nxt),
                                                   status=status, source="imap", confidence=0.5 if status == "review" else 1))


def run_app(test, start=None, config_text=None):
    if config_text:
        write_config(config_text)
    ctx = AppContext.load()
    seed(ctx)

    async def go():
        app = SubwatchApp(ctx, start)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await test(app, pilot)

    try:
        asyncio.run(go())
    finally:
        ctx.close()
    return ctx


def test_list_navigation_and_tabs():
    async def t(app, pilot):
        table = app.query_one("#subs-table")
        assert table.row_count == 2  # review item lives in its own tab
        await pilot.press("j")
        assert table.cursor_row == 1
        await pilot.press("k")
        assert table.cursor_row == 0
        await pilot.press("c")
        assert app.query_one("#tabs").active == "charts"
        await pilot.press("r")
        assert app.query_one("#tabs").active == "review"
        await pilot.press("1")
        assert app.query_one("#tabs").active == "subs"
    run_app(t)


def test_custom_keys_from_config():
    async def t(app, pilot):
        table = app.query_one("#subs-table")
        await pilot.press("j")
        assert table.cursor_row == 0  # j is no longer bound
        await pilot.press("ctrl+n")
        assert table.cursor_row == 1
    run_app(t, config_text='[ui.keys]\ndown = "ctrl+n"\n')


def test_hot_reload_rebinds_keys():
    async def t(app, pilot):
        from subwatch import paths

        path = paths.config_file()
        path.write_text('[ui.keys]\ndown = "ctrl+n"\n', encoding="utf-8")
        future = time.time() + 5
        os.utime(path, (future, future))
        app.poll_changes()
        await pilot.pause()
        table = app.query_one("#subs-table")
        await pilot.press("ctrl+n")
        assert table.cursor_row == 1
    run_app(t, config_text='[ui]\nreload_interval = 60\n')


def test_search_and_sort():
    async def t(app, pilot):
        await pilot.press("slash")
        await pilot.press(*"icl")
        await pilot.press("enter")
        assert app.query_one("#subs-table").row_count == 1
        await pilot.press("escape")
        assert app.query_one("#subs-table").row_count == 2
        await pilot.press("s")
        assert app.sort_key == "amount"
    run_app(t)


def test_review_confirm_with_keys():
    async def t(app, pilot):
        await pilot.press("r")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert app.review == []
        assert any(s.service == "Мегадиск" and s.status == "active" for s in app.subs)
    ctx = run_app(t)
    ctx2 = AppContext.load()
    assert ctx2.store.has_rule("accept_service", "мегадиск")
    ctx2.close()


def test_add_via_form():
    async def t(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        form = app.screen
        form.query_one("#service").value = "Okko"
        form.query_one("#amount").value = "399"
        form.query_one("#currency").value = "RUB"
        form.query_one("#next").value = "2026-11-03"
        form.action_save()
        await pilot.pause()
        assert any(s.service == "Okko" and s.amount == Decimal(399) for s in app.subs)
    run_app(t)


def test_form_validation_message():
    async def t(app, pilot):
        await pilot.press("a")
        await pilot.pause()
        form = app.screen
        form.query_one("#service").value = "Okko"
        form.query_one("#next").value = "когда-нибудь"
        form.action_save()
        await pilot.pause()
        assert "Не понял дату" in str(form.query_one("#form-error").render())
    run_app(t)


def test_omarchy_theme_colors(tmp_path, monkeypatch):
    from subwatch import paths

    theme_dir = paths.state_home() / "omarchy" / "current" / "theme"
    theme_dir.mkdir(parents=True)
    (theme_dir / "colors.toml").write_text('mode = "dark"\naccent = "#ff00aa"\nbackground = "#101010"\n'
                                           'foreground = "#eeeeee"\nred = "#ff0000"\n', encoding="utf-8")

    async def t(app, pilot):
        assert app.theme == "subwatch-omarchy"
        assert app.current_theme.primary == "#ff00aa"
    run_app(t)


def test_theme_override_from_config():
    async def t(app, pilot):
        assert app.theme == "nord"
    run_app(t, config_text='[ui]\ntheme = "nord"\n')


def test_help_screen_shows_symbols():
    async def t(app, pilot):
        await pilot.press("question_mark")
        await pilot.pause()
        text = str(app.screen.query_one("Static").render())
        assert "Esc" in text and "справка" in text
    run_app(t)
