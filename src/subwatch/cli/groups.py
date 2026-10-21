"""Command groups: config, auth, review, import, rates, export, budget,
rules, plugins, ai, keybinds, integrate, completion."""


import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from .. import clock, paths
from ..errors import NotFoundError, SubwatchError
from ..i18n import t, tn
from .common import State, ask, confirm, console, get_app, handle_errors, ok, say, warn


def register(app: typer.Typer, make, opt, arg) -> None:
    def group(name: str) -> typer.Typer:
        g = make(f"cli.{name}.help")
        app.add_typer(g, name=name, help=t(f"cli.{name}.help"), short_help=t(f"cli.{name}.short"))
        return g

    def sub(g: typer.Typer, name: str, key: str):
        return g.command(name, help=t(f"cli.{key}.help"), short_help=t(f"cli.{key}.short"),
                         options_metavar=t("cli.chrome.options_metavar"))

    # ------------------------------------------------------------- config

    config = group("config")

    @sub(config, "path", "config_path")
    @handle_errors
    def config_path() -> None:
        console.print(str(get_app().loaded.path), markup=False)

    @sub(config, "show", "config_show")
    @handle_errors
    def config_show(
        sources: Annotated[bool, opt("--sources", key="sources")] = False,
    ) -> None:
        from ..config.editor import plain, render_value
        from ..config.loader import flatten

        a = get_app()
        flat = flatten(plain(a.config))
        for key in sorted(flat):
            line = f"{key} = {render_value(flat[key])}"
            if sources:
                line += f"    # {t('config.origin.' + a.loaded.origin(key))}"
            console.print(line, markup=False)

    @sub(config, "get", "config_get")
    @handle_errors
    def config_get(
        key: Annotated[str, arg("key", "key")],
        source: Annotated[bool, opt("--source", key="show_source")] = False,
    ) -> None:
        from ..config.editor import get_value, render_value

        a = get_app()
        value = get_value(a.config, key)
        text = render_value(value)
        if source:
            text += f"    # {t('config.origin.' + a.loaded.origin(key))}"
        console.print(text, markup=False)

    @sub(config, "set", "config_set")
    @handle_errors
    def config_set(
        key: Annotated[str, arg("key", "key")],
        value: Annotated[str, arg("value", "value")],
    ) -> None:
        from ..config.editor import ensure_config_file, render_value, set_value
        from ..config.effects import apply_side_effects

        a = get_app()
        old = a.config
        path, _ = ensure_config_file(a.loaded.path)
        before, after = set_value(key, value, path)
        ok(t("cli.config.set_done", key=key, old=render_value(before) if before is not None else "—",
             new=render_value(after)))
        from ..config.loader import load_config

        new = load_config(path).config
        for step in apply_side_effects(old, new):
            say(t("cli.config.side_effect", what=t(step.key, **step.params)), "dim")
        env_key = "SUBWATCH_" + "__".join(p.upper() for p in key.split("."))
        if env_key in os.environ:
            warn(t("cli.config.env_shadow", var=env_key))

    @sub(config, "unset", "config_unset")
    @handle_errors
    def config_unset(key: Annotated[str, arg("key", "key")]) -> None:
        from ..config.editor import unset_value

        a = get_app()
        if unset_value(key, a.loaded.path):
            ok(t("cli.config.unset_done", key=key))
        else:
            say(t("cli.config.unset_absent", key=key))

    @sub(config, "edit", "config_edit")
    @handle_errors
    def config_edit() -> None:
        from ..config.editor import backup, ensure_config_file
        from ..config.effects import apply_side_effects
        from ..config.loader import ConfigError, load_config

        a = get_app()
        old = a.config
        path, _ = ensure_config_file(a.loaded.path)
        saved = backup(path)
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
        while True:
            subprocess.run([*shlex.split(editor), str(path)], check=False)
            try:
                new = load_config(path).config
                break
            except ConfigError as exc:
                console.print(exc.render(), markup=False, style="red")
                if not confirm(t("cli.config.edit_again"), default=True):
                    if saved and confirm(t("cli.config.restore"), default=True):
                        path.write_text(saved.read_text(encoding="utf-8"), encoding="utf-8")
                        say(t("cli.config.restored"))
                    raise typer.Exit(78) from None
        if saved:
            saved.unlink(missing_ok=True)
        ok(t("cli.config.valid", path=paths.contract_home(path)))
        for step in apply_side_effects(old, new):
            say(t("cli.config.side_effect", what=t(step.key, **step.params)), "dim")

    @sub(config, "reset", "config_reset")
    @handle_errors
    def config_reset(
        key: Annotated[Optional[str], arg("reset_key", "key")] = None,
        yes: Annotated[bool, opt("--yes", "-y", key="yes")] = False,
    ) -> None:
        from ..config.editor import reset_file, unset_value

        a = get_app()
        if key:
            unset_value(key, a.loaded.path)
            ok(t("cli.config.reset_key", key=key))
            return
        if not confirm(t("cli.config.reset_confirm"), assume_yes=yes):
            raise typer.Abort()
        saved = reset_file(a.loaded.path)
        ok(t("cli.config.reset_done", backup=paths.contract_home(saved) if saved else "—"))

    @sub(config, "diff", "config_diff")
    @handle_errors
    def config_diff() -> None:
        from ..config.editor import diff, render_value

        a = get_app()
        changes = diff(a.config)
        if not changes:
            say(t("cli.config.no_diff"))
            return
        for key, default, current in changes:
            origin = t("config.origin." + a.loaded.origin(key))
            console.print(t("cli.config.diff_line", key=key, default=render_value(default),
                            current=render_value(current), origin=origin), markup=False)

    @sub(config, "check", "config_check")
    @handle_errors
    def config_check() -> None:
        from ..config.loader import load_config
        from ..integrate.systemd import validate_calendar

        a = get_app()
        cfg = load_config(a.loaded.path).config
        if not validate_calendar(cfg.scan.schedule):
            raise SubwatchError("integrate.systemd.bad_schedule", value=cfg.scan.schedule)
        exists = a.loaded.path.exists()
        ok(t("cli.config.valid", path=paths.contract_home(a.loaded.path)) if exists
           else t("cli.config.defaults_only"))
        if a.loaded.env_data:
            say(t("cli.config.env_active", keys=", ".join(sorted(_flat_keys(a.loaded.env_data)))), "yellow")

    # --------------------------------------------------------------- auth

    auth = group("auth")

    @sub(auth, "gmail", "auth_gmail")
    @handle_errors
    def auth_gmail(
        account: Annotated[str, opt("--account", key="gmail_account", metavar="name")] = "default",
        client_secret: Annotated[Optional[Path], opt("--client-secret", key="client_secret", metavar="path")] = None,
        no_browser: Annotated[bool, opt("--no-browser", key="no_browser")] = False,
    ) -> None:
        from .auth_gmail import run_wizard

        run_wizard(get_app(), account, client_secret, no_browser)

    @sub(auth, "imap", "auth_imap")
    @handle_errors
    def auth_imap(
        name: Annotated[str, opt("--name", key="imap_name", metavar="name")],
        host: Annotated[str, opt("--host", key="imap_host", metavar="host")],
        user: Annotated[str, opt("--user", key="imap_user", metavar="user")],
        port: Annotated[int, opt("--port", key="imap_port", metavar="n")] = 993,
        no_ssl: Annotated[bool, opt("--no-ssl", key="imap_no_ssl")] = False,
        starttls: Annotated[bool, opt("--starttls", key="imap_starttls")] = False,
        folder: Annotated[Optional[list[str]], opt("--folder", key="imap_folder", metavar="folder")] = None,
        test: Annotated[bool, opt("--test/--no-test", key="imap_test")] = True,
        password_stdin: Annotated[bool, opt("--password-stdin", key="password_stdin")] = False,
    ) -> None:
        from .. import secrets
        from ..config.schema import ImapAccount
        from ..sources.imap import test_login
        from .tomledit import upsert_imap_account

        a = get_app()
        account = ImapAccount(name=name, host=host, username=user, port=port, ssl=not no_ssl,
                              starttls=starttls, folders=list(folder or ["INBOX"]))
        say(t("cli.auth.imap_intro", host=host), "bold")
        say(t("cli.auth.imap_app_password"), "dim")
        password = sys.stdin.readline().rstrip("\n") if password_stdin else ask(t("cli.auth.imap_password"), secret=True)
        if not password:
            raise typer.Abort()
        if test:
            with console.status(t("cli.auth.imap_testing")):
                folders = test_login(account, password)
            ok(t("cli.auth.imap_ok", count=len(folders)))
            missing = [f for f in account.folders if f not in folders]
            if missing:
                warn(t("cli.auth.imap_missing_folders", folders=", ".join(missing),
                       available=", ".join(folders[:15])))
        secrets.put(secrets.imap_password_name(name), password)
        upsert_imap_account(a.loaded.path, account)
        ok(t("cli.auth.imap_saved", name=name))
        say(t("cli.auth.next_scan"), "dim")

    @sub(auth, "ai", "auth_ai")
    @handle_errors
    def auth_ai(
        provider: Annotated[Optional[str], opt("--provider", key="ai_provider", metavar="name")] = None,
    ) -> None:
        from .. import secrets

        a = get_app()
        prov = provider or a.config.ai.provider
        key = ask(t("cli.auth.ai_key", provider=prov), secret=True)
        if not key:
            raise typer.Abort()
        secrets.put(secrets.ai_key_name(prov), key.strip())
        ok(t("cli.auth.ai_saved", provider=prov))

    @sub(auth, "status", "auth_status")
    @handle_errors
    def auth_status() -> None:
        from .. import secrets
        from ..ai import needs_key

        a = get_app()
        cfg = a.config
        gm = cfg.sources.gmail
        has = secrets.exists(secrets.gmail_token_name(gm.account))
        say(t("cli.auth.status_gmail", state=t("cli.auth.on") if gm.enabled else t("cli.auth.off"),
              token=t("cli.auth.token_yes") if has else t("cli.auth.token_no"), account=gm.account))
        for acc in cfg.sources.imap.accounts:
            has = secrets.exists(secrets.imap_password_name(acc.name))
            say(t("cli.auth.status_imap", name=acc.name, user=acc.username, host=acc.host,
                  token=t("cli.auth.token_yes") if has else t("cli.auth.token_no")))
        if not cfg.sources.imap.accounts:
            say(t("cli.auth.status_no_imap"), "dim")
        if cfg.ai.enabled and needs_key(cfg.ai):
            has = secrets.exists(secrets.ai_key_name(cfg.ai.provider))
            say(t("cli.auth.status_ai", provider=cfg.ai.provider,
                  token=t("cli.auth.token_yes") if has else t("cli.auth.token_no")))

    @sub(auth, "revoke", "auth_revoke")
    @handle_errors
    def auth_revoke(
        what: Annotated[str, arg("revoke_what", "what")] = "all",
        name: Annotated[Optional[str], arg("revoke_name", "name")] = None,
        yes: Annotated[bool, opt("--yes", "-y", key="yes")] = False,
    ) -> None:
        from .. import secrets
        from ..sources.gmail import revoke

        a = get_app()
        cfg = a.config
        if what not in ("gmail", "imap", "ai", "all"):
            raise SubwatchError("cli.err.bad_revoke", value=what)
        if not confirm(t("cli.auth.revoke_confirm", what=what), assume_yes=yes):
            raise typer.Abort()
        if what in ("gmail", "all"):
            done = revoke(cfg.sources.gmail.account)
            say(t("cli.auth.revoked_gmail") if done else t("cli.auth.revoked_gmail_local"))
            if cfg.sources.gmail.enabled and a.loaded.path.exists():
                from ..config.editor import set_value

                set_value("sources.gmail.enabled", "false", a.loaded.path)
        if what in ("imap", "all"):
            for acc in cfg.sources.imap.accounts:
                if name and acc.name != name:
                    continue
                secrets.delete(secrets.imap_password_name(acc.name))
                say(t("cli.auth.revoked_imap", name=acc.name, host=acc.host))
        if what in ("ai", "all"):
            secrets.delete(secrets.ai_key_name(cfg.ai.provider))
            say(t("cli.auth.revoked_ai", provider=cfg.ai.provider))
        if what in ("gmail", "imap"):
            a.store.clear_cursors(what)
        elif what == "all":
            a.store.clear_cursors()
        ok(t("cli.auth.revoke_done"))

    # ------------------------------------------------------------- review

    review = make("cli.review.help", invoke_without_command=True)
    app.add_typer(review, name="review", help=t("cli.review.help"), short_help=t("cli.review.short"))

    @review.callback()
    @handle_errors
    def review_root(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            if sys.stdin.isatty():
                _review_interactive()
            else:
                _review_list(False)

    @sub(review, "list", "review_list")
    @handle_errors
    def review_list(as_json: Annotated[bool, opt("--json", key="json")] = False) -> None:
        _review_list(as_json)

    @sub(review, "confirm", "review_confirm")
    @handle_errors
    def review_confirm(ref: Annotated[str, arg("ref", "ref")]) -> None:
        a = get_app()
        sub_ = _review_item(a, ref)
        _decide(a, sub_, True)
        ok(t("cli.review.confirmed", service=sub_.service))

    @sub(review, "reject", "review_reject")
    @handle_errors
    def review_reject(ref: Annotated[str, arg("ref", "ref")]) -> None:
        a = get_app()
        sub_ = _review_item(a, ref)
        _decide(a, sub_, False)
        ok(t("cli.review.rejected", service=sub_.service))

    # ------------------------------------------------------------- import

    @app.command("import", help=t("cli.import.help"), short_help=t("cli.import.short"),
                 options_metavar=t("cli.chrome.options_metavar"))
    @handle_errors
    def import_command(
        files: Annotated[list[Path], arg("files", "path")],
        bank: Annotated[Optional[str], opt("--bank", "-b", key="bank", metavar="bank")] = None,
        mapping: Annotated[Optional[str], opt("--map", key="map", metavar="mapping")] = None,
        date_format: Annotated[Optional[str], opt("--date-format", key="date_format", metavar="format")] = None,
        delimiter: Annotated[Optional[str], opt("--delimiter", key="delimiter", metavar="char")] = None,
        encoding: Annotated[Optional[str], opt("--encoding", key="encoding", metavar="name")] = None,
        currency: Annotated[Optional[str], opt("--currency", key="currency", metavar="currency")] = None,
        save_template: Annotated[Optional[str], opt("--save-template", key="save_template", metavar="name")] = None,
        dry_run: Annotated[bool, opt("--dry-run", key="dry_run")] = False,
        force: Annotated[bool, opt("--force", key="force_import")] = False,
    ) -> None:
        from .import_cmd import run_import

        run_import(get_app(), files, bank, mapping, date_format, delimiter, encoding, currency,
                   save_template, dry_run, force)

    @app.command("banks", help=t("cli.banks.help"), short_help=t("cli.banks.short"),
                 options_metavar=t("cli.chrome.options_metavar"))
    @handle_errors
    def banks_command() -> None:
        from ..sources.statements import load_templates

        for tpl in load_templates().values():
            say(t("cli.banks.line", name=tpl.name, title=tpl.title, format=tpl.format,
                  origin=t("cli.banks.user") if tpl.user else t("cli.banks.builtin")))

    # -------------------------------------------------------------- rates

    rates = group("rates")

    @sub(rates, "show", "rates_show")
    @handle_errors
    def rates_show() -> None:
        from ..fmt import format_number

        a = get_app()
        r = a.rates()
        say(t("cli.rates.header", base=r.base, source=r.source,
              when=clock.iso(r.fetched_at) if r.fetched_at else "—",
              stale=t("cli.rates.stale") if r.stale else ""), "bold")
        used = sorted({s.currency for s in a.store.subscriptions() if s.currency})
        for code in used or sorted(r.table)[:15]:
            if code == r.base:
                continue
            rate = r.rate(code)
            manual = code in r.from_manual
            say(t("cli.rates.line", code=code, rate=format_number(rate, 4) if rate else "—", base=r.base,
                  manual=t("cli.rates.manual") if manual else ""))

    @sub(rates, "update", "rates_update")
    @handle_errors
    def rates_update() -> None:
        a = get_app()
        r = a.rates(allow_network=True, force=True)
        if r.stale:
            warn(t("cli.rates.update_failed"))
            raise typer.Exit(1)
        ok(t("cli.rates.updated", source=r.source, count=len(r.table)))

    @sub(rates, "set", "rates_set")
    @handle_errors
    def rates_set(
        code: Annotated[str, arg("code", "currency")],
        rate: Annotated[str, arg("rate", "amount")],
    ) -> None:
        from ..config.editor import ensure_config_file, set_value

        a = get_app()
        path, _ = ensure_config_file(a.loaded.path)
        set_value(f"currency.manual_rates.{code.upper()}", rate.replace(",", "."), path)
        ok(t("cli.rates.set_done", code=code.upper(), rate=rate, base=a.config.currency.base))

    # ------------------------------------------------------------- export

    export = group("export")

    def _export(kind: str, output: Optional[Path], include_all: bool) -> None:
        from ..export import build_ics, subscription_rows, to_csv, to_json, write_ics

        a = get_app()
        subs = a.store.subscriptions(include_cancelled=include_all)
        if kind == "ics":
            if output is None:
                path = write_ics(subs, a.config)
                ok(t("cli.export.ics_written", path=paths.contract_home(path)))
                say(t("cli.export.ics_subscribe", url=path.as_uri()), "dim")
                return
            text = build_ics(subs, a.config)
        else:
            rows = subscription_rows(subs, a.config, a.rates())
            text = to_csv(rows) if kind == "csv" else to_json(rows, a.config)
        if output is None or str(output) == "-":
            sys.stdout.write(text)
        else:
            output.write_text(text, encoding="utf-8")
            ok(t("cli.export.written", path=paths.contract_home(output)))

    @sub(export, "csv", "export_csv")
    @handle_errors
    def export_csv(output: Annotated[Optional[Path], opt("--output", "-o", key="output", metavar="path")] = None,
                   all_: Annotated[bool, opt("--all", "-a", key="all")] = False) -> None:
        _export("csv", output, all_)

    @sub(export, "json", "export_json")
    @handle_errors
    def export_json(output: Annotated[Optional[Path], opt("--output", "-o", key="output", metavar="path")] = None,
                    all_: Annotated[bool, opt("--all", "-a", key="all")] = False) -> None:
        _export("json", output, all_)

    @sub(export, "ics", "export_ics")
    @handle_errors
    def export_ics(output: Annotated[Optional[Path], opt("--output", "-o", key="output", metavar="path")] = None) -> None:
        _export("ics", output, False)

    # ------------------------------------------------------------- budget

    budget = make("cli.budget.help", invoke_without_command=True)
    app.add_typer(budget, name="budget", help=t("cli.budget.help"), short_help=t("cli.budget.short"))

    @budget.callback()
    @handle_errors
    def budget_root(ctx: typer.Context) -> None:
        if ctx.invoked_subcommand is None:
            from ..analysis import budget_status, totals
            from ..fmt import format_money

            a = get_app()
            cfg = a.config
            tot = totals(a.store.subscriptions(), a.rates(), cfg)
            statuses = budget_status(tot, cfg)
            if not statuses:
                say(t("cli.budget.none"))
                say(t("cli.budget.none_hint"), "dim")
            for st in statuses:
                name = t("bar.tip_budget_total") if st.scope == "total" else cfg.category_name(st.scope)
                style = {"ok": "green", "warn": "yellow", "over": "bold red"}[st.level]
                say(t(f"bar.tip_budget_{st.level}", name=name,
                      spent=format_money(st.spent, cfg.currency.base, 0),
                      limit=format_money(st.limit, cfg.currency.base, 0)), style)

    @sub(budget, "set", "budget_set")
    @handle_errors
    def budget_set(
        amount: Annotated[str, arg("budget_amount", "amount")],
        category: Annotated[Optional[str], opt("--category", key="category", metavar="category")] = None,
    ) -> None:
        from ..config.editor import ensure_config_file, set_value
        from ..money import parse_number
        from .main import parse_category

        a = get_app()
        value = parse_number(amount)
        if value is None:
            raise SubwatchError("cli.err.bad_amount", hint="cli.hint.amount_formats", value=amount)
        path, _ = ensure_config_file(a.loaded.path)
        if category:
            key = parse_category(category, a.config)
            set_value(f"categories.{key}.budget", str(value), path)
        else:
            set_value("budget.monthly_limit", str(value), path)
        ok(t("cli.budget.set_done"))

    # -------------------------------------------------------------- rules

    rules = group("rules")

    @sub(rules, "list", "rules_list")
    @handle_errors
    def rules_list() -> None:
        a = get_app()
        rows = a.store.rules()
        if not rows:
            say(t("cli.rules.none"))
            return
        for r in rows:
            say(t("cli.rules.line", id=r["id"], kind=t(f"cli.rules.kind.{r['kind']}"), pattern=r["pattern"],
                  value=r["value"] or "", origin=t(f"cli.rules.origin.{r['origin']}")))

    @sub(rules, "remove", "rules_remove")
    @handle_errors
    def rules_remove(rule_id: Annotated[int, arg("rule_id", "id")]) -> None:
        a = get_app()
        if not a.store.remove_rule(rule_id):
            raise NotFoundError("cli.rules.not_found", id=rule_id)
        ok(t("cli.rules.removed", id=rule_id))

    @sub(rules, "add", "rules_add")
    @handle_errors
    def rules_add(
        kind: Annotated[str, arg("rule_kind", "kind")],
        pattern: Annotated[str, arg("rule_pattern", "pattern")],
        value: Annotated[Optional[str], arg("rule_value", "value")] = None,
    ) -> None:
        from ..models import service_key

        kinds = ("ignore_service", "ignore_sender", "accept_service", "alias", "category")
        if kind not in kinds:
            raise SubwatchError("cli.rules.bad_kind", value=kind, known=", ".join(kinds))
        a = get_app()
        stored = pattern.lower() if kind == "ignore_sender" else service_key(pattern)
        a.store.add_rule(kind, stored, value)
        ok(t("cli.rules.added", kind=t(f"cli.rules.kind.{kind}"), pattern=pattern))

    # ------------------------------------------------------------ plugins

    plugins = group("plugins")

    @sub(plugins, "list", "plugins_list")
    @handle_errors
    def plugins_list() -> None:
        from ..sources.base import PLUGIN_ERRORS, PLUGIN_FILES, available, load_plugins

        a = get_app()
        load_plugins(a.config)
        for name, src in available(a.config).items():
            state = t("cli.plugins.enabled") if src.enabled(a.config) else t("cli.plugins.disabled")
            origin = t("cli.plugins.builtin") if src.builtin else paths.contract_home(PLUGIN_FILES.get(name, ""))
            say(t("cli.plugins.line", name=name, kind=t(f"cli.plugins.kind.{src.kind}"), state=state,
                  origin=origin))
        for path, error in PLUGIN_ERRORS.items():
            warn(t("doctor.plugins.error", path=paths.contract_home(path), detail=error))
        say(t("cli.plugins.dir", path=paths.contract_home(paths.plugins_dir())), "dim")

    # ----------------------------------------------------------------- ai

    ai = group("ai")

    @sub(ai, "test", "ai_test")
    @handle_errors
    def ai_test(
        file: Annotated[Path, arg("eml", "path")],
        dry_run: Annotated[bool, opt("--dry-run", key="ai_test_dry")] = False,
    ) -> None:
        from ..ai import AIExtractor, merge
        from ..extract.engine import Context, analyse
        from ..extract.text import parse_email
        from ..fmt import format_money, format_period
        from .main import _print_ai_dry_run

        a = get_app()
        if not file.exists():
            raise NotFoundError("cli.err.no_file", path=str(file))
        msg = parse_email(file.read_bytes(), "file", f"file:{file.name}")
        ctx = Context.build(a.config, a.book, a.learned())
        res = analyse(msg, ctx)
        det = res.detection
        if det:
            say(t("cli.ai.rules_found", service=det.service, confidence=round(det.confidence * 100),
                  amount=format_money(det.amount, det.currency) if det.amount is not None else "—",
                  period=format_period(det.period) if det.period else "—"))
        else:
            say(t("cli.ai.rules_none"))
        extractor = AIExtractor(a.config, None if dry_run else a.store, dry_run=dry_run)
        if not a.config.ai.enabled and not dry_run:
            raise SubwatchError("cli.ai.disabled", hint="cli.ai.enable_hint")
        ai_det = extractor.extract(msg, res.text)
        if dry_run:
            _print_ai_dry_run(extractor.dry_runs)
            return
        if extractor.disabled_reason:
            raise SubwatchError("cli.ai.unavailable", reason=extractor.disabled_reason)
        merged = merge(det, ai_det)
        if ai_det is None:
            say(t("cli.ai.model_none"))
        if merged:
            say(t("cli.ai.result", service=merged.service, confidence=round(merged.confidence * 100),
                  amount=format_money(merged.amount, merged.currency) if merged.amount is not None else "—",
                  period=format_period(merged.period) if merged.period else "—"), "bold")

    # ----------------------------------------------------------- keybinds

    keybinds = group("keybinds")

    @sub(keybinds, "apply", "keybinds_apply")
    @handle_errors
    def keybinds_apply(dry_run: Annotated[bool, opt("--dry-run", key="dry_run")] = False) -> None:
        from ..integrate import hyprland
        from .render import print_steps

        steps = hyprland.apply(get_app().config, dry_run=dry_run)
        print_steps(steps)
        if any(s.status == "failed" for s in steps):
            raise typer.Exit(1)

    @sub(keybinds, "show", "keybinds_show")
    @handle_errors
    def keybinds_show() -> None:
        from ..integrate import hyprland

        items, steps = hyprland.plan(get_app().config)
        for item in items:
            state = t("cli.keybinds.conflict", what=item.conflict) if item.conflict else t("cli.keybinds.free")
            say(t("cli.keybinds.line", combo=str(item.combo), desc=item.description, state=state),
                "yellow" if item.conflict else None)
        for s in steps:
            warn(t(s.key, **s.params))

    @sub(keybinds, "check", "keybinds_check")
    @handle_errors
    def keybinds_check() -> None:
        from ..integrate import hyprland

        items, steps = hyprland.plan(get_app().config)
        conflicts = [i for i in items if i.conflict]
        for i in conflicts:
            warn(t("integrate.keys.conflict", combo=str(i.combo), what=i.conflict,
                   action=i.description))
        for s in steps:
            warn(t(s.key, **s.params))
        if conflicts or steps:
            raise typer.Exit(1)
        ok(t("cli.keybinds.no_conflicts"))

    @sub(keybinds, "remove", "keybinds_remove")
    @handle_errors
    def keybinds_remove() -> None:
        from ..integrate import hyprland
        from .render import print_steps

        print_steps(hyprland.remove())

    # ---------------------------------------------------------- integrate

    integ = group("integrate")

    @sub(integ, "apply", "integrate_apply")
    @handle_errors
    def integrate_apply(
        only: Annotated[Optional[list[str]], opt("--only", key="only", metavar="component")] = None,
        dry_run: Annotated[bool, opt("--dry-run", key="dry_run")] = False,
    ) -> None:
        from ..integrate import COMPONENTS, apply_all
        from .render import print_steps

        bad = [o for o in only or [] if o not in COMPONENTS]
        if bad:
            raise SubwatchError("cli.err.bad_component", value=", ".join(bad), known=", ".join(COMPONENTS))
        a = get_app()
        steps = apply_all(a.config, only, dry_run)
        if not State.quiet:
            print_steps(steps)
        from .. import bar

        bar.invalidate_cache()
        if any(s.status == "failed" for s in steps):
            raise typer.Exit(1)

    @sub(integ, "remove", "integrate_remove")
    @handle_errors
    def integrate_remove(
        only: Annotated[Optional[list[str]], opt("--only", key="only", metavar="component")] = None,
        dry_run: Annotated[bool, opt("--dry-run", key="dry_run")] = False,
    ) -> None:
        from ..integrate import remove_all
        from .render import print_steps

        print_steps(remove_all(only, dry_run))

    @sub(integ, "status", "integrate_status")
    @handle_errors
    def integrate_status() -> None:
        from .. import doctor
        from .render import print_checks

        a = get_app()
        checks = doctor.check_systemd(a.config) + doctor.check_integration(a.config)
        print_checks(checks)

    # ---------------------------------------------------------- completion

    completion = group("completion")

    @sub(completion, "show", "completion_show")
    @handle_errors
    def completion_show(shell: Annotated[str, arg("shell", "shell")] = "bash") -> None:
        from ..integrate import completion_source

        if shell not in ("bash", "zsh", "fish"):
            raise SubwatchError("cli.err.bad_shell", value=shell)
        sys.stdout.write(completion_source(shell))

    @sub(completion, "install", "completion_install")
    @handle_errors
    def completion_install() -> None:
        from ..integrate import apply_completion
        from .render import print_steps

        print_steps(apply_completion())


# -------------------------------------------------------------- helpers


def _flat_keys(data: dict, prefix: str = "") -> list[str]:
    out = []
    for k, v in data.items():
        if isinstance(v, dict):
            out += _flat_keys(v, f"{prefix}{k}.")
        else:
            out.append(prefix + k)
    return out


def _review_item(a, ref: str):
    from .main import _resolve

    sub = _resolve(a.store, ref)
    if sub.status != "review":
        raise SubwatchError("cli.review.not_in_queue", service=sub.service)
    return sub


def _decide(a, sub, accepted: bool) -> None:
    from ..hooks import run_hooks
    from ..ingest import remember_review_decision

    remember_review_decision(a.store, sub, accepted)
    if accepted:
        sub.status = "active"
        sub.review_reason = None
        sub.confidence = max(sub.confidence, a.config.extraction.auto_accept)
        a.store.update_subscription(sub)
        run_hooks(a.config, "new_subscription", sub, {"via": "review"})
    else:
        a.store.delete_subscription(sub.id or 0)
    a.after_change()


def _review_list(as_json: bool) -> None:
    from ..export import subscription_rows
    from .render import subscriptions_table

    a = get_app()
    items = a.store.review_queue()
    if as_json:
        sys.stdout.write(json.dumps(subscription_rows(items, a.config, a.rates()), ensure_ascii=False,
                                    indent=2) + "\n")
        return
    if not items:
        say(t("cli.review.empty"))
        return
    say(t("cli.review.title", count=tn("fmt.units.item", len(items))), "bold")
    console.print(subscriptions_table(items, a.config, a.rates()))
    say(t("cli.review.hint"), "dim")


def _review_interactive() -> None:
    from .render import subscription_details

    a = get_app()
    items = a.store.review_queue()
    if not items:
        say(t("cli.review.empty"))
        return
    rates = a.rates()
    for i, sub in enumerate(items, 1):
        say(t("cli.review.item_header", n=i, total=len(items)), "bold")
        console.print(subscription_details(sub, a.config, rates))
        answer = ask(t("cli.review.prompt")).strip().lower()
        if answer in tuple(t("cli.review.answers_yes").split(",")):
            _decide(a, sub, True)
            ok(t("cli.review.confirmed", service=sub.service))
        elif answer in tuple(t("cli.review.answers_no").split(",")):
            _decide(a, sub, False)
            ok(t("cli.review.rejected", service=sub.service))
        elif answer in tuple(t("cli.review.answers_quit").split(",")):
            break
        say("")
