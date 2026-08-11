"""认知层的严格、版本化数据契约。"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$"
INLINE_RESULT_REFERENCE_PATTERN = re.compile(r"\[(result:[^\]\r\n]*)\]")
VALID_RESULT_REFERENCE_PATTERN = re.compile(r"^result:[A-Za-z0-9][A-Za-z0-9._:-]{0,72}$")
PROHIBITED_INVESTMENT_RECOMMENDATION_PATTERNS = (
    re.compile(
        r"\b(?:you should|i recommend|we recommend|consider)\s+"
        r"(?:buy|buying|sell|selling|hold|holding|short|shorting|invest|investing|"
        r"trade|trading|increase|increasing|decrease|decreasing)\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"(?<!不)(?:建议|应该|应当|不妨|可以考虑).{0,12}"
        r"(?:买入|卖出|持有|做多|做空|投资|交易|加仓|减仓)"
    ),
)


class StrictFrozenModel(BaseModel):
    """拒绝未知字段，并阻止通过模型实例原地篡改已验证的决策。"""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Direction(StrEnum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    MIXED = "MIXED"


class ActionPreference(StrEnum):
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    HOLD = "HOLD"
    EXIT = "EXIT"
    ABSTAIN = "ABSTAIN"
    POST_ONLY = "POST_ONLY"


class EvidenceStance(StrEnum):
    SUPPORTS_UPSIDE = "SUPPORTS_UPSIDE"
    SUPPORTS_DOWNSIDE = "SUPPORTS_DOWNSIDE"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"
    UNCERTAIN = "UNCERTAIN"


class EvidenceSourceType(StrEnum):
    OFFICIAL_COMPANY = "official_company"
    OFFICIAL_EXCHANGE = "official_exchange"
    OFFICIAL_REGULATOR = "official_regulator"
    FILING = "filing"
    REPUTABLE_NEWS = "reputable_news"
    SOCIAL = "social"
    SYNTHETIC = "synthetic"
    OTHER = "other"


class VolatilityRegime(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    STRESSED = "stressed"


class TrustProfile(StrictFrozenModel):
    official: float = Field(ge=0.0, le=1.0)
    news: float = Field(ge=0.0, le=1.0)
    social: float = Field(ge=0.0, le=1.0)


class AgentProfile(StrictFrozenModel):
    id: str = Field(min_length=3, max_length=128, pattern=IDENTIFIER_PATTERN)
    role: str = Field(min_length=2, max_length=80, pattern=r"^[a-z][a-z0-9_]{1,79}$")
    risk_tolerance: float = Field(ge=0.0, le=1.0)
    loss_aversion: float = Field(ge=0.1, le=10.0)
    horizon_minutes: int = Field(ge=1, le=10_080)
    confirmation_bias: float = Field(ge=0.0, le=1.0)
    trust_profile: TrustProfile


class PortfolioObservation(StrictFrozenModel):
    cash_cents: int = Field(ge=0, le=10**15)
    position: int = Field(ge=-1_000_000, le=1_000_000)
    unrealized_pnl_pct: float = Field(ge=-10.0, le=10.0)
    max_position: int = Field(ge=1, le=1_000_000)

    @model_validator(mode="after")
    def validatePositionLimit(self) -> PortfolioObservation:
        if abs(self.position) > self.max_position:
            raise ValueError("position must be within max_position")
        return self


class MarketObservation(StrictFrozenModel):
    instrument_id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Z0-9._-]+$")
    mid_price_ticks: int = Field(ge=1, le=10**12)
    best_bid_ticks: int | None = Field(default=None, ge=1, le=10**12)
    best_ask_ticks: int | None = Field(default=None, ge=1, le=10**12)
    return_1m: float = Field(ge=-1.0, le=1.0)
    return_15m: float = Field(ge=-1.0, le=1.0)
    spread_bps: float = Field(ge=0.0, le=10_000.0)
    depth_10bps: int = Field(ge=0, le=10**12)
    order_imbalance: float = Field(ge=-1.0, le=1.0)
    volatility_regime: VolatilityRegime

    @model_validator(mode="after")
    def validateTopOfBook(self) -> MarketObservation:
        if (
            self.best_bid_ticks is not None
            and self.best_ask_ticks is not None
            and self.best_bid_ticks >= self.best_ask_ticks
        ):
            raise ValueError("best_bid_ticks must be below best_ask_ticks")
        return self


class EvidenceItem(StrictFrozenModel):
    evidence_id: str = Field(min_length=3, max_length=128, pattern=IDENTIFIER_PATTERN)
    claim: str = Field(min_length=1, max_length=4_000)
    source_type: EvidenceSourceType
    known_at: datetime
    credibility: float = Field(ge=0.0, le=1.0)
    human_approved: bool

    @model_validator(mode="after")
    def validateTimezone(self) -> EvidenceItem:
        if self.known_at.tzinfo is None or self.known_at.utcoffset() is None:
            raise ValueError("known_at must include a timezone")
        return self


class SocialPost(StrictFrozenModel):
    post_id: str = Field(min_length=3, max_length=128, pattern=IDENTIFIER_PATTERN)
    text: str = Field(min_length=1, max_length=1_000)
    author_trust: float = Field(ge=0.0, le=1.0)
    seen_at: datetime

    @model_validator(mode="after")
    def validateTimezone(self) -> SocialPost:
        if self.seen_at.tzinfo is None or self.seen_at.utcoffset() is None:
            raise ValueError("seen_at must include a timezone")
        return self


class MemorySummary(StrictFrozenModel):
    memory_id: str = Field(min_length=3, max_length=128, pattern=IDENTIFIER_PATTERN)
    summary: str = Field(min_length=1, max_length=500)
    salience: float = Field(ge=0.0, le=1.0)


class Observation(StrictFrozenModel):
    """LLM 能看到的完整且有限的观察；不接受订单簿原始明细。"""

    schema_version: Literal["observation_v1.0.0"] = "observation_v1.0.0"
    observation_id: str = Field(min_length=3, max_length=128, pattern=IDENTIFIER_PATTERN)
    now: datetime
    agent: AgentProfile
    portfolio: PortfolioObservation
    market: MarketObservation
    new_evidence: tuple[EvidenceItem, ...] = Field(default=(), max_length=64)
    social_feed: tuple[SocialPost, ...] = Field(default=(), max_length=50)
    memory_summary: tuple[MemorySummary, ...] = Field(default=(), max_length=50)
    allowed_actions: tuple[ActionPreference, ...] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def validateObservationBoundary(self) -> Observation:
        if self.now.tzinfo is None or self.now.utcoffset() is None:
            raise ValueError("now must include a timezone")
        evidenceIds = [item.evidence_id for item in self.new_evidence]
        if len(evidenceIds) != len(set(evidenceIds)):
            raise ValueError("new_evidence contains duplicate evidence_id values")
        if any(item.known_at > self.now for item in self.new_evidence):
            raise ValueError("observation cannot contain future evidence")
        if any(not item.human_approved for item in self.new_evidence):
            raise ValueError("cognitive agents may only observe human-approved evidence")
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError("allowed_actions contains duplicates")
        if ActionPreference.ABSTAIN not in self.allowed_actions:
            raise ValueError("allowed_actions must always include ABSTAIN")
        return self

    def evidenceIds(self) -> frozenset[str]:
        return frozenset(item.evidence_id for item in self.new_evidence)


class EvidenceAssessment(StrictFrozenModel):
    evidence_id: str = Field(min_length=3, max_length=128, pattern=IDENTIFIER_PATTERN)
    stance: EvidenceStance
    weight: float = Field(ge=0.0, le=1.0)


class BeliefDecision(StrictFrozenModel):
    """LLM 的唯一可执行输出；它表达信念，不是订单。"""

    schema_version: Literal["belief_decision_v1.0.0"] = "belief_decision_v1.0.0"
    direction: Direction
    expected_value_change_pct: float = Field(ge=-1.0, le=1.0)
    uncertainty: float = Field(ge=0.0, le=1.0)
    perceived_tail_risk: float = Field(ge=0.0, le=1.0)
    horizon_minutes: int = Field(ge=1, le=10_080)
    evidence: tuple[EvidenceAssessment, ...] = Field(default=(), max_length=64)
    action_preference: ActionPreference
    target_position_fraction: float = Field(ge=-1.0, le=1.0)
    urgency: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    decision_summary: str = Field(min_length=1, max_length=500)
    public_message: str | None = Field(default=None, max_length=500)
    abstain_reason: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def validateDecision(self) -> BeliefDecision:
        evidenceIds = [item.evidence_id for item in self.evidence]
        if len(evidenceIds) != len(set(evidenceIds)):
            raise ValueError("evidence contains duplicate evidence_id values")
        if self.action_preference == ActionPreference.ABSTAIN:
            if not self.abstain_reason:
                raise ValueError("ABSTAIN requires abstain_reason")
            if self.target_position_fraction != 0.0 or self.urgency != 0.0:
                raise ValueError("ABSTAIN requires zero target_position_fraction and urgency")
        elif self.abstain_reason is not None:
            raise ValueError("abstain_reason is only valid for ABSTAIN")
        if self.action_preference == ActionPreference.POST_ONLY and not self.public_message:
            raise ValueError("POST_ONLY requires public_message")
        if (
            self.action_preference
            in {
                ActionPreference.INCREASE,
                ActionPreference.REDUCE,
                ActionPreference.EXIT,
                ActionPreference.POST_ONLY,
            }
            and not self.evidence
        ):
            raise ValueError("an active decision must cite at least one evidence item")
        return self

    def evidenceIds(self) -> frozenset[str]:
        return frozenset(item.evidence_id for item in self.evidence)


class ClaimType(StrEnum):
    FACT = "FACT"
    ESTIMATE = "ESTIMATE"
    OPINION = "OPINION"
    RUMOR = "RUMOR"


class ExtractedClaim(StrictFrozenModel):
    candidate_claim_id: str = Field(min_length=3, max_length=128, pattern=IDENTIFIER_PATTERN)
    source_evidence_ids: tuple[str, ...] = Field(min_length=1, max_length=16)
    claim: str = Field(min_length=1, max_length=1_000)
    claim_type: ClaimType
    known_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    instruction_like_text_detected: bool
    requires_human_review: Literal[True] = True

    @model_validator(mode="after")
    def validateClaim(self) -> ExtractedClaim:
        if len(self.source_evidence_ids) != len(set(self.source_evidence_ids)):
            raise ValueError("source_evidence_ids contains duplicates")
        if self.known_at.tzinfo is None or self.known_at.utcoffset() is None:
            raise ValueError("known_at must include a timezone")
        return self


class EventExtractionResult(StrictFrozenModel):
    schema_version: Literal["event_extraction_v1.0.0"] = "event_extraction_v1.0.0"
    claims: tuple[ExtractedClaim, ...] = Field(default=(), max_length=100)
    source_summary: str = Field(min_length=1, max_length=500)
    abstain_reason: str | None = Field(default=None, min_length=1, max_length=300)

    @model_validator(mode="after")
    def validateExtraction(self) -> EventExtractionResult:
        claimIds = [item.candidate_claim_id for item in self.claims]
        if len(claimIds) != len(set(claimIds)):
            raise ValueError("claims contains duplicate candidate_claim_id values")
        if not self.claims and not self.abstain_reason:
            raise ValueError("an empty extraction requires abstain_reason")
        if self.claims and self.abstain_reason is not None:
            raise ValueError("abstain_reason must be null when claims are present")
        return self

    def evidenceIds(self) -> frozenset[str]:
        return frozenset(
            evidenceId for claim in self.claims for evidenceId in claim.source_evidence_ids
        )


class ResultEvidenceTool(StrEnum):
    """结果解释器可以调用的只读工具；不允许任意路径、网络或数据库查询。"""

    OVERVIEW = "OVERVIEW"
    METRIC_SUMMARY = "METRIC_SUMMARY"
    PAIRED_DELTAS = "PAIRED_DELTAS"
    PATH_SERIES = "PATH_SERIES"
    TRACE = "TRACE"
    AGENT_OUTCOMES = "AGENT_OUTCOMES"
    COGNITION_SUMMARY = "COGNITION_SUMMARY"
    COGNITION_DECISIONS = "COGNITION_DECISIONS"
    ANALYSIS_DIAGNOSTICS = "ANALYSIS_DIAGNOSTICS"
    LIMITATIONS = "LIMITATIONS"
    MANIFEST = "MANIFEST"


class ResultToolPlan(StrictFrozenModel):
    """追问阶段的结构化只读工具计划。"""

    schema_version: Literal["result_tool_plan_v1.0.0"] = "result_tool_plan_v1.0.0"
    tools: tuple[ResultEvidenceTool, ...] = Field(min_length=1, max_length=11)
    plan_summary: str = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def validateUniqueTools(self) -> ResultToolPlan:
        if len(self.tools) != len(set(self.tools)):
            raise ValueError("tools must not contain duplicates")
        return self


class ResultInterpretationAnswer(StrictFrozenModel):
    """面向用户的结果解释；analysis_summary 是可核验摘要，不是隐藏思维链。"""

    # 对外只返回规范化后的引用清单，但保留模型最初报告过的 ID，供网关继续执行
    # allowedEvidenceIds 检查。否则“未内联的未知 ID”会在清理时消失，绕过证据边界。
    _reported_grounding_references: tuple[str, ...] = PrivateAttr(default=())

    schema_version: Literal["result_interpretation_v1.0.0"] = "result_interpretation_v1.0.0"
    answer: str = Field(min_length=1, max_length=12_000)
    analysis_summary: str | None = Field(default=None, min_length=1, max_length=2_000)
    grounding_references: tuple[str, ...] = Field(default=(), max_length=20)
    follow_up_suggestions: tuple[str, ...] = Field(default=(), max_length=3)
    scenario_not_forecast: Literal[True] = True
    investment_advice_provided: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def normalizeRecoverableProviderShape(cls, value: object) -> object:
        """修复常见且无歧义的 JSON 形状偏差，避免正常解释因格式细节消失。"""

        if not isinstance(value, dict):
            return value
        aliasMap = {
            "schemaVersion": "schema_version",
            "analysisSummary": "analysis_summary",
            "groundingReferences": "grounding_references",
            "followUpSuggestions": "follow_up_suggestions",
            "scenarioNotForecast": "scenario_not_forecast",
            "investmentAdviceProvided": "investment_advice_provided",
        }
        normalized = {aliasMap.get(key, key): item for key, item in value.items()}
        allowedFields = {
            "schema_version",
            "answer",
            "analysis_summary",
            "grounding_references",
            "follow_up_suggestions",
            "scenario_not_forecast",
            "investment_advice_provided",
        }
        normalized = {key: item for key, item in normalized.items() if key in allowedFields}

        # 这两个值是产品边界而不是由模型自由判断的内容；正文仍会独立扫描
        # 投资建议，因此固定布尔值不会掩盖违规文本。
        normalized["schema_version"] = "result_interpretation_v1.0.0"
        normalized["scenario_not_forecast"] = True
        normalized["investment_advice_provided"] = False

        if normalized.get("analysis_summary") == "":
            normalized["analysis_summary"] = None
        references = normalized.get("grounding_references")
        if isinstance(references, str):
            normalized["grounding_references"] = (references,)
        elif isinstance(references, list):
            normalized["grounding_references"] = tuple(
                item for item in references if isinstance(item, str)
            )

        suggestions = normalized.get("follow_up_suggestions")
        if isinstance(suggestions, str):
            suggestions = (suggestions,)
        if isinstance(suggestions, (list, tuple)):
            cleanedSuggestions: list[str] = []
            for suggestion in suggestions:
                if not isinstance(suggestion, str):
                    continue
                cleaned = INLINE_RESULT_REFERENCE_PATTERN.sub("", suggestion).strip()
                if cleaned:
                    cleanedSuggestions.append(cleaned[:400])
            normalized["follow_up_suggestions"] = tuple(cleanedSuggestions[:3])
        return normalized

    @model_validator(mode="after")
    def validateReviewableAnswer(self) -> ResultInterpretationAnswer:
        if any(
            VALID_RESULT_REFERENCE_PATTERN.fullmatch(reference) is None
            for reference in self.grounding_references
        ):
            raise ValueError("grounding_references contains an invalid evidence ID")
        reportedReferences = tuple(dict.fromkeys(self.grounding_references))
        reviewableText = "\n".join(
            part for part in (self.answer, self.analysis_summary) if part is not None
        )
        citedReferencesInOrder = tuple(
            dict.fromkeys(INLINE_RESULT_REFERENCE_PATTERN.findall(reviewableText))
        )
        if any(
            VALID_RESULT_REFERENCE_PATTERN.fullmatch(reference) is None
            for reference in citedReferencesInOrder
        ):
            raise ValueError("result interpretation contains an invalid inline evidence ID")

        # 引用清单只是供界面生成证据卡的冗余索引。模型漏抄清单、顺序不同或
        # 只在清单中给出合法引用时，服务端可以无损规范化，没必要再次计费或
        # 丢弃正文。未知 ID 仍通过 evidenceIds() 的并集进入网关 allowlist 硬校验。
        allReportedReferences = tuple(dict.fromkeys((*reportedReferences, *citedReferencesInOrder)))
        normalizedReferences = citedReferencesInOrder or reportedReferences

        object.__setattr__(self, "_reported_grounding_references", allReportedReferences)
        object.__setattr__(self, "grounding_references", normalizedReferences)
        if any(
            pattern.search(reviewableText)
            for pattern in PROHIBITED_INVESTMENT_RECOMMENDATION_PATTERNS
        ):
            raise ValueError("result interpretation must not contain an investment recommendation")
        if any(not suggestion.strip() for suggestion in self.follow_up_suggestions):
            raise ValueError("follow_up_suggestions must not contain blank values")
        if any(len(suggestion) > 400 for suggestion in self.follow_up_suggestions):
            raise ValueError("follow_up_suggestions items must not exceed 400 characters")
        # 建议按钮按纯文本展示并会直接写回下一轮问题，因此不能把仅供内部
        # grounding 的证据标记泄露给普通用户或带入后续会话。
        if any(
            INLINE_RESULT_REFERENCE_PATTERN.search(suggestion)
            for suggestion in self.follow_up_suggestions
        ):
            raise ValueError("follow_up_suggestions must not contain result evidence references")
        return self

    def evidenceIds(self) -> frozenset[str]:
        # 使用模型原始报告集合执行 allowlist 校验；规范化不能掩盖未知证据 ID。
        return frozenset(self._reported_grounding_references or self.grounding_references)
