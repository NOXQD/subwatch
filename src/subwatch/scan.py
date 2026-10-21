"""The scan job: fetch from sources, extract, store, react."""

from __future__ import annotations

import time
import traceback
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from . import analysis, clock, hooks, log, reminders
from .ai import AIExtractor, merge
from .app import AppContext
from .classify import assign_category, assign_tags
from .errors import SubwatchError
from .extract.engine import Context, analyse, sender_excluded, service_excluded
from .i18n import t, tn
from .ingest import Event, Ingestor
from .lock import lower_priority, single_instance
from .models import Detection, RawMessage, Transaction
from .notify import Notification, self_command, send
from .sources.base import SourceContext, available, load_plugins


@dataclass
class ScanReport:
    stats: dict[str, Counter] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    would: list[tuple[Detection, str]] = field(default_factory=list)
    ai: AIExtractor | None = None
    seconds: float = 0.0
    dry_run: bool = False

    def total(self, key: str) -> int:
        return sum(c.get(key, 0) for c in self.stats.values())


class _DryStore:
    """Read-through wrapper that drops every write (for --dry-run)."""

    def __init__(self, store):
        self._store = store

    def __getattr__(self, name: str):
        if name.startswith(("set_", "mark_", "add_", "insert_", "update_", "delete_", "save_",
                            "log_", "ack_", "ensure_", "clear_", "forget_", "purge_", "drop_")):
            return lambda *a, **k: None
        return getattr(self._store, name)


def make_prefilter(ctx: Context) -> Callable[[str, str], bool]:
    """Cheap header check before a body is downloaded."""
    domains = {s for m in ctx.book.merchants for s in m.senders if "@" not in s}
    groups = ("subscription", "paid", "renewal", "cancellation", "trial", "price_change")

    def check(sender: str, subject: str) -> bool:
        if sender_excluded(sender, ctx):
            return False
        domain = sender.rpartition("@")[2]
        parts = domain.split(".")
        for i in range(len(parts) - 1):
            if ".".join(parts[i:]) in domains:
                return True
        cf = (subject or "").casefold()
        if any(ctx.keywords.any(cf, g) for g in groups):
            return True
        return any(rx.search(cf) for m in ctx.book.merchants if not m.generic for rx in m.patterns)

    return check


