"""Modal screens of the TUI."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from ..config.schema import Config
from ..i18n import t
from ..models import STATUSES, Subscription


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "answer(True)", show=False),
        Binding("n", "answer(False)", show=False),
        Binding("escape", "answer(False)", show=False),
    ]

    def __init__(self, question: str):
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.question, id="question")
            with Horizontal(id="buttons"):
                yield Button(t("tui.yes"), variant="error", id="yes")
                yield Button(t("tui.no"), variant="primary", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class FormScreen(ModalScreen[dict[str, Any] | None]):
    """Add or edit a subscription. Returns raw field values or None."""

    BINDINGS = [Binding("escape", "cancel", show=False), Binding("ctrl+s", "save", show=False)]

    def __init__(self, config: Config, sub: Subscription | None = None):
        super().__init__()
        self.config = config
        self.sub = sub

    def compose(self) -> ComposeResult:
        from ..fmt import format_number

        s = self.sub
        cats = [(c.name, key) for key, c in self.config.categories.items()]
        title = t("tui.form.edit_title", service=s.service) if s else t("tui.form.add_title")
        with VerticalScroll(id="form"):
            yield Static(title, id="form-title")
            with Grid(id="form-grid"):
                yield Label(t("tui.form.service"))
                yield Input(value=s.service if s else "", placeholder=t("tui.form.service_ph"), id="service")
                yield Label(t("tui.form.amount"))
                amount = format_number(s.amount, 2).replace(" ", " ") if s and s.amount is not None else ""
                yield Input(value=amount, placeholder=t("tui.form.amount_ph"), id="amount")
                yield Label(t("tui.form.currency"))
                yield Input(value=(s.currency if s and s.currency else self.config.currency.base),
                            placeholder=self.config.currency.base, id="currency", max_length=3)
                yield Label(t("tui.form.period"))
                yield Input(value=s.period.code if s else "1m", placeholder=t("tui.form.period_ph"), id="period")
                yield Label(t("tui.form.next"))
                yield Input(value=s.next_charge.isoformat() if s and s.next_charge else "",
                            placeholder=t("tui.form.next_ph"), id="next")
                yield Label(t("tui.form.category"))
                yield Select(cats, value=s.category if s else "other", allow_blank=False,
                             prompt=t("tui.form.category"), id="category")
                yield Label(t("tui.form.tags"))
                yield Input(value=", ".join(s.tags) if s else "", placeholder=t("tui.form.tags_ph"), id="tags")
                yield Label(t("tui.form.cancel_url"))
                yield Input(value=(s.cancel_url or "") if s else "", placeholder=t("tui.form.url_ph"), id="cancel_url")
                yield Label(t("tui.form.notes"))
                yield Input(value=(s.notes or "") if s else "", id="notes")
                if s:
                    yield Label(t("tui.form.status"))
                    yield Select([(t(f"status.{x}"), x) for x in STATUSES], value=s.status, allow_blank=False,
                                 prompt=t("tui.form.status"), id="status")
                yield Label("")
                yield Checkbox(t("tui.form.track_usage"), value=bool(s and s.track_usage), id="track")
            yield Static("", id="form-error")
            with Horizontal(id="buttons"):
                yield Button(t("tui.form.save"), variant="primary", id="save")
                yield Button(t("tui.form.cancel"), id="cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def show_error(self, message: str) -> None:
        self.query_one("#form-error", Static).update(message)

    def action_save(self) -> None:
        values: dict[str, Any] = {}
        for field in ("service", "amount", "currency", "period", "next", "tags", "cancel_url", "notes"):
            values[field] = self.query_one(f"#{field}", Input).value.strip()
        values["category"] = self.query_one("#category", Select).value
        values["track_usage"] = self.query_one("#track", Checkbox).value
        if self.sub:
            values["status"] = self.query_one("#status", Select).value
        if not values["service"]:
            self.show_error(t("tui.form.need_service"))
            return
        try:
            self.app.validate_form(values)  # type: ignore[attr-defined]
        except Exception as exc:  # SubwatchError carries a localised message
            self.show_error(str(exc))
            return
        self.dismiss(values)


class FilterScreen(ModalScreen[dict[str, str | None] | None]):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, config: Config, category: str | None, status: str | None):
        super().__init__()
        self.config = config
        self.category = category
        self.status = status

    def compose(self) -> ComposeResult:
        cats = [(t("tui.filter.any"), "")] + [(c.name, k) for k, c in self.config.categories.items()]
        statuses = [(t("tui.filter.any"), "")] + [(t(f"status.{s}"), s) for s in STATUSES]
        with Vertical(id="dialog"):
            yield Label(t("tui.filter.title"), id="question")
            yield Label(t("tui.filter.category"))
            yield Select(cats, value=self.category or "", allow_blank=False, prompt=t("tui.filter.category"),
                         id="f-category")
            yield Label(t("tui.filter.status"))
            yield Select(statuses, value=self.status or "", allow_blank=False, prompt=t("tui.filter.status"),
                         id="f-status")
            with Horizontal(id="buttons"):
                yield Button(t("tui.filter.apply"), variant="primary", id="apply")
                yield Button(t("tui.filter.reset"), id="reset")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "reset":
            self.dismiss({"category": None, "status": None})
            return
        cat = self.query_one("#f-category", Select).value
        st = self.query_one("#f-status", Select).value
        self.dismiss({"category": cat or None, "status": st or None})

    def action_cancel(self) -> None:
        self.dismiss(None)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", show=False), Binding("q", "close", show=False),
                Binding("question_mark", "close", show=False)]

    def __init__(self, rows: list[tuple[str, str]]):
        super().__init__()
        self.rows = rows

    def compose(self) -> ComposeResult:
        lines = [f"[b]{t('tui.help.title')}[/b]", ""]
        for keys, desc in self.rows:
            lines.append(f"[$accent]{keys:<22}[/] {desc}")
        lines += ["", t("tui.help.footer")]
        with VerticalScroll(id="help"):
            yield Static("\n".join(lines), markup=True)

    def action_close(self) -> None:
        self.dismiss(None)
