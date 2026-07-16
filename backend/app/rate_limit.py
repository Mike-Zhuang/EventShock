"""公开 Demo 的轻量滑动窗口限流，不依赖外部状态服务。"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class RateLimitRule:
    key: str
    limit: int
    windowSeconds: float = 60.0


class RateLimitExceeded(Exception):
    def __init__(self, retryAfterSeconds: int) -> None:
        super().__init__("rate limit exceeded")
        self.retryAfterSeconds = retryAfterSeconds


class SlidingWindowRateLimiter:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        maxBuckets: int = 10_000,
    ) -> None:
        self.clock = clock
        self.maxBuckets = maxBuckets
        self.buckets: dict[str, deque[float]] = {}
        self.lock = threading.Lock()

    def check(self, rules: list[RateLimitRule]) -> None:
        now = self.clock()
        with self.lock:
            for rule in rules:
                bucket = self.buckets.setdefault(rule.key, deque())
                cutoff = now - rule.windowSeconds
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if len(bucket) >= rule.limit:
                    retryAfter = max(1, math.ceil(rule.windowSeconds - (now - bucket[0])))
                    raise RateLimitExceeded(retryAfter)
            # 所有规则均通过后再同时记账，避免部分规则消耗配额。
            for rule in rules:
                self.buckets[rule.key].append(now)
            self._boundMemory()

    def _boundMemory(self) -> None:
        if len(self.buckets) <= self.maxBuckets:
            return
        emptyKeys = [key for key, bucket in self.buckets.items() if not bucket]
        for key in emptyKeys:
            self.buckets.pop(key, None)
        while len(self.buckets) > self.maxBuckets:
            self.buckets.pop(next(iter(self.buckets)))