class Scanner:
    def __init__(self, app: AppContext, dry_run: bool = False, ai_dry_run: bool = False,
                 no_ai: bool = False, reprocess: bool = False):
        self.app = app
        self.config = app.config
        self.dry_run = dry_run or ai_dry_run
        self.reprocess = reprocess
        self.store = _DryStore(app.store) if self.dry_run else app.store
        self.ctx = Context.build(self.config, app.book, app.learned())
        self.ingestor = Ingestor(app.store, self.config, self.ctx.learned)
        use_ai = (self.config.ai.enabled or ai_dry_run) and not no_ai
        self.ai = AIExtractor(self.config, self.store if not self.dry_run else None,
                              dry_run=ai_dry_run) if use_ai else None
        self.report = ScanReport(ai=self.ai, dry_run=self.dry_run)
        self.transactions: list[Transaction] = []

    # ----------------------------------------------------------- messages

    def process_message(self, msg: RawMessage, stats: Counter) -> None:
        stats["seen"] += 1
        if not self.reprocess and self.app.store.is_processed(msg.source, msg.key):
            stats["already"] += 1
            return
        result = analyse(msg, self.ctx)
        det = result.detection
        if result.skipped:
            stats["filtered"] += 1
        if self.ai is not None and result.signals and (
            det is None or det.confidence < self.config.extraction.auto_accept
        ):
            ai_det = self.ai.extract(msg, result.text)
            if ai_det is not None:
                stats["ai"] += 1
            det = merge(det, ai_det)
        outcome = "no_match"
        if det is not None:
            stats["detections"] += 1
            if service_excluded(det.service, self.ctx):
                outcome = "excluded"
                stats["filtered"] += 1
            else:
                text_cf = result.text.casefold()
                category = assign_category(det.service, self.config, self.ctx.learned, det.sender,
                                           text_cf, det.category)
                amount_base = None
                if det.amount is not None:
                    amount_base = self.app.rates().convert(det.amount, det.currency)
                tags = assign_tags(det.service, category, self.config, det.sender, text_cf, amount_base)
                if self.dry_run:
                    self.report.would.append((det, category))
                    outcome = "dry_run"
                else:
                    res = self.ingestor.ingest(det, category, tags)
                    stats[res.action] += 1
                    self.report.events.extend(res.events)
                    outcome = res.action
        if not self.dry_run:
            self.app.store.mark_processed(msg.source, msg.key, outcome)

    # -------------------------------------------------------------- run

    def run(self, only: list[str] | None = None, full: bool = False, months: int | None = None,
            progress: Callable[[str, int], None] | None = None) -> ScanReport:
        started = time.monotonic()
        load_plugins(self.config)
        sources = available(self.config)
        months = months or self.config.scan.months_back
        since = clock.today() - timedelta(days=int(months * 30.44))
        prefilter = make_prefilter(self.ctx)
        for name, src in sources.items():
            if only and name not in only:
                continue
            if not only and not src.enabled(self.config):
                continue
            if src.kind == "manual":
                continue
            stats: Counter = Counter()
            self.report.stats[name] = stats
            sctx = SourceContext(
                config=self.config, store=self.store, since=since, full=full,
                max_messages=self.config.scan.max_messages,
                options=dict(self.config.plugins.options.get(name, {})),
                prefilter=prefilter, progress=progress,
            )
            log.info("scan_source_started", source=name)
            try:
                for item in src.fetch(sctx):
                    if isinstance(item, Transaction):
                        stats["transactions"] += 1
                        self.transactions.append(item)
                    elif isinstance(item, RawMessage):
                        self.process_message(item, stats)
                    if progress:
                        progress(name, stats["seen"] + stats["transactions"])
            except SubwatchError as exc:
                self._fail(name, exc.message + (f" {exc.hint_text}" if exc.hint_text else ""))
            except Exception as exc:  # a broken source must not stop the others
                log.error("scan_source_crashed", source=name, error=repr(exc),
                          trace=traceback.format_exc(limit=5))
                self._fail(name, t("scan.err.crashed", source=name, detail=repr(exc)))
            log.info("scan_source_finished", source=name, **{k: v for k, v in stats.items()})
        if self.transactions:
            self._ingest_transactions()
        self.report.seconds = time.monotonic() - started
        return self.report

    def _fail(self, source: str, message: str) -> None:
        self.report.errors.append((source, message))
        log.error("scan_failed", source=source, error=message)

    def _ingest_transactions(self) -> None:
        from .recurrence import detect_recurring

        store = self.app.store
        if not self.dry_run:
            store.add_transactions(self.transactions)
        history = store.transactions(since=clock.today() - timedelta(
            days=self.config.sources.statements.keep_transactions_days))
        if self.dry_run:
            history = history + self.transactions
        stats = self.report.stats.setdefault("recurrence", Counter())
        for det in detect_recurring(history, self.config, self.app.book):
            stats["detections"] += 1
            if service_excluded(det.service, self.ctx):
                continue
            category = assign_category(det.service, self.config, self.ctx.learned, None, "",
                                       det.category)
            tags = assign_tags(det.service, category, self.config)
            if self.dry_run:
                self.report.would.append((det, category))
                continue
            res = self.ingestor.ingest(det, category, tags)
            stats[res.action] += 1
            self.report.events.extend(res.events)


# ------------------------------------------------------------- reactions


def _notify(app: AppContext, enabled: bool, summary: str, body: str, kind: str,
            urgency: str | None = None) -> None:
    if enabled:
        send(Notification(summary=summary, body=body, kind=kind,
                          urgency=urgency or app.config.notifications.urgency,
                          click=self_command() + ["open"]), app.config.notifications)


