"""供应商中立的结构化模型网关契约。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from backend.app.cognition.models import (
    ActionPreference,
    BeliefDecision,
    Direction,
    EventExtractionResult,
    StrictFrozenModel,
)
from backend.app.cognition.streaming import ModelStreamObserver

LiteralOne = Literal[1]


class FailureCode(StrEnum):
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_TRANSPORT_ERROR = "MODEL_TRANSPORT_ERROR"
    MODEL_AUTHENTICATION_ERROR = "MODEL_AUTHENTICATION_ERROR"
    MODEL_PERMISSION_ERROR = "MODEL_PERMISSION_ERROR"
    MODEL_RATE_LIMITED = "MODEL_RATE_LIMITED"
    MODEL_OVERLOADED = "MODEL_OVERLOADED"
    MODEL_QUOTA_EXHAUSTED = "MODEL_QUOTA_EXHAUSTED"
    MODEL_REQUEST_INVALID = "MODEL_REQUEST_INVALID"
    MODEL_RESPONSE_INVALID = "MODEL_RESPONSE_INVALID"
    MODEL_PRICING_UNAVAILABLE = "MODEL_PRICING_UNAVAILABLE"
    MODEL_COST_BUDGET_EXCEEDED = "MODEL_COST_BUDGET_EXCEEDED"
    MODEL_USAGE_MISSING = "MODEL_USAGE_MISSING"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    REFUSAL = "REFUSAL"
    CONTENT_FILTERED = "CONTENT_FILTERED"
    EVIDENCE_ID_UNKNOWN = "EVIDENCE_ID_UNKNOWN"
    ACTION_NOT_ALLOWED = "ACTION_NOT_ALLOWED"
    FALLBACK_USED = "FALLBACK_USED"
    RULE_FALLBACK_USED = "RULE_FALLBACK_USED"


class ModelGatewayError(RuntimeError):
    def __init__(
        self,
        code: FailureCode,
        message: str,
        *,
        retryable: bool = False,
        httpStatus: int | None = None,
        providerCode: str | None = None,
        attempts: int = 0,
        uncertainBillableAttempts: int = 0,
        repairUsed: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.httpStatus = httpStatus
        self.providerCode = providerCode
        self.attempts = attempts
        self.uncertainBillableAttempts = uncertainBillableAttempts
        self.repairUsed = repairUsed


class SamplingConfig(StrictFrozenModel):
    thinking_enabled: bool = False
    do_sample: bool = False
    max_tokens: int = Field(default=2_048, ge=1, le=131_072)
    reasoning_effort: str | None = Field(
        default=None,
        pattern=r"^(max|xhigh|high|medium|low|minimal|none)$",
    )

    @model_validator(mode="after")
    def validateReasoningEffort(self) -> SamplingConfig:
        if self.reasoning_effort is not None and not self.thinking_enabled:
            raise ValueError("reasoning_effort requires thinking_enabled")
        return self


class ModelPolicy(StrictFrozenModel):
    timeout_seconds: float = Field(default=45.0, ge=1.0, le=300.0)
    max_transport_attempts: int = Field(default=3, ge=1, le=3)
    repair_attempts: LiteralOne = 1
    base_backoff_seconds: float = Field(default=0.25, ge=0.0, le=10.0)
    allow_rule_fallback: bool = True


@dataclass(frozen=True, slots=True)
class ModelRequest:
    provider: str
    model: str
    requestId: str
    userId: str
    systemPrompt: str
    userContent: str
    promptHash: str
    schemaVersion: str
    agentConfigHash: str
    observationHash: str
    allowedEvidenceIds: frozenset[str]
    samplingConfig: SamplingConfig
    apiKey: str = field(repr=False)
    allowedActionValues: frozenset[str] = frozenset()
    # 只有交互式解释链路启用供应商流式传输；回调只接收计数和阶段，绝不接收
    # 未验证正文或供应商隐藏思维链。
    streamResponse: bool = False
    streamObserver: ModelStreamObserver | None = field(
        default=None,
        repr=False,
        compare=False,
    )


@dataclass(frozen=True, slots=True)
class ModelUsage:
    promptTokens: int = 0
    completionTokens: int = 0
    cachedTokens: int = 0

    @property
    def totalTokens(self) -> int:
        return self.promptTokens + self.completionTokens

    def plus(self, other: ModelUsage) -> ModelUsage:
        return ModelUsage(
            promptTokens=self.promptTokens + other.promptTokens,
            completionTokens=self.completionTokens + other.completionTokens,
            cachedTokens=self.cachedTokens + other.cachedTokens,
        )


@dataclass(frozen=True, slots=True)
class ModelResult[ModelT: BaseModel]:
    data: ModelT
    provider: str
    model: str
    requestId: str
    promptHash: str
    responseHash: str
    cacheKey: str
    usage: ModelUsage
    latencyMs: float
    transportAttempts: int
    repairUsed: bool
    fallbackUsed: bool
    cacheHit: bool
    # 超时或传输异常无法证明请求未到达供应商；预算必须为这些尝试保留上界费用。
    uncertainBillableAttempts: int = 0
    failureCodes: tuple[FailureCode, ...] = ()
    costUpperBoundUsd: float | None = None


class ModelGateway(Protocol):
    async def generateStructured[ModelT: BaseModel](
        self,
        request: ModelRequest,
        schema: type[ModelT],
        policy: ModelPolicy,
    ) -> ModelResult[ModelT]: ...


def sha256Text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonicalHash(value: BaseModel | dict) -> str:
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validateEvidenceReferences(value: BaseModel, allowedEvidenceIds: frozenset[str]) -> None:
    evidenceMethod = getattr(value, "evidenceIds", None)
    referencedIds = evidenceMethod() if callable(evidenceMethod) else frozenset()
    unknownIds = referencedIds - allowedEvidenceIds
    if unknownIds:
        raise ModelGatewayError(
            FailureCode.EVIDENCE_ID_UNKNOWN,
            f"model referenced unknown evidence IDs: {', '.join(sorted(unknownIds))}",
        )


def validateAllowedAction(value: BaseModel, allowedActionValues: frozenset[str]) -> None:
    if not allowedActionValues or not isinstance(value, BeliefDecision):
        return
    if value.action_preference.value not in allowedActionValues:
        raise ModelGatewayError(
            FailureCode.ACTION_NOT_ALLOWED,
            f"action is not allowed: {value.action_preference.value}",
        )


def buildRuleFallback[ModelT: BaseModel](schema: type[ModelT], failureCode: FailureCode) -> ModelT:
    if schema is BeliefDecision:
        value = BeliefDecision(
            direction=Direction.NEUTRAL,
            expected_value_change_pct=0.0,
            uncertainty=1.0,
            perceived_tail_risk=1.0,
            horizon_minutes=1,
            evidence=(),
            action_preference=ActionPreference.ABSTAIN,
            target_position_fraction=0.0,
            urgency=0.0,
            confidence=0.0,
            decision_summary="No model decision passed deterministic validation.",
            public_message=None,
            abstain_reason=f"Rule fallback after {failureCode.value}.",
        )
        return value  # type: ignore[return-value]
    if schema is EventExtractionResult:
        value = EventExtractionResult(
            claims=(),
            source_summary="No candidate claims passed deterministic validation.",
            abstain_reason=f"Rule fallback after {failureCode.value}.",
        )
        return value  # type: ignore[return-value]
    raise ModelGatewayError(
        FailureCode.MODEL_RESPONSE_INVALID,
        f"no safe rule fallback is registered for {schema.__name__}",
    )
