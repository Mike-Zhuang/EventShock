"""结果解释的确定性事实目录与语义校验。

模型负责把结果解释成人类可读语言，但它无权重新计算统计量，也无权改变
“区间是否跨零”“配对差值方向”“有效样本数”等事实。本模块把服务端结果
转换为可验证目录，并在任何模型文本进入会话历史前执行保守校验。
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

from backend.app.cognition.models import ResultInterpretationAnswer

ResultLanguage = Literal["en", "zh-CN"]


class SemanticViolationCode(StrEnum):
    INTERVAL_CROSSES_ZERO_STRONG_CLAIM = "INTERVAL_CROSSES_ZERO_STRONG_CLAIM"
    DIRECTION_MISMATCH = "DIRECTION_MISMATCH"
    DIRECTION_CONSISTENCY_MISMATCH = "DIRECTION_CONSISTENCY_MISMATCH"
    METRIC_NUMBER_UNSUPPORTED = "METRIC_NUMBER_UNSUPPORTED"
    DELTA_VALUE_MISREPRESENTED_AS_RAW = "DELTA_VALUE_MISREPRESENTED_AS_RAW"
    AVAILABLE_INTERVAL_DENIED = "AVAILABLE_INTERVAL_DENIED"
    REQUIRED_PRIMARY_FINDING_OMITTED = "REQUIRED_PRIMARY_FINDING_OMITTED"
    REQUIRED_STRONGEST_FINDING_OMITTED = "REQUIRED_STRONGEST_FINDING_OMITTED"
    STOPPING_REASON_UNSUPPORTED = "STOPPING_REASON_UNSUPPORTED"
    DIAGNOSTIC_TYPE_CONFLATED = "DIAGNOSTIC_TYPE_CONFLATED"
    COGNITION_COUNT_MISMATCH = "COGNITION_COUNT_MISMATCH"
    COGNITION_EFFECT_UNSUPPORTED = "COGNITION_EFFECT_UNSUPPORTED"
    COGNITION_ZERO_EFFECT_CAUSE_UNSUPPORTED = "COGNITION_ZERO_EFFECT_CAUSE_UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class MetricFact:
    metric_id: str
    baseline_median: float | None
    intervention_median: float | None
    paired_difference_median: float | None
    interval_lower: float | None
    interval_upper: float | None
    contains_zero: bool | None
    direction_consistency: float | None
    valid_n: int | None
    preregistered_primary: bool

    def supportedNumbers(self) -> tuple[float, ...]:
        values = (
            self.baseline_median,
            self.intervention_median,
            self.paired_difference_median,
            self.interval_lower,
            self.interval_upper,
            self.direction_consistency,
            float(self.valid_n) if self.valid_n is not None else None,
        )
        return tuple(value for value in values if value is not None and math.isfinite(value))


@dataclass(frozen=True, slots=True)
class ResultFactCatalog:
    metrics: tuple[MetricFact, ...]
    primary_metric_id: str | None
    valid_paired_seeds: int | None
    stopping_reason: str | None
    stopping_reasons: tuple[str, ...]
    stopping_completed_pairs: int | None
    stopping_maximum_pairs: int | None
    cognition_counts: Mapping[str, int]

    def metric(self, metricId: str) -> MetricFact | None:
        return next((item for item in self.metrics if item.metric_id == metricId), None)


@dataclass(frozen=True, slots=True)
class SemanticValidationReport:
    valid: bool
    violation_codes: tuple[SemanticViolationCode, ...]
    strongest_metric_ids: tuple[str, ...]


METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "maxDrawdownPct": ("maxdrawdownpct", "maximum drawdown", "max drawdown", "最大回撤"),
    "realizedVolatilityPct": (
        "realizedvolatilitypct",
        "realized volatility",
        "已实现波动率",
        "实现波动率",
    ),
    "maxSpreadBps": ("maxspreadbps", "peak spread", "maximum spread", "峰值价差", "最大价差"),
    "minDepth": ("mindepth", "minimum market depth", "minimum depth", "最低市场深度", "最小深度"),
    "recoverySteps": ("recoverysteps", "recovery time", "恢复时间"),
    "totalVolume": ("totalvolume", "total volume", "总成交量"),
    "orderImbalance": ("orderimbalance", "order imbalance", "订单不平衡"),
    "cascadeScore": ("cascadescore", "cascade score", "级联得分"),
    "networkReachRate": ("networkreachrate", "network reach", "信息网络触达率"),
    "informationDelaySteps": ("informationdelaysteps", "information delay", "信息延迟"),
    "liquidityStressIndex": (
        "liquiditystressindex",
        "liquidity stress",
        "流动性压力指数",
    ),
    "tailLossProbability": ("taillossprobability", "tail loss probability", "尾部损失概率"),
    "agentPnlDispersionCents": (
        "agentpnldispersioncents",
        "agent pnl dispersion",
        "智能体损益离散度",
    ),
    "systemEquityChangeCents": (
        "systemequitychangecents",
        "system equity change",
        "系统权益变化",
    ),
    "forcedLiquidationVolume": (
        "forcedliquidationvolume",
        "forced liquidation volume",
        "强制平仓量",
    ),
    "ledgerRejectedOrders": (
        "ledgerrejectedorders",
        "ledger rejected orders",
        "账本拒绝订单数",
    ),
    "cognitiveOrderCount": (
        "cognitiveordercount",
        "cognition-influenced orders",
        "认知信号影响订单数",
    ),
    "benchmarkReturnPct": ("benchmarkreturnpct", "benchmark return", "基准收益率"),
    "abnormalReturnPct": ("abnormalreturnpct", "abnormal return", "异常收益率"),
    "haltCount": ("haltcount", "halt count", "停牌次数"),
    "haltedSteps": ("haltedsteps", "halted steps", "停牌步数"),
    "totalFeesPaidCents": ("totalfeespaidcents", "total fees", "总支付费用"),
}

_NUMBER_PATTERN = re.compile(r"(?<![\w:])([+\-−]?\d+(?:,\d{3})*(?:\.\d+)?)(%?)")
_INLINE_REFERENCE_PATTERN = re.compile(r"\[result:[a-z-]+\]")
_STRONG_CLAIM_PATTERN = re.compile(
    r"\b(significant|significantly|reliable|conclusive|clearly|proves?|demonstrates?)\b"
    r"|显著|明确证明|可靠结论|确定(?:地)?表明|证实",
    re.IGNORECASE,
)
_INCREASE_PATTERN = re.compile(
    r"\b(increase[sd]?|higher|rose|rises|upward|expanded|widened)\b|上升|增加|扩大|变高",
    re.IGNORECASE,
)
_DECREASE_PATTERN = re.compile(
    r"\b(decrease[sd]?|lower|fell|falls|downward|declined|narrowed)\b|下降|减少|收窄|变低",
    re.IGNORECASE,
)
_DIRECTION_CONSISTENCY_VALUE_PATTERN = re.compile(
    r"(?:direction(?:al)? consistency|方向一致率|一致率)[^\d%]{0,32}"
    r"(\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
_STOP_TARGET_PATTERN = re.compile(
    r"target (?:confidence|interval|ci)|target half-width|目标(?:置信)?区间|目标区间半宽",
    re.IGNORECASE,
)
_STOP_FIXED_PATTERN = re.compile(
    r"fixed (?:pair|seed|sample) count|maximum (?:pair|seed|sample)|固定(?:配对|种子|样本)"
    r"|达到最大(?:配对|种子|样本)",
    re.IGNORECASE,
)
_EARLY_STOP_OR_SAVINGS_PATTERN = re.compile(
    r"\b(?:stop(?:ped|ping)? early|early stop|saved|avoided|did not exhaust|"
    r"before (?:the )?(?:maximum|preset))\b.{0,48}\b(?:pair|seed|sample)s?\b"
    r"|提前停止|提前终止|节省.{0,24}(?:配对|种子|样本)|未用完.{0,24}(?:配对|种子|样本)"
    r"|没有耗尽.{0,24}(?:配对|种子|样本)",
    re.IGNORECASE,
)
_COGNITION_EFFECT_PATTERN = re.compile(
    r"\bllm\b.{0,80}\b(changed|influenced|caused|generated|drove)\b.{0,80}\b"
    r"(intent|order|market|price)\b|大语言模型.{0,80}(改变|影响|导致|生成|驱动)"
    r".{0,80}(意图|订单|市场|价格)",
    re.IGNORECASE,
)
_RAW_NEGATIVE_METRIC_PATTERN = re.compile(
    r"(?:minimum market depth|minimum depth|最低市场深度|最小深度).{0,48}"
    r"(?:was|were|is|are|为|是|全部为).{0,20}[-−]\d",
    re.IGNORECASE,
)
_DELTA_LANGUAGE_PATTERN = re.compile(
    r"\b(?:difference|delta|change|changed|decreased|fell|lower by)\b|"
    r"差值|变化|改变|下降|减少|少于",
    re.IGNORECASE,
)
_INTERVAL_DENIAL_PATTERN = re.compile(
    r"\b(?:no|not|without|unavailable|missing).{0,24}"
    r"(?:interval|confidence interval)\b|(?:未|没有|缺少|不可用).{0,16}(?:区间|置信区间)",
    re.IGNORECASE,
)
_DIAGNOSTIC_CONFLATION_PATTERN = re.compile(
    r"(?:negative control|负向对照|负对照).{0,100}"
    r"(?:parameter restoration|restore|knockout|参数恢复|敲除)"
    r"|(?:parameter restoration|restore|knockout|参数恢复|敲除).{0,100}"
    r"(?:negative control|负向对照|负对照)",
    re.IGNORECASE,
)
_DIAGNOSTIC_DISTINCTION_PATTERN = re.compile(
    r"\b(?:different|distinct|separate|not the same)\b|不同|独立|分别|不能混同",
    re.IGNORECASE,
)
_DIRECT_ORDER_CAUSE_PATTERN = re.compile(
    r"(?:this (?:shows?|means?)|therefore|because).{0,48}\bllm\b.{0,48}"
    r"(?:no|not|did not|cannot).{0,24}(?:direct )?orders?"
    r"|(?:这表明|因此|因为).{0,48}(?:大语言模型|LLM).{0,48}"
    r"(?:没有|未|不能).{0,24}(?:直接)?(?:订单|下单)",
    re.IGNORECASE,
)
_NEGATION_PATTERN = re.compile(
    r"\b(no|not|none|zero|did not|does not|cannot)\b|没有|未产生|未改变|不代表|无法证明",
    re.IGNORECASE,
)
_COGNITION_COUNT_ALIASES: dict[str, tuple[str, ...]] = {
    "calls": ("model calls", "llm calls", "模型调用", "调用次数"),
    "fallbackCount": ("fallback", "rule fallback", "回退", "规则降级"),
    "validCognitionDecisionCount": ("valid cognition decisions", "有效认知决策"),
    "cognitionSignalConsumedCount": ("consumed cognition signals", "已消费认知信号"),
    "cognitionChangedIntentCount": ("changed intents", "改变意图"),
    "cognitionInfluencedOrderCount": ("influenced orders", "影响订单"),
    "cognitionBlockedByRiskCount": ("blocked by risk", "被风控阻止"),
    "cognitionNoActionCount": ("no-action decisions", "不行动决策"),
    "decisionRoundCount": ("decision rounds", "认知轮数", "决策轮数"),
}


def buildResultFactCatalog(result: Mapping[str, Any]) -> ResultFactCatalog:
    summaries = _mapping(result.get("metricSummaries"))
    diagnostics = _mapping(result.get("analysisDiagnostics"))
    primaryMetricId = _optionalText(diagnostics.get("preregisteredPrimaryOutcome"))
    metrics: list[MetricFact] = []
    for metricId, rawSummary in summaries.items():
        summary = _mapping(rawSummary)
        baseline = _mapping(summary.get("baseline"))
        intervention = _mapping(summary.get("intervention"))
        delta = _mapping(summary.get("delta"))
        bootstrap = _mapping(delta.get("bootstrap95"))
        interval = bootstrap or _mapping(delta.get("interval95"))
        lower = _optionalFloat(interval.get("lower"))
        upper = _optionalFloat(interval.get("upper"))
        containsZero = interval.get("containsZero")
        if not isinstance(containsZero, bool) and lower is not None and upper is not None:
            containsZero = lower <= 0 <= upper
        metrics.append(
            MetricFact(
                metric_id=str(metricId),
                baseline_median=_optionalFloat(baseline.get("median")),
                intervention_median=_optionalFloat(intervention.get("median")),
                paired_difference_median=_optionalFloat(
                    delta.get("medianDifference", delta.get("median"))
                ),
                interval_lower=lower,
                interval_upper=upper,
                contains_zero=containsZero if isinstance(containsZero, bool) else None,
                direction_consistency=_optionalFloat(
                    delta.get("directionConsistencyRate", delta.get("signConsistency"))
                ),
                valid_n=_optionalInt(delta.get("validN")),
                preregistered_primary=str(metricId) == primaryMetricId,
            )
        )
    metrics.sort(key=lambda item: item.metric_id)

    manifest = _mapping(result.get("manifest"))
    stoppingRule = _mapping(result.get("stoppingRule"))
    cognition = _mapping(result.get("cognition"))
    cognitionCounts: dict[str, int] = {}
    for key in _COGNITION_COUNT_ALIASES:
        value = _optionalInt(cognition.get(key))
        if value is not None:
            cognitionCounts[key] = value
    if "fallbackCount" not in cognitionCounts:
        fallbackReasons = _sequence(cognition.get("fallbackReasons"))
        fallbackDecisions = [
            item
            for item in _sequence(cognition.get("decisions"))
            if _mapping(item).get("fallbackUsed") is True
        ]
        if fallbackReasons or fallbackDecisions:
            cognitionCounts["fallbackCount"] = max(len(fallbackReasons), len(fallbackDecisions))
    decisions = [_mapping(item) for item in _sequence(cognition.get("decisions"))]
    decisionRounds = {
        value
        for item in decisions
        if (value := _optionalInt(item.get("decisionRound"))) is not None
    }
    if decisionRounds:
        cognitionCounts["decisionRoundCount"] = len(decisionRounds)

    return ResultFactCatalog(
        metrics=tuple(metrics),
        primary_metric_id=primaryMetricId,
        valid_paired_seeds=_optionalInt(manifest.get("validPairedSeeds")),
        stopping_reason=_optionalText(
            stoppingRule.get("primaryReason", stoppingRule.get("reason"))
        ),
        stopping_reasons=tuple(
            str(reason)
            for reason in _sequence(stoppingRule.get("reasons"))
            if _optionalText(reason) is not None
        )
        or tuple(
            reason
            for reason in (
                _optionalText(stoppingRule.get("primaryReason", stoppingRule.get("reason"))),
            )
            if reason is not None
        ),
        stopping_completed_pairs=_optionalInt(stoppingRule.get("completedPairs")),
        stopping_maximum_pairs=_optionalInt(stoppingRule.get("maximumPairs")),
        cognition_counts=cognitionCounts,
    )


def strongestMetricFacts(
    catalog: ResultFactCatalog,
    *,
    limit: int = 3,
) -> tuple[MetricFact, ...]:
    """稳定排序最值得先读的指标，不用模型自行挑选“好看结果”。

    预注册主要指标优先；其后优先区间不跨零、方向一致率更高、配对差值
    非零的指标。排序只决定阅读顺序，不把非零或一致率误称为统计显著性。
    """

    def score(item: MetricFact) -> tuple[int, int, float, float, str]:
        pairedDifference = abs(item.paired_difference_median or 0.0)
        directionConsistency = item.direction_consistency or 0.0
        return (
            1 if item.preregistered_primary else 0,
            1 if item.contains_zero is False else 0,
            directionConsistency,
            pairedDifference,
            item.metric_id,
        )

    eligible = [
        item
        for item in catalog.metrics
        if item.paired_difference_median is not None and item.valid_n not in {None, 0}
    ]
    return tuple(sorted(eligible, key=score, reverse=True)[: max(0, limit)])


def validateInterpretationSemantics(
    answer: ResultInterpretationAnswer,
    result: Mapping[str, Any],
    *,
    requirePrimaryFinding: bool,
) -> SemanticValidationReport:
    catalog = buildResultFactCatalog(result)
    violations: set[SemanticViolationCode] = set()
    reviewableText = "\n".join(
        part for part in (answer.answer, answer.analysis_summary) if part is not None
    )
    normalizedText = _INLINE_REFERENCE_PATTERN.sub("", reviewableText)
    mentionedMetrics: set[str] = set()

    for sentence in _sentences(normalizedText):
        sentenceLower = sentence.casefold()
        sentenceMetrics = [
            metric for metric in catalog.metrics if _mentionsMetric(sentenceLower, metric.metric_id)
        ]
        if not sentenceMetrics:
            _validateStoppingSentence(sentence, catalog, violations)
            _validateDiagnosticSentence(sentence, violations)
            _validateCognitionSentence(sentence, catalog, violations)
            continue
        mentionedMetrics.update(item.metric_id for item in sentenceMetrics)
        for metric in sentenceMetrics:
            if metric.contains_zero is True and _STRONG_CLAIM_PATTERN.search(sentence):
                violations.add(SemanticViolationCode.INTERVAL_CROSSES_ZERO_STRONG_CLAIM)
            pairedDifference = metric.paired_difference_median
            if pairedDifference is not None:
                if pairedDifference > 0 and _DECREASE_PATTERN.search(sentence):
                    violations.add(SemanticViolationCode.DIRECTION_MISMATCH)
                if pairedDifference < 0 and _INCREASE_PATTERN.search(sentence):
                    violations.add(SemanticViolationCode.DIRECTION_MISMATCH)
            _validateMetricNumbers(sentence, metric, catalog, violations)
        _validateStoppingSentence(sentence, catalog, violations)
        _validateDiagnosticSentence(sentence, violations)
        _validateCognitionSentence(sentence, catalog, violations)

    strongest = tuple(item.metric_id for item in strongestMetricFacts(catalog))
    if requirePrimaryFinding:
        if catalog.primary_metric_id and catalog.primary_metric_id not in mentionedMetrics:
            violations.add(SemanticViolationCode.REQUIRED_PRIMARY_FINDING_OMITTED)
        # 第一轮解释必须同时覆盖后端排序中“区间不跨零”的最强结果，
        # 防止模型只挑选叙事方便、但证据更弱的指标。后续追问则允许聚焦局部。
        requiredStrongest = {
            item.metric_id for item in strongestMetricFacts(catalog) if item.contains_zero is False
        }
        if not requiredStrongest.issubset(mentionedMetrics):
            violations.add(SemanticViolationCode.REQUIRED_STRONGEST_FINDING_OMITTED)

    orderedViolations = tuple(sorted(violations, key=lambda item: item.value))
    return SemanticValidationReport(
        valid=not orderedViolations,
        violation_codes=orderedViolations,
        strongest_metric_ids=strongest,
    )


def deterministicInterpretationFallback(
    result: Mapping[str, Any],
    *,
    language: ResultLanguage,
    includeAnalysisSummary: bool,
) -> ResultInterpretationAnswer:
    """当语义修复仍失败时生成只含服务器事实的保守答案。"""

    catalog = buildResultFactCatalog(result)
    strongest = strongestMetricFacts(catalog)
    if language == "zh-CN":
        lines = [
            "这是以合成假设为条件的情景分析，不是预测，也不构成投资建议。",
            "",
            "## 服务器核验结果",
        ]
        if strongest:
            for fact in strongest:
                lines.append(_factLineZh(fact))
        else:
            lines.append("当前结果没有足够的有效配对指标可供自动解释。")
        lines.extend(
            (
                "",
                "区间、方向和样本数均直接来自服务器计算；模型生成的未核验统计叙述未被展示。"
                " [result:metric-summary]",
                "",
                "请结合实验设计、证据来源和局限阅读这些结果。"
                " [result:overview] [result:limitations]",
            )
        )
        analysisSummary = (
            "已核对预注册主要指标、配对差值中位数、经验区间是否跨零、方向一致率"
            "和有效配对数；未采用任何无法与服务器事实目录匹配的数字或结论。"
            if includeAnalysisSummary
            else None
        )
        suggestions = (
            "当前结果中哪个区间最需要解释？",
            "哪些限制会影响这次合成情景的适用范围？",
        )
    else:
        lines = [
            "This is scenario analysis conditional on synthetic assumptions, not a "
            "prediction and not investment advice.",
            "",
            "## Server-verified results",
        ]
        if strongest:
            for fact in strongest:
                lines.append(_factLineEn(fact))
        else:
            lines.append(
                "The result does not contain enough valid paired metrics for an automatic "
                "interpretation."
            )
        lines.extend(
            (
                "",
                "Intervals, directions, and sample counts come directly from server "
                "calculations. Unverified model-written statistical claims were not shown. "
                "[result:metric-summary]",
                "",
                "Read these values with the experiment design, evidence provenance, and "
                "limitations. [result:overview] [result:limitations]",
            )
        )
        analysisSummary = (
            "Checked the preregistered primary metric, paired-difference median, whether "
            "the empirical interval crosses zero, direction consistency, and valid pairs. "
            "No unmatched number or conclusion was retained."
            if includeAnalysisSummary
            else None
        )
        suggestions = (
            "Which interval in the current result needs the most explanation?",
            "Which limitations bound this synthetic scenario?",
        )
    return ResultInterpretationAnswer(
        answer="\n".join(lines),
        analysis_summary=analysisSummary,
        grounding_references=(
            "result:metric-summary",
            "result:overview",
            "result:limitations",
        ),
        follow_up_suggestions=suggestions,
    )


def semanticRepairInstruction(
    answer: ResultInterpretationAnswer,
    report: SemanticValidationReport,
    *,
    language: ResultLanguage,
) -> str:
    """构造一次受限语义修复输入，不包含隐藏提示词或额外权限。"""

    codes = [item.value for item in report.violation_codes]
    if language == "zh-CN":
        instruction = (
            "服务器拒绝了候选解释，因为它与确定性事实目录不一致。请只根据原有"
            " result_tool_outputs 重写完整 JSON；不得猜测数字，不得省略正文内证据标记，"
            "不得输出原始 HTML。必须修复以下代码："
        )
    else:
        instruction = (
            "The server rejected the candidate explanation because it conflicts with the "
            "deterministic fact catalog. Rewrite the complete JSON using only the original "
            "result_tool_outputs. Do not guess numbers, omit inline evidence markers, or emit "
            "raw HTML. Fix these codes:"
        )
    return (
        f"{instruction}\n{codes}\n\n"
        "REJECTED_CANDIDATE_JSON:\n"
        f"{answer.model_dump_json(exclude_none=True)}"
    )


def _validateMetricNumbers(
    sentence: str,
    metric: MetricFact,
    catalog: ResultFactCatalog,
    violations: set[SemanticViolationCode],
) -> None:
    supported = list(metric.supportedNumbers())
    if catalog.valid_paired_seeds is not None:
        supported.append(float(catalog.valid_paired_seeds))
    # 0、1、95 和 100 是解释区间、比例及零值边界时允许使用的通用常数。
    supported.extend((0.0, 1.0, 95.0, 100.0))
    for rawNumber, percentSuffix in _NUMBER_PATTERN.findall(sentence):
        value = float(rawNumber.replace(",", "").replace("−", "-"))
        candidates = [value]
        if percentSuffix:
            candidates.append(value / 100.0)
        if not any(
            _approximatelyEqual(candidate, expected)
            for candidate in candidates
            for expected in supported
        ):
            violations.add(SemanticViolationCode.METRIC_NUMBER_UNSUPPORTED)
    if (
        metric.paired_difference_median is not None
        and metric.paired_difference_median < 0
        and _RAW_NEGATIVE_METRIC_PATTERN.search(sentence)
        and not _DELTA_LANGUAGE_PATTERN.search(sentence)
    ):
        violations.add(SemanticViolationCode.DELTA_VALUE_MISREPRESENTED_AS_RAW)
    if (
        metric.interval_lower is not None
        and metric.interval_upper is not None
        and _INTERVAL_DENIAL_PATTERN.search(sentence)
    ):
        violations.add(SemanticViolationCode.AVAILABLE_INTERVAL_DENIED)
    if metric.direction_consistency is not None:
        consistencyPercent = metric.direction_consistency * 100.0
        for rawNumber in _DIRECTION_CONSISTENCY_VALUE_PATTERN.findall(sentence):
            value = float(rawNumber)
            if not _approximatelyEqual(value, consistencyPercent):
                violations.add(SemanticViolationCode.DIRECTION_CONSISTENCY_MISMATCH)


def _validateStoppingSentence(
    sentence: str,
    catalog: ResultFactCatalog,
    violations: set[SemanticViolationCode],
) -> None:
    if not re.search(
        r"\bstop|stopping|terminated|completion\b|停止|终止|完成", sentence, re.I
    ) and not _EARLY_STOP_OR_SAVINGS_PATTERN.search(sentence):
        return
    reason = " ".join(catalog.stopping_reasons) or catalog.stopping_reason or ""
    if _STOP_TARGET_PATTERN.search(sentence) and "TARGET_CI_HALF_WIDTH" not in reason:
        violations.add(SemanticViolationCode.STOPPING_REASON_UNSUPPORTED)
    if _STOP_FIXED_PATTERN.search(sentence) and not any(
        token in reason for token in ("FIXED", "MAXIMUM_PAIR", "PAIR_COUNT")
    ):
        violations.add(SemanticViolationCode.STOPPING_REASON_UNSUPPORTED)
    maximumWasReached = any(
        token in reason for token in ("FIXED_PAIR_COUNT_REACHED", "MAXIMUM_PAIRS_REACHED")
    )
    completedPreset = (
        catalog.stopping_completed_pairs is not None
        and catalog.stopping_maximum_pairs is not None
        and catalog.stopping_completed_pairs >= catalog.stopping_maximum_pairs
    )
    if maximumWasReached and completedPreset and _EARLY_STOP_OR_SAVINGS_PATTERN.search(sentence):
        violations.add(SemanticViolationCode.STOPPING_REASON_UNSUPPORTED)


def _validateDiagnosticSentence(
    sentence: str,
    violations: set[SemanticViolationCode],
) -> None:
    if _DIAGNOSTIC_CONFLATION_PATTERN.search(
        sentence
    ) and not _DIAGNOSTIC_DISTINCTION_PATTERN.search(sentence):
        violations.add(SemanticViolationCode.DIAGNOSTIC_TYPE_CONFLATED)


def _validateCognitionSentence(
    sentence: str,
    catalog: ResultFactCatalog,
    violations: set[SemanticViolationCode],
) -> None:
    lower = sentence.casefold()
    for key, aliases in _COGNITION_COUNT_ALIASES.items():
        if not any(alias in lower for alias in aliases):
            continue
        expected = catalog.cognition_counts.get(key)
        if expected is None:
            continue
        numbers = [
            int(float(raw.replace(",", "").replace("−", "-")))
            for raw, suffix in _NUMBER_PATTERN.findall(sentence)
            if not suffix
        ]
        if numbers and expected not in numbers:
            violations.add(SemanticViolationCode.COGNITION_COUNT_MISMATCH)
    influencedOrders = catalog.cognition_counts.get("cognitionInfluencedOrderCount")
    if influencedOrders is None:
        metric = catalog.metric("cognitiveOrderCount")
        if metric is not None and metric.intervention_median is not None:
            influencedOrders = int(metric.intervention_median)
    if (
        influencedOrders == 0
        and _COGNITION_EFFECT_PATTERN.search(sentence)
        and not _NEGATION_PATTERN.search(sentence)
    ):
        violations.add(SemanticViolationCode.COGNITION_EFFECT_UNSUPPORTED)
    if influencedOrders == 0 and _DIRECT_ORDER_CAUSE_PATTERN.search(sentence):
        violations.add(SemanticViolationCode.COGNITION_ZERO_EFFECT_CAUSE_UNSUPPORTED)


def _mentionsMetric(sentenceLower: str, metricId: str) -> bool:
    aliases = METRIC_ALIASES.get(metricId, (metricId.casefold(),))
    return any(alias.casefold() in sentenceLower for alias in aliases)


def _factLineZh(fact: MetricFact) -> str:
    difference = _formatNumber(fact.paired_difference_median)
    interval = _formatInterval(fact.interval_lower, fact.interval_upper)
    intervalMeaning = (
        "区间跨过零"
        if fact.contains_zero is True
        else "区间未跨过零"
        if fact.contains_zero is False
        else "区间是否跨零不可用"
    )
    consistency = (
        f"{fact.direction_consistency:.0%}" if fact.direction_consistency is not None else "不可用"
    )
    return (
        f"- **{fact.metric_id}**：配对差值中位数 {difference}；经验区间 {interval}"
        f"（{intervalMeaning}）；方向一致率 {consistency}；有效配对 "
        f"{fact.valid_n if fact.valid_n is not None else '不可用'}。"
    )


def _factLineEn(fact: MetricFact) -> str:
    difference = _formatNumber(fact.paired_difference_median)
    interval = _formatInterval(fact.interval_lower, fact.interval_upper)
    intervalMeaning = (
        "crosses zero"
        if fact.contains_zero is True
        else "does not cross zero"
        if fact.contains_zero is False
        else "zero-crossing unavailable"
    )
    consistency = (
        f"{fact.direction_consistency:.0%}"
        if fact.direction_consistency is not None
        else "unavailable"
    )
    return (
        f"- **{fact.metric_id}**: paired-difference median {difference}; empirical interval "
        f"{interval} ({intervalMeaning}); direction consistency {consistency}; valid pairs "
        f"{fact.valid_n if fact.valid_n is not None else 'unavailable'}."
    )


def _formatNumber(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:.6g}"


def _formatInterval(lower: float | None, upper: float | None) -> str:
    if lower is None or upper is None:
        return "unavailable"
    return f"[{lower:.6g}, {upper:.6g}]"


def _approximatelyEqual(left: float, right: float) -> bool:
    tolerance = max(0.0005, abs(right) * 0.0005)
    return abs(left - right) <= tolerance


def _sentences(value: str) -> tuple[str, ...]:
    parts = re.split(r"(?<=[。！？.!?])\s+|\n+", value)
    return tuple(part.strip() for part in parts if part.strip())


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def _optionalText(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optionalFloat(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _optionalInt(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
