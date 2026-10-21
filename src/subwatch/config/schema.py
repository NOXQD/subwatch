"""Configuration schema.

Every option a user can put into config.toml is declared here. Unknown keys
are rejected so typos show up in `subwatch config check` instead of being
silently ignored. Descriptions for docs and the default config live in the
catalog (config.desc.*) and in resources/config.default.toml.
"""

from __future__ import annotations

import re
from datetime import time, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..i18n import t
from ..money import is_valid_code
from ..period import Period, PeriodError


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


# ---------------------------------------------------------------- helpers

_DURATION = re.compile(r"^\s*(\d+)\s*(s|m|h|d|w)\s*$")
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> timedelta:
    m = _DURATION.match(str(text).lower())
    if not m:
        raise ValueError(t("config.err.duration", value=text))
    return timedelta(seconds=int(m.group(1)) * _DURATION_UNITS[m.group(2)])


def parse_clock(text: str) -> time:
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(text))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(t("config.err.clock", value=text))
    return time(int(m.group(1)), int(m.group(2)))


def _check_duration(v: str) -> str:
    parse_duration(v)
    return v


def _check_clock(v: str) -> str:
    parse_clock(v)
    return v


def _split_list(v: Any) -> Any:
    if isinstance(v, str):
        return [item.strip() for item in v.split(",") if item.strip()]
    return v


# ---------------------------------------------------------------- sections


class UIColors(Strict):
    primary: str = ""
    secondary: str = ""
    accent: str = ""
    background: str = ""
    foreground: str = ""
    surface: str = ""
    panel: str = ""
    success: str = ""
    warning: str = ""
    error: str = ""

    @field_validator("*")
    @classmethod
    def _color(cls, v: str) -> str:
        if v and not re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", v):
            raise ValueError(t("config.err.color", value=v))
        return v


class UIKeys(Strict):
    """TUI key map: action -> comma separated Textual key names."""

    down: str = "j,down"
    up: str = "k,up"
    top: str = "g,home"
    bottom: str = "G,end"
    page_down: str = "ctrl+d,pagedown"
    page_up: str = "ctrl+u,pageup"
    open: str = "enter,l"
    back: str = "escape,h"
    search: str = "slash"
    filter: str = "f"
    sort: str = "s"
    reverse: str = "S"
    add: str = "a"
    edit: str = "e"
    delete: str = "d"
    cancel: str = "x"
    used: str = "u"
    review: str = "r"
    confirm: str = "y"
    reject: str = "n"
    charts: str = "c"
    subscriptions: str = "1"
    rescan: str = "R"
    config: str = "comma"
    help: str = "question_mark"
    quit: str = "q"


class UIConfig(Strict):
    language: str = "ru"
    theme: str = "auto"
    colors: UIColors = Field(default_factory=UIColors)
    keys: UIKeys = Field(default_factory=UIKeys)
    default_sort: Literal["next_charge", "amount", "monthly", "name", "category", "status"] = (
        "next_charge"
    )
    sort_reverse: bool = False
    show_cancelled: bool = False
    date_style: Literal["both", "relative", "absolute"] = "both"
    money_decimals: int = Field(2, ge=0, le=2)
    terminal: str = "auto"
    reload_interval: int = Field(2, ge=1, le=60)

    @field_validator("language")
    @classmethod
    def _lang(cls, v: str) -> str:
        v = v.strip().lower()
        if not re.fullmatch(r"[a-z]{2,3}(_[a-z]{2})?", v):
            raise ValueError(t("config.err.language", value=v))
        return v


class GeneralConfig(Strict):
    timezone: str = "local"

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        if v and v != "local":
            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(t("config.err.timezone", value=v)) from None
        return v or "local"


