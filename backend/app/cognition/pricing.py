"""供应商公开价格快照与并发安全的模型费用硬预算。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from decimal import ROUND_UP, Decimal
from types import MappingProxyType
from typing import Literal

from backend.app.cognition.catalog import (
    DEFAULT_PROVIDER,
    ProviderId,
    getModel,
    getZhipuModel,
)
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
PRICING_SNAPSHOT_VERSION = "multi-provider-public-list-2026-07-20"
PRICING_VERIFIED_AT = "2026-07-20T00:00:00Z"
MULTI_PROVIDER_PRICING_VERIFIED_AT = "2026-07-20T00:00:00Z"

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


@dataclass(frozen=True, slots=True)
class TokenPriceDescriptor:
    """每百万 token 的公开价格及预算上界。

    ``list*`` 是用户可识别的公开刊例价，``budget*UpperBound`` 用于硬预算。
    分档、长上下文或缓存写入会变贵时，预算字段取所有适用档位中的最高值。
    """

    provider: ProviderId
    modelId: str
    currency: Literal["USD", "CNY"]
    listInputPerMillion: Decimal
    listCachedInputPerMillion: Decimal | None
    listOutputPerMillion: Decimal
    budgetInputUpperBoundPerMillion: Decimal
    budgetOutputUpperBoundPerMillion: Decimal
    sourceUrl: str
    region: str
    verifiedAt: str = MULTI_PROVIDER_PRICING_VERIFIED_AT
    pricingNote: str = "Published pay-as-you-go token price; account discounts are excluded."


def _tokenPrice(
    provider: ProviderId,
    modelId: str,
    currency: Literal["USD", "CNY"],
    inputRate: str,
    cachedInputRate: str | None,
    outputRate: str,
    *,
    budgetInputRate: str | None = None,
    budgetOutputRate: str | None = None,
    sourceUrl: str,
    region: str,
    note: str,
) -> TokenPriceDescriptor:
    return TokenPriceDescriptor(
        provider=provider,
        modelId=modelId,
        currency=currency,
        listInputPerMillion=Decimal(inputRate),
        listCachedInputPerMillion=(
            Decimal(cachedInputRate) if cachedInputRate is not None else None
        ),
        listOutputPerMillion=Decimal(outputRate),
        budgetInputUpperBoundPerMillion=Decimal(budgetInputRate or inputRate),
        budgetOutputUpperBoundPerMillion=Decimal(budgetOutputRate or outputRate),
        sourceUrl=sourceUrl,
        region=region,
        pricingNote=note,
    )


# 所有预算率均是适用公开档位的保守上界。未知价格的模型不得在此放占位值；
# getTokenPrice 会返回 None，让配置与调用预算执行 fail-closed。
MODEL_TOKEN_PRICES = MappingProxyType(
    {
        ("zhipu", "glm-5.2"): _tokenPrice(
            "zhipu",
            "glm-5.2",
            "CNY",
            "8",
            "2",
            "28",
            sourceUrl="https://bigmodel.cn/pricing",
            region="CN",
            note=(
                "Published standard and cached-input rates; budget charges all input at full rate."
            ),
        ),
        ("zhipu", "glm-4.7-flashx"): _tokenPrice(
            "zhipu",
            "glm-4.7-flashx",
            "CNY",
            "0.5",
            "0.1",
            "3",
            sourceUrl="https://bigmodel.cn/pricing",
            region="CN",
            note=(
                "Published standard and cached-input rates; budget charges all input at full rate."
            ),
        ),
        ("openai", "gpt-5.6-luna"): _tokenPrice(
            "openai",
            "gpt-5.6-luna",
            "USD",
            "1",
            "0.1",
            "6",
            budgetInputRate="2",
            budgetOutputRate="9",
            sourceUrl="https://openai.com/api/pricing/",
            region="GLOBAL",
            note="Budget uses the official >272K-token multiplier upper bound.",
        ),
        ("openai", "gpt-5.6-terra"): _tokenPrice(
            "openai",
            "gpt-5.6-terra",
            "USD",
            "2.5",
            "0.25",
            "15",
            budgetInputRate="5",
            budgetOutputRate="22.5",
            sourceUrl="https://openai.com/api/pricing/",
            region="GLOBAL",
            note="Budget uses the official >272K-token multiplier upper bound.",
        ),
        ("openai", "gpt-5.6-sol"): _tokenPrice(
            "openai",
            "gpt-5.6-sol",
            "USD",
            "5",
            "0.5",
            "30",
            budgetInputRate="10",
            budgetOutputRate="45",
            sourceUrl="https://openai.com/api/pricing/",
            region="GLOBAL",
            note="Budget uses the official >272K-token multiplier upper bound.",
        ),
        ("anthropic", "claude-haiku-4-5-20251001"): _tokenPrice(
            "anthropic",
            "claude-haiku-4-5-20251001",
            "USD",
            "1",
            "0.1",
            "5",
            budgetInputRate="2",
            sourceUrl="https://platform.claude.com/docs/en/about-claude/pricing",
            region="GLOBAL",
            note="Input budget includes the published 1-hour cache-write 2x upper bound.",
        ),
        ("anthropic", "claude-sonnet-4-6"): _tokenPrice(
            "anthropic",
            "claude-sonnet-4-6",
            "USD",
            "3",
            "0.3",
            "15",
            budgetInputRate="6",
            sourceUrl="https://platform.claude.com/docs/en/about-claude/pricing",
            region="GLOBAL",
            note="Input budget includes the published 1-hour cache-write 2x upper bound.",
        ),
        ("anthropic", "claude-sonnet-5"): _tokenPrice(
            "anthropic",
            "claude-sonnet-5",
            "USD",
            "2",
            "0.2",
            "10",
            budgetInputRate="6",
            budgetOutputRate="15",
            sourceUrl="https://platform.claude.com/docs/en/about-claude/pricing",
            region="GLOBAL",
            note=(
                "List rates are the promotion through 2026-08-31; budget rates cover the "
                "standard prices effective 2026-09-01 and the 1-hour cache-write upper bound."
            ),
        ),
        ("google", "gemini-3.5-flash"): _tokenPrice(
            "google",
            "gemini-3.5-flash",
            "USD",
            "1.5",
            "0.15",
            "9",
            sourceUrl="https://ai.google.dev/gemini-api/docs/pricing",
            region="GLOBAL",
            note=(
                "Token-only upper bound. Explicit cache storage and optional tool charges are "
                "excluded and must remain disabled under this hard budget."
            ),
        ),
        ("deepseek", "deepseek-v4-flash"): _tokenPrice(
            "deepseek",
            "deepseek-v4-flash",
            "USD",
            "0.14",
            "0.0028",
            "0.28",
            sourceUrl="https://api-docs.deepseek.com/quick_start/pricing",
            region="GLOBAL",
            note="Published cache-miss input rate is used as the input budget upper bound.",
        ),
        ("deepseek", "deepseek-v4-pro"): _tokenPrice(
            "deepseek",
            "deepseek-v4-pro",
            "USD",
            "0.435",
            "0.003625",
            "0.87",
            sourceUrl="https://api-docs.deepseek.com/quick_start/pricing",
            region="GLOBAL",
            note="Published cache-miss input rate is used as the input budget upper bound.",
        ),
        ("alibaba", "qwen3.6-flash"): _tokenPrice(
            "alibaba",
            "qwen3.6-flash",
            "CNY",
            "4.8",
            "0.96",
            "28.8",
            budgetInputRate="6",
            sourceUrl="https://www.alibabacloud.com/help/en/model-studio/model-pricing",
            region="CN_BEIJING",
            note=(
                "List rates use the highest token-length tier; input budget also includes "
                "the published 1.25x explicit-cache write multiplier."
            ),
        ),
        ("moonshot", "kimi-k2.6"): _tokenPrice(
            "moonshot",
            "kimi-k2.6",
            "CNY",
            "6.5",
            "1.1",
            "27",
            sourceUrl="https://platform.kimi.com/docs/pricing/chat-k26",
            region="CN",
            note="Published cache-miss input rate is used as the input budget upper bound.",
        ),
        ("moonshot", "kimi-k3"): _tokenPrice(
            "moonshot",
            "kimi-k3",
            "CNY",
            "20",
            "2",
            "100",
            sourceUrl="https://platform.kimi.com/docs/pricing/chat-k3",
            region="CN",
            note="Published cache-miss input rate is used as the input budget upper bound.",
        ),
    }
)


def getTokenPrice(provider: ProviderId | str, modelId: str) -> TokenPriceDescriptor | None:
    """先验证 provider/model 联合键，再返回价格；未知价格不做推测。"""

    getModel(provider, modelId)
    price = MODEL_TOKEN_PRICES.get((provider, modelId))  # type: ignore[arg-type]
    if price is not None or provider != "zhipu":
        return price
    legacyPrice = getZhipuTokenPrice(modelId)
    if legacyPrice is None:
        return None
    return TokenPriceDescriptor(
        provider="zhipu",
        modelId=modelId,
        currency="CNY",
        listInputPerMillion=legacyPrice.inputCnyPerMillion,
        listCachedInputPerMillion=None,
        listOutputPerMillion=legacyPrice.outputCnyPerMillion,
        budgetInputUpperBoundPerMillion=legacyPrice.inputCnyPerMillion,
        budgetOutputUpperBoundPerMillion=legacyPrice.outputCnyPerMillion,
        sourceUrl=legacyPrice.sourceUrl,
        region="CN",
        verifiedAt=legacyPrice.verifiedAt,
        pricingNote=legacyPrice.pricingNote,
    )


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


def _moneyUpperBoundUsd(amount: Decimal, currency: Literal["USD", "CNY"]) -> Decimal:
    if currency == "CNY":
        return _usdUpperBound(amount)
    return amount.quantize(COST_QUANTUM_USD, rounding=ROUND_UP)


def usageCostUpperBoundForProviderUsd(
    provider: ProviderId | str,
    modelId: str,
    usage: ModelUsage,
) -> Decimal:
    """按联合 provider/model 与保守预算率计算费用上界。

    缓存 token 仍按完整输入上界计费，避免缓存失效、缓存写入或供应商账单
    口径变化导致硬预算被低估。
    """

    price = getTokenPrice(provider, modelId)
    if price is None:
        raise ModelGatewayError(
            FailureCode.MODEL_PRICING_UNAVAILABLE,
            f"no verified public token price is available for {provider}/{modelId}",
        )
    cost = (
        Decimal(usage.promptTokens) * price.budgetInputUpperBoundPerMillion
        + Decimal(usage.completionTokens) * price.budgetOutputUpperBoundPerMillion
    ) / ONE_MILLION_TOKENS
    return _moneyUpperBoundUsd(cost, price.currency)


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
    provider: str = DEFAULT_PROVIDER


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
    provider: ProviderId | str = DEFAULT_PROVIDER,
) -> CostReservation:
    # 旧智谱型号继续走旧目录与旧价格表；通用安全集合走联合键目录。
    if provider == "zhipu":
        descriptor = getZhipuModel(modelId)
        legacyPrice = getZhipuTokenPrice(modelId)
        price = None
    else:
        descriptor = getModel(provider, modelId)
        legacyPrice = None
        price = getTokenPrice(provider, modelId)
    if provider == "zhipu" and legacyPrice is None:
        raise ModelGatewayError(
            FailureCode.MODEL_PRICING_UNAVAILABLE,
            f"no verified public token price is available for {modelId}",
        )
    if price is None:
        if provider != "zhipu":
            raise ModelGatewayError(
                FailureCode.MODEL_PRICING_UNAVAILABLE,
                f"no verified public token price is available for {provider}/{modelId}",
            )
        inputRate = legacyPrice.inputCnyPerMillion  # type: ignore[union-attr]
        outputRate = legacyPrice.outputCnyPerMillion  # type: ignore[union-attr]
        currency: Literal["USD", "CNY"] = "CNY"
    else:
        inputRate = price.budgetInputUpperBoundPerMillion
        outputRate = price.budgetOutputUpperBoundPerMillion
        currency = price.currency

    officialMaximum = descriptor.max_output_tokens
    if officialMaximum is None:
        raise ModelGatewayError(
            FailureCode.MODEL_PRICING_UNAVAILABLE,
            f"no verified maximum output limit is available for {provider}/{modelId}",
        )
    if not 1 <= maxOutputTokens <= officialMaximum:
        raise ValueError("maxOutputTokens is outside the selected model limit")

    # timeout/transport failure 无法证明供应商一定未计费，因此初始请求与 repair
    # 的每一次允许重试都必须按一个完整可计费响应预留，不能假定 request_id 幂等。
    maximumBillableResponses = (1 + int(policy.repair_attempts)) * policy.max_transport_attempts
    # 官方“上下文”是否包含输出在不同页面的表述并不完全一致。为避免低估，
    # 预算把完整 context_tokens 全部视为可计费输入，并额外预留最大输出。
    maximumPromptPerResponse = descriptor.context_tokens
    maximumPromptTokens = maximumPromptPerResponse * maximumBillableResponses
    maximumCompletionTokens = maxOutputTokens * maximumBillableResponses
    maximumAmount = (
        Decimal(maximumPromptTokens) * inputRate + Decimal(maximumCompletionTokens) * outputRate
    ) / ONE_MILLION_TOKENS

    # 估算只用于可观测性；真正的预留金额始终使用上面的完整上下文上限。
    promptByteUpper = len(systemPrompt.encode("utf-8")) + len(userContent.encode("utf-8")) + 64
    estimatedPromptPerResponse = min(maximumPromptPerResponse, max(1, promptByteUpper))
    return CostReservation(
        reservationId=0,
        modelId=modelId,
        maximumUsd=_moneyUpperBoundUsd(maximumAmount, currency),
        estimatedPromptTokens=estimatedPromptPerResponse * maximumBillableResponses,
        estimatedCompletionTokens=maximumCompletionTokens,
        maximumPromptTokens=maximumPromptTokens,
        maximumCompletionTokens=maximumCompletionTokens,
        maximumBillableResponses=maximumBillableResponses,
        provider=str(provider),
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
        self._provider: str | None = None
        self._billingCurrency: str | None = None
        self._priceSourceUrl: str | None = None
        self._providerPricingVerifiedAt: str | None = None

    def reserve(self, request: ModelRequest, policy: ModelPolicy) -> CostReservation:
        draft = estimateReservation(
            modelId=request.model,
            maxOutputTokens=request.samplingConfig.max_tokens,
            policy=policy,
            systemPrompt=request.systemPrompt,
            userContent=request.userContent,
            provider=request.provider,
        )
        price = getTokenPrice(request.provider, request.model)
        if price is None:
            raise ModelGatewayError(
                FailureCode.MODEL_PRICING_UNAVAILABLE,
                (
                    "no verified public token price is available for "
                    f"{request.provider}/{request.model}"
                ),
            )
        with self._lock:
            if self._provider is not None and self._provider != request.provider:
                raise ValueError("one model cost budget cannot mix providers")
            self._provider = request.provider
            self._billingCurrency = price.currency
            self._priceSourceUrl = price.sourceUrl
            self._providerPricingVerifiedAt = price.verifiedAt
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
                provider=draft.provider,
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
            uncertainAttempts = result.uncertainBillableAttempts
            invalidUsage = (
                usage.cachedTokens > usage.promptTokens
                or usage.promptTokens > active.maximumPromptTokens
                or usage.completionTokens > active.maximumCompletionTokens
                or not isinstance(uncertainAttempts, int)
                or isinstance(uncertainAttempts, bool)
                or uncertainAttempts < 0
                or uncertainAttempts > result.transportAttempts
                or uncertainAttempts > active.maximumBillableResponses
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
            chargedUsd = (
                usageCostUpperBoundUsd(active.modelId, usage)
                if active.provider == "zhipu"
                else usageCostUpperBoundForProviderUsd(active.provider, active.modelId, usage)
            )
            if uncertainAttempts:
                # timeout/transport error 后无法知道请求是否已到达并计费。按预留总额中
                # 对应响应次数的比例继续占用预算，不能因后续重试成功而静默释放。
                uncertainUsd = (
                    active.maximumUsd
                    * Decimal(uncertainAttempts)
                    / Decimal(active.maximumBillableResponses)
                ).quantize(COST_QUANTUM_USD, rounding=ROUND_UP)
                chargedUsd += uncertainUsd
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
            if uncertainAttempts:
                self._unknownUsageCalls += 1
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
                "provider": self._provider,
                "billingCurrency": self._billingCurrency or "UNSET",
                "fxConversionApplied": self._billingCurrency == "CNY",
                "pricingSnapshotVersion": PRICING_SNAPSHOT_VERSION,
                "pricingVerifiedAt": self._providerPricingVerifiedAt or PRICING_VERIFIED_AT,
                "priceSourceUrl": self._priceSourceUrl or PRICE_SOURCE_URL,
                "fxSourceUrl": FX_SOURCE_URL,
                "officialFxSnapshotCnyPerUsd": float(OFFICIAL_FX_SNAPSHOT_CNY_PER_USD),
                "cnyPerUsdBudgetFloor": float(CNY_PER_USD_BUDGET_FLOOR),
                "semantics": (
                    "Upper-bound USD budget accounting from verified public token rates; "
                    "CNY rates use the conservative frozen FX floor, while USD rates require "
                    "no currency conversion. Cached input is charged at the full input rate. "
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
