"""Extraction over the synthetic ru/en/kk corpus in fixtures/emails.py."""

from datetime import date
from decimal import Decimal

import pytest

from fixtures.emails import EMAILS
from subwatch.config.schema import Config
from subwatch.extract.engine import Context, analyse
from subwatch.extract.merchants import MerchantBook
from subwatch.extract.text import html_to_text, parse_email

CFG = Config()


@pytest.fixture(scope="module")
def ctx():
    return Context.build(CFG, MerchantBook.load())


def status_of(det):
    if det is None or det.confidence < CFG.extraction.review_threshold:
        return "ignored"
    return "active" if det.confidence >= CFG.extraction.auto_accept else "review"


def test_corpus_is_big_enough():
    langs = {e.lang for e in EMAILS}
    assert len(EMAILS) >= 30 and langs == {"ru", "en", "kk"}
    assert sum(1 for e in EMAILS if e.expect is None) >= 5


@pytest.mark.parametrize("email", EMAILS, ids=[e.id for e in EMAILS])
def test_email(ctx, email):
    msg = parse_email(email.to_bytes(), "imap", email.id)
    det = analyse(msg, ctx).detection
    x = email.expect
    if x is None:
        assert status_of(det) == "ignored", f"{det.service} {det.confidence}" if det else ""
        return
    assert det is not None
    assert det.service == x.service
    assert det.kind == x.kind
    if x.kind == "cancellation":
        assert det.confidence >= CFG.extraction.review_threshold
        return
    assert status_of(det) == x.status
    if x.amount is not None:
        assert det.amount == Decimal(x.amount)
        assert det.currency == x.currency
    if x.period is not None:
        assert det.period is not None and det.period.code == x.period
    if x.next is not None:
        assert det.next_charge == date.fromisoformat(x.next)
    if x.trial_until is not None:
        assert det.trial_until == date.fromisoformat(x.trial_until)
    if x.old_amount is not None:
        assert det.old_amount == Decimal(x.old_amount)
    if x.category is not None:
        assert det.category == x.category


def test_html_to_text_keeps_structure():
    text = html_to_text("<html><style>p{}</style><p>Сумма</p><table><tr><td>199 ₽</td></tr></table>"
                        "<script>alert(1)</script></html>")
    assert "Сумма" in text and "199 ₽" in text and "alert" not in text


def test_excluded_sender_is_skipped(ctx):
    cfg = Config.model_validate({"filters": {"exclude_senders": ["*@netflix.com"]}})
    c = Context.build(cfg, MerchantBook.load())
    msg = parse_email(EMAILS[0].to_bytes(), "imap", "x")
    msg.sender = "info@netflix.com"
    res = analyse(msg, c)
    assert res.detection is None and res.skipped == "sender"


def test_exclude_keywords(ctx):
    cfg = Config.model_validate({"filters": {"exclude_keywords": ["платёж прошёл"]}})
    c = Context.build(cfg, MerchantBook.load())
    res = analyse(parse_email(EMAILS[0].to_bytes(), "imap", "x"), c)
    assert res.detection is None and res.skipped == "keyword"


def test_languages_option_limits_keywords():
    kk_only = Context.build(Config.model_validate({"extraction": {"languages": ["kk"]}}), MerchantBook.load())
    email = next(e for e in EMAILS if e.id == "ru_megadisk_unknown")
    assert analyse(parse_email(email.to_bytes(), "imap", "x"), kk_only).detection is None


def test_extra_keywords_option():
    msg = parse_email(next(e for e in EMAILS if e.id == "ru_megadisk_unknown").to_bytes(), "imap", "x")
    msg.subject = "Хранилище на ноябрь"
    msg.text = "590 ₽ в месяц."
    base = Context.build(CFG, MerchantBook.load())
    tuned = Context.build(Config.model_validate({"extraction": {"extra_keywords": ["хранилище"]}}),
                          MerchantBook.load())
    assert analyse(msg, base).detection is None
    assert analyse(msg, tuned).detection.amount == Decimal(590)


def test_store_snippets_option():
    email = EMAILS[0]
    off = analyse(parse_email(email.to_bytes(), "imap", "x"), Context.build(CFG, MerchantBook.load()))
    assert off.detection.snippet is None
    cfg = Config.model_validate({"extraction": {"store_snippets": True, "snippet_chars": 80}})
    on = analyse(parse_email(email.to_bytes(), "imap", "x"), Context.build(cfg, MerchantBook.load()))
    assert on.detection.snippet and len(on.detection.snippet) <= 80
    assert "4417" not in on.detection.snippet  # card number redacted
