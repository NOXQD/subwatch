"""Category and tag assignment."""

from __future__ import annotations

from decimal import Decimal

from .config.schema import Config
from .extract.engine import Learned, glob_match
from .models import service_key


def _sender_hit(patterns: list[str], sender: str | None) -> bool:
    if not sender:
        return False
    domain = sender.rpartition("@")[2]
    return any(glob_match(p, sender) or glob_match(p, domain) for p in patterns)


def assign_category(
    service: str,
    config: Config,
    learned: Learned | None = None,
    sender: str | None = None,
    text_cf: str = "",
    suggested: str | None = None,
) -> str:
    key = service_key(service)
    for rule in config.category_rules:
        if any(service_key(s) == key for s in rule.services):
            return rule.category
        if _sender_hit(rule.senders, sender):
            return rule.category
        if text_cf and any(k.casefold() in text_cf for k in rule.keywords):
            return rule.category
    if learned and key in learned.categories and learned.categories[key] in config.categories:
        return learned.categories[key]
    if suggested and suggested in config.categories:
        return suggested
    return "other"


def assign_tags(
    service: str,
    category: str,
    config: Config,
    sender: str | None = None,
    text_cf: str = "",
    amount_base: Decimal | None = None,
) -> list[str]:
    key = service_key(service)
    tags: list[str] = []
    for rule in config.tag_rules:
        hit = (
            any(service_key(s) == key for s in rule.services)
            or category in rule.categories
            or _sender_hit(rule.senders, sender)
            or bool(text_cf and any(k.casefold() in text_cf for k in rule.keywords))
            or (rule.min_amount is not None and amount_base is not None and amount_base >= rule.min_amount)
        )
        if hit and rule.tag not in tags:
            tags.append(rule.tag)
    return tags
