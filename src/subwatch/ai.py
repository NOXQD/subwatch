"""Optional AI fallback for emails the rules could not handle.

Off by default (ai.enabled = false). Before anything is sent the text goes
through extract.redact.minimize(): addresses, card and phone numbers,
greetings and postal addresses are removed and only lines that look relevant
are kept, capped at ai.max_input_chars. For cloud providers this is always
done; for a local model it can be turned off with ai.redact_local = false.

`--dry-run` shows the exact payload and sends nothing. Every real request is
written to the ai_log table (time, provider, model, size, hash; the payload
itself only with ai.audit_payloads = true), see `subwatch privacy`.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from importlib import resources
from typing import Any

from . import clock, log, secrets
from .config.schema import AIConfig, Config
from .errors import SubwatchError
from .extract.keywords import Keywords
from .extract.redact import minimize, redact
from .models import Detection, RawMessage
from .money import is_valid_code
from .period import Period, PeriodError

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

OPENAI_COMPATIBLE = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "together": "https://api.together.xyz/v1",
    "lmstudio": "http://localhost:1234/v1",
    "vllm": "http://localhost:8000/v1",
    "openai_compatible": "",
}
DEFAULT_BASES = {"ollama": "http://localhost:11434", "anthropic": "https://api.anthropic.com",
                 **OPENAI_COMPATIBLE}

Completion = Callable[[list[dict[str, str]], AIConfig, str | None], str]


@dataclass
class DryRunItem:
    message_key: str
    sender_domain: str
    provider: str
    model: str
    is_local: bool
    messages: list[dict[str, str]]


def api_base(cfg: AIConfig) -> str:
    return (cfg.api_base or DEFAULT_BASES.get(cfg.provider, "")).rstrip("/")


def is_local(cfg: AIConfig) -> bool:
    base = api_base(cfg)
    if not base:
        return False
    host = urllib.parse.urlparse(base).hostname or ""
    return host in LOCAL_HOSTS or host.endswith(".local")


def needs_key(cfg: AIConfig) -> bool:
    return not is_local(cfg) and cfg.provider != "ollama"


def system_prompt(received: date) -> str:
    text = (resources.files("subwatch") / "resources" / "ai_prompt.txt").read_text(encoding="utf-8")
    return text.replace("{received}", received.isoformat())


def _post_json(url: str, body: dict[str, Any], headers: dict[str, str], timeout: int) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise SubwatchError("ai.err.http", status=exc.code, detail=detail) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SubwatchError("ai.err.network", hint="ai.hint.network", detail=str(exc)) from None


def builtin_completion(messages: list[dict[str, str]], cfg: AIConfig, key: str | None) -> str:
    base = api_base(cfg)
    if cfg.provider == "ollama":
        resp = _post_json(f"{base}/api/chat", {
            "model": cfg.model, "messages": messages, "stream": False, "format": "json",
            "options": {"temperature": cfg.temperature},
        }, {}, cfg.timeout)
        return str((resp.get("message") or {}).get("content", ""))
    if cfg.provider == "anthropic":
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        resp = _post_json(f"{base}/v1/messages", {
            "model": cfg.model, "max_tokens": 512, "temperature": cfg.temperature, "system": system,
            "messages": [m for m in messages if m["role"] != "system"],
        }, {"x-api-key": key or "", "anthropic-version": "2023-06-01"}, cfg.timeout)
        parts = resp.get("content") or []
        return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    if cfg.provider in OPENAI_COMPATIBLE:
        if not base:
            raise SubwatchError("ai.err.no_base", hint="ai.hint.no_base", provider=cfg.provider)
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        resp = _post_json(f"{base}/chat/completions", {
            "model": cfg.model, "messages": messages, "temperature": cfg.temperature,
            "response_format": {"type": "json_object"},
        }, headers, cfg.timeout)
        choices = resp.get("choices") or [{}]
        return str((choices[0].get("message") or {}).get("content", ""))
    return litellm_completion(messages, cfg, key)


def litellm_completion(messages: list[dict[str, str]], cfg: AIConfig, key: str | None) -> str:
    try:
        import litellm  # type: ignore[import-not-found]
    except ImportError:
        raise SubwatchError("ai.err.no_litellm", hint="ai.hint.no_litellm", provider=cfg.provider) from None
    model = cfg.model if "/" in cfg.model else f"{cfg.provider}/{cfg.model}"
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "temperature": cfg.temperature,
                              "timeout": cfg.timeout}
    if cfg.api_base:
        kwargs["api_base"] = cfg.api_base
    if key:
        kwargs["api_key"] = key
    resp = litellm.completion(**kwargs)
    return str(resp.choices[0].message.content or "")


def parse_answer(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def answer_to_detection(data: dict[str, Any], msg: RawMessage) -> Detection | None:
    if not data.get("is_subscription") or not data.get("service"):
        return None
    kind = str(data.get("kind") or "charge")
    if kind not in ("charge", "renewal", "trial", "cancellation", "price_change"):
        return None
    amount = None
    if data.get("amount") not in (None, ""):
        try:
            amount = Decimal(str(data["amount"]))
        except InvalidOperation:
            amount = None
    currency = str(data.get("currency") or "").upper() or None
    if currency and not is_valid_code(currency):
        currency = None
    period = None
    if data.get("period"):
        try:
            period = Period.parse(str(data["period"]))
        except PeriodError:
            period = None
    try:
        confidence = float(data.get("confidence") or 0.5)
    except (TypeError, ValueError):
        confidence = 0.5
    received = clock.to_local(msg.date).date() if msg.date else clock.today()
    return Detection(
        service=str(data["service"]).strip()[:80],
        kind=kind,
        amount=amount,
        currency=currency if amount is not None else None,
        period=period,
        charge_date=received if kind == "charge" and amount is not None else None,
        next_charge=_date(data.get("next_charge")),
        trial_until=_date(data.get("trial_until")),
        confidence=max(0.0, min(confidence, 1.0)),
        source=msg.source,
        source_ref=msg.key,
        source_account=msg.account,
        sender=msg.sender or None,
        reasons=["ai"],
    )


@dataclass
class AIExtractor:
    config: Config
    store: Any
    dry_run: bool = False
    completion: Completion | None = None
    requests: int = 0
    dry_runs: list[DryRunItem] = field(default_factory=list)
    disabled_reason: str | None = None

    @property
    def cfg(self) -> AIConfig:
        return self.config.ai

    def available(self) -> bool:
        if not self.cfg.enabled and not self.dry_run:
            return False
        if self.disabled_reason:
            return False
        if self.requests >= self.cfg.max_requests_per_scan:
            return False
        if not self.dry_run and self.store is not None:
            since = clock.now() - timedelta(days=1)
            if self.store.ai_requests_since(since) >= self.cfg.max_requests_per_day:
                return False
        return True

    def payload(self, msg: RawMessage, text: str) -> str:
        kw = Keywords(self.config.extraction.languages, self.config.extraction.extra_keywords)
        if not is_local(self.cfg) or self.cfg.redact_local:
            body = minimize(text, msg.subject, kw, self.cfg.max_input_chars)
            sender = msg.sender_domain
        else:
            body = (msg.subject + "\n" + text)[: self.cfg.max_input_chars]
            sender = msg.sender
        return f"From: {sender}\n{body}"

    def messages_for(self, msg: RawMessage, text: str) -> list[dict[str, str]]:
        received = clock.to_local(msg.date).date() if msg.date else clock.today()
        return [
            {"role": "system", "content": system_prompt(received)},
            {"role": "user", "content": self.payload(msg, text)},
        ]

    def extract(self, msg: RawMessage, text: str) -> Detection | None:
        if not self.available():
            return None
        messages = self.messages_for(msg, text)
        local = is_local(self.cfg)
        user_payload = messages[-1]["content"]
        self.requests += 1
        if self.dry_run:
            self.dry_runs.append(DryRunItem(msg.key, msg.sender_domain, self.cfg.provider,
                                            self.cfg.model, local, messages))
            return None
        key = None
        if needs_key(self.cfg):
            key = secrets.get(secrets.ai_key_name(self.cfg.provider))
            if not key:
                self.disabled_reason = "no_key"
                log.warning("ai_no_key", provider=self.cfg.provider)
                return None
        fn = self.completion or builtin_completion
        outcome = "error"
        try:
            answer = fn(messages, self.cfg, key)
            data = parse_answer(answer)
            det = answer_to_detection(data, msg) if data else None
            outcome = "detected" if det else "nothing"
            return det
        except SubwatchError as exc:
            log.warning("ai_failed", provider=self.cfg.provider, error=exc.message)
            if exc.key in ("ai.err.network", "ai.err.no_litellm", "ai.err.no_base"):
                self.disabled_reason = exc.key
            return None
        finally:
            if self.store is not None:
                self.store.log_ai(provider=self.cfg.provider, model=self.cfg.model, is_local=local,
                                  message_key=msg.key, sender_domain=msg.sender_domain,
                                  payload=user_payload, outcome=outcome,
                                  keep_payload=self.cfg.audit_payloads)


def merge(rule: Detection | None, ai: Detection | None) -> Detection | None:
    """Combine the rule result with the AI answer. AI alone never auto-accepts."""
    if ai is None:
        return rule
    if rule is None:
        ai.confidence = min(ai.confidence, 0.75)
        return ai
    from .models import service_key

    same = service_key(rule.service) == service_key(ai.service)
    if rule.amount is None and ai.amount is not None:
        rule.amount, rule.currency = ai.amount, ai.currency
        if rule.kind == "charge" and rule.charge_date is None:
            rule.charge_date = ai.charge_date
    if rule.period is None and ai.period is not None:
        rule.period = ai.period
    if rule.next_charge is None and ai.next_charge is not None:
        rule.next_charge = ai.next_charge
    if same:
        rule.confidence = min(0.95, rule.confidence + 0.15)
    rule.reasons.append("ai")
    return rule


def redacted_preview(text: str) -> str:
    return redact(text)


def received_date(msg: RawMessage) -> date:
    if isinstance(msg.date, datetime):
        return clock.to_local(msg.date).date()
    return clock.today()
