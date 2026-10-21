"""Export to CSV, JSON and an .ics calendar of upcoming charges."""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import clock, paths
from .analysis import expected_dates
from .config.schema import Config
from .fmt import format_money, format_period
from .fx import Rates
from .i18n import t
from .models import Subscription
from .period import add_months

COLUMNS = (
    "id", "service", "amount", "currency", "period", "monthly_base", "next_charge", "last_charge",
    "category", "tags", "status", "source", "confidence", "cancel_url", "notes",
)


def subscription_rows(subs: list[Subscription], config: Config, rates: Rates) -> list[dict[str, Any]]:
    rows = []
    for s in subs:
        monthly = rates.convert(s.monthly_amount, s.currency) if s.monthly_amount is not None else None
        rows.append({
            "id": s.id,
            "service": s.service,
            "amount": str(s.amount) if s.amount is not None else "",
            "currency": s.currency or "",
            "period": s.period.code,
            "monthly_base": str(monthly) if monthly is not None else "",
            "next_charge": s.next_charge.isoformat() if s.next_charge else "",
            "last_charge": s.last_charge.isoformat() if s.last_charge else "",
            "category": config.category_name(s.category),
            "tags": ", ".join(s.tags),
            "status": s.status,
            "source": s.source,
            "confidence": round(s.confidence, 2),
            "cancel_url": s.cancel_url or "",
            "notes": s.notes or "",
        })
    return rows


def to_csv(rows: list[dict[str, Any]], localized_headers: bool = True) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";" if localized_headers else ",")
    header = [t(f"export.col.{c}") for c in COLUMNS] if localized_headers else list(COLUMNS)
    writer.writerow(header)
    for row in rows:
        writer.writerow([row[c] for c in COLUMNS])
    return buf.getvalue()


def to_json(rows: list[dict[str, Any]], config: Config) -> str:
    return json.dumps({
        "generated_at": clock.iso(clock.now()),
        "base_currency": config.currency.base,
        "subscriptions": rows,
    }, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------- ics


def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> str:
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts = []
    current = b""
    for ch in line:
        enc = ch.encode("utf-8")
        limit = 75 if not parts else 74
        if len(current) + len(enc) > limit:
            parts.append(current.decode("utf-8"))
            current = b""
        current += enc
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def ics_path(config: Config) -> Path:
    if config.export.ics_path:
        return paths.expand(config.export.ics_path)
    return paths.data_dir() / "subwatch.ics"


def build_ics(subs: list[Subscription], config: Config, today: date | None = None) -> str:
    today = today or clock.today()
    horizon = add_months(today, config.export.ics_months_ahead)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    statuses = {"active"} | ({"review"} if config.export.ics_include_review else set())
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Subwatch//Subwatch//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:" + _escape(t("export.ics.calendar_name")),
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    ]
    if config.general.timezone != "local":
        lines.append("X-WR-TIMEZONE:" + config.general.timezone)
    for sub in sorted(subs, key=lambda s: s.service.casefold()):
        if sub.status not in statuses:
            continue
        for day in expected_dates(sub, today, horizon):
            amount = format_money(sub.amount, sub.currency) if sub.amount is not None else ""
            summary = t("export.ics.summary", service=sub.service, amount=amount).strip(" —-")
            desc_parts = [format_period(sub.period), t("export.ics.category",
                                                       name=config.category_name(sub.category))]
            if sub.cancel_url:
                desc_parts.append(t("export.ics.cancel", url=sub.cancel_url))
            lines += [
                "BEGIN:VEVENT",
                f"UID:sub-{sub.id}-{day:%Y%m%d}@subwatch",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
                f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
                "SUMMARY:" + _escape(summary),
                "DESCRIPTION:" + _escape("\n".join(desc_parts)),
                "CATEGORIES:" + _escape(config.category_name(sub.category)),
                "TRANSP:TRANSPARENT",
            ]
            if sub.cancel_url:
                lines.append("URL:" + sub.cancel_url)
            if config.export.ics_alarm_days > 0:
                lines += [
                    "BEGIN:VALARM",
                    "ACTION:DISPLAY",
                    "DESCRIPTION:" + _escape(summary),
                    f"TRIGGER:-P{config.export.ics_alarm_days}D",
                    "END:VALARM",
                ]
            lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def write_ics(subs: list[Subscription], config: Config, path: Path | None = None) -> Path:
    from .config.editor import write_atomic

    target = path or ics_path(config)
    write_atomic(target, build_ics(subs, config), mode=0o600)
    return target