class CurrencyConfig(Strict):
    base: str = "KZT"
    rates_source: Literal["auto", "nbk", "cbr", "open_er_api", "frankfurter", "manual"] = "auto"
    cache_ttl_hours: int = Field(12, ge=1, le=24 * 30)
    manual_rates: dict[str, Decimal] = Field(default_factory=dict)
    timeout: int = Field(10, ge=1, le=120)

    @field_validator("base")
    @classmethod
    def _base(cls, v: str) -> str:
        v = v.strip().upper()
        if not is_valid_code(v):
            raise ValueError(t("config.err.currency", value=v))
        return v

    @field_validator("manual_rates")
    @classmethod
    def _rates(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        out = {}
        for code, rate in v.items():
            code = code.strip().upper()
            if not is_valid_code(code):
                raise ValueError(t("config.err.currency", value=code))
            if rate <= 0:
                raise ValueError(t("config.err.rate", code=code))
            out[code] = rate
        return out


class ScanConfig(Strict):
    schedule: str = "daily"
    randomized_delay: str = "10m"
    persistent: bool = True
    months_back: int = Field(12, ge=1, le=120)
    max_messages: int = Field(5000, ge=10, le=200_000)
    nice: int = Field(10, ge=0, le=19)
    io_class: Literal["idle", "best-effort", "none"] = "idle"
    notify_summary: bool = True
    remind_after_scan: bool = True

    _schedule_ok = field_validator("randomized_delay")(classmethod(lambda cls, v: _check_duration(v)))

    @field_validator("schedule")
    @classmethod
    def _schedule(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError(t("config.err.schedule", value=v))
        return v


class GmailConfig(Strict):
    enabled: bool = False
    account: str = "default"
    labels: list[str] = Field(default_factory=list)
    exclude_labels: list[str] = Field(default_factory=lambda: ["SPAM", "TRASH"])
    query: str = ""
    rate_limit: float = Field(8.0, gt=0, le=50)
    max_retries: int = Field(5, ge=0, le=10)

    _lists = field_validator("labels", "exclude_labels", mode="before")(
        classmethod(lambda cls, v: _split_list(v))
    )


class ImapAccount(Strict):
    name: str
    host: str
    username: str
    port: int = Field(993, ge=1, le=65535)
    ssl: bool = True
    starttls: bool = False
    folders: list[str] = Field(default_factory=lambda: ["INBOX"])
    enabled: bool = True
    timeout: int = Field(30, ge=1, le=600)

    _lists = field_validator("folders", mode="before")(classmethod(lambda cls, v: _split_list(v)))

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", v):
            raise ValueError(t("config.err.account_name", value=v))
        return v


class ImapConfig(Strict):
    enabled: bool = True
    accounts: list[ImapAccount] = Field(default_factory=list)
    max_retries: int = Field(3, ge=0, le=10)
    fetch_max_bytes: int = Field(200_000, ge=4096, le=10_000_000)
    batch_size: int = Field(200, ge=10, le=2000)

    @model_validator(mode="after")
    def _unique(self) -> "ImapConfig":
        names = [a.name for a in self.accounts]
        if len(names) != len(set(names)):
            raise ValueError(t("config.err.duplicate_account"))
        return self


class StatementsConfig(Strict):
    inbox_dir: str = ""
    default_bank: str = "auto"
    keep_transactions_days: int = Field(800, ge=30, le=5000)


class SourcesConfig(Strict):
    gmail: GmailConfig = Field(default_factory=GmailConfig)
    imap: ImapConfig = Field(default_factory=ImapConfig)
    statements: StatementsConfig = Field(default_factory=StatementsConfig)


class FiltersConfig(Strict):
    exclude_senders: list[str] = Field(default_factory=list)
    exclude_services: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)

    _lists = field_validator("*", mode="before")(classmethod(lambda cls, v: _split_list(v)))


class ExtractionConfig(Strict):
    languages: list[Literal["ru", "en", "kk"]] = Field(default_factory=lambda: ["ru", "en", "kk"])
    auto_accept: float = Field(0.8, ge=0, le=1)
    review_threshold: float = Field(0.45, ge=0, le=1)
    store_snippets: bool = False
    snippet_chars: int = Field(300, ge=50, le=2000)
    extra_keywords: list[str] = Field(default_factory=list)

    _lists = field_validator("languages", "extra_keywords", mode="before")(
        classmethod(lambda cls, v: _split_list(v))
    )

    @model_validator(mode="after")
    def _order(self) -> "ExtractionConfig":
        if self.review_threshold > self.auto_accept:
            raise ValueError(t("config.err.thresholds"))
        return self


class RecurrenceConfig(Strict):
    periods: list[int] = Field(default_factory=lambda: [7, 30, 90, 365])
    tolerance_pct: float = Field(10.0, ge=0, le=50)
    max_tolerance_days: int = Field(10, ge=0, le=60)
    amount_tolerance_pct: float = Field(5.0, ge=0, le=50)
    min_occurrences: int = Field(3, ge=2, le=24)
    min_occurrences_yearly: int = Field(2, ge=2, le=10)

    _lists = field_validator("periods", mode="before")(classmethod(lambda cls, v: _split_list(v)))

    @field_validator("periods")
    @classmethod
    def _periods(cls, v: list[int]) -> list[int]:
        if not v or any(p < 1 or p > 800 for p in v):
            raise ValueError(t("config.err.periods"))
        return sorted(set(v))


class AIConfig(Strict):
    enabled: bool = False
    provider: str = "ollama"
    model: str = "llama3.1:8b"
    api_base: str = ""
    max_requests_per_scan: int = Field(20, ge=0, le=1000)
    max_requests_per_day: int = Field(100, ge=0, le=10_000)
    max_input_chars: int = Field(1500, ge=200, le=20_000)
    timeout: int = Field(60, ge=5, le=600)
    temperature: float = Field(0.0, ge=0, le=2)
    redact_local: bool = True
    audit_payloads: bool = False


class QuietHours(Strict):
    enabled: bool = True
    start: str = "22:00"
    end: str = "08:00"

    _clock = field_validator("start", "end")(classmethod(lambda cls, v: _check_clock(v)))


class ReminderRule(Strict):
    name: str = ""
    services: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    days_before: list[int] | None = None
    time: str | None = None
    repeat: bool | None = None
    enabled: bool = True

    _lists = field_validator("services", "categories", "days_before", mode="before")(
        classmethod(lambda cls, v: _split_list(v))
    )

    @field_validator("time")
    @classmethod
    def _time(cls, v: str | None) -> str | None:
        return None if v is None else _check_clock(v)

    @field_validator("days_before")
    @classmethod
    def _days(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and any(d < 0 or d > 365 for d in v):
            raise ValueError(t("config.err.days_before"))
        return v

    @property
    def specificity(self) -> int:
        """Service rules beat amount rules, which beat category rules."""
        if self.services:
            return 3
        if self.min_amount is not None or self.max_amount is not None:
            return 2
        if self.categories:
            return 1
        return 0


class RemindersConfig(Strict):
    enabled: bool = True
    days_before: list[int] = Field(default_factory=lambda: [3, 1])
    time: str = "10:00"
    quiet_hours: QuietHours = Field(default_factory=QuietHours)
    repeat_unacknowledged: bool = True
    repeat_every: str = "4h"
    max_repeats: int = Field(2, ge=0, le=20)
    snooze: str = "1d"
    snooze_options: list[str] = Field(default_factory=lambda: ["3h", "1d", "3d"])
    trial_days_before: list[int] = Field(default_factory=lambda: [2, 0])
    amount_basis: Literal["charge", "monthly"] = "charge"
    check_interval: str = "15m"
    rules: list[ReminderRule] = Field(default_factory=list)

    _lists = field_validator("days_before", "snooze_options", "trial_days_before", mode="before")(
        classmethod(lambda cls, v: _split_list(v))
    )
    _clock = field_validator("time")(classmethod(lambda cls, v: _check_clock(v)))
    _dur = field_validator("repeat_every", "snooze", "check_interval")(
        classmethod(lambda cls, v: _check_duration(v))
    )

    @field_validator("snooze_options")
    @classmethod
    def _opts(cls, v: list[str]) -> list[str]:
        for item in v:
            _check_duration(item)
        return v

    @field_validator("days_before", "trial_days_before")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 365 for d in v):
            raise ValueError(t("config.err.days_before"))
        return sorted(set(v), reverse=True)


class NotificationsConfig(Strict):
    backend: Literal["auto", "omarchy", "notify-send", "none"] = "auto"
    urgency: Literal["low", "normal", "critical"] = "normal"
    timeout_ms: int = Field(0, ge=0, le=600_000)
    glyph: str = ""
    on_scan_summary: bool = True
    on_job_failed: bool = True
    on_budget: bool = True
    on_price_change: bool = True
    on_duplicates: bool = True
    on_zombies: bool = True


class BudgetConfig(Strict):
    monthly_limit: Decimal = Decimal(0)
    warn_at_pct: int = Field(90, ge=1, le=100)
    include_review: bool = False

    @field_validator("monthly_limit")
    @classmethod
    def _limit(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(t("config.err.negative"))
        return v


class Category(Strict):
    name: str = ""
    icon: str = ""
    budget: Decimal = Decimal(0)

    @field_validator("budget")
    @classmethod
    def _budget(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError(t("config.err.negative"))
        return v


class CategoryRule(Strict):
    category: str
    services: list[str] = Field(default_factory=list)
    senders: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    _lists = field_validator("services", "senders", "keywords", mode="before")(
        classmethod(lambda cls, v: _split_list(v))
    )


class TagRule(Strict):
    tag: str
    services: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    senders: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    min_amount: Decimal | None = None

    _lists = field_validator("services", "categories", "senders", "keywords", mode="before")(
        classmethod(lambda cls, v: _split_list(v))
    )


HOOK_EVENTS = (
    "new_subscription",
    "upcoming_charge",
    "price_changed",
    "job_failed",
    "budget_exceeded",
    "duplicate_found",
    "zombie_found",
    "subscription_cancelled",
)


class HooksConfig(Strict):
    new_subscription: list[str] = Field(default_factory=list)
    upcoming_charge: list[str] = Field(default_factory=list)
    price_changed: list[str] = Field(default_factory=list)
    job_failed: list[str] = Field(default_factory=list)
    budget_exceeded: list[str] = Field(default_factory=list)
    duplicate_found: list[str] = Field(default_factory=list)
    zombie_found: list[str] = Field(default_factory=list)
    subscription_cancelled: list[str] = Field(default_factory=list)
    timeout: int = Field(30, ge=1, le=3600)
    shell: str = "bash"


class DetectionConfig(Strict):
    price_change_pct: float = Field(1.0, ge=0, le=100)
    duplicates: bool = True
    duplicate_similarity: float = Field(0.85, ge=0.5, le=1)
    zombies: bool = True
    zombie_days: int = Field(45, ge=1, le=3650)


class ExportConfig(Strict):
    ics_auto: bool = True
    ics_path: str = ""
    ics_months_ahead: int = Field(12, ge=1, le=60)
    ics_alarm_days: int = Field(1, ge=0, le=30)
    ics_include_review: bool = False


class BarConfig(Strict):
    mode: Literal["auto", "total", "next"] = "auto"
    next_within_days: int = Field(7, ge=0, le=365)
    icon: str = ""
    interval: int = Field(300, ge=5, le=86400)
    tooltip_items: int = Field(6, ge=1, le=30)
    section: Literal["left", "center", "right"] = "right"
    hide_when_empty: bool = False


class KeybindsConfig(Strict):
    enabled: bool = True
    open_tui: str = "SUPER + CTRL + U"
    upcoming: str = "SUPER + CTRL + ALT + U"
    menu: str = "SUPER + CTRL + SHIFT + U"
    rescan: str = ""
    add: str = ""
    override_conflicts: bool = False
    auto_apply: bool = True


class MenuConfig(Strict):
    enabled: bool = True
    picker: Literal["auto", "omarchy", "walker", "fuzzel", "wofi", "rofi", "fzf"] = "auto"
    upcoming_days: int = Field(30, ge=1, le=366)


class StorageConfig(Strict):
    encrypt: bool = False
    db_path: str = ""
    backup_before_migrate: bool = True


class LoggingConfig(Strict):
    level: Literal["debug", "info", "warning", "error"] = "info"
    journal: bool = True
    file: str = ""


class PluginsConfig(Strict):
    enabled: bool = True
    disabled: list[str] = Field(default_factory=list)
    options: dict[str, dict[str, Any]] = Field(default_factory=dict)

    _lists = field_validator("disabled", mode="before")(classmethod(lambda cls, v: _split_list(v)))


def _default_categories() -> dict[str, Category]:
    icons = {
        "music": "\U000f075a",
        "video": "\U000f0381",
        "cloud": "",
        "games": "\U000f0297",
        "education": "\U000f0474",
        "software": "\U000f0614",
        "other": "\U000f01d8",
    }
    return {key: Category(name=t(f"category.{key}"), icon=icon) for key, icon in icons.items()}


class Config(Strict):
    ui: UIConfig = Field(default_factory=UIConfig)
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    currency: CurrencyConfig = Field(default_factory=CurrencyConfig)
    scan: ScanConfig = Field(default_factory=ScanConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    recurrence: RecurrenceConfig = Field(default_factory=RecurrenceConfig)
    ai: AIConfig = Field(default_factory=AIConfig)
    reminders: RemindersConfig = Field(default_factory=RemindersConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    categories: dict[str, Category] = Field(default_factory=_default_categories)
    category_rules: list[CategoryRule] = Field(default_factory=list)
    tag_rules: list[TagRule] = Field(default_factory=list)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    export: ExportConfig = Field(default_factory=ExportConfig)
    bar: BarConfig = Field(default_factory=BarConfig)
    keybinds: KeybindsConfig = Field(default_factory=KeybindsConfig)
    menu: MenuConfig = Field(default_factory=MenuConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)

    @field_validator("categories")
    @classmethod
    def _cats(cls, v: dict[str, Category]) -> dict[str, Category]:
        for key in v:
            if not re.fullmatch(r"[a-z0-9_-]{1,32}", key):
                raise ValueError(t("config.err.category_key", value=key))
        if "other" not in v:
            v = {**v, "other": Category(name=t("category.other"), icon="\U000f01d8")}
        for key, cat in v.items():
            if not cat.name:
                cat.name = t(f"category.{key}") if key in DEFAULT_CATEGORY_KEYS else key
        return v

    @model_validator(mode="after")
    def _rules_reference_categories(self) -> "Config":
        for rule in self.category_rules:
            if rule.category not in self.categories:
                raise ValueError(t("config.err.unknown_category", value=rule.category))
        return self

    # Convenience accessors used across the code base.

    def category_name(self, key: str | None) -> str:
        if not key:
            key = "other"
        cat = self.categories.get(key)
        return cat.name if cat else key

    def category_icon(self, key: str | None) -> str:
        cat = self.categories.get(key or "other")
        return cat.icon if cat else ""


DEFAULT_CATEGORY_KEYS = ("music", "video", "cloud", "games", "education", "software", "other")


def period_or_error(value: str) -> Period:
    try:
        return Period.parse(value)
    except PeriodError:
        raise ValueError(t("config.err.period", value=value)) from None
