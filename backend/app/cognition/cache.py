"""不可覆盖的认知决策缓存，用于配对实验与确定性重放。"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


class CacheConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CachedDecision:
    cacheKey: str
    payload: bytes
    provider: str
    model: str
    promptHash: str
    responseHash: str
    createdAt: float


def canonicalModelBytes(value: BaseModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def buildDecisionCacheKey(
    *,
    tenantHash: str,
    provider: str,
    model: str,
    promptHash: str,
    schemaVersion: str,
    agentConfigHash: str,
    observationHash: str,
    samplingConfig: Mapping[str, Any],
) -> str:
    material = {
        # 认知缓存按登录会话隔离；这里只写不可逆摘要，避免把用户标识带入缓存元数据。
        "tenantHash": tenantHash,
        "provider": provider,
        "model": model,
        "promptHash": promptHash,
        "schemaVersion": schemaVersion,
        "agentConfigHash": agentConfigHash,
        "observationHash": observationHash,
        "samplingConfig": samplingConfig,
    }
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ImmutableDecisionCache:
    def __init__(self, *, maxEntries: int = 10_000) -> None:
        if not 1 <= maxEntries <= 1_000_000:
            raise ValueError("maxEntries must be between 1 and 1000000")
        self._maxEntries = maxEntries
        self._items: dict[str, CachedDecision] = {}
        self._lock = threading.RLock()

    def get[ModelT: BaseModel](
        self, cacheKey: str, schema: type[ModelT]
    ) -> tuple[ModelT, CachedDecision] | None:
        with self._lock:
            item = self._items.get(cacheKey)
        if item is None:
            return None
        # 每次从不可变字节重建对象，调用者无法污染缓存中的实例。
        return schema.model_validate_json(item.payload), item

    def put(
        self,
        *,
        cacheKey: str,
        decision: BaseModel,
        provider: str,
        model: str,
        promptHash: str,
        responseHash: str | None = None,
    ) -> CachedDecision:
        if len(cacheKey) != 64:
            raise ValueError("cacheKey must be a SHA-256 hex digest")
        payload = canonicalModelBytes(decision)
        resolvedResponseHash = responseHash or hashlib.sha256(payload).hexdigest()
        item = CachedDecision(
            cacheKey=cacheKey,
            payload=payload,
            provider=provider,
            model=model,
            promptHash=promptHash,
            responseHash=resolvedResponseHash,
            createdAt=time.time(),
        )
        with self._lock:
            existing = self._items.get(cacheKey)
            if existing is not None:
                if existing.payload != payload:
                    raise CacheConflictError("an immutable cache key cannot be overwritten")
                return existing
            if len(self._items) >= self._maxEntries:
                raise OverflowError("immutable decision cache capacity exceeded")
            self._items[cacheKey] = item
        return item

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
