"""按匿名会话隔离、仅驻留内存的模型凭据配置。"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from backend.app.cognition.catalog import DEFAULT_PROVIDER, ProviderId, getModel
from backend.app.cognition.gateway import (
    AdvancedModelParameters,
    validateAdvancedModelParameters,
)
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
    advanced_parameters: AdvancedModelParameters | None = None
    credential_hint: str | None = None
    expires_at: datetime | None = None
    credential_source: Literal["SESSION", "ADMIN_SERVER_ENCRYPTED"] | None = None


@dataclass(frozen=True, slots=True)
class RuntimeProviderConfig:
    provider: ProviderId
    model: str
    thinkingEnabled: bool
    maxTokens: int
    advancedParameters: AdvancedModelParameters
    apiKey: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _SessionCredential:
    provider: ProviderId
    model: str
    thinkingEnabled: bool
    maxTokens: int
    advancedParameters: AdvancedModelParameters
    expiresAt: float
    apiKey: str = field(repr=False)


class SessionConfigStore:
    """临时密钥只驻内存；缺失时可由受信任的持久解析器安全回退。"""

    def __init__(
        self,
        *,
        ttlSeconds: int = 1_800,
        clock: Callable[[], float] = time.time,
        persistentRuntimeResolver: Callable[[str], RuntimeProviderConfig | None] | None = None,
        persistentViewResolver: Callable[[str], SessionProviderConfigView | None] | None = None,
    ) -> None:
        if not 30 <= ttlSeconds <= 86_400:
            raise ValueError("ttlSeconds must be between 30 and 86400")
        self._ttlSeconds = ttlSeconds
        self._clock = clock
        self._persistentRuntimeResolver = persistentRuntimeResolver
        self._persistentViewResolver = persistentViewResolver
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
        advancedParameters: AdvancedModelParameters | None = None,
    ) -> SessionProviderConfigView:
        self._validateSessionId(sessionId)
        validateApiKey(apiKey)
        resolvedAdvancedParameters = validateProviderConfiguration(
            provider=provider,
            model=model,
            thinkingEnabled=thinkingEnabled,
            maxTokens=maxTokens,
            advancedParameters=advancedParameters,
        )

        expiresAt = self._clock() + self._ttlSeconds
        credential = _SessionCredential(
            provider=provider,
            model=model,
            thinkingEnabled=thinkingEnabled,
            maxTokens=maxTokens,
            advancedParameters=resolvedAdvancedParameters,
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
            runtime = (
                RuntimeProviderConfig(
                    provider=credential.provider,
                    model=credential.model,
                    thinkingEnabled=credential.thinkingEnabled,
                    maxTokens=credential.maxTokens,
                    advancedParameters=credential.advancedParameters,
                    apiKey=credential.apiKey,
                )
                if credential is not None
                else None
            )
        if runtime is not None:
            return runtime
        if self._persistentRuntimeResolver is not None:
            persistentRuntime = self._persistentRuntimeResolver(sessionId)
            if persistentRuntime is not None:
                return persistentRuntime
        raise CredentialNotConfiguredError("model credential is not configured")

    def getView(self, sessionId: str) -> SessionProviderConfigView:
        self._validateSessionId(sessionId)
        with self._lock:
            self._purgeExpiredLocked(self._clock())
            credential = self._activeCredential(sessionId)
            view = self._toView(credential) if credential is not None else None
        if view is not None:
            return view
        if self._persistentViewResolver is not None:
            persistentView = self._persistentViewResolver(sessionId)
            if persistentView is not None:
                return persistentView
        return SessionProviderConfigView(configured=False)

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
    def _toView(credential: _SessionCredential) -> SessionProviderConfigView:
        return SessionProviderConfigView(
            configured=True,
            provider=credential.provider,
            model=credential.model,
            thinking_enabled=credential.thinkingEnabled,
            max_tokens=credential.maxTokens,
            advanced_parameters=credential.advancedParameters,
            credential_hint=f"••••{credential.apiKey[-4:]}",
            expires_at=datetime.fromtimestamp(credential.expiresAt, tz=UTC),
            credential_source="SESSION",
        )


def validateApiKey(apiKey: str) -> None:
    """统一验证临时与持久凭据，避免持久层绕过既有输入边界。"""

    if not 8 <= len(apiKey) <= 4_096 or apiKey != apiKey.strip():
        raise ValueError("invalid API key")
    if any(character.isspace() for character in apiKey):
        raise ValueError("invalid API key")


def validateProviderConfiguration(
    *,
    provider: ProviderId,
    model: str,
    thinkingEnabled: bool,
    maxTokens: int,
    advancedParameters: AdvancedModelParameters | None,
) -> AdvancedModelParameters:
    """复用目录、定价、输出上限和高级参数白名单校验。"""

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
    resolvedAdvancedParameters = advancedParameters or AdvancedModelParameters()
    validateAdvancedModelParameters(provider, resolvedAdvancedParameters)
    return resolvedAdvancedParameters
