"""公开 Demo 的滑动窗口限流；认证关键桶通过 SQLite 跨重启保留。"""

from __future__ import annotations

import hashlib
import math
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class RateLimitRule:
    key: str
    limit: int
    windowSeconds: float = 60.0
    protected: bool = False


class RateLimitExceeded(Exception):
    def __init__(self, retryAfterSeconds: int) -> None:
        super().__init__("rate limit exceeded")
        self.retryAfterSeconds = retryAfterSeconds


class SlidingWindowRateLimiter:
    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        maxBuckets: int = 10_000,
        persistencePath: Path | None = None,
        persistentClock: Callable[[], float] = time.time,
    ) -> None:
        self.clock = clock
        self.persistentClock = persistentClock
        self.maxBuckets = maxBuckets
        self.persistencePath = persistencePath
        self.buckets: dict[str, deque[float]] = {}
        self.protectedKeys: set[str] = set()
        self.lock = threading.Lock()
        self.persistentStoreReady = False

    def check(self, rules: list[RateLimitRule]) -> None:
        now = self.clock()
        with self.lock:
            persistentRules = [
                rule for rule in rules if rule.protected and self.persistencePath is not None
            ]
            memoryRules = [
                rule for rule in rules if not (rule.protected and self.persistencePath is not None)
            ]
            for rule in memoryRules:
                if rule.protected:
                    self.protectedKeys.add(rule.key)
                bucket = self.buckets.setdefault(rule.key, deque())
                cutoff = now - rule.windowSeconds
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if len(bucket) >= rule.limit:
                    retryAfter = max(1, math.ceil(rule.windowSeconds - (now - bucket[0])))
                    raise RateLimitExceeded(retryAfter)

            persistentConnection: sqlite3.Connection | None = None
            persistentNow = self.persistentClock()
            try:
                if persistentRules:
                    persistentConnection = self._openPersistentStore()
                    persistentConnection.execute("BEGIN IMMEDIATE")
                    persistentConnection.execute(
                        "DELETE FROM security_rate_limit_events WHERE expires_at <= ?",
                        (persistentNow,),
                    )
                    for rule in persistentRules:
                        bucketHash = self._persistentKey(rule.key)
                        cutoff = persistentNow - rule.windowSeconds
                        row = persistentConnection.execute(
                            """
                            SELECT COUNT(*) AS event_count, MIN(occurred_at) AS oldest
                            FROM security_rate_limit_events
                            WHERE bucket_hash=? AND occurred_at>?
                            """,
                            (bucketHash, cutoff),
                        ).fetchone()
                        eventCount = int(row[0]) if row is not None else 0
                        if eventCount >= rule.limit:
                            oldest = (
                                float(row[1])
                                if row is not None and row[1] is not None
                                else persistentNow
                            )
                            retryAfter = max(
                                1,
                                math.ceil(rule.windowSeconds - (persistentNow - oldest)),
                            )
                            persistentConnection.rollback()
                            raise RateLimitExceeded(retryAfter)

                # 所有规则均通过后再同时记账，避免部分规则消耗配额。
                for rule in memoryRules:
                    self.buckets[rule.key].append(now)
                if persistentConnection is not None:
                    persistentConnection.executemany(
                        """
                        INSERT INTO security_rate_limit_events(
                            bucket_hash, occurred_at, expires_at
                        ) VALUES (?, ?, ?)
                        """,
                        [
                            (
                                self._persistentKey(rule.key),
                                persistentNow,
                                persistentNow + rule.windowSeconds,
                            )
                            for rule in persistentRules
                        ],
                    )
                    persistentConnection.commit()
            finally:
                if persistentConnection is not None:
                    persistentConnection.close()
            self._boundMemory()

    def _openPersistentStore(self) -> sqlite3.Connection:
        if self.persistencePath is None:
            raise RuntimeError("persistent rate-limit storage is not configured")
        self.persistencePath.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.persistencePath, timeout=5)
        if not self.persistentStoreReady:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS security_rate_limit_events (
                    bucket_hash TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_security_rate_limit_events_bucket_time
                ON security_rate_limit_events(bucket_hash, occurred_at)
                """
            )
            connection.commit()
            self.persistentStoreReady = True
        return connection

    @staticmethod
    def _persistentKey(key: str) -> str:
        """持久化固定长度摘要，不把邮箱、IP 或会话标识写入数据库。"""

        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def _boundMemory(self) -> None:
        if len(self.buckets) <= self.maxBuckets:
            return
        emptyKeys = [
            key
            for key, bucket in self.buckets.items()
            if not bucket and key not in self.protectedKeys
        ]
        for key in emptyKeys:
            self.buckets.pop(key, None)
        removableKeys = (key for key in self.buckets if key not in self.protectedKeys)
        while len(self.buckets) > self.maxBuckets:
            try:
                removableKey = next(removableKeys)
            except StopIteration:
                # 认证关键桶不可被攻击者制造的大量会话桶驱逐。若只剩关键桶，
                # 宁可暂时超过软内存上限，也不能重置登录和验证码保护。
                break
            self.buckets.pop(removableKey, None)
