"""`subwatch import`: statements in, recurring charges out."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import typer

from .. import paths
from ..errors import NotFoundError, SubwatchError
from ..i18n import t, tn
from .common import ask, console, ok, say, warn


def _interactive_mapping(path: Path, encoding: str | None, delimiter: str | None) -> str:
    from ..sources.statements import csv_headers

    headers = csv_headers(path, encoding or "auto", delimiter or "auto")
    if not headers:
        raise SubwatchError("statements.err.no_headers", path=str(path))
    say(t("cli.import.headers_title"), "bold")
    for i, h in enumerate(headers, 1):
        say(f"  {i}. {h}")

    def pick(question: str, required: bool = True) -> str:
        while True:
            answer = ask(question).strip()
            if not answer and not required:
                return ""
            if answer.isdigit() and 1 <= int(answer) <= len(headers):
                return headers[int(answer) - 1]
            if answer in headers:
                return answer
            warn(t("cli.import.bad_column"))

    date = pick(t("cli.import.ask_date"))
    amount = pick(t("cli.import.ask_amount"))
    desc = pick(t("cli.import.ask_description"))
    currency = pick(t("cli.import.ask_currency"), required=False)
    mapping = f"date={date},amount={amount},description={desc}"
    if currency:
        mapping += f",currency={currency}"
    return mapping


def run_import(app, files: list[Path], bank, mapping, date_format, delimiter, encoding, currency,
               save_template, dry_run: bool, force: bool) -> None:
    from ..recurrence import detect_recurring
    from ..scan import react
    from ..sources.statements import (
        BankTemplate, detect_template, file_sha256, load_templates, read_statement, template_from_mapping,
    )

    cfg = app.config
    store = app.store
    templates = load_templates()
    forced: BankTemplate | None = None
    if bank:
        forced = templates.get(bank)
        if forced is None:
            raise NotFoundError("statements.err.no_template", hint="statements.hint.bank", name=bank)
    all_new = []
    for path in files:
        if not path.exists():
            raise NotFoundError("cli.err.no_file", path=str(path))
        sha = file_sha256(path)
        if store.is_imported(sha) and not force and not dry_run:
            say(t("cli.import.already", path=path.name), "dim")
            continue
        tpl = forced
        if mapping:
            tpl = template_from_mapping(mapping, forced, date_format=date_format,
                                        delimiter=delimiter, encoding=encoding,
                                        currency=currency.upper() if currency else None)
        elif tpl is None and path.suffix.lower() != ".pdf":
            from ..sources.statements import _decode

            if detect_template(path, _decode(path.read_bytes(), encoding or "auto"), templates) is None:
                if not sys.stdin.isatty():
                    raise SubwatchError("statements.err.unknown_format", hint="statements.hint.bank",
                                        path=str(path))
                say(t("cli.import.unknown", path=path.name), "yellow")
                mapping = _interactive_mapping(path, encoding, delimiter)
                fmt = date_format or ask(t("cli.import.ask_date_format"), "").strip() or None
                tpl = template_from_mapping(mapping, None, date_format=fmt, delimiter=delimiter,
                                            encoding=encoding, currency=currency.upper() if currency else None)
        elif tpl is not None:
            for attr, value in (("date_format", date_format), ("delimiter", delimiter), ("encoding", encoding)):
                if value:
                    setattr(tpl, attr, value)
            if currency:
                tpl.currency = currency.upper()
        result = read_statement(path, cfg, tpl, templates)
        say(t("cli.import.parsed", path=path.name, template=result.template.title or result.template.name,
              rows=result.rows, debits=tn("fmt.units.transaction", len(result.transactions)),
              skipped=result.skipped))
        if save_template and (mapping or tpl is not None):
            target = paths.banks_dir() / f"{save_template}.toml"
            paths.ensure_private_dir(target.parent)
            saved = BankTemplate(**{**result.template.__dict__, "name": save_template,
                                    "title": save_template})
            if not saved.detect_headers and saved.format == "csv":
                saved.detect_headers = [h for h in (saved.date, saved.amount, saved.description) if h]
            target.write_text(saved.to_toml(), encoding="utf-8")
            ok(t("cli.import.template_saved", path=paths.contract_home(target)))
        if not dry_run:
            inserted = store.add_transactions(result.transactions)
            store.mark_imported(sha, path.name, result.template.name, result.rows, len(result.transactions))
            say(t("cli.import.stored", count=tn("fmt.units.transaction", inserted)), "dim")
        all_new += result.transactions
    if not all_new and not dry_run:
        return
    from datetime import timedelta

    from .. import clock
    from ..classify import assign_category, assign_tags
    from ..extract.engine import Learned, service_excluded
    from ..ingest import Ingestor

    history = store.transactions(since=clock.today() - timedelta(days=cfg.sources.statements.keep_transactions_days))
    if dry_run:
        history = history + all_new
    detections = detect_recurring(history, cfg, app.book)
    learned = Learned.from_store(store)
    if not detections:
        say(t("cli.import.none_found"))
        return
    stats: Counter = Counter()
    events = []
    ingestor = Ingestor(store, cfg, learned)
    from ..fmt import format_money, format_period

    for det in detections:
        if service_excluded(det.service, ingestor):
            continue
        category = assign_category(det.service, cfg, learned, None, "", det.category)
        if dry_run:
            say(t("cli.import.would", service=det.service, amount=format_money(det.amount, det.currency),
                  period=format_period(det.period), confidence=round(det.confidence * 100)))
            continue
        res = ingestor.ingest(det, category, assign_tags(det.service, category, cfg))
        stats[res.action] += 1
        events += res.events
        if res.action in ("created", "review", "promoted"):
            say(t("cli.import.found", service=det.service, amount=format_money(det.amount, det.currency),
                  period=format_period(det.period),
                  status=t("status.active") if res.action != "review" else t("status.review")))
    if dry_run:
        return
    react(app, events, None, stats)
    ok(t("cli.import.summary", created=stats.get("created", 0) + stats.get("promoted", 0),
         review=stats.get("review", 0), updated=stats.get("updated", 0) + stats.get("duplicate", 0)))
    console.print()
    if stats.get("review"):
        say(t("cli.list.review_hint", count=tn("fmt.units.item", stats["review"])), "yellow")
    raise typer.Exit(0)
