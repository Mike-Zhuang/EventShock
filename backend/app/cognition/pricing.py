"""智谱公开价格快照与并发安全的模型费用硬预算。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import ROUND_UP, Decimal

from backend.app.cognition.catalog import getZhipuModel
from backend.app.cognition.gateway import (
    FailureCode,
    ModelGatewayError,
    ModelPolicy,
    ModelRequest,
    ModelResult,
    ModelUsage,
)

PRICE_SOURCE_URL = "https://bigmodel.cn/pricing"
FX_SOURCE_URL = "https://www.federalreserve.gov/Releases/h10/current/default.htm"
PRICING_SNAPSHOT_VERSION = "zhipu-public-list-2026-07-15"
PRICING_VERIFIED_AT = "2026-07-15T00:00:00Z"

# 2026-07-10 的美联储 H.10 为 6.7766 CNY/USD。预算换算刻意采用更低的
# 6.00 CNY/USD，使同一人民币刊例费用得到更高的美元预算值；这不是账单汇率。
CNY_PER_USD_BUDGET_FLOOR = Decimal("6.00")
OFFICIAL_FX_SNAPSHOT_CNY_PER_USD = Decimal("6.7766")
ONE_MILLION_TOKENS = Decimal("1000000")
COST_QUANTUM_USD = Decimal("0.000000001")


@dataclass(frozen=True, slots=True)
class ZhipuTokenPrice:
    """每百万 token 的公开刊例价上界；分档模型取所有分档中的最高值。"""

    modelId: str
    inputCnyPerMillion: Decimal
    outputCnyPerMillion: Decimal
    sourceUrl: str = PRICE_SOURCE_URL
    verifiedAt: str = PRICING_VERIFIED_AT
    pricingNote: str = "Maximum published pay-as-you-go rate across all token-length tiers."

    @property
    def free(self) -> bool:
        return self.inputCnyPerMillion == 0 and self.outputCnyPerMillion == 0


def _price(modelId: str, inputRate: str, outputRate: str, *, note: str | None = None):
    return ZhipuTokenPrice(
        modelId=modelId,
        inputCnyPerMillion=Decimal(inputRate),
        outputCnyPerMillion=Decimal(outputRate),
        pricingNote=note or "Maximum published pay-as-you-go rate across all token-length tiers.",
    )


# 仅收录能从智谱公开价格页或官方模型概览稳定核验的型号。没有精确价格的
# GLM-4.6 与 GLM-4.5-AirX 故意缺席，调用预算必须 fail-closed。
ZHIPU_TOKEN_PRICES: dict[str, ZhipuTokenPrice] = {
    "glm-5.2": _price("glm-5.2", "8", "28"),
    "glm-5.1": _price("glm-5.1", "8", "28"),
    "glm-5-turbo": _price("glm-5-turbo", "7", "26"),
    "glm-5": _price("glm-5", "6", "22"),
    "glm-4.7": _price("glm-4.7", "4", "16"),
    "glm-4.7-flashx": _price("glm-4.7-flashx", "0.5", "3"),
    "glm-4.7-flash": _price(
        "glm-4.7-flash",
        "0",
        "0",
        note="Official pricing page identifies this model as free.",
    ),
    "glm-4.5-air": _price("glm-4.5-air", "1.2", "8"),
    "glm-4.5-flash": _price(
        "glm-4.5-flash",
        "0",
        "0",
        note="Official model overview identifies this legacy model as free.",
    ),
    "glm-4-flash-250414": _price(
        "glm-4-flash-250414",
        "0",
        "0",
        note="Official model overview identifies this model as free.",
    ),
    "glm-4-flashx-250414": _price(
        "glm-4-flashx-250414",
        "0.1",
        "0.1",
        note=(
            "Official legacy table publishes one combined token rate; it is applied "
            "to both directions as an upper bound."
        ),
    ),
}


def getZhipuTokenPrice(modelId: str) -> ZhipuTokenPrice | None:
    """返回可核验价格；未知价格返回 None，由调用方执行 fail-closed。"""

    getZhipuModel(modelId)
    return ZHIPU_TOKEN_PRICES.get(modelId)


def _usdUpperBound(cnyAmount: Decimal) -> Decimal:
    return (cnyAmount / CNY_PER_USD_BUDGET_FLOOR).quantize(
        COST_QUANTUM_USD,
        rounding=ROUND_UP,
    )


def usageCostUpperBoundUsd(modelId: str, usage: ModelUsage) -> Decimal:
    price = getZhipuTokenPrice(modelId)
    if price is None:
        raise ModelGatewayError(
            FailureCode.MODEL_PRICING_UNAVAILABLE,
            f"no verified public token price is available for {modelId}",
        )
    costCny = (
        Decimal(usage.promptTokens) * price.inputCnyPerMillion
        + Decimal(usage.completionTokens) * price.outputCnyPerMillion
    ) / ONE_MILLION_TOKENS
    return _usdUpperBound(costCny)


@dataclass(frozen=True, slots=True)
class CostReservation:
    reservationId: int
    modelId: str
    maximumUsd: Decimal
    estimatedPromptTokens: int
    estimatedCompletionTokens: int
    maximumPromptTokens: int
    maximumCompletionTokens: int
    maximumBillableResponses: int


@dataclass(frozen=True, slots=True)
class CostSettlement:
    chargedUsdUpperBound: Decimal
    promptTokens: int
    completionTokens: int
    cachedTokens: int


def estimateReservation(
    *,
    modelId: str,
    maxOutputTokens: int,
    policy: ModelPolicy,
    systemPrompt: str = "",
    userContent: str = "",
) -> CostReservation:
    descriptor = getZhipuModel(modelId)
    price = getZhipuTokenPrice(modelId)
    if price is None:
        raise ModelGatewayError(
            FailureCode.MODEL_PRICING_UNAVAILABLE,
            f"no verified public token price is available for {modelId}",
        )
    if not 1 <= maxOutputTokens <= descriptor.max_output_tokens:
        raise ValueError("maxOutputTokens is outside the selected model limit")

    # timeout/transport failure 无法证明供应商一定未计费，因此初始请求与 repair
    # 的每一次允许重试都必须按一个完整可计费响应预留，不能假定 request_id 幂等。
    maximumBillableResponses = (1 + int(policy.repair_attempts)) * policy.max_transport_attempts
    # 官方“上下文”是否包含输出在不同页面的表述并不完全一致。为避免低估，
    # 预算把完整 context_tokens 全部视为可计费输入，并额外预留最大输出。
    maximumPromptPerResponse = descriptor.context_tokens
    maximumPromptTokens = maximumPromptPerResponse * maximumBillableResponses
    maximumCompletionTokens = maxOutputTokens * maximumBillableResponses
    maximumCny = (
        Decimal(maximumPromptTokens) * price.inputCnyPerMillion
        + Decimal(maximumCompletionTokens) * price.outputCnyPerMillion
    ) / ONE_MILLION_TOKENS

    # 估算只用于可观测性；真正的预留金额始终使用上面的完整上下文上限。
    promptByteUpper = len(systemPrompt.encode("utf-8")) + len(userContent.encode("utf-8")) + 64
    estimatedPromptPerResponse = min(maximumPromptPerResponse, max(1, promptByteUpper))
    return CostReservation(
        reservationId=0,
        modelId=modelId,
        maximumUsd=_usdUpperBound(maximumCny),
        estimatedPromptTokens=estimatedPromptPerResponse * maximumBillableResponses,
        estimatedCompletionTokens=maximumCompletionTokens,
        maximumPromptTokens=maximumPromptTokens,
        maximumCompletionTokens=maximumCompletionTokens,
        maximumBillableResponses=maximumBillableResponses,
    )


class ModelCostBudget:
    """以预留/结算方式保证任何并发调用都不能越过场景美元硬上限。"""

    def __init__(self, capUsd: float | Decimal) -> None:
        self._capUsd = Decimal(str(capUsd)).quantize(COST_QUANTUM_USD)
        if self._capUsd < 0:
            raise ValueError("capUsd must be non-negative")
        self._lock = threading.RLock()
        self._nextReservationId = 1
        self._active: dict[int, CostReservation] = {}
        self._chargedUsd = Decimal(0)
        self._estimatedPromptTokens = 0
        self._estimatedCompletionTokens = 0
        self._actualPromptTokens = 0
        self._actualCompletionTokens = 0
        self._cachedTokens = 0
        self._reservedCalls = 0
        self._settledCalls = 0
        self._blockedCalls = 0
        self._unknownUsageCalls = 0

    def reserve(self, request: ModelRequest, policy: ModelPolicy) -> CostReservation:
        draft = estimateReservation(
            modelId=request.model,
            maxOutputTokens=request.samplingConfig.max_tokens,
            policy=policy,
            systemPrompt=request.systemPrompt,
            userContent=request.userContent,
        )
        with self._lock:
            activeUsd = sum(
                (item.maximumUsd for item in self._active.values()),
                Decimal("0"),
            )
            if self._chargedUsd + activeUsd + draft.maximumUsd > self._capUsd:
                self._blockedCalls += 1
                remaining = max(Decimal(0), self._capUsd - self._chargedUsd - activeUsd)
                raise ModelGatewayError(
                    FailureCode.MODEL_COST_BUDGET_EXCEEDED,
                    (
                        "model call blocked before dispatch: "
                        f"${draft.maximumUsd} worst-case reservation exceeds "
                        f"${remaining.quantize(COST_QUANTUM_USD)} remaining budget"
                    ),
                )
            reservation = CostReservation(
                reservationId=self._nextReservationId,
                modelId=draft.modelId,
                maximumUsd=draft.maximumUsd,
                estimatedPromptTokens=draft.estimatedPromptTokens,
                estimatedCompletionTokens=draft.estimatedCompletionTokens,
                maximumPromptTokens=draft.maximumPromptTokens,
                maximumCompletionTokens=draft.maximumCompletionTokens,
                maximumBillableResponses=draft.maximumBillableResponses,
            )
            self._nextReservationId += 1
            self._active[reservation.reservationId] = reservation
            self._reservedCalls += 1
            self._estimatedPromptTokens += reservation.estimatedPromptTokens
            self._estimatedCompletionTokens += reservation.estimatedCompletionTokens
            return reservation

    def settle(
        self,
        reservation: CostReservation,
        result: ModelResult,
    ) -> CostSettlement:
        usage = result.usage
        with self._lock:
            active = self._popActive(reservation)
            invalidUsage = (
                usage.cachedTokens > usage.promptTokens
                or usage.promptTokens > active.maximumPromptTokens
                or usage.completionTokens > active.maximumCompletionTokens
                or FailureCode.MODEL_USAGE_MISSING in result.failureCodes
                or (not result.cacheHit and result.transportAttempts > 0 and usage.totalTokens == 0)
            )
            if invalidUsage:
                self._chargedUsd += active.maximumUsd
                self._unknownUsageCalls += 1
                raise ModelGatewayError(
                    FailureCode.MODEL_USAGE_MISSING,
                    "provider token usage was missing or outside the reserved maximum",
                )
            chargedUsd = usageCostUpperBoundUsd(active.modelId, usage)
            if chargedUsd > active.maximumUsd:
                self._chargedUsd += active.maximumUsd
                self._unknownUsageCalls += 1
                raise ModelGatewayError(
                    FailureCode.MODEL_USAGE_MISSING,
                    "provider usage cost exceeded the pre-dispatch reservation",
                )
            self._chargedUsd += chargedUsd
            self._actualPromptTokens += usage.promptTokens
            self._actualCompletionTokens += usage.completionTokens
            self._cachedTokens += usage.cachedTokens
            self._settledCalls += 1
            return CostSettlement(
                chargedUsdUpperBound=chargedUsd,
                promptTokens=usage.promptTokens,
                completionTokens=usage.completionTokens,
                cachedTokens=usage.cachedTokens,
            )

    def failClosed(self, reservation: CostReservation) -> None:
        """无法取得可信 usage 时按整个预留金额入账，阻止预算被重新使用。"""

        with self._lock:
            active = self._popActive(reservation)
            self._chargedUsd += active.maximumUsd
            self._unknownUsageCalls += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            activeUsd = sum(
                (item.maximumUsd for item in self._active.values()),
                Decimal("0"),
            )
            remainingUsd = max(Decimal(0), self._capUsd - self._chargedUsd - activeUsd)
            return {
                "capUsd": float(self._capUsd),
                "chargedUsdUpperBound": float(
                    self._chargedUsd.quantize(COST_QUANTUM_USD, rounding=ROUND_UP)
                ),
                "activeReservationUsd": float(
                    activeUsd.quantize(COST_QUANTUM_USD, rounding=ROUND_UP)
                ),
                "remainingUsd": float(remainingUsd.quantize(COST_QUANTUM_USD, rounding=ROUND_UP)),
                "estimatedPromptTokens": self._estimatedPromptTokens,
                "estimatedCompletionTokens": self._estimatedCompletionTokens,
                "actualPromptTokens": self._actualPromptTokens,
                "actualCompletionTokens": self._actualCompletionTokens,
                "cachedPromptTokens": self._cachedTokens,
                "reservedCalls": self._reservedCalls,
                "settledCalls": self._settledCalls,
                "blockedCalls": self._blockedCalls,
                "unknownUsageCalls": self._unknownUsageCalls,
                "billingCurrency": "CNY",
                "pricingSnapshotVersion": PRICING_SNAPSHOT_VERSION,
                "pricingVerifiedAt": PRICING_VERIFIED_AT,
                "priceSourceUrl": PRICE_SOURCE_URL,
                "fxSourceUrl": FX_SOURCE_URL,
                "officialFxSnapshotCnyPerUsd": float(OFFICIAL_FX_SNAPSHOT_CNY_PER_USD),
                "cnyPerUsdBudgetFloor": float(CNY_PER_USD_BUDGET_FLOOR),
                "semantics": (
                    "Upper-bound budget accounting from verified public CNY token rates; "
                    "cached input is charged at the full input rate and the frozen FX floor "
                    "is deliberately more conservative than the cited official snapshot. "
                    "Every allowed transport attempt for the initial request and repair is "
                    "reserved because provider-side idempotency is not assumed. "
                    "Taxes, payment-processor fees, discounts, and account-specific bundles "
                    "are outside this model-call cap."
                ),
            }

    def _popActive(self, reservation: CostReservation) -> CostReservation:
        active = self._active.pop(reservation.reservationId, None)
        if active is None or active != reservation:
            raise RuntimeError("cost reservation is not active")
        return active
