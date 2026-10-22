"""Retries with exponential backoff and a simple rate limiter."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def retry(
    fn: Callable[[], T],
    attempts: int = 4,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    retry_on: tuple[type[BaseException], ...] = (OSError,),
    should_retry: Callable[[BaseException], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call fn, retrying transient failures with jittered exponential backoff."""
    last: BaseException | None = None
    for attempt in range(max(1, attempts)):
        try:
            return fn()
        except retry_on as exc:
            if should_retry is not None and not should_retry(exc):
                raise
            last = exc
            if attempt == attempts - 1:
                break
            delay = min(max_delay, base_delay * (2 ** attempt))
            sleep(delay * (0.5 + random.random() / 2))
    assert last is not None
    raise last


class RateLimiter:
    """Token bucket: at most `rate` calls per second on average."""

    def __init__(self, rate: float, burst: int | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.rate = max(rate, 0.001)
        self.capacity = burst or max(1, int(rate))
        self.tokens = float(self.capacity)
        self.clock = clock
        self.sleep = sleep
        self.last = clock()
        self.lock = threading.Lock()
        self.waited = 0.0

    def acquire(self) -> None:
        with self.lock:
            now = self.clock()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
            self.last = now
            if self.tokens < 1:
                wait = (1 - self.tokens) / self.rate
                self.waited += wait
                self.sleep(wait)
                self.tokens = 0
                self.last = self.clock()
            else:
                self.tokens -= 1
