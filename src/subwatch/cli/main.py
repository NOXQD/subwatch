"""Command line interface (typer). Language is chosen before this module is
imported (see __main__.py), because help texts are read at import time."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Annotated, Optional

import typer

from .. import __version__, clock
from ..errors import NotFoundError, SubwatchError
from ..i18n import t, tn
from ..userinput import parse_category, parse_user_amount, parse_user_date, parse_user_period
from . import chrome
from .common import State, confirm, console, get_app, handle_errors, ok, say, warn

chrome.install()

META = {"options_metavar": t("cli.chrome.options_metavar")}


def _typer(help_key: str, **kw) -> typer.Typer:
    return typer.Typer(
        help=t(help_key),
        add_completion=False,
        no_args_is_help=False,
        rich_markup_mode="rich",
        context_settings={"help_option_names": ["-h", "--help"]},
        subcommand_metavar=t("cli.chrome.subcommand_metavar"),
        options_metavar=t("cli.chrome.options_metavar"),
        **kw,
    )


app = _typer("cli.app.help", invoke_without_command=True, epilog=t("cli.app.epilog"))


def cmd(name: str, hidden: bool = False):
    return app.command(name, help=t(f"cli.{name}.help"), short_help=t(f"cli.{name}.short"),
                       hidden=hidden, **META)


def opt(*decls: str, key: str, metavar: str | None = None, **kw):
    if metavar is not None:
        kw["metavar"] = t(f"cli.metavar.{metavar}")
    return typer.Option(*decls, help=t(f"cli.opt.{key}"), **kw)


def arg(key: str, metavar: str, **kw):
    return typer.Argument(help=t(f"cli.arg.{key}"), metavar=t(f"cli.metavar.{metavar}"), **kw)


def _version(value: bool) -> None:
    if value:
        console.print(t("cli.version_line", version=__version__), markup=False)
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    config: Annotated[Optional[Path], opt("--config", "-c", key="config", metavar="path")] = None,
    set_: Annotated[Optional[list[str]], opt("--set", key="set", metavar="key_value")] = None,
    lang: Annotated[Optional[str], opt("--lang", key="lang", metavar="lang")] = None,
    quiet: Annotated[bool, opt("--quiet", "-q", key="quiet")] = False,
    verbose: Annotated[bool, opt("--verbose", "-v", key="verbose")] = False,
    version: Annotated[bool, opt("--version", key="version", callback=_version, is_eager=True)] = False,
) -> None:
    State.config_path = str(config) if config else None
    State.overrides = list(set_ or [])
    if lang:
        State.overrides.append(f"ui.language={lang}")
    State.quiet = quiet
    State.verbose = verbose
    if ctx.invoked_subcommand is None:
        if sys.stdin.isatty() and sys.stdout.isatty():
            tui_command()
        else:
            list_command()


# ------------------------------------------------------------------ helpers


def _resolve(store, ref: str):
    sub = store.resolve(ref)
    if sub is None:
        matches = store.find_by_service(ref) if not ref.isdigit() else []
        if len(matches) > 1:
            raise SubwatchError("cli.err.ambiguous", hint="cli.hint.use_id", ref=ref,
                                ids=", ".join(str(m.id) for m in matches))
        raise NotFoundError("cli.err.not_found", hint="cli.hint.list", ref=ref)
    return sub


def _json_out(data) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n")


# --------------------------------------------------------------- tui / open


@cmd("tui")
@handle_errors
def tui_command(
    add: Annotated[bool, opt("--add", key="tui_add")] = False,
    review: Annotated[bool, opt("--review", key="tui_review")] = False,
) -> None:
    from ..tui.app import run_tui

    a = get_app()
    run_tui(a, start="add" if add else ("review" if review else None))


@cmd("open")
@handle_errors
def open_command(
    add: Annotated[bool, opt("--add", key="tui_add")] = False,
    review: Annotated[bool, opt("--review", key="tui_review")] = False,
) -> None:
    from ..integrate.common import subwatch_exe

    a = get_app()
    args = [subwatch_exe(), "tui"] + (["--add"] if add else []) + (["--review"] if review else [])
    term = a.config.ui.terminal
    if term != "auto":
        command = shlex.split(term) + args
    elif shutil.which("omarchy-launch-or-focus-tui"):
        command = ["omarchy-launch-or-focus-tui", *args]
    elif shutil.which("xdg-terminal-exec"):
        command = ["xdg-terminal-exec", *args]
    elif os.environ.get("TERMINAL"):
        command = [os.environ["TERMINAL"], "-e", *args]
    else:
        raise SubwatchError("cli.err.no_terminal", hint="cli.hint.terminal")
    subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------- listings


SORTS = ("next_charge", "amount", "monthly", "name", "category", "status")


def sort_subscriptions(subs, key: str, reverse: bool, rates):
    far = date(9999, 12, 31)

    def k(s):
        if key == "amount":
            return rates.convert(s.amount, s.currency) or 0
        if key == "monthly":
            return rates.convert(s.monthly_amount, s.currency) or 0 if s.monthly_amount is not None else 0
        if key == "name":
            return s.service.casefold()
        if key == "category":
            return (s.category, s.service.casefold())
        if key == "status":
            return (s.status, s.service.casefold())
        return (s.next_charge or far, s.service.casefold())

    return sorted(subs, key=k, reverse=reverse)


@cmd("list")
@handle_errors
def list_command(
    all_: Annotated[bool, opt("--all", "-a", key="all")] = False,
    status: Annotated[Optional[str], opt("--status", key="status", metavar="status")] = None,
    category: Annotated[Optional[str], opt("--category", key="category", metavar="category")] = None,
    sort: Annotated[Optional[str], opt("--sort", key="sort", metavar="sort")] = None,
    reverse: Annotated[bool, opt("--reverse", "-r", key="reverse")] = False,
    as_json: Annotated[bool, opt("--json", key="json")] = False,
) -> None:
    from ..export import subscription_rows
    from .render import subscriptions_table

    a = get_app()
    cfg = a.config
    subs = a.store.subscriptions(include_cancelled=all_ or cfg.ui.show_cancelled)
    if status:
        subs = [s for s in subs if s.status == status]
    if category:
        key = parse_category(category, cfg)
        subs = [s for s in subs if s.category == key]
    rates = a.rates()
    sort = sort or cfg.ui.default_sort
    if sort not in SORTS:
        raise SubwatchError("cli.err.bad_sort", value=sort, known=", ".join(SORTS))
    subs = sort_subscriptions(subs, sort, reverse != cfg.ui.sort_reverse, rates)
    if as_json:
        _json_out(subscription_rows(subs, cfg, rates))
        return
    if not subs:
        say(t("cli.list.empty"))
        say(t("cli.list.empty_hint"), "dim")
        return
    console.print(subscriptions_table(subs, cfg, rates))
    from ..analysis import totals

    tot = totals(subs, rates, cfg)
    from ..fmt import format_money

    say("")
    places = cfg.ui.money_decimals
    say(t("cli.list.total", total=format_money(tot.monthly, cfg.currency.base, places),
          yearly=format_money(tot.yearly, cfg.currency.base, places),
          count=tn("fmt.units.subscription", tot.count)))
    if tot.unconverted:
        warn(t("cli.list.unconverted", services=", ".join(s.service for s in tot.unconverted)))
    review = len(a.store.review_queue())
    if review and not status:
        say(tn("cli.list.review_hint", review), "yellow")


@cmd("show")
@handle_errors
def show_command(
    ref: Annotated[str, arg("ref", "ref")],
    as_json: Annotated[bool, opt("--json", key="json")] = False,
) -> None:
    from ..export import subscription_rows
    from .render import subscription_details

    a = get_app()
    sub = _resolve(a.store, ref)
    rates = a.rates()
    if as_json:
        _json_out(subscription_rows([sub], a.config, rates)[0])
        return
    console.print(subscription_details(sub, a.config, rates, a.store.charges(sub.id)))


@cmd("add")
@handle_errors
def add_command(
    service: Annotated[Optional[str], arg("service", "service")] = None,
    amount: Annotated[Optional[str], opt("--amount", key="amount", metavar="amount")] = None,
    currency: Annotated[Optional[str], opt("--currency", key="currency", metavar="currency")] = None,
    period: Annotated[Optional[str], opt("--period", key="period", metavar="period")] = None,
    next_: Annotated[Optional[str], opt("--next", key="next", metavar="date")] = None,
    category: Annotated[Optional[str], opt("--category", key="category", metavar="category")] = None,
    tag: Annotated[Optional[list[str]], opt("--tag", key="tag", metavar="tag")] = None,
    cancel_url: Annotated[Optional[str], opt("--cancel-url", key="cancel_url", metavar="url")] = None,
    notes: Annotated[Optional[str], opt("--notes", key="notes", metavar="text")] = None,
    trial_until: Annotated[Optional[str], opt("--trial-until", key="trial_until", metavar="date")] = None,
    track_usage: Annotated[bool, opt("--track-usage", key="track_usage")] = False,
) -> None:
    from ..classify import assign_category
    from ..extract.merchants import default_book
    from ..models import Subscription
    from .common import ask

    a = get_app()
    cfg = a.config
    interactive = sys.stdin.isatty()
    if not service:
        if not interactive:
            raise SubwatchError("cli.err.need_service")
        service = ask(t("cli.add.ask_service"))
        if not service:
            raise typer.Abort()
    known = default_book().find_service(service)
    if known:
        service = known.name
    if amount is None and interactive:
        amount = ask(t("cli.add.ask_amount"), "")
    value, code = (None, None)
    if amount:
        value, code = parse_user_amount(amount, (currency or cfg.currency.base).upper())
    if currency:
        code = currency.upper()
    if period is None and interactive:
        default_period = known.period.code if known and known.period else "1m"
        period = ask(t("cli.add.ask_period"), default_period)
    p = parse_user_period(period or (known.period.code if known and known.period else "1m"))
    if next_ is None and interactive:
        next_ = ask(t("cli.add.ask_next"), "")
    nxt = parse_user_date(next_) if next_ else None
    cat = parse_category(category, cfg) if category else assign_category(
        service, cfg, a.learned(), suggested=known.category if known else None)
    sub = Subscription(
        service=service, amount=value, currency=code, period=p, next_charge=nxt,
        anchor_day=nxt.day if nxt else None, category=cat, tags=list(tag or []),
        cancel_url=cancel_url or (known.cancel_url if known else None), notes=notes,
        trial_until=parse_user_date(trial_until) if trial_until else None,
        source="manual", confidence=1.0, track_usage=track_usage,
        last_used=clock.today() if track_usage else None,
    )
    existing = a.store.find_by_key(sub.key)
    if existing and existing.status != "cancelled":
        raise SubwatchError("cli.err.exists", hint="cli.hint.edit", service=service, id=existing.id)
    if existing:
        sub.id = existing.id
        sub.created_at = existing.created_at
        a.store.update_subscription(sub)
    else:
        a.store.insert_subscription(sub)
    from ..hooks import run_hooks

    run_hooks(cfg, "new_subscription", sub, {"via": "manual"})
    a.after_change()
    ok(t("cli.add.done", service=sub.service, id=sub.id))


@cmd("edit")
@handle_errors
def edit_command(
    ref: Annotated[str, arg("ref", "ref")],
    service: Annotated[Optional[str], opt("--service", key="service_name", metavar="service")] = None,
    amount: Annotated[Optional[str], opt("--amount", key="amount", metavar="amount")] = None,
    currency: Annotated[Optional[str], opt("--currency", key="currency", metavar="currency")] = None,
    period: Annotated[Optional[str], opt("--period", key="period", metavar="period")] = None,
    next_: Annotated[Optional[str], opt("--next", key="next", metavar="date")] = None,
    category: Annotated[Optional[str], opt("--category", key="category", metavar="category")] = None,
    tag: Annotated[Optional[list[str]], opt("--tag", key="tag", metavar="tag")] = None,
    status: Annotated[Optional[str], opt("--status", key="set_status", metavar="status")] = None,
    cancel_url: Annotated[Optional[str], opt("--cancel-url", key="cancel_url", metavar="url")] = None,
    notes: Annotated[Optional[str], opt("--notes", key="notes", metavar="text")] = None,
    track_usage: Annotated[Optional[bool], opt("--track-usage/--no-track-usage", key="track_usage")] = None,
) -> None:
    from ..models import STATUSES, service_key

    a = get_app()
    cfg = a.config
    sub = _resolve(a.store, ref)
    before = sub.service
    if service:
        sub.service = service
    if amount:
        sub.amount, code = parse_user_amount(amount, sub.currency or cfg.currency.base)
        sub.currency = code
    if currency:
        sub.currency = currency.upper()
    if period:
        sub.period = parse_user_period(period)
    if next_:
        sub.next_charge = parse_user_date(next_)
        sub.anchor_day = sub.next_charge.day
    if category:
        sub.category = parse_category(category, cfg)
        a.store.add_rule("category", service_key(sub.service), sub.category)
    if tag is not None:
        sub.tags = list(tag)
    if status:
        if status not in STATUSES:
            raise SubwatchError("cli.err.bad_status", value=status, known=", ".join(STATUSES))
        sub.status = status
        if status == "cancelled":
            sub.cancelled_at = clock.now()
    if cancel_url is not None:
        sub.cancel_url = cancel_url or None
    if notes is not None:
        sub.notes = notes or None
    if track_usage is not None:
        sub.track_usage = track_usage
        if track_usage and not sub.last_used:
            sub.last_used = clock.today()
    if service and service_key(before) != service_key(service):
        a.store.add_rule("alias", service_key(before), service)
    sub.key = sub.make_key()
    a.store.update_subscription(sub)
    a.after_change()
    ok(t("cli.edit.done", service=sub.service))


@cmd("remove")
@handle_errors
def remove_command(
    ref: Annotated[str, arg("ref", "ref")],
    yes: Annotated[bool, opt("--yes", "-y", key="yes")] = False,
) -> None:
    a = get_app()
    sub = _resolve(a.store, ref)
    if not confirm(t("cli.remove.confirm", service=sub.service), assume_yes=yes):
        raise typer.Abort()
    a.store.delete_subscription(sub.id or 0)
    a.after_change()
    ok(t("cli.remove.done", service=sub.service))


@cmd("cancel")
@handle_errors
def cancel_command(
    ref: Annotated[str, arg("ref", "ref")],
    open_page: Annotated[bool, opt("--open/--no-open", key="open_page")] = True,
) -> None:
    from .. import ops

    a = get_app()
    sub = _resolve(a.store, ref)
    if not sub.cancel_url:
        say(t("cli.cancel.no_url", service=sub.service), "yellow")
    if ops.cancel(a, sub, "cli", open_page=open_page):
        say(t("cli.cancel.opened", url=sub.cancel_url))
    ok(t("cli.cancel.done", service=sub.service))


@cmd("pause")
@handle_errors
def pause_command(ref: Annotated[str, arg("ref", "ref")]) -> None:
    from .. import ops

    a = get_app()
    sub = _resolve(a.store, ref)
    ops.pause(a, sub)
    ok(t("cli.pause.done", service=sub.service))


@cmd("resume")
@handle_errors
def resume_command(ref: Annotated[str, arg("ref", "ref")]) -> None:
    from .. import ops

    a = get_app()
    sub = _resolve(a.store, ref)
    ops.resume(a, sub)
    ok(t("cli.resume.done", service=sub.service))


@cmd("used")
@handle_errors
def used_command(
    ref: Annotated[str, arg("ref", "ref")],
    when: Annotated[Optional[str], opt("--date", key="used_date", metavar="date")] = None,
) -> None:
    from .. import ops

    a = get_app()
    sub = _resolve(a.store, ref)
    ops.mark_used(a, sub, parse_user_date(when) if when else None)
    ok(t("cli.used.done", service=sub.service))


@cmd("merge")
@handle_errors
def merge_command(
    keep: Annotated[str, arg("keep", "ref")],
    drop: Annotated[str, arg("drop", "ref")],
    yes: Annotated[bool, opt("--yes", "-y", key="yes")] = False,
) -> None:
    a = get_app()
    a_sub = _resolve(a.store, keep)
    b_sub = _resolve(a.store, drop)
    if a_sub.id == b_sub.id:
        raise SubwatchError("cli.err.same_record")
    if not confirm(t("cli.merge.confirm", keep=a_sub.service, drop=b_sub.service), assume_yes=yes):
        raise typer.Abort()
    with a.store.transaction():
        a.store.move_charges(b_sub.id or 0, a_sub.id or 0)
        for attr in ("cancel_url", "notes", "trial_until", "last_used"):
            if getattr(a_sub, attr) is None and getattr(b_sub, attr) is not None:
                setattr(a_sub, attr, getattr(b_sub, attr))
        a_sub.tags = sorted(set(a_sub.tags) | set(b_sub.tags))
        a.store.update_subscription(a_sub)
        a.store.delete_subscription(b_sub.id or 0)
    a.after_change()
    ok(t("cli.merge.done", keep=a_sub.service, drop=b_sub.service))


@cmd("upcoming")
@handle_errors
def upcoming_command(
    days: Annotated[Optional[int], opt("--days", "-d", key="days", metavar="n")] = None,
    notify: Annotated[bool, opt("--notify", key="notify")] = False,
    as_json: Annotated[bool, opt("--json", key="json")] = False,
) -> None:
    from ..analysis import upcoming
    from ..fmt import format_date, format_money, format_relative_days
    from ..notify import Notification, self_command, send
    from .render import upcoming_table

    a = get_app()
    cfg = a.config
    horizon = days or cfg.menu.upcoming_days
    items = upcoming(a.store.subscriptions(), horizon)
    if as_json:
        _json_out([{"id": s.id, "service": s.service, "date": s.next_charge, "amount": s.amount,
                    "currency": s.currency} for s in items])
        return
    if notify:
        if items:
            lines = [t("cli.upcoming.notify_line", date=format_date(s.next_charge), service=s.service,
                       amount=format_money(s.amount, s.currency) if s.amount is not None else "",
                       relative=format_relative_days((s.next_charge - clock.today()).days))
                     for s in items[:8]]
            body = "\n".join(lines)
        else:
            body = t("cli.upcoming.none", days=tn("fmt.units.day", horizon))
        send(Notification(t("cli.upcoming.notify_title", days=tn("fmt.units.day", horizon)), body,
                          kind="upcoming", click=self_command() + ["open"]), cfg.notifications)
        return
    if not items:
        say(t("cli.upcoming.none", days=tn("fmt.units.day", horizon)))
        return
    say(t("cli.upcoming.title", days=tn("fmt.units.day", horizon)), "bold")
    console.print(upcoming_table(items, cfg))


@cmd("spend")
@handle_errors
def spend_command(
    months: Annotated[int, opt("--months", "-m", key="months_hist", metavar="n")] = 6,
    by: Annotated[str, opt("--by", key="by", metavar="by")] = "category",
    notify: Annotated[bool, opt("--notify", key="notify")] = False,
    as_json: Annotated[bool, opt("--json", key="json")] = False,
) -> None:
    from rich.table import Table

    from ..analysis import budget_status, monthly_spend, totals
    from ..fmt import format_money, month_name
    from ..notify import Notification, self_command, send
    from .render import bar_line

    a = get_app()
    cfg = a.config
    rates = a.rates()
    subs = a.store.subscriptions(include_cancelled=True)
    tot = totals(subs, rates, cfg)
    statuses = budget_status(tot, cfg)
    base = cfg.currency.base
    if as_json:
        hist = monthly_spend(a.store, subs, rates, cfg, months_back=max(0, months - 1))
        _json_out({"monthly": tot.monthly, "yearly": tot.yearly, "currency": base,
                   "by_category": tot.by_category,
                   "history": [{"month": m.isoformat(), "total": v, "forecast": f, "by_category": c}
                               for m, v, f, c in hist],
                   "budgets": [{"scope": s.scope, "limit": s.limit, "spent": s.spent, "level": s.level}
                               for s in statuses]})
        return
    if notify:
        lines = [t("cli.spend.notify_total", total=format_money(tot.monthly, base),
                   yearly=format_money(tot.yearly, base))]
        for key, value in sorted(tot.by_category.items(), key=lambda kv: kv[1], reverse=True)[:5]:
            lines.append(t("cli.spend.notify_cat", name=cfg.category_name(key), amount=format_money(value, base, 0)))
        for st in statuses:
            if st.level != "ok":
                name = t("bar.tip_budget_total") if st.scope == "total" else cfg.category_name(st.scope)
                lines.append(t(f"bar.tip_budget_{st.level}", name=name, spent=format_money(st.spent, base, 0),
                               limit=format_money(st.limit, base, 0)))
        send(Notification(t("cli.spend.notify_title"), "\n".join(lines), kind="spend",
                          click=self_command() + ["open"]), cfg.notifications)
        return
    say(t("cli.spend.total", total=format_money(tot.monthly, base), yearly=format_money(tot.yearly, base),
          count=tn("fmt.units.subscription", tot.count)), "bold")
    for st in statuses:
        name = t("bar.tip_budget_total") if st.scope == "total" else cfg.category_name(st.scope)
        style = {"ok": "green", "warn": "yellow", "over": "bold red"}[st.level]
        say(t(f"bar.tip_budget_{st.level}", name=name, spent=format_money(st.spent, base, 0),
              limit=format_money(st.limit, base, 0)), style)
    say("")
    if by == "category":
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column(t("table.category"))
        table.add_column(t("table.monthly"), justify="right")
        table.add_column("")
        peak = max(tot.by_category.values(), default=0)
        for key, value in sorted(tot.by_category.items(), key=lambda kv: kv[1], reverse=True):
            table.add_row(cfg.category_name(key), format_money(value, base, 0), bar_line(value, peak, 24))
        console.print(table)
    else:
        hist = monthly_spend(a.store, subs, rates, cfg, months_back=max(0, months - 1))
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column(t("table.month"))
        table.add_column(t("table.total"), justify="right")
        table.add_column("")
        peak = max((v for _, v, _, _ in hist), default=0)
        for month, value, _forecast, _ in hist:
            label = f"{month_name(month.month, 'nominative')} {month.year}"
            table.add_row(label, format_money(value, base, 0), bar_line(value, peak, 24))
        console.print(table)
    if tot.unconverted:
        warn(t("cli.list.unconverted", services=", ".join(s.service for s in tot.unconverted)))


# -------------------------------------------------------------------- scan


@cmd("scan")
@handle_errors
def scan_command(
    source: Annotated[Optional[list[str]], opt("--source", "-s", key="source", metavar="source")] = None,
    full: Annotated[bool, opt("--full", key="full")] = False,
    months: Annotated[Optional[int], opt("--months", "-m", key="months", metavar="n")] = None,
    dry_run: Annotated[bool, opt("--dry-run", key="dry_run")] = False,
    ai_dry_run: Annotated[bool, opt("--ai-dry-run", key="ai_dry_run")] = False,
    no_ai: Annotated[bool, opt("--no-ai", key="no_ai")] = False,
    reprocess: Annotated[bool, opt("--reprocess", key="reprocess")] = False,
) -> None:
    from rich.table import Table

    from ..scan import run_job

    extra = {"scan": {"months_back": months}} if months else None
    a = get_app(extra)
    status = None
    progress = None
    if not State.quiet and sys.stdout.isatty():
        status = console.status(t("cli.scan.running"))
        status.start()

        def progress(name: str, n: int) -> None:
            status.update(t("cli.scan.progress", source=t(f"source.{name}") if not name.startswith("plugin")
                            else name, count=n))
    try:
        report = run_job(a, only=source, full=full, months=months, dry_run=dry_run,
                         ai_dry_run=ai_dry_run, no_ai=no_ai, reprocess=reprocess, progress=progress)
    finally:
        if status is not None:
            status.stop()
    if ai_dry_run and report.ai is not None:
        _print_ai_dry_run(report.ai.dry_runs)
    if dry_run or ai_dry_run:
        _print_would(report.would, a.config)
    if State.quiet:
        if report.errors:
            raise typer.Exit(1)
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    for col in ("source", "seen", "created", "review", "updated", "filtered"):
        table.add_column(t(f"cli.scan.col.{col}"), justify="left" if col == "source" else "right")
    if not report.stats:
        say(t("cli.scan.no_sources"), "yellow")
        say(t("cli.scan.no_sources_hint"), "dim")
    for name, c in report.stats.items():
        label = t(f"source.{name}") if not name.startswith("plugin") else name
        table.add_row(label, str(c.get("seen", 0) + c.get("transactions", 0)),
                      str(c.get("created", 0) + c.get("promoted", 0)), str(c.get("review", 0)),
                      str(c.get("updated", 0) + c.get("cancelled", 0)), str(c.get("filtered", 0)))
    if report.stats:
        console.print(table)
    for src, message in report.errors:
        warn(t("cli.scan.error_line", source=src, message=message))
    if not dry_run:
        say(t("cli.scan.done", seconds=f"{report.seconds:.1f}"))
    if report.errors:
        raise typer.Exit(1)


def _print_ai_dry_run(items) -> None:
    if not items:
        say(t("cli.ai.dry_none"))
        return
    for i, item in enumerate(items, 1):
        kind = t("cli.ai.local") if item.is_local else t("cli.ai.cloud")
        say(t("cli.ai.dry_header", n=i, provider=item.provider, model=item.model, kind=kind,
              sender=item.sender_domain or "—"), "bold")
        for m in item.messages:
            say(f"[{m['role']}]", "dim")
            say(m["content"])
        say("")


def _print_would(would, config) -> None:
    from ..fmt import format_money, format_period

    if not would:
        say(t("cli.scan.would_none"))
        return
    say(t("cli.scan.would_title"), "bold")
    for det, category in would:
        status = t("cli.scan.would_active") if det.confidence >= config.extraction.auto_accept else (
            t("cli.scan.would_review") if det.confidence >= config.extraction.review_threshold
            else t("cli.scan.would_ignored"))
        say(t("cli.scan.would_line", service=det.service, kind=t(f"kind.{det.kind}"),
              amount=format_money(det.amount, det.currency) if det.amount is not None else "—",
              period=format_period(det.period) if det.period else "—",
              category=config.category_name(category), confidence=round(det.confidence * 100), status=status))


# ---------------------------------------------------------------- reminders


@cmd("remind")
@handle_errors
def remind_command(
    dry_run: Annotated[bool, opt("--dry-run", key="dry_run")] = False,
) -> None:
    from .. import reminders
    from ..fmt import format_date

    a = get_app()
    report = reminders.run(a.store, a.config, a.rates(), dry_run=dry_run)
    if not dry_run:
        a.after_change()
    if State.quiet:
        return
    if not report.sent:
        say(t("cli.remind.none"))
    for s in report.sent:
        say(t("cli.remind.line", service=s.subscription.service, date=format_date(s.charge_date),
              repeat=t("cli.remind.repeat") if s.repeat else ""))


@cmd("notify-action", hidden=True)
@handle_errors
def notify_action_command(
    reminder_id: Annotated[int, arg("reminder", "id")],
    action: Annotated[Optional[str], opt("--action", key="action", metavar="action")] = None,
    snooze: Annotated[Optional[str], opt("--snooze", key="snooze", metavar="duration")] = None,
) -> None:
    from .. import picker, reminders
    from ..config.schema import parse_duration
    from ..fmt import format_duration
    from ..notify import Notification, send

    a = get_app()
    cfg = a.config
    row = a.store.reminder(reminder_id)
    if row is None:
        raise NotFoundError("remind.action.missing")
    sub = a.store.get_subscription(row["subscription_id"])
    if action is None:
        options = [picker.Option("keep", t("action.keep"), ""),
                   picker.Option("cancel", t("action.cancel_long") if sub and sub.cancel_url
                                 else t("action.cancel"), "")]
        for opt_ in cfg.reminders.snooze_options:
            options.append(picker.Option(f"snooze:{opt_}", t("action.snooze",
                                                             duration=format_duration(parse_duration(opt_))),
                                         ""))
        chosen = picker.choose(t("action.prompt", service=sub.service if sub else ""), options, cfg.menu.picker)
        if not chosen:
            return
        action, _, picked = chosen.partition(":")
        snooze = picked or snooze
    result = reminders.apply_action(a.store, cfg, reminder_id, action, snooze)
    a.after_change()
    send(Notification(t(result, service=sub.service if sub else ""),
                      t(result + "_body", service=sub.service if sub else "",
                        duration=format_duration(parse_duration(snooze or cfg.reminders.snooze))),
                      urgency="low", kind="ack"), cfg.notifications)


@cmd("notify-wait", hidden=True)
@handle_errors
def notify_wait_command(payload: Annotated[str, typer.Argument(hidden=True)]) -> None:
    from ..notify import wait_for_action

    chosen = wait_for_action(payload)
    data = json.loads(payload)
    if chosen in ("keep", "cancel", "snooze"):
        notify_action_command(int(data["reminder_id"]), chosen, None)


# --------------------------------------------------------------- bar / menu


@cmd("bar")
def bar_command(
    fmt: Annotated[str, opt("--format", "-f", key="bar_format", metavar="format")] = "waybar",
) -> None:
    """Never fails loudly: a broken bar module is worse than an empty one."""
    from .. import bar

    if fmt == "panel":
        sys.stdout.write(json.dumps(_panel_data(), ensure_ascii=False) + "\n")
        return
    try:
        a = get_app()
        data = bar.read_cache(a.db_path, a.loaded.path) if fmt == "waybar" else None
        if data is None:
            data = bar.bar_data(a.store.subscriptions(), a.config, a.rates(),
                                review_count=len(a.store.review_queue()))
            bar.write_cache(data, a.db_path, a.loaded.path)
        a.close()
        State.app = None
    except Exception as exc:
        data = {"text": " !", "tooltip": t("bar.error", detail=str(exc)), "class": ["subwatch", "error"]}
    if fmt == "text":
        sys.stdout.write(data["text"] + "\n")
    else:
        sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")


def _panel_data() -> dict:
    """Data for the Omarchy widget and its popup, cached like the bar text."""
    from .. import bar
    from ..gui.views import dashboard

    try:
        a = get_app()
        data = bar.read_cache(a.db_path, a.loaded.path, "panel")
        if data is None:
            data = dashboard(a)
            bar.write_cache(data, a.db_path, a.loaded.path, "panel")
        a.close()
        State.app = None
        return data
    except Exception as exc:
        return {"version": 1, "error": t("bar.error", detail=str(exc))}


@cmd("settings")
@handle_errors
def settings_command(
    page: Annotated[Optional[str], arg("settings_page", "page")] = None,
) -> None:
    from ..integrate import omarchy

    payload = json.dumps({"page": page} if page else {})
    if omarchy.plugin_installed() and shutil.which("omarchy-shell"):
        done = subprocess.run(["omarchy-shell", "shell", "summon", omarchy.PLUGIN_ID, payload],
                              capture_output=True, text=True, check=False)
        if done.returncode == 0 and "false" not in done.stdout:
            return
    open_command()


@cmd("gui-server", hidden=True)
def gui_server_command() -> None:
    from ..gui.server import main

    main()


@cmd("menu")
@handle_errors
def menu_command(
    route: Annotated[Optional[str], arg("route", "route")] = None,
) -> None:
    from .. import picker
    from ..analysis import upcoming
    from ..fmt import format_date, format_money, format_relative_days
    from ..integrate import omarchy

    a = get_app()
    cfg = a.config
    exe = _self()
    if route is None:
        if omarchy.menu_installed() and shutil.which("omarchy-menu"):
            subprocess.run(["omarchy-menu", "summon", "subwatch"], check=False)
            return
        entries = omarchy.menu_entries(cfg)[1:]
        options = [picker.Option(k, v["label"], v.get("icon", "")) for k, v in entries]
        chosen = picker.choose("Subwatch", options, cfg.menu.picker)
        action = dict(entries).get(chosen or "", {}).get("action")
        if action:
            subprocess.Popen(["bash", "-c", action], start_new_session=True)
        return
    if route == "upcoming":
        items = upcoming(a.store.subscriptions(), cfg.menu.upcoming_days)
        if not items:
            options = [picker.Option("open", t("cli.upcoming.none", days=tn("fmt.units.day",
                                                                          cfg.menu.upcoming_days)))]
        else:
            options = [picker.Option(str(s.id), s.service, "\U000f00f0",
                                     t("cli.menu.upcoming_detail", date=format_date(s.next_charge),
                                       relative=format_relative_days((s.next_charge - clock.today()).days),
                                       amount=format_money(s.amount, s.currency) if s.amount is not None else ""))
                       for s in items]
        chosen = picker.choose(t("integrate.menu.upcoming"), options, cfg.menu.picker)
        if not chosen or chosen == "open":
            return
        sub = a.store.get_subscription(int(chosen))
        if sub is None:
            return
        actions = [picker.Option("open", t("cli.menu.open_tui"), "")]
        if sub.cancel_url:
            actions.append(picker.Option("cancel_page", t("cli.menu.cancel_page"), ""))
        actions.append(picker.Option("used", t("cli.menu.mark_used"), ""))
        pick = picker.choose(sub.service, actions, cfg.menu.picker)
        if pick == "open":
            subprocess.Popen([exe, "open"], start_new_session=True)
        elif pick == "cancel_page":
            from ..reminders import open_url

            open_url(sub.cancel_url or "")
        elif pick == "used":
            sub.track_usage = True
            sub.last_used = clock.today()
            a.store.update_subscription(sub)
        return
    raise SubwatchError("cli.err.bad_route", value=route)


def _self() -> str:
    from ..integrate.common import subwatch_exe

    return subwatch_exe()


# ------------------------------------------------------------ maintenance


@cmd("doctor")
@handle_errors
def doctor_command(
    fix: Annotated[bool, opt("--fix", key="fix")] = False,
    online: Annotated[bool, opt("--online", key="online")] = False,
    as_json: Annotated[bool, opt("--json", key="json")] = False,
) -> None:
    from .. import doctor
    from .render import print_checks

    checks = doctor.run_checks(online=online)
    if fix:
        fixed = 0
        for c in checks:
            if c.fix is not None and c.status in ("warn", "fail"):
                try:
                    if c.fix():
                        fixed += 1
                except Exception as exc:
                    warn(t("doctor.fix_failed", detail=str(exc)))
        if fixed:
            say(t("doctor.fixed", count=fixed), "green")
            checks = doctor.run_checks(online=online)
    if as_json:
        _json_out([{"group": c.group, "status": c.status, "message": t(c.key, **c.params),
                    "hint": t(c.hint, **c.params) if c.hint else None} for c in checks])
        raise typer.Exit(doctor.exit_code(checks))
    print_checks(checks)
    s = doctor.summary(checks)
    say("")
    if s["fail"]:
        say(t("doctor.summary_fail", ok=s["ok"], warn=s["warn"], fail=s["fail"]), "bold red")
        if any(c.fix for c in checks if c.status == "fail") and not fix:
            say(t("doctor.try_fix"), "dim")
    elif s["warn"]:
        say(t("doctor.summary_warn", ok=s["ok"], warn=s["warn"]), "bold yellow")
    else:
        say(t("doctor.summary_ok", ok=s["ok"]), "bold green")
    raise typer.Exit(doctor.exit_code(checks))


@cmd("privacy")
@handle_errors
def privacy_command(
    payloads: Annotated[bool, opt("--payloads", key="payloads")] = False,
) -> None:
    from .. import paths, privacy

    a = get_app()
    rep = privacy.report(a.config, show_payloads=payloads)
    say(t("privacy.title"), "bold")
    say(t("privacy.principles"))
    say("")
    say(t("privacy.files"), "bold")
    for f in rep.files:
        if f.exists:
            say(t("privacy.file_line", path=paths.contract_home(f.path), size=f.size, mode=f.mode))
        else:
            say(t("privacy.file_missing", path=paths.contract_home(f.path)), "dim")
    say(t("privacy.encryption_on") if rep.encrypted else t("privacy.encryption_off"))
    say("")
    say(t("privacy.stored"), "bold")
    for table, count in rep.counts.items():
        say(t("privacy.table_line", name=t(f"privacy.table.{table}"), count=count))
    say(t("privacy.snippets_on", count=rep.snippets) if rep.store_snippets else t("privacy.snippets_off"))
    say("")
    say(t("privacy.secrets"), "bold")
    for name, exists in rep.secrets:
        if exists:
            say(t("privacy.secret_line", name=name))
    if not any(e for _, e in rep.secrets):
        say(t("privacy.no_secrets"), "dim")
    say("")
    say(t("privacy.ai"), "bold")
    if not rep.ai_total:
        say(t("privacy.ai_none"))
    else:
        say(t("privacy.ai_total", total=rep.ai_total, cloud=rep.ai_cloud))
        for label, n in rep.ai_by_model.items():
            say(t("privacy.ai_model", model=label, count=n))
        for row in rep.ai_recent:
            say(t("privacy.ai_row", ts=row["ts"], model=f"{row['provider']}/{row['model']}",
                  sender=row["sender_domain"] or "—", chars=row["chars"], outcome=row["outcome"]), "dim")
            if payloads and row.get("payload"):
                say(row["payload"])


@cmd("purge")
@handle_errors
def purge_command(
    yes: Annotated[bool, opt("--yes", "-y", key="yes")] = False,
    all_: Annotated[bool, opt("--all", key="purge_all")] = False,
) -> None:
    from .. import privacy

    a = get_app()
    if not confirm(t("cli.purge.confirm_all") if all_ else t("cli.purge.confirm"), assume_yes=yes):
        raise typer.Abort()
    config = a.config
    a.close()
    State.app = None
    removed = privacy.purge(config, include_config=all_)
    for item in removed:
        say(t("cli.purge.removed", item=item))
    ok(t("cli.purge.done"))


@cmd("logs")
def logs_command(
    follow: Annotated[bool, opt("--follow", "-f", key="follow")] = False,
    lines: Annotated[int, opt("--lines", "-n", key="lines", metavar="n")] = 50,
) -> None:
    args = ["journalctl", "--user", "-t", "subwatch", "-n", str(lines), "--no-pager"]
    if follow:
        args.append("-f")
    try:
        os.execvp("journalctl", args)
    except OSError:
        raise typer.Exit(1) from None


@cmd("version")
def version_command() -> None:
    console.print(t("cli.version_line", version=__version__), markup=False)


# Sub-command groups live in their own modules.
from . import groups  # noqa: E402

groups.register(app, _typer, opt, arg)


def click_command():
    import typer.main

    return typer.main.get_command(app)


def run(argv: list[str]) -> None:
    if any(k.startswith("_SUBWATCH_COMPLETE") for k in os.environ):
        from typer._completion_classes import completion_init

        completion_init()
    app(args=argv, prog_name="subwatch")
