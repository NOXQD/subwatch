"""Reminder scheduling and delivery.

For every active subscription the next charge date (and the end of a trial)
gets one reminder per "days before" offset at the configured time of day.
Which offsets and time apply is decided by the most specific matching rule:
per service > per amount > per category > defaults from [reminders].

A reminder that falls into quiet hours moves to their end. If the user does
not react, it is repeated every `repeat_every` up to `max_repeats` times.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from . import clock, hooks, log
from .config.schema import Config, QuietHours, ReminderRule, parse_clock, parse_duration
from .db import Store
from .fmt import format_date, format_duration, format_money, format_relative_days
from .fx import Rates
from .i18n import t
from .models import Subscription, service_key
from .notify import Notification, self_command, send


@dataclass
class Effective:
    enabled: bool
    days_before: list[int]
    time: time
    repeat: bool
    rule: str = ""


@dataclass
class Plan:
    charge_date: date
    days_before: int
    kind: str
    due_at: datetime


@dataclass
class Sent:
    reminder_id: int
    subscription: Subscription
    charge_date: date
    kind: str
    repeat: bool


@dataclass
class RunReport:
    sent: list[Sent] = field(default_factory=list)
    planned: int = 0
    rolled: int = 0


def amount_in_base(sub: Subscription, rates: Rates | None, basis: str) -> Decimal | None:
    amount = sub.monthly_amount if basis == "monthly" else sub.amount
    if amount is None:
        return None
    if rates is None:
        return amount if sub.currency is None else None
    return rates.convert(amount, sub.currency)


def _rule_matches(rule: ReminderRule, sub: Subscription, amount: Decimal | None) -> bool:
    if rule.services and service_key(sub.service) not in {service_key(s) for s in rule.services}:
        return False
    if rule.categories and sub.category not in rule.categories:
        return False
    if rule.min_amount is not None and (amount is None or amount < rule.min_amount):
        return False
    if rule.max_amount is not None and (amount is None or amount > rule.max_amount):
        return False
    return True


def effective_settings(sub: Subscription, config: Config, rates: Rates | None = None) -> Effective:
    cfg = config.reminders
    amount = amount_in_base(sub, rates, cfg.amount_basis)
    best: ReminderRule | None = None
    for rule in cfg.rules:
        if _rule_matches(rule, sub, amount) and (best is None or rule.specificity > best.specificity):
            best = rule
    eff = Effective(
        enabled=cfg.enabled,
        days_before=list(cfg.days_before),
        time=parse_clock(cfg.time),
        repeat=cfg.repeat_unacknowledged,
    )
    if best is not None:
        eff.rule = best.name
        if not best.enabled:
            eff.enabled = False
        if best.days_before is not None:
            eff.days_before = sorted(set(best.days_before), reverse=True)
        if best.time is not None:
            eff.time = parse_clock(best.time)
        if best.repeat is not None:
            eff.repeat = best.repeat
    return eff


def in_quiet_hours(moment: datetime, quiet: QuietHours) -> bool:
    if not quiet.enabled:
        return False
    start, end = parse_clock(quiet.start), parse_clock(quiet.end)
    now = moment.time()
    if start == end:
        return False
    if start < end:
        return start <= now < end
    return now >= start or now < end


def leave_quiet_hours(moment: datetime, quiet: QuietHours) -> datetime:
    if not in_quiet_hours(moment, quiet):
        return moment
    end = parse_clock(quiet.end)
    candidate = moment.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if candidate <= moment:
        candidate += timedelta(days=1)
    return candidate


def plan_for(sub: Subscription, config: Config, rates: Rates | None, now: datetime) -> list[Plan]:
    eff = effective_settings(sub, config, rates)
    if not eff.enabled or not sub.is_active or sub.status == "paused":
        return []
    tz = clock.local_tz()
    plans: list[Plan] = []
    targets: list[tuple[date, list[int], str]] = []
    if sub.next_charge:
        targets.append((sub.next_charge, eff.days_before, "charge"))
    if sub.trial_until and sub.trial_until >= now.date():
        targets.append((sub.trial_until, list(config.reminders.trial_days_before), "trial"))
    for charge_date, offsets, kind in targets:
        if charge_date < now.date():
            continue
        for days in offsets:
            day = charge_date - timedelta(days=days)
            due = datetime.combine(day, eff.time, tzinfo=tz)
            due = leave_quiet_hours(due, config.reminders.quiet_hours)
            plans.append(Plan(charge_date, days, kind, due))
    return plans


def roll_forward(store: Store, sub: Subscription, today: date) -> bool:
    """Move a past next_charge to the next period (the charge happened)."""
    if not sub.next_charge or sub.next_charge >= today or not sub.is_active:
        return False
    previous = sub.next_charge
    nxt = previous
    while nxt < today:
        nxt = sub.period.advance(nxt, 1, sub.anchor_day)
    sub.last_charge = max(sub.last_charge or previous, previous)
    sub.next_charge = nxt
    if sub.trial_until and sub.trial_until < today:
        sub.trial_until = None
    store.update_subscription(sub)
    return True


def compose(sub: Subscription, charge_date: date, kind: str, today: date, repeat: bool,
            snooze: str) -> tuple[str, str]:
    days = (charge_date - today).days
    amount = format_money(sub.amount, sub.currency) if sub.amount is not None else t("fmt.unknown_amount")
    params = dict(service=sub.service, date=format_date(charge_date),
                  relative=format_relative_days(days), amount=amount,
                  snooze=format_duration(parse_duration(snooze)))
    if kind == "trial":
        summary = t("remind.trial_summary", **params)
        body = t("remind.trial_body", **params)
    else:
        summary = t("remind.summary", **params)
        body = t("remind.body", **params)
    if repeat:
        summary = t("remind.repeat_prefix", summary=summary)
    return summary, body + "\n" + t("remind.hint")


def _notification(sub: Subscription, row, config: Config, today: date, repeat: bool) -> Notification:
    charge_date = date.fromisoformat(row["charge_date"])
    summary, body = compose(sub, charge_date, row["kind"], today, repeat, config.reminders.snooze)
    snooze_label = t("action.snooze", duration=format_duration(parse_duration(config.reminders.snooze)))
    return Notification(
        summary=summary,
        body=body,
        urgency=config.notifications.urgency,
        kind="reminder",
        reminder_id=int(row["id"]),
        actions=[("keep", t("action.keep")), ("cancel", t("action.cancel")), ("snooze", snooze_label)],
        click=self_command() + ["notify-action", str(row["id"])],
    )


def run(store: Store, config: Config, rates: Rates | None, now: datetime | None = None,
        dry_run: bool = False, notifier=send) -> RunReport:
    now = clock.to_local(now or clock.now())
    today = now.date()
    report = RunReport()
    subs = {s.id: s for s in store.active_subscriptions()}
    for sub in subs.values():
        if not dry_run and roll_forward(store, sub, today):
            report.rolled += 1
        plans = plan_for(sub, config, rates, now)
        report.planned += len(plans)
        if dry_run:
            continue
        store.drop_stale_reminders(sub.id or 0, [p.charge_date for p in plans])
        for p in plans:
            store.ensure_reminder(sub.id or 0, p.charge_date, p.days_before, p.kind, p.due_at)

    if not config.reminders.enabled:
        return report
    repeat_every = parse_duration(config.reminders.repeat_every)
    quiet = config.reminders.quiet_hours
    due_rows = [r for r in store.open_reminders() if clock.parse_iso(r["due_at"]) <= now]
    # Of several due offsets for the same charge only the latest matters.
    latest: dict[tuple[int, str, str], object] = {}
    for row in due_rows:
        key = (row["subscription_id"], row["charge_date"], row["kind"])
        prev = latest.get(key)
        if prev is None or row["days_before"] < prev["days_before"]:  # type: ignore[index]
            latest[key] = row
    for row in due_rows:
        key = (row["subscription_id"], row["charge_date"], row["kind"])
        if latest[key] is not row:
            if not dry_run and row["sent_count"] == 0:
                store.ack_reminder(row["id"], "superseded")
            continue
        sub = subs.get(row["subscription_id"])
        if sub is None:
            continue
        charge_date = date.fromisoformat(row["charge_date"])
        if charge_date < today:
            if not dry_run:
                store.ack_reminder(row["id"], "expired")
            continue
        eff = effective_settings(sub, config, rates)
        if not eff.enabled:
            continue
        snoozed = clock.parse_iso(row["snoozed_until"])
        if snoozed and snoozed > now:
            continue
        repeat = False
        if row["sent_count"] == 0 or (snoozed and snoozed <= now):
            pass
        else:
            last = clock.parse_iso(row["last_sent_at"])
            if not eff.repeat or row["sent_count"] > config.reminders.max_repeats:
                continue
            if last and now - last < repeat_every:
                continue
            repeat = True
        if in_quiet_hours(now, quiet):
            continue
        report.sent.append(Sent(int(row["id"]), sub, charge_date, row["kind"], repeat))
        if dry_run:
            continue
        notifier(_notification(sub, row, config, today, repeat), config.notifications)
        store.mark_reminder_sent(int(row["id"]), now)
        if snoozed:
            store.conn.execute("UPDATE reminders SET snoozed_until = NULL WHERE id = ?", (row["id"],))
        if row["sent_count"] == 0 and not repeat:
            hooks.run_hooks(config, "upcoming_charge", sub, {
                "charge_date": charge_date.isoformat(), "days_left": (charge_date - today).days,
                "reminder_id": int(row["id"]), "kind": row["kind"],
            })
        log.info("reminder_sent", service=sub.service, charge_date=charge_date.isoformat(),
                 repeat=repeat, reminder_id=row["id"])
    return report


def open_url(url: str) -> bool:
    for cmd in (["omarchy-launch-browser", url], ["xdg-open", url]):
        try:
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            return True
        except OSError:
            continue
    return False


def apply_action(store: Store, config: Config, reminder_id: int, action: str,
                 snooze: str | None = None, open_page: bool = True) -> str:
    """Handle keep / cancel / snooze; returns a catalog key describing the result."""
    row = store.reminder(reminder_id)
    if row is None:
        return "remind.action.missing"
    sub = store.get_subscription(row["subscription_id"])
    if sub is None:
        return "remind.action.missing"
    charge_date = date.fromisoformat(row["charge_date"])
    if action == "keep":
        store.ack_all_for_charge(sub.id or 0, charge_date, "keep")
        return "remind.action.kept"
    if action == "snooze":
        delta = parse_duration(snooze or config.reminders.snooze)
        store.ack_reminder(reminder_id, "snooze", clock.now() + delta)
        return "remind.action.snoozed"
    if action == "cancel":
        store.ack_all_for_charge(sub.id or 0, charge_date, "cancel")
        opened = bool(sub.cancel_url) and open_page and open_url(sub.cancel_url or "")
        sub.status = "cancelled"
        sub.cancelled_at = clock.now()
        sub.next_charge = None
        store.update_subscription(sub)
        hooks.run_hooks(config, "subscription_cancelled", sub, {"via": "reminder"})
        return "remind.action.cancelled_opened" if opened else "remind.action.cancelled"
    return "remind.action.unknown"
