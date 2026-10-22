"""Textual TUI.

Three tabs: subscriptions (with a details pane), the review queue and
charts. Every action has a binding id; the keys come from [ui.keys] and are
applied with App.set_keymap, so changing config.toml rebinds keys on the fly.
"""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from typing import Any

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Input, Static, TabbedContent, TabPane

from .. import barcache, clock
from ..analysis import budget_status, monthly_spend, totals
from ..app import AppContext
from ..config.loader import ConfigWatcher
from ..config.schema import UIKeys
from ..fmt import format_date, format_money, format_period, format_when
from ..i18n import t, tn
from ..models import Subscription, service_key
from . import charts
from .screens import ConfirmScreen, FilterScreen, FormScreen, HelpScreen
from .theme import build_theme, palette_mtime

ACTIONS = [
    # (binding id / [ui.keys] field, action, show in footer)
    ("down", "cursor('down')", False),
    ("up", "cursor('up')", False),
    ("top", "cursor('top')", False),
    ("bottom", "cursor('bottom')", False),
    ("page_down", "cursor('page_down')", False),
    ("page_up", "cursor('page_up')", False),
    ("open", "open_item", False),
    ("back", "back", False),
    ("search", "search", True),
    ("filter", "filter", True),
    ("sort", "sort", True),
    ("reverse", "reverse", False),
    ("add", "add", True),
    ("edit", "edit", True),
    ("delete", "delete", False),
    ("cancel", "cancel_sub", True),
    ("used", "used", False),
    ("subscriptions", "tab('subs')", False),
    ("review", "tab('review')", True),
    ("charts", "tab('charts')", True),
    ("confirm", "confirm_review", False),
    ("reject", "reject_review", False),
    ("rescan", "rescan", True),
    ("config", "open_config", False),
    ("help", "help", True),
    ("quit", "quit", True),
]

SORTS = ("next_charge", "amount", "monthly", "name", "category", "status")

CSS = """
Screen { layout: vertical; }
#subs-row, #review-row { height: 1fr; }
DataTable { width: 2fr; height: 1fr; }
.details { width: 1fr; min-width: 34; max-width: 64; height: 1fr; border-left: tall $panel; padding: 0 1; }
#status-line { height: 1; padding: 0 1; color: $text-muted; }
#search { dock: bottom; display: none; }
#search.visible { display: block; }
#charts-body { padding: 1 2; }
#dialog { width: 64; height: auto; padding: 1 2; border: thick $primary; background: $surface; }
#question { margin-bottom: 1; text-style: bold; }
#buttons { height: auto; margin-top: 1; align-horizontal: right; }
#buttons Button { margin-left: 1; }
FormScreen, ConfirmScreen, FilterScreen, HelpScreen { align: center middle; }
#form { width: 84; height: auto; max-height: 90%; padding: 1 2; border: thick $primary; background: $surface; }
#form-title { text-style: bold; margin-bottom: 1; }
#form-grid { grid-size: 2; grid-columns: 20 1fr; grid-gutter: 0 1; height: auto; }
#form-grid Label { padding-top: 1; }
#form-error { color: $error; height: auto; margin-top: 1; }
#help { width: 72; height: auto; max-height: 90%; padding: 1 2; border: thick $primary; background: $surface; }
"""


class DetailsPane(VerticalScroll):
    """Scrolls with the mouse but never takes keyboard focus."""

    can_focus = False


KEY_LABELS = {
    "down": "↓", "up": "↑", "left": "←", "right": "→", "slash": "/", "question_mark": "?",
    "comma": ",", "full_stop": ".", "escape": "Esc", "enter": "Enter", "home": "Home", "end": "End",
    "pagedown": "PgDn", "pageup": "PgUp", "space": "Space", "tab": "Tab", "delete": "Del",
}


def key_label(keys: str) -> str:
    out = []
    for key in keys.split(","):
        key = key.strip()
        parts = key.split("+")
        parts = [p.capitalize() if p in ("ctrl", "shift", "alt", "super") else KEY_LABELS.get(p, p) for p in parts]
        out.append("+".join(parts))
    return ", ".join(out)


