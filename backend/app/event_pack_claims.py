"""Event Pack 规则回退抽取与本地质量门禁。

该模块只在外部模型不可用或主动弃答时使用。它不会把排版行、URL 或日期
伪装成事实，也不会把“官方来源”误写为市场影响概率。所有产物仍是必须由
人类逐条审核的候选主张。
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, Protocol


class EventSourceLike(Protocol):
    """避免质量工具反向导入总 Schema 所形成的包初始化循环。"""

    sourceId: str
    sourceType: str
    publishedAt: datetime
    knownAt: datetime
    rawText: str


ALLOWED_IMPACT_CHANNELS = ("belief", "liquidity", "passiveFlow", "stopLoss")

_TERMINAL_PUNCTUATION_PATTERN = re.compile(r"[.!?。！？](?:[\"'”’)\]]+)?$")
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?。！？])\s+")
_URL_ONLY_PATTERN = re.compile(r"^(?:https?://|www\.)\S+$", re.IGNORECASE)
_DATE_ONLY_PATTERN = re.compile(
    r"^(?:date\s*:\s*)?(?:"
    r"(?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december)\s+\d{1,2},?\s+\d{4}"
    r"|\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?"
    r")$",
    re.IGNORECASE,
)
_DOCUMENT_LABEL_PATTERN = re.compile(
    r"^(?:airworthiness directive|emergency airworthiness directive|"
    r"federal aviation administration|department of transportation|"
    r"table of contents|contents|page \d+(?: of \d+)?)$",
    re.IGNORECASE,
)
_ENGLISH_PREDICATE_PATTERN = re.compile(
    r"\b(?:is|are|was|were|be|been|has|have|had|does|did|will|would|can|could|"
    r"may|might|must|shall|should|issued?|prohibits?|requires?|reported?|"
    r"resulted?|determined?|confirms?|confirmed|considers?|applies?|allows?|affects?|causes?|"
    r"announced?|suspended?|ordered?|identified?)\b",
    re.IGNORECASE,
)
_CHINESE_PREDICATE_PATTERN = re.compile(
    r"(?:是|为|已|将|会|可能|导致|造成|要求|禁止|适用|发布|宣布|暂停|恢复|"
    r"检查|确定|认为|影响|触发|发生|脱落|下降|上升)"
)
_LEADING_FRAGMENT_PATTERN = re.compile(
    r"^(?:and|or|but|which|that|who|whose|where|when|because|until|"
    r"the potential|described previously|applicable)\b",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)

_CHANNEL_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "belief": (
        re.compile(
            r"\b(?:report|risk|unsafe|warning|investigation|incident|injury|loss of control|"
            r"determined|expects?|uncertain|guidance|claim)\b|"
            r"报告|风险|不安全|警告|调查|事故|受伤|失控|认定|预期|不确定",
            re.IGNORECASE,
        ),
    ),
    "liquidity": (
        re.compile(
            r"\b(?:prohibits?|ground(?:ed|ing)?|suspend|halt|inspect(?:ed|ion)?|"
            r"corrective action|"
            r"capacity|inventory|liquidity|spread|market mak|trading)\b|"
            r"禁止|停飞|暂停|检查|纠正措施|产能|库存|流动性|价差|做市|交易",
            re.IGNORECASE,
        ),
    ),
    "passiveFlow": (
        re.compile(
            r"\b(?:index|etf|passive fund|rebalance|benchmark inclusion|mandated allocation)\b|"
            r"指数|交易所交易基金|被动基金|再平衡|基准纳入|强制配置",
            re.IGNORECASE,
        ),
    ),
    "stopLoss": (
        re.compile(
            r"\b(?:stop[- ]?loss|margin call|forced liquidation|liquidat(?:e|ion)|"
            r"price threshold|risk limit|deleverag)\b|"
            r"止损|追缴保证金|强制平仓|清算|价格阈值|风险限额|去杠杆",
            re.IGNORECASE,
        ),
    ),
}

_CHANNEL_RATIONALE: dict[str, tuple[str, str, str]] = {
    "belief": (
        "The claim can change participants' assessment of event severity or future state.",
        "该主张可能改变参与者对事件严重程度或未来状态的判断。",
        "beliefShock",
    ),
    "liquidity": (
        "The claim describes an operational or trading constraint that may change liquidity.",
        "该主张描述了可能改变流动性供给的运营或交易约束。",
        "marketMakerCapacity",
    ),
    "passiveFlow": (
        "The claim explicitly concerns index, ETF, or rule-based portfolio flows.",
        "该主张明确涉及指数、ETF 或规则化组合资金流。",
        "passiveFlowMultiplier",
    ),
    "stopLoss": (
        "The claim explicitly concerns a price, margin, liquidation, or risk threshold.",
        "该主张明确涉及价格、保证金、平仓或风险阈值。",
        "stopLossSensitivity",
    ),
}


def extractRuleFallbackClaims(
    sources: Sequence[EventSourceLike],
    *,
    maximumClaims: int,
    requestedImpactChannels: Sequence[str] = ALLOWED_IMPACT_CHANNELS,
) -> list[dict[str, Any]]:
    """生成去碎片、去重复且带质量元数据的确定性候选主张。"""

    if maximumClaims < 1:
        raise ValueError("maximumClaims must be positive")
    allowedChannels = tuple(
        channel
        for channel in dict.fromkeys(requestedImpactChannels)
        if channel in ALLOWED_IMPACT_CHANNELS
    )
    if not allowedChannels:
        raise ValueError("requestedImpactChannels must include a supported channel")

    candidates: list[dict[str, Any]] = []
    acceptedFingerprints: list[set[str]] = []
    for source in sources:
        for sentence in preprocessSourceText(source.rawText):
            fingerprint = _fingerprint(sentence)
            if _isDuplicateFingerprint(fingerprint, acceptedFingerprints):
                continue
            acceptedFingerprints.append(fingerprint)
            channels = inferImpactChannels(sentence, allowedChannels=allowedChannels)
            confidenceComponents = _confidenceComponents(
                sentence,
                sourceType=source.sourceType,
                publishedAt=source.publishedAt,
                knownAt=source.knownAt,
            )
            confidence = round(
                confidenceComponents["textualFidelity"] * 0.5
                + confidenceComponents["sourceTierStrength"] * 0.3
                + confidenceComponents["timeBoundaryCertainty"] * 0.2,
                2,
            )
            claimDigest = hashlib.blake2s(
                f"{source.sourceId}:{sentence}".encode(),
                digest_size=8,
            ).hexdigest()
            candidates.append(
                {
                    "claimId": f"claim-{claimDigest}",
                    "text": sentence[:1_000],
                    "textZh": sentence[:1_000],
                    "claimType": _claimType(source.sourceType),
                    "sourceIds": [source.sourceId],
                    "sourceTier": source.sourceType,
                    "publishedAt": source.publishedAt.isoformat(),
                    "knownAt": source.knownAt.isoformat(),
                    "confidence": confidence,
                    "confidenceMeaning": "EXTRACTION_FIDELITY_NOT_EVENT_PROBABILITY",
                    "confidenceComponents": confidenceComponents,
                    "impactChannels": channels,
                    "impactChannelRationale": buildImpactChannelRationale(channels),
                    "channelMappingIsInference": True,
                    "reviewStatus": "AI_PROPOSED",
                    "isRequired": not candidates,
                    "evidenceQuote": sentence[:500],
                    "synthetic": False,
                    "extractionQuality": "RULE_FALLBACK_REVIEW_REQUIRED",
                    "bulkApprovalEligible": False,
                }
            )
            if len(candidates) >= maximumClaims:
                return candidates
    return candidates


def buildLlmClaimQualityMetadata(
    sentence: str,
    *,
    sourceTypes: Sequence[str],
    publishedAt: datetime | None,
    knownAt: datetime,
    requestedImpactChannels: Sequence[str],
    modelReportedConfidence: float,
) -> dict[str, Any]:
    """把模型自报分数改造成可解释、本地校验的抽取质量字段。"""

    allowedChannels = tuple(
        channel
        for channel in dict.fromkeys(requestedImpactChannels)
        if channel in ALLOWED_IMPACT_CHANNELS
    )
    channels = inferImpactChannels(sentence, allowedChannels=allowedChannels)
    tokenCount = len(_TOKEN_PATTERN.findall(sentence))
    textualFidelity = 0.86
    if 12 <= tokenCount <= 40:
        textualFidelity += 0.08
    elif tokenCount > 40:
        textualFidelity += 0.04
    if not _TERMINAL_PUNCTUATION_PATTERN.search(sentence):
        textualFidelity -= 0.04
    sourceStrengths = [
        {
            "OFFICIAL": 0.95,
            "REPORTING": 0.78,
            "ESTIMATE": 0.58,
            "USER_PROVIDED": 0.52,
        }.get(sourceType, 0.5)
        for sourceType in sourceTypes
    ]
    # 多来源主张按最弱来源保守计分，避免“包含一个官方来源”掩盖其余证据质量。
    sourceStrength = min(sourceStrengths, default=0.5)
    timeCertainty = (
        0.95
        if publishedAt is not None and knownAt >= publishedAt
        else 0.82
        if publishedAt is None
        else 0.6
    )
    confidenceComponents = {
        "textualFidelity": round(max(0.0, min(1.0, textualFidelity)), 2),
        "sourceTierStrength": round(sourceStrength, 2),
        "timeBoundaryCertainty": round(timeCertainty, 2),
    }
    confidence = round(
        confidenceComponents["textualFidelity"] * 0.5
        + confidenceComponents["sourceTierStrength"] * 0.3
        + confidenceComponents["timeBoundaryCertainty"] * 0.2,
        2,
    )
    return {
        "confidence": confidence,
        "modelReportedConfidence": round(modelReportedConfidence, 4),
        "confidenceMeaning": "EXTRACTION_FIDELITY_NOT_EVENT_PROBABILITY",
        "confidenceComponents": confidenceComponents,
        "impactChannels": channels,
        "impactChannelRationale": buildImpactChannelRationale(channels),
        "channelMappingIsInference": True,
        "extractionQuality": "MODEL_EXTRACTED_REVIEW_REQUIRED",
        "bulkApprovalEligible": True,
    }


def buildImpactChannelRationale(channels: Sequence[str]) -> list[dict[str, str]]:
    return [
        {
            "channel": channel,
            "reason": _CHANNEL_RATIONALE[channel][0],
            "reasonZh": _CHANNEL_RATIONALE[channel][1],
            "evidenceType": "MECHANISM_HYPOTHESIS",
            "simulatorParameter": _CHANNEL_RATIONALE[channel][2],
        }
        for channel in channels
        if channel in _CHANNEL_RATIONALE
    ]


def preprocessSourceText(rawText: str) -> tuple[str, ...]:
    """把 PDF/网页换行恢复为可审核句子，并过滤文档噪声。"""

    logicalLines: list[str] = []
    buffer = ""
    for rawLine in rawText.splitlines():
        line = " ".join(rawLine.split()).strip()
        if not line:
            if buffer:
                logicalLines.append(buffer)
                buffer = ""
            continue
        if _isDocumentNoise(line):
            continue
        buffer = f"{buffer} {line}".strip() if buffer else line
        if _TERMINAL_PUNCTUATION_PATTERN.search(line):
            logicalLines.append(buffer)
            buffer = ""
    if buffer:
        logicalLines.append(buffer)

    sentences: list[str] = []
    pendingFragment = ""
    for paragraph in logicalLines:
        for rawSentence in _SENTENCE_SPLIT_PATTERN.split(paragraph):
            sentence = " ".join(rawSentence.split()).strip()
            if not sentence or _isDocumentNoise(sentence):
                continue
            if pendingFragment:
                sentence = f"{pendingFragment} {sentence}"
                pendingFragment = ""
            if not _looksComplete(sentence):
                pendingFragment = sentence
                continue
            if _LEADING_FRAGMENT_PATTERN.search(sentence) and sentences:
                sentences[-1] = f"{sentences[-1]} {sentence}"
                continue
            sentences.append(sentence)
    if pendingFragment and sentences and _LEADING_FRAGMENT_PATTERN.search(pendingFragment):
        sentences[-1] = f"{sentences[-1]} {pendingFragment}"
    elif pendingFragment and _looksComplete(pendingFragment):
        sentences.append(pendingFragment)
    return tuple(_deduplicateSentences(sentences))


def inferImpactChannels(
    sentence: str,
    *,
    allowedChannels: Sequence[str] = ALLOWED_IMPACT_CHANNELS,
) -> list[str]:
    """从明确关键词推断最多两个通道；没有命中时只保留认知通道。"""

    allowed = set(allowedChannels)
    scored: list[tuple[int, str]] = []
    for channel in ALLOWED_IMPACT_CHANNELS:
        if channel not in allowed:
            continue
        score = sum(len(pattern.findall(sentence)) for pattern in _CHANNEL_PATTERNS[channel])
        if score:
            scored.append((score, channel))
    if not scored and "belief" in allowed:
        return ["belief"]
    scored.sort(key=lambda item: (-item[0], ALLOWED_IMPACT_CHANNELS.index(item[1])))
    return [channel for _score, channel in scored[:2]]


def _isDocumentNoise(value: str) -> bool:
    if len(value) > 300:
        return False
    normalized = value.strip(" \t:-–—")
    if not normalized:
        return True
    if _URL_ONLY_PATTERN.fullmatch(normalized):
        return True
    if _DATE_ONLY_PATTERN.fullmatch(normalized):
        return True
    if _DOCUMENT_LABEL_PATTERN.fullmatch(normalized):
        return True
    words = normalized.split()
    return (
        len(words) <= 8
        and normalized.upper() == normalized
        and any(character.isalpha() for character in normalized)
        and not _ENGLISH_PREDICATE_PATTERN.search(normalized)
    )


def _looksComplete(value: str) -> bool:
    tokens = _TOKEN_PATTERN.findall(value)
    if len(value) < 30 or len(tokens) < 5:
        return False
    hasPredicate = bool(
        _ENGLISH_PREDICATE_PATTERN.search(value) or _CHINESE_PREDICATE_PATTERN.search(value)
    )
    hasSubject = any(
        token.casefold() not in {"and", "or", "but", "which", "that", "the", "a", "an"}
        for token in tokens[:4]
    )
    return hasPredicate and hasSubject


def _fingerprint(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _TOKEN_PATTERN.findall(value)
        if len(token) > 1 and token.casefold() not in {"the", "and", "that", "this", "with"}
    }


def _isDuplicateFingerprint(
    candidate: set[str],
    accepted: Iterable[set[str]],
) -> bool:
    if not candidate:
        return True
    for prior in accepted:
        overlap = len(candidate & prior)
        union = len(candidate | prior)
        if union and overlap / union >= 0.88:
            return True
        if overlap == min(len(candidate), len(prior)) and overlap >= 8:
            return True
    return False


def _deduplicateSentences(sentences: Sequence[str]) -> list[str]:
    accepted: list[str] = []
    fingerprints: list[set[str]] = []
    for sentence in sentences:
        fingerprint = _fingerprint(sentence)
        if _isDuplicateFingerprint(fingerprint, fingerprints):
            continue
        accepted.append(sentence)
        fingerprints.append(fingerprint)
    return accepted


def _confidenceComponents(
    sentence: str,
    *,
    sourceType: str,
    publishedAt: datetime,
    knownAt: datetime,
) -> dict[str, float]:
    textualFidelity = 0.82 if _TERMINAL_PUNCTUATION_PATTERN.search(sentence) else 0.72
    if _LEADING_FRAGMENT_PATTERN.search(sentence):
        textualFidelity -= 0.12
    if len(_TOKEN_PATTERN.findall(sentence)) >= 12:
        textualFidelity += 0.04
    sourceStrength = {
        "OFFICIAL": 0.95,
        "REPORTING": 0.78,
        "ESTIMATE": 0.58,
        "USER_PROVIDED": 0.52,
    }.get(sourceType, 0.5)
    timeCertainty = 0.95 if knownAt >= publishedAt else 0.7
    return {
        "textualFidelity": round(max(0.0, min(1.0, textualFidelity)), 2),
        "sourceTierStrength": sourceStrength,
        "timeBoundaryCertainty": timeCertainty,
    }


def _claimType(sourceType: str) -> str:
    if sourceType == "OFFICIAL":
        return "FACT"
    if sourceType == "ESTIMATE":
        return "ATTRIBUTED_ESTIMATE"
    return "CLAIM"