def react(app: AppContext, events: list[Event], errors: list[tuple[str, str]] | None = None,
          summary: Counter | None = None) -> dict[str, Any]:
    """Hooks, notifications and derived findings after data changed."""
    cfg = app.config
    store = app.store
    out: dict[str, Any] = {"duplicates": [], "zombies": [], "budget": []}
    for ev in events:
        hooks.run_hooks(cfg, ev.name, ev.subscription, ev.data)
        if ev.name == "price_changed" and ev.subscription is not None:
            sub = ev.subscription
            from .fmt import format_money

            _notify(app, cfg.notifications.on_price_change,
                    t("notify.price.summary", service=sub.service),
                    t("notify.price.body", old=format_money(ev.data.get("old"), sub.currency),
                      new=format_money(ev.data.get("new"), sub.currency)), "price")
        store.add_event(ev.name, ev.subscription.id if ev.subscription else None, ev.data)

    subs = store.subscriptions()
    for dup in analysis.find_duplicates(subs, cfg, app.book):
        seen = any(r["payload"] and dup.key in r["payload"] for r in store.events("duplicate_found", 500))
        if seen:
            continue
        payload = {"pair": dup.key, "reason": dup.reason, "a": dup.a.service, "b": dup.b.service}
        store.add_event("duplicate_found", dup.a.id, payload)
        hooks.run_hooks(cfg, "duplicate_found", dup.a, payload)
        _notify(app, cfg.notifications.on_duplicates, t("notify.duplicate.summary"),
                t(f"notify.duplicate.{dup.reason}", a=dup.a.service, b=dup.b.service), "duplicate")
        out["duplicates"].append(dup)

    today = clock.today()
    for z in analysis.find_zombies(subs, cfg, today):
        last = store.last_event("zombie_found", z.id)
        if last and clock.now() - clock.parse_iso(last["ts"]) < timedelta(days=30):
            continue
        payload = {"days": cfg.detection.zombie_days}
        store.add_event("zombie_found", z.id, payload)
        hooks.run_hooks(cfg, "zombie_found", z, payload)
        _notify(app, cfg.notifications.on_zombies, t("notify.zombie.summary", service=z.service),
                t("notify.zombie.body", service=z.service, days=tn("fmt.units.day", cfg.detection.zombie_days)),
                "zombie")
        out["zombies"].append(z)

    rates = app.rates()
    tot = analysis.totals(subs, rates, cfg)
    month = today.strftime("%Y-%m")
    for st in analysis.budget_status(tot, cfg):
        if st.level != "over":
            continue
        already = any(month in (r["payload"] or "") and f'"{st.scope}"' in (r["payload"] or "")
                      for r in store.events("budget_exceeded", 200))
        if already:
            continue
        payload = {"scope": st.scope, "month": month, "limit": str(st.limit), "spent": str(st.spent)}
        store.add_event("budget_exceeded", None, payload)
        hooks.run_hooks(cfg, "budget_exceeded", None, payload)
        from .fmt import format_money

        name = t("bar.tip_budget_total") if st.scope == "total" else cfg.category_name(st.scope)
        _notify(app, cfg.notifications.on_budget, t("notify.budget.summary"),
                t("notify.budget.body", name=name, spent=format_money(st.spent, cfg.currency.base, 0),
                  limit=format_money(st.limit, cfg.currency.base, 0)), "budget", "critical")
        out["budget"].append(st)

    for source, message in errors or []:
        hooks.run_hooks(cfg, "job_failed", None, {"job": "scan", "source": source, "error": message})
        _notify(app, cfg.notifications.on_job_failed, t("notify.failed.summary", source=source),
                message, "error", "critical")

    if summary is not None and cfg.notifications.on_scan_summary and cfg.scan.notify_summary:
        created = summary.get("created", 0) + summary.get("promoted", 0)
        review = summary.get("review", 0)
        if created or review:
            parts = []
            if created:
                parts.append(tn("notify.summary.new", created))
            if review:
                parts.append(tn("notify.summary.review", review))
            _notify(app, True, t("notify.summary.title"), "; ".join(parts), "summary")
    app.after_change()
    return out


def run_job(app: AppContext, only: list[str] | None = None, full: bool = False,
            months: int | None = None, dry_run: bool = False, ai_dry_run: bool = False,
            no_ai: bool = False, reprocess: bool = False,
            progress: Callable[[str, int], None] | None = None) -> ScanReport:
    """Everything `subwatch scan` does, under the single-instance lock."""
    cfg = app.config
    with single_instance("scan"):
        lower_priority(cfg.scan.nice, cfg.scan.io_class)
        if not (dry_run or ai_dry_run):
            app.rates(allow_network=True)
        scanner = Scanner(app, dry_run=dry_run, ai_dry_run=ai_dry_run, no_ai=no_ai, reprocess=reprocess)
        report = scanner.run(only=only, full=full, months=months, progress=progress)
        if report.dry_run:
            return report
        total = Counter()
        for c in report.stats.values():
            total.update(c)
        react(app, report.events, report.errors, total)
        if cfg.scan.remind_after_scan:
            reminders.run(app.store, cfg, app.rates())
        app.store.purge_transactions_older_than(cfg.sources.statements.keep_transactions_days)
        log.info("scan_finished", seconds=round(report.seconds, 2), created=total.get("created", 0),
                 review=total.get("review", 0), errors=len(report.errors))
        return report