class SubwatchApp(App):
    CSS = CSS
    ENABLE_COMMAND_PALETTE = False
    TITLE = "Subwatch"

    BINDINGS = [
        Binding(getattr(UIKeys(), key), action, t(f"tui.keys.{key}"), show=show, id=f"subwatch.{key}")
        for key, action, show in ACTIONS
    ]

    def __init__(self, ctx: AppContext, start: str | None = None):
        super().__init__()
        self.ctx = ctx
        self.start = start
        self.watcher = ConfigWatcher(ctx.loaded)
        self.sort_key = ctx.config.ui.default_sort
        self.sort_reverse = ctx.config.ui.sort_reverse
        self.search_text = ""
        self.filter_category: str | None = None
        self.filter_status: str | None = None
        self.subs: list[Subscription] = []
        self.review: list[Subscription] = []
        self._db_stamp = 0.0
        self._theme_stamp = 0.0
        self._config_error_shown = False

    # -------------------------------------------------------------- layout

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with TabbedContent(initial="subs", id="tabs"):
            with TabPane(t("tui.tab.subs"), id="subs"):
                yield Static("", id="status-line")
                with Horizontal(id="subs-row"):
                    yield DataTable(id="subs-table", cursor_type="row", zebra_stripes=True)
                    with DetailsPane(classes="details"):
                        yield Static("", id="subs-details")
            with TabPane(t("tui.tab.review"), id="review"), Horizontal(id="review-row"):
                yield DataTable(id="review-table", cursor_type="row", zebra_stripes=True)
                with DetailsPane(classes="details"):
                    yield Static("", id="review-details")
            with TabPane(t("tui.tab.charts"), id="charts"), VerticalScroll(id="charts-scroll"):
                yield Static("", id="charts-body")
        yield Input(placeholder=t("tui.search_placeholder"), id="search", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        self.apply_config(first=True)
        self.reload_data()
        self.query_one("#subs-table", DataTable).focus()
        if self.start == "add":
            self.call_after_refresh(self.action_add)
        elif self.start == "review":
            self.call_after_refresh(lambda: self.action_tab("review"))
        self.set_interval(self.ctx.config.ui.reload_interval, self.poll_changes)

    # -------------------------------------------------------- live reload

    def apply_config(self, first: bool = False) -> None:
        cfg = self.ctx.config
        keymap = {f"subwatch.{key}": getattr(cfg.ui.keys, key) for key, _, _ in ACTIONS}
        self.set_keymap(keymap)
        theme, name = build_theme(cfg)
        if theme is not None:
            self.register_theme(theme)
        try:
            self.theme = name
        except Exception:  # unknown theme name in config
            self.theme = "textual-dark"
            if first:
                self.notify(t("tui.bad_theme", name=name), severity="warning")
        self._theme_stamp = palette_mtime()

    def poll_changes(self) -> None:
        fresh = self.watcher.poll()
        if fresh is not None:
            self.ctx.reload(fresh)
            self.apply_config()
            self.reload_data()
            self.notify(t("tui.config_reloaded"))
            self._config_error_shown = False
        elif self.watcher.last_error is not None and not self._config_error_shown:
            self._config_error_shown = True
            self.notify(self.watcher.last_error.render(), severity="error", timeout=10)
        if palette_mtime() != self._theme_stamp:
            self.apply_config()
        stamp = barcache._stamp(self.ctx.db_path)
        if stamp != self._db_stamp:
            self.reload_data()

    # ---------------------------------------------------------------- data

    def reload_data(self) -> None:
        store = self.ctx.store
        cfg = self.ctx.config
        self._db_stamp = barcache._stamp(self.ctx.db_path)
        self.subs = store.subscriptions(include_cancelled=True)
        self.review = [s for s in self.subs if s.status == "review"]
        self.rates = self.ctx.rates()
        tot = totals(self.subs, self.rates, cfg)
        self.sub_title = t("tui.subtitle", total=format_money(tot.monthly, cfg.currency.base, decimals=0),
                           count=tn("fmt.units.subscription", tot.count))
        self.refresh_subs()
        self.refresh_review()
        self.refresh_charts(tot)
        tabs = self.query_one("#tabs", TabbedContent)
        tabs.get_tab("review").label = t("tui.tab.review_count", count=len(self.review)) if self.review \
            else t("tui.tab.review")

    def visible_subs(self) -> list[Subscription]:
        cfg = self.ctx.config
        items = [s for s in self.subs if s.status != "review"]
        if not cfg.ui.show_cancelled and self.filter_status != "cancelled":
            items = [s for s in items if s.status != "cancelled"]
        if self.filter_category:
            items = [s for s in items if s.category == self.filter_category]
        if self.filter_status:
            items = [s for s in items if s.status == self.filter_status]
        if self.search_text:
            needle = self.search_text.casefold()
            items = [s for s in items if needle in s.service.casefold() or needle in " ".join(s.tags).casefold()]
        from ..cli.main import sort_subscriptions

        return sort_subscriptions(items, self.sort_key, self.sort_reverse, self.rates)

    def _fill(self, table: DataTable, subs: list[Subscription]) -> None:
        cfg = self.ctx.config
        keep = None
        if table.row_count and table.cursor_row is not None:
            try:
                keep = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
            except Exception:
                keep = None
        table.clear(columns=True)
        for col in ("service", "amount", "period", "next", "category", "status"):
            table.add_column(t(f"table.{col}"), key=col)
        today = clock.today()
        for s in subs:
            nxt = Text(format_when(s.next_charge, cfg.ui.date_style) if s.next_charge else "—")
            if s.next_charge and (s.next_charge - today).days <= 1:
                nxt.stylize("bold")
            status = t(f"status.{s.status}") + (" " + t("status.trial_mark") if s.is_trial else "")
            table.add_row(
                Text(s.service),
                Text(format_money(s.amount, s.currency, cfg.ui.money_decimals) if s.amount is not None else "—",
                     justify="right"),
                format_period(s.period),
                nxt,
                f"{cfg.category_icon(s.category)} {cfg.category_name(s.category)}",
                status,
                key=str(s.id),
            )
        if keep is not None:
            try:
                table.move_cursor(row=table.get_row_index(keep))
            except Exception:
                pass

    def refresh_subs(self) -> None:
        table = self.query_one("#subs-table", DataTable)
        items = self.visible_subs()
        self._fill(table, items)
        parts = [t("tui.status.sort", field=t(f"tui.sort.{self.sort_key}"),
                   direction=t("tui.status.desc") if self.sort_reverse else t("tui.status.asc"))]
        if self.filter_category:
            parts.append(t("tui.status.category", name=self.ctx.config.category_name(self.filter_category)))
        if self.filter_status:
            parts.append(t("tui.status.status", name=t(f"status.{self.filter_status}")))
        if self.search_text:
            parts.append(t("tui.status.search", text=self.search_text))
        parts.append(tn("fmt.units.subscription", len(items)))
        self.query_one("#status-line", Static).update(Text(" · ".join(parts)))
        self.show_details(self.current_sub("subs-table"), "#subs-details")
        if not items:
            self.query_one("#subs-details", Static).update(Text(t("tui.empty")))

    def refresh_review(self) -> None:
        table = self.query_one("#review-table", DataTable)
        self._fill(table, self.review)
        details = self.query_one("#review-details", Static)
        if not self.review:
            details.update(Text(t("tui.review.empty")))
        else:
            self.show_details(self.current_sub("review-table"), "#review-details", review=True)

    def refresh_charts(self, tot) -> None:
        cfg = self.ctx.config
        history = monthly_spend(self.ctx.store, self.subs, self.rates, cfg, months_back=11, months_ahead=3)
        body = "\n\n".join([
            charts.monthly(history, cfg),
            charts.by_category(tot.by_category, cfg),
            charts.budgets(budget_status(tot, cfg), cfg),
        ])
        self.query_one("#charts-body", Static).update(body)

    def current_sub(self, table_id: str) -> Subscription | None:
        table = self.query_one(f"#{table_id}", DataTable)
        if not table.row_count:
            return None
        try:
            key = table.coordinate_to_cell_key((table.cursor_row, 0)).row_key.value
        except Exception:
            return None
        return next((s for s in self.subs if str(s.id) == key), None)

    def show_details(self, sub: Subscription | None, target: str, review: bool = False) -> None:
        widget = self.query_one(target, Static)
        if sub is None:
            widget.update("")
            return
        cfg = self.ctx.config
        monthly = self.rates.convert(sub.monthly_amount, sub.currency) if sub.monthly_amount is not None else None
        def row(label_key: str, value: str) -> str:
            return f"{escape(t(label_key))}: {escape(value)}"

        def money(amount, currency) -> str:
            return format_money(amount, currency) if amount is not None else "—"

        source = t("source." + sub.source) if not sub.source.startswith("plugin") else sub.source
        rows = [
            f"[b]{escape(sub.service)}[/b]",
            "",
            row("details.amount", money(sub.amount, sub.currency)),
            row("details.period", format_period(sub.period)),
            row("details.monthly", money(monthly, cfg.currency.base)),
            row("details.next", format_when(sub.next_charge) if sub.next_charge else "—"),
            row("details.last", format_date(sub.last_charge) if sub.last_charge else "—"),
            row("details.category", cfg.category_name(sub.category)),
            row("details.status", t("status." + sub.status)),
            row("details.source", source),
            row("details.confidence", f"{round(sub.confidence * 100)} %"),
        ]
        if sub.tags:
            rows.append(f"{escape(t('details.tags'))}: {escape(', '.join(sub.tags))}")
        if sub.trial_until:
            rows.append(f"[$warning]{escape(t('details.trial'))}: {escape(format_when(sub.trial_until))}[/]")
        if sub.previous_amount is not None:
            rows.append("[$warning]" + escape(t("details.price_change_value",
                        old=format_money(sub.previous_amount, sub.currency),
                        new=format_money(sub.amount, sub.currency),
                        date=format_date(sub.price_changed_at))) + "[/]")
        if sub.track_usage:
            rows.append(row("details.last_used", format_date(sub.last_used) if sub.last_used else "—"))
        if sub.cancel_url:
            rows.append(f"{escape(t('details.cancel_url'))}: {escape(sub.cancel_url)}")
        if sub.notes:
            rows.append(f"{escape(t('details.notes'))}: {escape(sub.notes)}")
        charges = self.ctx.store.charges(sub.id)
        if charges:
            rows += ["", f"[b]{escape(t('details.history'))}[/b]"]
            for c in charges[-6:]:
                rows.append(escape(f"{format_date(c.date)} — {format_money(c.amount, c.currency)}"))
        if review:
            reasons = ", ".join(t(f"review.reason.{r}") for r in (sub.review_reason or "low_confidence").split(","))
            rows += ["", f"[$warning]{escape(t('tui.review.why', reasons=reasons))}[/]", "",
                     escape(t("tui.review.keys", confirm=self.ctx.config.ui.keys.confirm.split(",")[0],
                              reject=self.ctx.config.ui.keys.reject.split(",")[0]))]
        widget.update("\n".join(rows))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "subs-table":
            self.action_edit()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "subs-table":
            self.show_details(self.current_sub("subs-table"), "#subs-details")
        elif event.data_table.id == "review-table":
            self.show_details(self.current_sub("review-table"), "#review-details", review=True)

    # ------------------------------------------------------------- helpers

    def active_tab(self) -> str:
        return self.query_one("#tabs", TabbedContent).active

    def active_table(self) -> DataTable | None:
        tab = self.active_tab()
        if tab == "subs":
            return self.query_one("#subs-table", DataTable)
        if tab == "review":
            return self.query_one("#review-table", DataTable)
        return None

    def selected(self) -> Subscription | None:
        tab = self.active_tab()
        if tab == "subs":
            return self.current_sub("subs-table")
        if tab == "review":
            return self.current_sub("review-table")
        return None

    def changed(self) -> None:
        self.ctx.after_change()
        self.reload_data()

    def validate_form(self, values: dict[str, Any]) -> None:
        from ..cli.main import parse_user_amount, parse_user_date, parse_user_period

        if values["amount"]:
            parse_user_amount(values["amount"], values["currency"] or self.ctx.config.currency.base)
        parse_user_period(values["period"] or "1m")
        if values["next"]:
            parse_user_date(values["next"])

    def _apply_form(self, sub: Subscription, values: dict[str, Any]) -> Subscription:
        from ..cli.main import parse_user_amount, parse_user_date, parse_user_period

        cfg = self.ctx.config
        before = sub.service
        sub.service = values["service"]
        if values["amount"]:
            sub.amount, code = parse_user_amount(values["amount"], (values["currency"] or cfg.currency.base).upper())
            sub.currency = (values["currency"] or code).upper()
        else:
            sub.amount = None
            sub.currency = (values["currency"] or "").upper() or None
        sub.period = parse_user_period(values["period"] or "1m")
        sub.next_charge = parse_user_date(values["next"]) if values["next"] else None
        if sub.next_charge:
            sub.anchor_day = sub.next_charge.day
        if values["category"] != sub.category:
            self.ctx.store.add_rule("category", service_key(sub.service), values["category"])
        sub.category = values["category"]
        sub.tags = [x.strip() for x in values["tags"].split(",") if x.strip()]
        sub.cancel_url = values["cancel_url"] or None
        sub.notes = values["notes"] or None
        if values.get("status"):
            sub.status = values["status"]
        if values["track_usage"] and not sub.track_usage:
            sub.last_used = sub.last_used or clock.today()
        sub.track_usage = values["track_usage"]
        if before and service_key(before) != service_key(sub.service):
            self.ctx.store.add_rule("alias", service_key(before), sub.service)
        sub.key = sub.make_key()
        return sub

    # ------------------------------------------------------------- actions

    def action_cursor(self, where: str) -> None:
        table = self.active_table()
        if table is None:
            return
        {
            "down": table.action_cursor_down,
            "up": table.action_cursor_up,
            "top": table.action_scroll_top,
            "bottom": table.action_scroll_bottom,
            "page_down": table.action_page_down,
            "page_up": table.action_page_up,
        }[where]()

    def action_open_item(self) -> None:
        if self.active_tab() == "review":
            return
        sub = self.selected()
        if sub is not None:
            self.action_edit()

    def action_back(self) -> None:
        search = self.query_one("#search", Input)
        if search.has_class("visible"):
            search.remove_class("visible")
            search.disabled = True
            self.query_one("#subs-table", DataTable).focus()
        elif self.search_text or self.filter_category or self.filter_status:
            self.search_text = ""
            self.filter_category = self.filter_status = None
            self.refresh_subs()

    def action_tab(self, name: str) -> None:
        self.query_one("#tabs", TabbedContent).active = name
        table = self.active_table()
        if table is not None:
            table.focus()
        else:
            self.query_one("#charts-scroll", VerticalScroll).focus()

    def action_search(self) -> None:
        self.action_tab("subs")
        search = self.query_one("#search", Input)
        search.disabled = False
        search.add_class("visible")
        search.value = self.search_text
        search.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search":
            self.search_text = event.value.strip()
            self.refresh_subs()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search":
            event.input.remove_class("visible")
            event.input.disabled = True
            self.query_one("#subs-table", DataTable).focus()

    def action_filter(self) -> None:
        def done(result) -> None:
            if result is not None:
                self.filter_category = result["category"]
                self.filter_status = result["status"]
                self.refresh_subs()

        self.push_screen(FilterScreen(self.ctx.config, self.filter_category, self.filter_status), done)

    def action_sort(self) -> None:
        i = SORTS.index(self.sort_key) if self.sort_key in SORTS else 0
        self.sort_key = SORTS[(i + 1) % len(SORTS)]
        self.refresh_subs()

    def action_reverse(self) -> None:
        self.sort_reverse = not self.sort_reverse
        self.refresh_subs()

    def action_add(self) -> None:
        def done(values) -> None:
            if not values:
                return
            sub = self._apply_form(Subscription(service=values["service"], source="manual"), values)
            existing = self.ctx.store.find_by_key(sub.key)
            if existing and existing.status != "cancelled":
                self.notify(t("cli.err.exists", service=sub.service, id=existing.id), severity="warning")
                return
            self.ctx.store.insert_subscription(sub)
            from ..hooks import run_hooks

            run_hooks(self.ctx.config, "new_subscription", sub, {"via": "tui"})
            self.notify(t("cli.add.done", service=sub.service, id=sub.id))
            self.changed()

        self.push_screen(FormScreen(self.ctx.config), done)

    def action_edit(self) -> None:
        sub = self.selected()
        if sub is None:
            return

        def done(values) -> None:
            if not values:
                return
            self.ctx.store.update_subscription(self._apply_form(sub, values))
            self.notify(t("cli.edit.done", service=sub.service))
            self.changed()

        self.push_screen(FormScreen(self.ctx.config, sub), done)

    def action_delete(self) -> None:
        sub = self.selected()
        if sub is None:
            return

        def done(yes: bool | None) -> None:
            if yes:
                self.ctx.store.delete_subscription(sub.id or 0)
                self.notify(t("cli.remove.done", service=sub.service))
                self.changed()

        self.push_screen(ConfirmScreen(t("cli.remove.confirm", service=sub.service)), done)

    def action_cancel_sub(self) -> None:
        sub = self.selected()
        if sub is None or sub.status == "cancelled":
            return

        def done(yes: bool | None) -> None:
            if not yes:
                return
            from ..hooks import run_hooks
            from ..reminders import open_url

            if sub.cancel_url:
                open_url(sub.cancel_url)
            sub.status = "cancelled"
            sub.cancelled_at = clock.now()
            sub.next_charge = None
            self.ctx.store.update_subscription(sub)
            run_hooks(self.ctx.config, "subscription_cancelled", sub, {"via": "tui"})
            self.notify(t("cli.cancel.done", service=sub.service))
            self.changed()

        question = t("tui.cancel_confirm_url", service=sub.service) if sub.cancel_url else \
            t("tui.cancel_confirm", service=sub.service)
        self.push_screen(ConfirmScreen(question), done)

    def action_used(self) -> None:
        sub = self.selected()
        if sub is None:
            return
        sub.track_usage = True
        sub.last_used = clock.today()
        self.ctx.store.update_subscription(sub)
        self.notify(t("cli.used.done", service=sub.service))
        self.reload_data()

    def _decide(self, accepted: bool) -> None:
        if self.active_tab() != "review":
            return
        sub = self.current_sub("review-table")
        if sub is None:
            return
        from ..cli.groups import _decide

        _decide(self.ctx, sub, accepted)
        key = "cli.review.confirmed" if accepted else "cli.review.rejected"
        self.notify(t(key, service=sub.service))
        self.reload_data()

    def action_confirm_review(self) -> None:
        self._decide(True)

    def action_reject_review(self) -> None:
        self._decide(False)

    def action_rescan(self) -> None:
        from ..integrate.systemd import unit_dir

        if (unit_dir() / "subwatch-scan.service").exists() and shutil.which("systemctl"):
            subprocess.Popen(["systemctl", "--user", "start", "--no-block", "subwatch-scan.service"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.notify(t("tui.rescan_started"))
            return
        self.notify(t("tui.rescan_started"))
        self.scan_in_thread()

    @work(thread=True, exclusive=True)
    def scan_in_thread(self) -> None:
        from ..errors import SubwatchError
        from ..scan import run_job

        ctx = AppContext(self.ctx.loaded, quiet_logs=True)
        try:
            report = run_job(ctx)
            message = t("tui.rescan_done", created=report.total("created") + report.total("promoted"),
                        review=report.total("review"))
            severity = "warning" if report.errors else "information"
        except SubwatchError as exc:
            message, severity = exc.message, "error"
        finally:
            ctx.close()
        self.call_from_thread(self.notify, message, severity=severity)
        self.call_from_thread(self.reload_data)

    def action_open_config(self) -> None:
        from .. import paths

        path = str(self.ctx.loaded.path)
        if shutil.which("omarchy-launch-editor"):
            subprocess.Popen(["omarchy-launch-editor", path], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import os

            editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
            with self.suspend():
                subprocess.run([editor, path], check=False)
        self.notify(t("tui.config_opened", path=paths.contract_home(path)))

    def action_help(self) -> None:
        keys = self.ctx.config.ui.keys
        rows = [(key_label(getattr(keys, key)), t(f"tui.keys.{key}")) for key, _, _ in ACTIONS]
        self.push_screen(HelpScreen(rows))

    def action_help_quit(self) -> None:
        self.notify(t("tui.how_to_quit", key=key_label(self.ctx.config.ui.keys.quit.split(",")[0])))


def run_tui(ctx: AppContext, start: str | None = None) -> None:
    from ..config.editor import ensure_config_file

    ensure_config_file(ctx.loaded.path)
    SubwatchApp(ctx, start).run()


def today() -> date:
    return clock.today()
