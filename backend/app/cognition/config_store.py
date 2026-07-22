"""按匿名会话隔离、仅驻留内存的模型凭据配置。"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import Field

from backend.app.cognition.catalog import DEFAULT_PROVIDER, ProviderId, getModel
from backend.app.cognition.models import StrictFrozenModel
from backend.app.cognition.pricing import getTokenPrice, getZhipuTokenPrice

SESSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class CredentialNotConfiguredError(LookupError):
    pass


class SessionProviderConfigView(StrictFrozenModel):
    configured: bool
    provider: ProviderId | None = None
    model: str | None = None
    thinking_enabled: bool | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    credential_hint: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RuntimeProviderConfig:
    provider: ProviderId
    model: str
    thinkingEnabled: bool
    maxTokens: int
    apiKey: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _SessionCredential:
    provider: ProviderId
    model: str
    thinkingEnabled: bool
    maxTokens: int
    expiresAt: float
    apiKey: str = field(repr=False)


class SessionConfigStore:
    """密钥不会落盘、不会回显；过期配置在读取时立即删除。"""

    def __init__(
        self,
        *,
        ttlSeconds: int = 1_800,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not 30 <= ttlSeconds <= 86_400:
            raise ValueError("ttlSeconds must be between 30 and 86400")
        self._ttlSeconds = ttlSeconds
        self._clock = clock
        self._items: dict[str, _SessionCredential] = {}
        self._lock = threading.RLock()

    def setConfig(
        self,
        *,
        sessionId: str,
        apiKey: str,
        model: str,
        provider: ProviderId = DEFAULT_PROVIDER,
        thinkingEnabled: bool = False,
        maxTokens: int = 2_048,
    ) -> SessionProviderConfigView:
        self._validateSessionId(sessionId)
        self._validateApiKey(apiKey)
        descriptor = getModel(provider, model)
        price = getZhipuTokenPrice(model) if provider == "zhipu" else getTokenPrice(provider, model)
        if price is None:
            raise ValueError(
                f"{provider}/{model} cannot be configured because no verified public token "
                "price is available"
            )
        if descriptor.max_output_tokens is None:
            raise ValueError(
                f"{provider}/{model} cannot be configured because no verified maximum output "
                "limit is available"
            )
        if not 1 <= maxTokens <= descriptor.max_output_tokens:
            raise ValueError(
                f"maxTokens must be between 1 and the application limit "
                f"{descriptor.max_output_tokens} for {provider}/{model}"
            )
        if thinkingEnabled and not descriptor.supports_thinking:
            raise ValueError(f"{model} does not support thinking")

        expiresAt = self._clock() + self._ttlSeconds
        credential = _SessionCredential(
            provider=provider,
            model=model,
            thinkingEnabled=thinkingEnabled,
            maxTokens=maxTokens,
            expiresAt=expiresAt,
            apiKey=apiKey,
        )
        with self._lock:
            self._purgeExpiredLocked(self._clock())
            self._items[sessionId] = credential
        return self._toView(credential)

    def getRuntimeConfig(self, sessionId: str) -> RuntimeProviderConfig:
        self._validateSessionId(sessionId)
        with self._lock:
            self._purgeExpiredLocked(self._clock())
            credential = self._activeCredential(sessionId)
            if credential is None:
                raise CredentialNotConfiguredError("model credential is not configured")
            return RuntimeProviderConfig(
                provider=credential.provider,
                model=credential.model,
                thinkingEnabled=credential.thinkingEnabled,
                maxTokens=credential.maxTokens,
                apiKey=credential.apiKey,
            )

    def getView(self, sessionId: str) -> SessionProviderConfigView:
        self._validateSessionId(sessionId)
        with self._lock:
            self._purgeExpiredLocked(self._clock())
            credential = self._activeCredential(sessionId)
            if credential is None:
                return SessionProviderConfigView(configured=False)
            return self._toView(credential)

    def clear(self, sessionId: str) -> bool:
        self._validateSessionId(sessionId)
        with self._lock:
            return self._items.pop(sessionId, None) is not None

    def purgeExpired(self) -> int:
        now = self._clock()
        with self._lock:
            return self._purgeExpiredLocked(now)

    def _purgeExpiredLocked(self, now: float) -> int:
        """调用方必须持有锁；每次配置活动都顺带清除其他会话的过期密钥。"""

        expiredSessionIds = [
            sessionId
            for sessionId, credential in self._items.items()
            if credential.expiresAt <= now
        ]
        for sessionId in expiredSessionIds:
            del self._items[sessionId]
        return len(expiredSessionIds)

    def _activeCredential(self, sessionId: str) -> _SessionCredential | None:
        credential = self._items.get(sessionId)
        if credential is not None and credential.expiresAt <= self._clock():
            del self._items[sessionId]
            return None
        return credential

    @staticmethod
    def _validateSessionId(sessionId: str) -> None:
        if not SESSION_PATTERN.fullmatch(sessionId):
            raise ValueError("invalid sessionId")

    @staticmethod
    def _validateApiKey(apiKey: str) -> None:
        if not 8 <= len(apiKey) <= 4_096 or apiKey != apiKey.strip():
            raise ValueError("invalid API key")
        if any(character.isspace() for character in apiKey):
            raise ValueError("invalid API key")

    @staticmethod
    def _toView(credential: _SessionCredential) -> SessionProviderConfigView:
        return SessionProviderConfigView(
            configured=True,
            provider=credential.provider,
            model=credential.model,
            thinking_enabled=credential.thinkingEnabled,
            max_tokens=credential.maxTokens,
            credential_hint=f"••••{credential.apiKey[-4:]}",
            expires_at=datetime.fromtimestamp(credential.expiresAt, tz=UTC),
        )
