"""Event Pack、实验队列、汇总与导出服务。"""

from __future__ import annotations

import asyncio
import copy
import csv
import hashlib
import io
import json
import logging
import math
import re
import statistics
import threading
import uuid
import zipfile
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.app.cognition import (
    ActionPreference,
    AgentProfile,
    CognitionService,
    CredentialNotConfiguredError,
    EvidenceItem,
    EvidenceSourceType,
    MarketObservation,
    MemorySummary,
    ModelCostBudget,
    ModelGatewayError,
    ModelPolicy,
    Observation,
    PersistentCredentialUnavailableError,
    PortfolioObservation,
    SocialPost,
    TrustProfile,
    VolatilityRegime,
    estimateReservation,
)
from backend.app.cognition.pricing import getTokenPrice
from backend.app.cognition.result_semantics import (
    buildResultFactCatalog,
    strongestMetricFacts,
)
from backend.app.cognition.streaming import ModelStreamProgress, ModelStreamStage
from backend.app.database import Database, utcNow
from backend.app.errors import ApiError
from backend.app.event_pack_claims import (
    ALLOWED_IMPACT_CHANNELS,
    extractRuleFallbackClaims,
)
from backend.app.export import buildParquetArtifacts
from backend.app.schemas import (
    BulkClaimApprovalRequest,
    ClaimReviewRequest,
    EventPackCreateRequest,
    EventSourceInput,
    ExperimentRequest,
)
from backend.app.simulation.analytics import METRIC_KEYS, aggregatePairedResults
from backend.app.simulation.engine import PRICE_SCALE, SIMULATION_STEP_SECONDS, runScenario
from backend.app.validation.statistics import (
    bootstrap95ConfidenceInterval,
    evaluateKnockout,
    evaluateNegativeControl,
    holmBonferroni,
    rankCorrelationSensitivity,
)

LOGGER = logging.getLogger(__name__)
ACTIVE_STATUSES = {"QUEUED", "RUNNING", "AGGREGATING", "CANCEL_REQUESTED"}
MAX_QUEUED_EXPERIMENTS = 8
MAX_EXPERIMENTS_PER_SESSION = 30
MAX_STORED_EXPERIMENTS = 500
MAX_RUNTIME_LOG_ENTRIES = 200
EXPERIMENT_CHECKPOINT_SCHEMA_VERSION = "1.0.0"
COGNITION_PILOT_SCHEDULE_MODE = "CLOSED_LOOP_PILOT_FROZEN_FOR_MATCHED_SEEDS"
MODEL_GENERATED_SOCIAL_LABEL = "[MODEL-GENERATED — NOT NEW EVIDENCE]"
SIMULATION_ENGINE_VERSION = "eventshock-simulation-0.3.0"
NO_EXTERNAL_COGNITION_REASON = "no external cognition requested"
BULK_APPROVAL_MIN_CONFIDENCE = 0.75


class _ModelCredentialStorageUnavailableError(RuntimeError):
    """混合认知所需持久凭据暂时不可解密，可在修复凭据后重试。"""


def _cognitionFailureCategory(code: str) -> str:
    if code == "LLM_CREDENTIAL_STORAGE_UNAVAILABLE":
        return "CREDENTIAL_STORAGE"
    if code in {"MODEL_AUTHENTICATION_ERROR", "MODEL_PERMISSION_ERROR", "LLM_CREDENTIAL_EXPIRED"}:
        return "AUTHENTICATION"
    if code in {"MODEL_TIMEOUT", "MODEL_OVERLOADED"}:
        return "AVAILABILITY"
    if code == "MODEL_TRANSPORT_ERROR":
        return "TRANSPORT"
    if code == "MODEL_RATE_LIMITED":
        return "RATE_LIMIT"
    if code == "MODEL_QUOTA_EXHAUSTED":
        return "QUOTA"
    if code in {"MODEL_PRICING_UNAVAILABLE", "MODEL_COST_BUDGET_EXCEEDED"}:
        return "COST_CONTROL"
    if code in {
        "MODEL_RESPONSE_INVALID",
        "SCHEMA_INVALID",
        "EVIDENCE_ID_UNKNOWN",
        "ACTION_NOT_ALLOWED",
    }:
        return "STRUCTURED_VALIDATION"
    if code in {"REFUSAL", "CONTENT_FILTERED", "PROMPT_DISCLOSURE_BLOCKED"}:
        return "SAFETY_OR_REFUSAL"
    if code in {"FALLBACK_USED", "RULE_FALLBACK_USED"}:
        return "RULE_FALLBACK"
    return "OTHER"


def _defaultContentSecuritySummary() -> dict[str, Any]:
    """兼容内部服务调用；HTTP 上传入口始终会传入真实扫描摘要。"""

    return {
        "schemaVersion": "1.0.0",
        "decision": "NOT_SCANNED_INTERNAL_CALL",
        "acknowledged": False,
        "sourceCount": 0,
        "findingCount": 0,
        "findingsTruncated": False,
        "findings": [],
        "sources": [],
        "rawContentRetained": False,
        "modelInputSummary": {
            "retainedFieldCount": 0,
            "removedFieldCount": 0,
            "redactedFieldCount": 0,
        },
    }


def _contentSecurityAuditSummary(
    summary: dict[str, Any] | None,
) -> dict[str, Any]:
    value = summary or _defaultContentSecuritySummary()
    return {
        "schemaVersion": value.get("schemaVersion", "1.0.0"),
        "decision": value.get("decision", "UNKNOWN"),
        "acknowledged": bool(value.get("acknowledged", False)),
        "sourceCount": int(value.get("sourceCount", 0)),
        "findingCount": int(value.get("findingCount", 0)),
        "findingsTruncated": bool(value.get("findingsTruncated", False)),
        "findingCodes": sorted(
            {
                str(item.get("code"))
                for item in value.get("findings", [])
                if isinstance(item, dict) and item.get("code")
            }
        ),
        "rawContentRetained": False,
        "modelInputSummary": value.get(
            "modelInputSummary",
            {
                "retainedFieldCount": 0,
                "removedFieldCount": 0,
                "redactedFieldCount": 0,
            },
        ),
    }


def _claimBulkApprovalExclusionReasons(
    eventPack: dict[str, Any],
    claim: dict[str, Any],
) -> list[str]:
    """服务端统一判定批量审核资格，避免客户端提示与实际写入规则漂移。"""

    # 仓库内置案例由版本化清单人工策展，不属于 Factory/模型抽取队列；
    # 质量门禁只约束可重抽取的自定义 Event Pack，保持既有案例审核契约。
    if eventPack.get("editableExtraction") is False:
        return []

    reasons: list[str] = []
    confidence = claim.get("confidence")
    if not isinstance(confidence, (int, float)) or float(confidence) < BULK_APPROVAL_MIN_CONFIDENCE:
        reasons.append("LOW_CONFIDENCE")
    channels = claim.get("impactChannels")
    if not isinstance(channels, list) or len(channels) > 1:
        reasons.append("MULTIPLE_IMPACT_CHANNELS")

    extraction = eventPack.get("extraction")
    contentSecurity = extraction.get("contentSecurity") if isinstance(extraction, dict) else None
    securitySources = contentSecurity.get("sources") if isinstance(contentSecurity, dict) else None
    reviewSourceIds = {
        str(source.get("sourceId"))
        for source in securitySources or []
        if isinstance(source, dict) and source.get("decision") == "REVIEW"
    }
    claimSourceIds = {
        str(sourceId) for sourceId in claim.get("sourceIds", []) if isinstance(sourceId, str)
    }
    if reviewSourceIds & claimSourceIds:
        reasons.append("CONTENT_SAFETY_REVIEW")

    if str(claim.get("sourceTier", "")).upper() != "OFFICIAL":
        reasons.append("NON_OFFICIAL_SOURCE")
    if claim.get("bulkApprovalEligible", True) is not True:
        reasons.append("EXTRACTION_NOT_ELIGIBLE")
    return list(dict.fromkeys(reasons))


def _annotateClaimBulkApprovalMetadata(eventPack: dict[str, Any]) -> None:
    for claim in eventPack.get("claims", []):
        if not isinstance(claim, dict):
            continue
        reasons = _claimBulkApprovalExclusionReasons(eventPack, claim)
        claim["bulkApprovalEligible"] = not reasons
        claim["bulkApprovalExclusionReasons"] = reasons
        claim["bulkApprovalMinimumConfidence"] = BULK_APPROVAL_MIN_CONFIDENCE


def _extractionQualityMetadata(
    extractionMode: str,
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """把抽取质量与批量审核权限写入不可含糊的服务端契约。"""

    ruleFallback = "RULE_FALLBACK" in extractionMode or extractionMode in {
        "RULE_ONLY",
        "RULE_FALLBACK",
    }
    bulkApprovalAllowed = not ruleFallback and all(
        claim.get("bulkApprovalEligible", True) is not False for claim in claims
    )
    return {
        "qualityTier": (
            "RULE_FALLBACK_REVIEW_REQUIRED" if ruleFallback else "MODEL_EXTRACTED_REVIEW_REQUIRED"
        ),
        "bulkApprovalAllowed": bulkApprovalAllowed,
        "confidenceMeaning": "EXTRACTION_FIDELITY_NOT_EVENT_PROBABILITY",
    }


class EventPackService:
    def __init__(
        self,
        database: Database,
        projectRoot: Path,
        cognition: CognitionService | None = None,
    ) -> None:
        self.database = database
        self.cognition = cognition
        self.canonicalPacks = self._loadCanonicalPacks(projectRoot / "event-packs")

    def listCases(self, sessionId: str | None = None) -> list[dict[str, Any]]:
        canonicalCases = [
            {
                "id": manifest["caseId"],
                "eventPackId": eventPackId,
                "title": manifest["title"],
                "titleZh": manifest["titleZh"],
                "summary": manifest["summary"],
                "summaryZh": manifest["summaryZh"],
                "synthetic": manifest["synthetic"],
                "syntheticLabel": manifest["syntheticLabel"],
                "syntheticLabelZh": manifest["syntheticLabelZh"],
                "instrument": manifest["instrument"],
                "defaultExperiment": manifest["defaultExperiment"],
                "limitations": manifest["limitations"],
                "featured": eventPackId == "spacex-nasdaq100-2026-v1",
                "caseRole": (
                    "FLAGSHIP_OUT_OF_SAMPLE"
                    if eventPackId == "spacex-nasdaq100-2026-v1"
                    else "HISTORICAL_VALIDATION_CASE"
                    if eventPackId in {"crowdstrike-outage-2024-v1", "gamestop-meme-2021-v1"}
                    else "SYNTHETIC_MECHANISM_FIXTURE"
                ),
                "validationStatus": manifest.get("validationStatus"),
            }
            for eventPackId, manifest in sorted(
                self.canonicalPacks.items(),
                key=lambda item: (
                    item[0] != "spacex-nasdaq100-2026-v1",
                    item[0] == "spacex-synthetic-v1",
                    item[0],
                ),
            )
        ]
        if sessionId is None:
            return canonicalCases
        customCases = [
            self._caseSummary(manifest)
            for manifest in self.database.listCustomEventPacks(sessionId)
        ]
        return [*customCases, *canonicalCases]

    def getEventPack(self, eventPackId: str, sessionId: str | None) -> dict[str, Any]:
        canonical = self.canonicalPacks.get(eventPackId)
        if canonical is None and sessionId is not None:
            canonical = self.database.getCustomEventPack(sessionId, eventPackId)
        if canonical is None:
            raise ApiError("EVENT_PACK_NOT_FOUND", 404, "The Event Pack does not exist.")
        eventPack = copy.deepcopy(canonical)
        if eventPackId in self.canonicalPacks:
            defaultExperiment = eventPack.get("defaultExperiment")
            if isinstance(defaultExperiment, dict):
                intervention = defaultExperiment.get("intervention")
                if isinstance(intervention, dict):
                    # 内置案例的问题与干预由同一份受版本控制的清单发布，可直接
                    # 标记为已对齐；旧的用户草稿仍保持未确认并要求人工复核。
                    defaultExperiment.setdefault(
                        "questionInterventionParameter",
                        intervention.get("parameter"),
                    )
        draft = self.database.getEventPackDraft(sessionId, eventPackId) if sessionId else None
        if draft:
            eventPack["claims"] = draft["claims"]
            eventPack["status"] = "FROZEN" if draft["frozen"] else "DRAFT"
            eventPack["frozenAt"] = draft["frozenAt"]
        else:
            eventPack["status"] = "DRAFT"
            eventPack["frozenAt"] = None
        eventPack["editableExtraction"] = eventPackId not in self.canonicalPacks
        eventPack["sessionScoped"] = True
        _annotateClaimBulkApprovalMetadata(eventPack)
        return eventPack

    def createEventPack(
        self,
        requestData: EventPackCreateRequest,
        sessionId: str,
        claims: list[dict[str, Any]] | None = None,
        extractionMode: str = "RULE_FALLBACK",
        contentSecurity: dict[str, Any] | None = None,
        eventPackId: str | None = None,
    ) -> dict[str, Any]:
        asOf = requestData.asOf.isoformat()
        self.validateSourcesAtCutoff(requestData.sources, requestData.asOf)
        slug = re.sub(r"[^a-z0-9]+", "-", requestData.title.lower()).strip("-")[:44]
        # 每次创建都是一个新的不可变版本。旧实现只对部分来源字段求摘要，
        # 相同标题和正文可能命中同一 ID 并通过 UPSERT 改写已冻结清单。
        if eventPackId is None:
            eventPackId = f"custom-{slug or 'event'}-{uuid.uuid4().hex[:16]}"
        elif len(eventPackId) > 100 or re.fullmatch(r"custom-[a-z0-9-]+", eventPackId) is None:
            raise ValueError("eventPackId must be a valid custom immutable identifier")
        sourceRecords = [self._sourceRecord(source) for source in requestData.sources]
        extractedClaims = claims or self.extractCandidateClaims(requestData, maximumClaims=16)
        extractionQuality = _extractionQualityMetadata(extractionMode, extractedClaims)
        manifest = {
            "schemaVersion": "1.0.0",
            "id": eventPackId,
            "caseId": f"case-{eventPackId}",
            "title": requestData.title,
            "titleZh": requestData.titleZh or requestData.title,
            "summary": requestData.summary,
            "summaryZh": requestData.summaryZh or requestData.summary,
            "asOf": asOf,
            "synthetic": False,
            "marketDataSynthetic": True,
            "syntheticLabel": "Source-backed facts with synthetic market assumptions",
            "syntheticLabelZh": "可追溯事实与合成市场假设",
            "instrument": requestData.instrument,
            "sources": sourceRecords,
            "timeline": [
                {
                    "eventType": "SOURCE_KNOWN",
                    "sourceId": source["sourceId"],
                    "publishedAt": source["publishedAt"],
                    "knownAt": source["knownAt"],
                }
                for source in sourceRecords
            ],
            "extraction": {
                "mode": extractionMode,
                "humanReviewRequired": True,
                "generatedAt": utcNow(),
                "contentSecurity": contentSecurity or _defaultContentSecuritySummary(),
                **extractionQuality,
            },
            "mechanismRules": {"clarificationClaimId": "claim-clarification"},
            "defaultExperiment": {
                "question": (
                    "How does lower market-making capacity change the simulated risk distribution?"
                ),
                "questionZh": "较低的做市能力会如何改变模拟风险分布？",
                "questionInterventionParameter": "marketMakerCapacity",
                "intervention": {
                    "parameter": "marketMakerCapacity",
                    "baselineValue": 1.0,
                    "interventionValue": 0.65,
                },
                "seedCount": 10,
                "populationSize": 56,
                "steps": 120,
            },
            "limitations": [
                {
                    "code": "SYNTHETIC_MARKET_ASSUMPTIONS",
                    "text": (
                        "The uploaded facts are source-bound, while prices, liquidity, "
                        "flows, and agent behavior remain synthetic scenario assumptions."
                    ),
                    "textZh": (
                        "上传事实受来源约束，但价格、流动性、资金流和智能体行为仍是合成场景假设。"
                    ),
                },
                {
                    "code": "HUMAN_REVIEW_REQUIRED",
                    "text": (
                        "Extracted claims are candidates and cannot enter a frozen "
                        "experiment before human review."
                    ),
                    "textZh": "抽取结果只是候选主张，未经人工审核不得进入冻结实验。",
                },
            ],
        }
        self.database.saveCustomEventPackWithAudit(
            sessionId,
            eventPackId,
            manifest,
            extractedClaims,
            auditAction="CREATED",
            auditPayload={
                "sourceCount": len(sourceRecords),
                "claimCount": len(extractedClaims),
                "extractionMode": extractionMode,
                "contentSecurity": _contentSecurityAuditSummary(contentSecurity),
            },
        )
        return self.getEventPack(eventPackId, sessionId)

    def saveExtractedClaims(
        self,
        eventPackId: str,
        sessionId: str,
        claims: list[dict[str, Any]],
        extractionMode: str,
        sources: list[EventSourceInput],
        contentSecurity: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        # LLM 请求在进入本方法前已经完成；这里只锁住最终的重新读取与落盘，
        # 防止重抽取基于旧 DRAFT 状态覆盖另一个线程刚冻结的 Event Pack。
        with self.database.writeLock:
            eventPack = self.getEventPack(eventPackId, sessionId)
            if eventPackId in self.canonicalPacks:
                raise ApiError(
                    "CANONICAL_PACK_EXTRACTION_FORBIDDEN",
                    409,
                    "Canonical repository Event Packs cannot be replaced by session extraction.",
                )
            if eventPack["status"] == "FROZEN":
                raise ApiError("EVENT_PACK_FROZEN", 409, "A frozen Event Pack cannot be edited.")
            self.validateSourcesAtCutoff(sources, eventPack["asOf"])
            sourceRecords = [self._sourceRecord(source) for source in sources]
            eventPack.pop("claims", None)
            eventPack.pop("status", None)
            eventPack.pop("frozenAt", None)
            eventPack.pop("sessionScoped", None)
            extractionQuality = _extractionQualityMetadata(extractionMode, claims)
            eventPack["extraction"] = {
                "mode": extractionMode,
                "humanReviewRequired": True,
                "generatedAt": utcNow(),
                "contentSecurity": contentSecurity or _defaultContentSecuritySummary(),
                **extractionQuality,
            }
            eventPack["sources"] = sourceRecords
            retainedTimeline = [
                item
                for item in eventPack.get("timeline", [])
                if not isinstance(item, dict) or item.get("eventType") != "SOURCE_KNOWN"
            ]
            eventPack["timeline"] = [
                *retainedTimeline,
                *[
                    {
                        "eventType": "SOURCE_KNOWN",
                        "sourceId": source["sourceId"],
                        "publishedAt": source["publishedAt"],
                        "knownAt": source["knownAt"],
                    }
                    for source in sourceRecords
                ],
            ]
            self.database.saveExtractedEventPackWithAudit(
                sessionId,
                eventPackId,
                eventPack,
                claims,
                auditAction="CLAIMS_EXTRACTED",
                auditPayload={
                    "claimCount": len(claims),
                    "sourceCount": len(sourceRecords),
                    "sourceIds": [source["sourceId"] for source in sourceRecords],
                    "extractionMode": extractionMode,
                    "contentSecurity": _contentSecurityAuditSummary(contentSecurity),
                },
            )
            return self.getEventPack(eventPackId, sessionId)

    @staticmethod
    def validateSourcesAtCutoff(
        sources: list[EventSourceInput],
        asOf: datetime | str,
    ) -> None:
        cutoff = (
            asOf.replace(tzinfo=UTC)
            if isinstance(asOf, datetime) and (asOf.tzinfo is None or asOf.utcoffset() is None)
            else asOf.astimezone(UTC)
            if isinstance(asOf, datetime)
            else _parseUtc(asOf)
        )
        futureSources = [
            source.sourceId
            for source in sources
            if (
                source.knownAt.replace(tzinfo=UTC)
                if source.knownAt.tzinfo is None or source.knownAt.utcoffset() is None
                else source.knownAt.astimezone(UTC)
            )
            > cutoff
        ]
        if futureSources:
            raise ApiError(
                "POINT_IN_TIME_LEAKAGE",
                422,
                "Every source knownAt must be on or before the Event Pack asOf time.",
            )

    def extractCandidateClaims(
        self,
        requestData: EventPackCreateRequest,
        maximumClaims: int,
        requestedImpactChannels: tuple[str, ...] = ALLOWED_IMPACT_CHANNELS,
    ) -> list[dict[str, Any]]:
        """无外部模型时只生成可读、去重且标明低质量边界的候选主张。"""

        candidates = extractRuleFallbackClaims(
            requestData.sources,
            maximumClaims=maximumClaims,
            requestedImpactChannels=requestedImpactChannels,
        )
        if not candidates:
            raise ApiError(
                "NO_EXTRACTABLE_CLAIMS",
                422,
                (
                    "No complete source sentence passed the deterministic claim-quality "
                    "gate. Add a source containing complete factual sentences or enable "
                    "a tested structured-output model."
                ),
            )
        return candidates

    def reviewClaim(
        self,
        eventPackId: str,
        claimId: str,
        sessionId: str,
        review: ClaimReviewRequest,
    ) -> dict[str, Any]:
        # 审核会重写整份 claims JSON，因此读取、修改、持久化与审计必须串行，
        # 否则两个快速点击可能各自基于旧快照并互相覆盖。
        with self.database.writeLock:
            eventPack = self.getEventPack(eventPackId, sessionId)
            if eventPack["status"] == "FROZEN":
                raise ApiError("EVENT_PACK_FROZEN", 409, "A frozen Event Pack cannot be edited.")
            claim = next(
                (item for item in eventPack["claims"] if item["claimId"] == claimId),
                None,
            )
            if claim is None:
                raise ApiError("CLAIM_NOT_FOUND", 404, "The claim does not exist.")
            claim["reviewStatus"] = review.reviewStatus.value
            if review.reviewStatus.value == "AI_PROPOSED":
                claim.pop("reviewedBy", None)
                claim.pop("reviewedAt", None)
                claim.pop("reviewRationale", None)
            else:
                claim["reviewedBy"] = sessionId
                claim["reviewedAt"] = utcNow()
                claim["reviewRationale"] = review.rationale
            if review.editedText:
                claim["originalText"] = claim["text"]
                claim["text"] = review.editedText
            if review.editedTextZh:
                claim["originalTextZh"] = claim.get("textZh")
                claim["textZh"] = review.editedTextZh
            if review.editedImpactChannels is not None:
                claim["originalImpactChannels"] = list(claim.get("impactChannels", []))
                claim["originalImpactChannelRationale"] = list(
                    claim.get("impactChannelRationale", [])
                )
                claim["impactChannels"] = list(review.editedImpactChannels)
                claim["impactChannelRationale"] = [
                    item.model_dump(mode="json")
                    for item in (review.editedImpactChannelRationale or [])
                ]
                claim["channelMappingIsInference"] = any(
                    item.evidenceType == "MECHANISM_HYPOTHESIS"
                    for item in (review.editedImpactChannelRationale or [])
                )
            self.database.saveEventPackDraftWithAudit(
                sessionId,
                eventPackId,
                eventPack["claims"],
                auditEntityType="CLAIM",
                auditEntityId=claimId,
                auditAction=review.reviewStatus.value,
                auditPayload={
                    "eventPackId": eventPackId,
                    "rationale": review.rationale,
                    "impactChannelsEdited": review.editedImpactChannels is not None,
                    "impactChannels": review.editedImpactChannels,
                },
            )
            return self.getEventPack(eventPackId, sessionId)

    def approveAllProposedClaims(
        self,
        eventPackId: str,
        sessionId: str,
        approval: BulkClaimApprovalRequest,
    ) -> dict[str, Any]:
        """一次批准用户在警告框中确认过的全部待审核主张。"""

        with self.database.writeLock:
            eventPack = self.getEventPack(eventPackId, sessionId)
            if eventPack["status"] == "FROZEN":
                raise ApiError("EVENT_PACK_FROZEN", 409, "A frozen Event Pack cannot be edited.")

            proposedClaims = [
                claim for claim in eventPack["claims"] if claim.get("reviewStatus") == "AI_PROPOSED"
            ]
            if not proposedClaims:
                raise ApiError(
                    "NO_PENDING_CLAIMS",
                    409,
                    "The Event Pack does not contain any pending claims.",
                )
            eligibleClaims = [
                claim
                for claim in proposedClaims
                if not _claimBulkApprovalExclusionReasons(eventPack, claim)
            ]
            eligibleClaimIds = [claim["claimId"] for claim in eligibleClaims]
            if not eligibleClaims:
                raise ApiError(
                    "NO_BULK_APPROVAL_ELIGIBLE_CLAIMS",
                    409,
                    (
                        "No pending claim satisfies the bulk-approval quality gate. "
                        "Review low-confidence, multi-channel, safety-review, and "
                        "non-official claims individually."
                    ),
                )
            if len(eligibleClaimIds) != len(approval.expectedClaimIds) or set(
                eligibleClaimIds
            ) != set(approval.expectedClaimIds):
                raise ApiError(
                    "CLAIM_QUEUE_CHANGED",
                    409,
                    (
                        "The bulk-eligible claim queue changed. Reload it and confirm "
                        "bulk approval again."
                    ),
                )

            reviewedAt = utcNow()
            for claim in eligibleClaims:
                claim["reviewStatus"] = "HUMAN_APPROVED"
                claim["reviewedBy"] = sessionId
                claim["reviewedAt"] = reviewedAt
                claim["reviewRationale"] = approval.rationale

            auditPayload: dict[str, Any] = {
                "claimCount": len(eligibleClaimIds),
                "claimIds": eligibleClaimIds,
                "reviewStatus": "HUMAN_APPROVED",
                "warningAcknowledged": approval.acknowledgedBulkApproval,
                "rationale": approval.rationale,
            }
            if eventPack.get("editableExtraction") is not False:
                auditPayload.update(
                    {
                        "excludedPendingCount": len(proposedClaims) - len(eligibleClaims),
                        "exclusionReasonCounts": {
                            reason: sum(
                                reason in _claimBulkApprovalExclusionReasons(eventPack, claim)
                                for claim in proposedClaims
                            )
                            for reason in (
                                "LOW_CONFIDENCE",
                                "MULTIPLE_IMPACT_CHANNELS",
                                "CONTENT_SAFETY_REVIEW",
                                "NON_OFFICIAL_SOURCE",
                                "EXTRACTION_NOT_ELIGIBLE",
                            )
                        },
                    }
                )
            self.database.saveEventPackDraftWithAudit(
                sessionId,
                eventPackId,
                eventPack["claims"],
                auditAction="BULK_CLAIMS_APPROVED",
                auditPayload=auditPayload,
            )
            return self.getEventPack(eventPackId, sessionId)

    def freezeEventPack(self, eventPackId: str, sessionId: str) -> dict[str, Any]:
        with self.database.writeLock:
            eventPack = self.getEventPack(eventPackId, sessionId)
            if eventPack["status"] == "FROZEN":
                return eventPack
            unresolvedClaims = [
                claim["claimId"]
                for claim in eventPack["claims"]
                if claim.get("reviewStatus") == "AI_PROPOSED"
            ]
            if unresolvedClaims:
                raise ApiError(
                    "CLAIMS_REQUIRE_HUMAN_REVIEW",
                    422,
                    "Every proposed claim must be approved, edited, or rejected before freezing.",
                )
            unapprovedClaims = [
                claim["claimId"]
                for claim in eventPack["claims"]
                if claim.get("isRequired")
                and claim.get("reviewStatus") not in {"HUMAN_APPROVED", "EDITED"}
            ]
            if unapprovedClaims:
                raise ApiError(
                    "REQUIRED_CLAIMS_NOT_APPROVED",
                    422,
                    "Every required claim must be human-approved or edited before freezing.",
                )
            frozenAt = utcNow()
            frozenClaims = [
                {
                    **claim,
                    "reviewStatus": "FROZEN",
                    "preFreezeReviewStatus": claim["reviewStatus"],
                }
                for claim in eventPack["claims"]
            ]
            self.database.saveEventPackDraftWithAudit(
                sessionId,
                eventPackId,
                frozenClaims,
                frozen=True,
                frozenAt=frozenAt,
                auditAction="FROZEN",
                auditPayload={"claimCount": len(frozenClaims), "frozenAt": frozenAt},
            )
            return self.getEventPack(eventPackId, sessionId)

    def validateExperiment(
        self,
        requestData: ExperimentRequest,
        sessionId: str,
        credentialSessionId: str | None = None,
    ) -> dict[str, Any]:
        errors: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []
        checks: list[dict[str, str]] = []
        degradationReasons: list[str] = []
        tokenPrice = None
        minimumReservationUsd: float | None = None
        configView = None

        def addCheck(code: str, status: str, message: str) -> None:
            checks.append({"code": code, "status": status, "message": message})

        def addDegradationReason(code: str) -> None:
            if code not in degradationReasons:
                degradationReasons.append(code)

        try:
            eventPack = self.getEventPack(requestData.eventPackId, sessionId)
        except ApiError:
            eventPack = None
            errors.append(
                {
                    "code": "EVENT_PACK_NOT_FOUND",
                    "message": "The selected Event Pack does not exist.",
                }
            )
            addCheck("EVENT_PACK_EXISTS", "FAIL", "The selected Event Pack does not exist.")
        else:
            addCheck("EVENT_PACK_EXISTS", "PASS", "The selected Event Pack exists.")
        if eventPack and eventPack["status"] != "FROZEN":
            errors.append(
                {
                    "code": "EVENT_PACK_NOT_FROZEN",
                    "message": "Review and freeze the Event Pack before running an experiment.",
                }
            )
            addCheck("EVENT_PACK_FROZEN", "FAIL", "The Event Pack is not frozen.")
        elif eventPack:
            addCheck("EVENT_PACK_FROZEN", "PASS", "The Event Pack is frozen for this session.")

        if eventPack:
            asOf = _parseUtc(eventPack["asOf"])
            futureEvidence = []
            scheduledEvidence = []
            for source in eventPack.get("sources", []):
                knownAt = source.get("knownAt")
                if knownAt and _parseUtc(knownAt) > asOf:
                    sourceId = str(source.get("sourceId", "unknown-source"))
                    if source.get("simulationEligibility") == "POST_EVENT_VALIDATION_ONLY":
                        scheduledEvidence.append(sourceId)
                    else:
                        futureEvidence.append(sourceId)
            for claim in eventPack.get("claims", []):
                knownAt = claim.get("knownAt")
                if knownAt and _parseUtc(knownAt) > asOf:
                    claimId = str(claim.get("claimId", "unknown-claim"))
                    isScheduledSynthetic = (
                        claim.get("synthetic") is True
                        and claim.get("claimType") == "SCENARIO_ASSUMPTION"
                    )
                    if isScheduledSynthetic:
                        scheduledEvidence.append(claimId)
                    else:
                        futureEvidence.append(claimId)
            if futureEvidence:
                errors.append(
                    {
                        "code": "POINT_IN_TIME_LEAKAGE",
                        "message": "Future evidence is visible at the Event Pack cutoff: "
                        + ", ".join(sorted(futureEvidence)),
                    }
                )
                addCheck(
                    "POINT_IN_TIME_BOUNDARY",
                    "FAIL",
                    "At least one source or claim is later than the Event Pack cutoff.",
                )
            else:
                addCheck(
                    "POINT_IN_TIME_BOUNDARY",
                    "PASS",
                    (
                        "No future evidence is visible at the initial observation; "
                        f"{len(scheduledEvidence)} later item(s) remain explicitly withheld."
                    ),
                )

            unreviewedClaims = [
                claim.get("claimId", "unknown-claim")
                for claim in eventPack.get("claims", [])
                if claim.get("preFreezeReviewStatus", claim.get("reviewStatus"))
                not in {"HUMAN_APPROVED", "EDITED", "FROZEN", "REJECTED"}
            ]
            if unreviewedClaims:
                errors.append(
                    {
                        "code": "CLAIM_REVIEW_INCOMPLETE",
                        "message": "Every candidate claim must receive an explicit human decision.",
                    }
                )
                addCheck(
                    "CLAIM_REVIEW_COMPLETE",
                    "FAIL",
                    "Some candidate claims do not have a human review decision.",
                )
            else:
                addCheck(
                    "CLAIM_REVIEW_COMPLETE",
                    "PASS",
                    "Every claim has an explicit human review decision.",
                )

            if any(source.get("contentHash") is None for source in eventPack.get("sources", [])):
                warnings.append(
                    {
                        "code": "LINK_ONLY_SOURCE_HASH",
                        "message": (
                            "At least one official source is link-only; its URL is retained, "
                            "but a content snapshot hash is not available."
                        ),
                    }
                )
                addCheck(
                    "SOURCE_CONTENT_HASHES",
                    "WARN",
                    "At least one source is link-only and has no captured content hash.",
                )
            else:
                addCheck(
                    "SOURCE_CONTENT_HASHES",
                    "PASS",
                    "Every source has a captured content hash.",
                )
            warnings.append(
                {
                    "code": "LICENSE_REVIEW_REQUIRED_FOR_REDISTRIBUTION",
                    "message": (
                        "Source availability is not redistribution permission; the bundle "
                        "exports source metadata and hashes rather than source text."
                    ),
                }
            )
            addCheck(
                "SOURCE_REDISTRIBUTION_BOUNDARY",
                "WARN",
                "A human license review remains required before public source redistribution.",
            )
        if (
            eventPack
            and requestData.intervention.parameter.value == "clarificationDelay"
            and not self._claimAccepted(
                eventPack,
                eventPack.get("mechanismRules", {}).get(
                    "clarificationClaimId", "claim-clarification"
                ),
            )
        ):
            errors.append(
                {
                    "code": "INTERVENTION_MECHANISM_DISABLED",
                    "message": (
                        "The clarification-delay intervention is unavailable because "
                        "the clarification claim was rejected."
                    ),
                }
            )
        if requestData.intervention.baselineValue == requestData.intervention.interventionValue:
            errors.append(
                {
                    "code": "INTERVENTION_HAS_NO_DIFF",
                    "message": "Baseline and intervention values must differ.",
                }
            )
            addCheck(
                "SINGLE_REGISTERED_INTERVENTION",
                "FAIL",
                "The intervention does not differ from the baseline.",
            )
        else:
            addCheck(
                "SINGLE_REGISTERED_INTERVENTION",
                "PASS",
                "Exactly one registered intervention differs from the baseline.",
            )

        questionParameter = requestData.questionInterventionParameter
        interventionParameter = requestData.intervention.parameter
        if questionParameter is None:
            warnings.append(
                {
                    "code": "QUESTION_INTERVENTION_REVIEW_REQUIRED",
                    "message": (
                        "The research question has no recorded human confirmation for the "
                        "selected intervention. Review it before using this draft in the UI."
                    ),
                }
            )
            addCheck(
                "QUESTION_INTERVENTION_ALIGNMENT",
                "WARN",
                "The research question and selected intervention require explicit review.",
            )
        elif questionParameter != interventionParameter:
            errors.append(
                {
                    "code": "QUESTION_INTERVENTION_MISMATCH",
                    "message": (
                        "The research question was confirmed for a different intervention. "
                        "Regenerate it or explicitly confirm the current wording."
                    ),
                }
            )
            addCheck(
                "QUESTION_INTERVENTION_ALIGNMENT",
                "FAIL",
                "The research question was confirmed for a different intervention.",
            )
        else:
            addCheck(
                "QUESTION_INTERVENTION_ALIGNMENT",
                "PASS",
                "The research question was explicitly confirmed for the selected intervention.",
            )

        unknownOutcomes = sorted(
            {
                requestData.primaryOutcome,
                *requestData.secondaryOutcomes,
            }
            - set(METRIC_KEYS)
        )
        if unknownOutcomes:
            errors.append(
                {
                    "code": "OUTCOME_NOT_REGISTERED",
                    "message": "Every outcome must be a registered simulator metric: "
                    + ", ".join(unknownOutcomes),
                }
            )
            addCheck(
                "OUTCOMES_REGISTERED",
                "FAIL",
                "At least one requested outcome is not produced by the simulator.",
            )
        else:
            addCheck(
                "OUTCOMES_REGISTERED",
                "PASS",
                "Primary and secondary outcomes are registered simulator metrics.",
            )

        if requestData.stoppingRule.targetCiHalfWidth is None:
            addCheck(
                "STOPPING_RULE",
                "PASS",
                f"The experiment uses a fixed count of {requestData.seedCount} paired seeds.",
            )
        else:
            addCheck(
                "STOPPING_RULE",
                "PASS",
                (
                    "Sequential stopping may begin after "
                    f"{requestData.stoppingRule.minimumPairs} pairs when the primary-outcome "
                    "bootstrap 95% interval reaches the preregistered half-width."
                ),
            )

        if requestData.network.averageDegree >= requestData.populationSize:
            errors.append(
                {
                    "code": "NETWORK_DEGREE_EXCEEDS_POPULATION",
                    "message": "Network average degree must be smaller than population size.",
                }
            )
            addCheck(
                "NETWORK_FEASIBLE",
                "FAIL",
                "The requested average degree cannot fit the population.",
            )
        else:
            addCheck(
                "NETWORK_FEASIBLE",
                "PASS",
                "The requested network degree fits the population.",
            )

        if requestData.population.shortSellingEnabled:
            addCheck(
                "BORROW_AND_MARGIN_CONTROLS",
                "PASS",
                (
                    "Short selling routes through the simulator borrow, reservation, "
                    "and margin ledger."
                ),
            )

        if requestData.llmPolicy.mode.value == "HYBRID_LLM":
            configView = (
                self.cognition.getConfig(credentialSessionId or sessionId)
                if self.cognition
                else None
            )
            if configView is None or not configView.configured:
                addDegradationReason("LLM_CREDENTIAL_NOT_CONFIGURED")
                status = "WARN" if requestData.llmPolicy.fallbackToRules else "FAIL"
                message = (
                    "No session LLM credential is configured; this run will use the "
                    "declared deterministic rule fallback."
                    if requestData.llmPolicy.fallbackToRules
                    else "Hybrid mode requires a configured session LLM credential."
                )
                target = warnings if requestData.llmPolicy.fallbackToRules else errors
                target.append({"code": "LLM_CREDENTIAL_NOT_CONFIGURED", "message": message})
                addCheck("LLM_RUNTIME_CONFIG", status, message)
            elif (
                configView.provider != requestData.llmPolicy.provider
                or configView.model != requestData.llmPolicy.modelId
            ):
                addDegradationReason("LLM_PROVIDER_MODEL_CONFIG_MISMATCH")
                errors.append(
                    {
                        "code": "LLM_PROVIDER_MODEL_CONFIG_MISMATCH",
                        "message": (
                            "The scenario provider/model does not match the session configuration."
                        ),
                    }
                )
                addCheck(
                    "LLM_RUNTIME_CONFIG",
                    "FAIL",
                    "The scenario provider/model and configured session route differ.",
                )
            else:
                addCheck(
                    "LLM_RUNTIME_CONFIG",
                    "PASS",
                    "The selected structured-output model is configured for this session.",
                )
            if requestData.llmPolicy.representativeAgentCount > requestData.llmPolicy.callBudget:
                addDegradationReason("LLM_CALL_BUDGET_TOO_SMALL")
                errors.append(
                    {
                        "code": "LLM_CALL_BUDGET_TOO_SMALL",
                        "message": (
                            "LLM call budget must cover every configured representative agent."
                        ),
                    }
                )
                addCheck(
                    "LLM_CALL_BUDGET",
                    "FAIL",
                    "The call budget is smaller than the representative-agent count.",
                )
            else:
                addCheck(
                    "LLM_CALL_BUDGET",
                    "PASS",
                    "The call budget covers the configured representative agents.",
                )

            try:
                tokenPrice = getTokenPrice(
                    requestData.llmPolicy.provider,
                    requestData.llmPolicy.modelId,
                )
            except ValueError:
                tokenPrice = None
            if tokenPrice is None:
                addDegradationReason("LLM_PRICE_UNAVAILABLE")
                status = "WARN" if requestData.llmPolicy.fallbackToRules else "FAIL"
                message = (
                    "No verified public token price is available; the runtime will fail "
                    "closed to deterministic rules without sending a model request."
                    if requestData.llmPolicy.fallbackToRules
                    else "Hybrid mode cannot call a model without a verified public token price."
                )
                target = warnings if requestData.llmPolicy.fallbackToRules else errors
                target.append({"code": "LLM_PRICE_UNAVAILABLE", "message": message})
                addCheck("LLM_COST_CONTROL", status, message)
            else:
                configuredMaxTokens = (
                    configView.max_tokens
                    if configView is not None
                    and configView.configured
                    and configView.provider == requestData.llmPolicy.provider
                    and configView.model == requestData.llmPolicy.modelId
                    and configView.max_tokens is not None
                    else 2_048
                )
                try:
                    reservation = estimateReservation(
                        modelId=requestData.llmPolicy.modelId,
                        maxOutputTokens=configuredMaxTokens,
                        policy=ModelPolicy(),
                        provider=requestData.llmPolicy.provider,
                    )
                except (ModelGatewayError, ValueError) as error:
                    addDegradationReason("LLM_OUTPUT_LIMIT_UNAVAILABLE")
                    status = "WARN" if requestData.llmPolicy.fallbackToRules else "FAIL"
                    message = (
                        "The model has no verified executable output limit; the runtime will "
                        "fail closed to deterministic rules without sending a model request."
                        if requestData.llmPolicy.fallbackToRules
                        else "Hybrid mode requires a verified executable model output limit."
                    )
                    target = warnings if requestData.llmPolicy.fallbackToRules else errors
                    target.append(
                        {
                            "code": "LLM_OUTPUT_LIMIT_UNAVAILABLE",
                            "message": message,
                            "detail": str(error),
                        }
                    )
                    addCheck("LLM_COST_CONTROL", status, message)
                else:
                    minimumReservationUsd = float(reservation.maximumUsd)
                    if reservation.maximumUsd > requestData.llmPolicy.maxCostUsd:
                        addDegradationReason("LLM_COST_CAP_INSUFFICIENT")
                        status = "WARN" if requestData.llmPolicy.fallbackToRules else "FAIL"
                        message = (
                            "The configured cap is below the worst-case reservation for one "
                            "response plus one repair; the runtime will not dispatch the model."
                        )
                        target = warnings if requestData.llmPolicy.fallbackToRules else errors
                        target.append({"code": "LLM_COST_CAP_INSUFFICIENT", "message": message})
                        addCheck("LLM_COST_CONTROL", status, message)
                    else:
                        addCheck(
                            "LLM_COST_CONTROL",
                            "PASS",
                            (
                                "The USD cap can reserve every allowed full-context transport "
                                "attempt for the initial response and one repair; each call "
                                "settles against provider-reported input/output tokens."
                            ),
                        )
                warnings.append(
                    {
                        "code": "LLM_PRICE_SNAPSHOT_UPPER_BOUND",
                        "message": (
                            "Cost control uses verified public list-price maxima in each "
                            "provider's source currency. CNY uses a conservative frozen USD "
                            "conversion; discounts, bundles, taxes, and invoice-specific terms "
                            "are excluded."
                        ),
                    }
                )
        else:
            addCheck(
                "LLM_RUNTIME_CONFIG",
                "PASS",
                "Rule-only mode makes no external model call.",
            )

        addCheck(
            "LLM_TOOL_AUTHORITY",
            "PASS",
            "Cognitive agents have no network, filesystem, pricing, or order-submission tool.",
        )
        addCheck(
            "REPRODUCIBILITY_METADATA",
            "PASS",
            (
                "Seeds, engine version, prompt version, model route, and configuration "
                "hashes are recorded."
            ),
        )
        if requestData.seedCount == 10:
            warnings.append(
                {
                    "code": "SMALL_SEED_COUNT",
                    "message": (
                        "Ten seeds are suitable for a demo but produce a wide empirical interval."
                    ),
                }
            )
        llmModeRequested = requestData.llmPolicy.mode.value == "HYBRID_LLM"
        degradationCodes = set(degradationReasons)
        structuralErrors = [error for error in errors if error["code"] not in degradationCodes]
        structurallyRunnable = not structuralErrors
        requestedCognitionRunnable = structurallyRunnable and (
            not llmModeRequested or not degradationReasons
        )
        simulationRunnable = structurallyRunnable and (
            requestedCognitionRunnable
            or (
                llmModeRequested
                and requestData.llmPolicy.fallbackToRules
                and bool(degradationReasons)
            )
        )
        effectiveCognitionMode = (
            "HYBRID_LLM"
            if llmModeRequested and requestedCognitionRunnable
            else "RULE_ONLY"
            if simulationRunnable
            else "UNAVAILABLE"
        )
        return {
            "valid": not errors,
            "simulationRunnable": simulationRunnable,
            "requestedCognitionRunnable": requestedCognitionRunnable,
            "effectiveCognitionMode": effectiveCognitionMode,
            "degradationReasons": degradationReasons,
            "requiresExplicitRuleFallbackConfirmation": (
                llmModeRequested and structurallyRunnable and not requestedCognitionRunnable
            ),
            "errors": errors,
            "warnings": warnings,
            "checks": checks,
            "scenarioDiff": {
                "changedPaths": [f"intervention.{requestData.intervention.parameter.value}"],
                "changeCount": 1,
                "parameter": requestData.intervention.parameter.value,
                "baselineValue": requestData.intervention.baselineValue,
                "interventionValue": requestData.intervention.interventionValue,
            },
            "estimatedRuns": requestData.seedCount * 2,
            "estimatedLlmCalls": (
                min(
                    requestData.llmPolicy.callBudget,
                    requestData.llmPolicy.representativeAgentCount
                    * math.ceil(requestData.steps / requestData.llmPolicy.decisionIntervalSteps),
                )
                if requestData.llmPolicy.mode.value == "HYBRID_LLM"
                else 0
            ),
            "llmCostCapUsd": requestData.llmPolicy.maxCostUsd,
            "llmPricingStatus": (
                "VERIFIED_UPPER_BOUND"
                if requestData.llmPolicy.mode.value == "HYBRID_LLM" and tokenPrice is not None
                else "NOT_APPLICABLE"
                if requestData.llmPolicy.mode.value == "RULE_ONLY"
                else "UNAVAILABLE_FAIL_CLOSED"
            ),
            "llmMinimumCallReservationUsd": minimumReservationUsd,
            "thinkingPreferenceEnabled": (
                configView.thinking_enabled
                if configView is not None and configView.configured
                else None
            ),
            "thinkingEnabled": False,
            "interpretationBoundary": "MECHANISM_DEMONSTRATION_NOT_FORECAST",
        }

    def canonicalHash(self, eventPackId: str) -> str:
        canonical = self.canonicalPacks[eventPackId]
        return _hashJson(canonical)

    @staticmethod
    def _sourceRecord(source: Any) -> dict[str, Any]:
        contentHash = hashlib.sha256(source.rawText.encode()).hexdigest()
        return {
            "sourceId": source.sourceId,
            "title": source.title,
            "titleZh": source.title,
            "publisher": source.publisher,
            "url": source.url,
            "sourceType": source.sourceType,
            "tier": "T1" if source.sourceType == "OFFICIAL" else "T2",
            "publishedAt": source.publishedAt.isoformat(),
            "knownAt": source.knownAt.isoformat(),
            "publicationTimeAssumed": bool(getattr(source, "publicationTimeAssumed", False)),
            "contentHash": contentHash,
            "isOfficial": source.sourceType == "OFFICIAL",
            "rawTextRetained": False,
            "snapshotPolicy": "CONTENT_HASH_ONLY",
            "licenseNote": (
                "The uploader remains responsible for lawful use; source text is "
                "processed in memory and is not redistributed by EventShock Lab."
            ),
            "simulationEligibility": "POINT_IN_TIME_INPUT",
        }

    @staticmethod
    def _caseSummary(manifest: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": manifest["caseId"],
            "eventPackId": manifest["id"],
            "title": manifest["title"],
            "titleZh": manifest.get("titleZh", manifest["title"]),
            "summary": manifest.get("summary", ""),
            "summaryZh": manifest.get("summaryZh", manifest.get("summary", "")),
            "synthetic": manifest.get("synthetic", False),
            "syntheticLabel": manifest.get("syntheticLabel", ""),
            "syntheticLabelZh": manifest.get("syntheticLabelZh", ""),
            "instrument": manifest.get("instrument", "CUSTOM"),
            "defaultExperiment": manifest.get("defaultExperiment", {}),
            "limitations": manifest.get("limitations", []),
            "featured": False,
            "caseRole": "SESSION_CUSTOM_CASE",
            "validationStatus": manifest.get("validationStatus"),
            "updatedAt": manifest.get("updatedAt"),
        }

    @staticmethod
    def _claimAccepted(eventPack: dict[str, Any], claimId: str) -> bool:
        claim = next(
            (item for item in eventPack.get("claims", []) if item.get("claimId") == claimId),
            None,
        )
        if claim is None:
            return False
        reviewStatus = claim.get("preFreezeReviewStatus", claim.get("reviewStatus"))
        return reviewStatus in {"HUMAN_APPROVED", "EDITED", "FROZEN"}

    @staticmethod
    def _loadCanonicalPacks(eventPacksRoot: Path) -> dict[str, dict[str, Any]]:
        canonicalPacks: dict[str, dict[str, Any]] = {}
        for manifestPath in sorted(eventPacksRoot.glob("*/manifest.json")):
            claimsPath = manifestPath.parent / "claims.json"
            if not claimsPath.is_file():
                continue
            manifest = json.loads(manifestPath.read_text(encoding="utf-8"))
            manifest["claims"] = json.loads(claimsPath.read_text(encoding="utf-8"))
            canonicalPacks[manifest["id"]] = manifest
        if not canonicalPacks:
            raise RuntimeError("No canonical Event Packs were found")
        return canonicalPacks


class ExperimentService:
    def __init__(
        self,
        database: Database,
        eventPacks: EventPackService,
        cognition: CognitionService | None = None,
    ) -> None:
        self.database = database
        self.eventPacks = eventPacks
        self.cognition = cognition
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="eventshock-simulation"
        )
        self.futures: dict[str, Future[None]] = {}
        self.futureLock = threading.RLock()

    def createExperiment(
        self,
        requestData: ExperimentRequest,
        sessionId: str,
        idempotencyKey: str | None,
        credentialSessionId: str | None = None,
    ) -> tuple[dict[str, Any], bool]:
        if idempotencyKey:
            existingExperiment = self.database.getExperimentByIdempotencyKey(
                sessionId, idempotencyKey
            )
            if existingExperiment is not None:
                if existingExperiment["request"] != requestData.model_dump(mode="json"):
                    raise ApiError(
                        "IDEMPOTENCY_KEY_REUSED",
                        409,
                        "The Idempotency-Key was already used with a different request.",
                    )
                return self.publicExperiment(existingExperiment), False
        self.database.enforceRetention(maxStoredExperiments=MAX_STORED_EXPERIMENTS)
        self.database.pruneSessionExperiments(
            sessionId, maxRetained=MAX_EXPERIMENTS_PER_SESSION - 1
        )
        if self.database.countExperiments(sessionId) >= MAX_EXPERIMENTS_PER_SESSION:
            raise ApiError(
                "SESSION_EXPERIMENT_QUOTA_REACHED",
                429,
                "This demo session has reached its retained experiment quota.",
            )
        if self.database.countExperiments() >= MAX_STORED_EXPERIMENTS:
            raise ApiError(
                "PUBLIC_STORAGE_QUOTA_REACHED",
                503,
                "The public demo has reached its retained experiment quota.",
            )
        validation = self.eventPacks.validateExperiment(
            requestData,
            sessionId,
            credentialSessionId,
        )
        if validation["requiresExplicitRuleFallbackConfirmation"]:
            raise ApiError(
                "HYBRID_LLM_DEGRADATION_REQUIRES_RULE_ONLY",
                409,
                (
                    "The requested hybrid cognition route cannot run as configured. "
                    "Explicitly change llmPolicy.mode to RULE_ONLY before creating the experiment."
                ),
                details={
                    "degradationReasons": validation["degradationReasons"],
                    "effectiveCognitionMode": validation["effectiveCognitionMode"],
                },
            )
        if not validation["valid"]:
            raise ApiError(
                validation["errors"][0]["code"],
                422,
                validation["errors"][0]["message"],
            )
        experimentId = f"exp-{uuid.uuid4().hex[:16]}"
        experiment, created = self.database.createExperiment(
            experimentId,
            sessionId,
            requestData.model_dump(mode="json"),
            idempotencyKey,
        )
        if not created and experiment["request"] != requestData.model_dump(mode="json"):
            raise ApiError(
                "IDEMPOTENCY_KEY_REUSED",
                409,
                "The Idempotency-Key was already used with a different request.",
            )
        if created:
            self.database.appendAuditEvent(
                sessionId,
                "EXPERIMENT",
                experimentId,
                "EXPERIMENT_CREATED",
                {
                    "eventPackId": requestData.eventPackId,
                    "configurationHash": _hashJson(requestData.model_dump(mode="json")),
                    "seedCount": requestData.seedCount,
                    "agentMode": requestData.llmPolicy.mode.value,
                },
            )
        return self.publicExperiment(experiment), created

    def listExperiments(self, sessionId: str) -> list[dict[str, Any]]:
        return [self.publicExperiment(item) for item in self.database.listExperiments(sessionId)]

    def getExperiment(self, experimentId: str, sessionId: str) -> dict[str, Any]:
        experiment = self.database.getExperiment(experimentId, sessionId)
        if experiment is None:
            raise ApiError("EXPERIMENT_NOT_FOUND", 404, "The experiment does not exist.")
        return experiment

    def startExperiment(
        self,
        experimentId: str,
        sessionId: str,
        credentialSessionId: str | None = None,
    ) -> dict[str, Any]:
        with self.futureLock:
            experiment = self.getExperiment(experimentId, sessionId)
            if experiment["status"] in {"QUEUED", "RUNNING", "AGGREGATING", "COMPLETED"}:
                return self.publicExperiment(experiment)
            if experiment["status"] not in {"READY", "FAILED_RETRYABLE"}:
                raise ApiError(
                    "EXPERIMENT_NOT_STARTABLE",
                    409,
                    "The experiment cannot start from its current state.",
                )
            if self._activeFutureCountUnlocked() >= MAX_QUEUED_EXPERIMENTS:
                raise ApiError(
                    "EXPERIMENT_QUEUE_FULL", 429, "The public demo queue is currently full."
                )
            if not self.database.claimExperimentForQueue(experimentId, sessionId):
                latestExperiment = self.getExperiment(experimentId, sessionId)
                if latestExperiment["status"] in ACTIVE_STATUSES | {"COMPLETED"}:
                    return self.publicExperiment(latestExperiment)
                raise ApiError(
                    "EXPERIMENT_START_CONFLICT",
                    409,
                    "Another request changed the experiment before it could be queued.",
                )
            self.database.appendAuditEvent(
                sessionId,
                "EXPERIMENT",
                experimentId,
                "RUN_QUEUED",
                {"simulationConcurrency": 1},
            )
            future = self.executor.submit(
                self._runExperiment,
                experimentId,
                sessionId,
                credentialSessionId or sessionId,
            )
            self.futures[experimentId] = future
            future.add_done_callback(lambda _future: self._removeFuture(experimentId))
        return self.publicExperiment(self.getExperiment(experimentId, sessionId))

    def cancelExperiment(self, experimentId: str, sessionId: str) -> dict[str, Any]:
        experiment = self.getExperiment(experimentId, sessionId)
        if experiment["status"] in {
            "COMPLETED",
            "FAILED_FINAL",
            "CANCELLED",
            "INVALIDATED",
        }:
            return self.publicExperiment(experiment)
        if experiment["status"] == "READY":
            self.database.updateExperiment(
                experimentId,
                sessionId,
                status="CANCELLED",
                cancel_requested=1,
                completed_at=utcNow(),
            )
        else:
            self.database.updateExperiment(
                experimentId,
                sessionId,
                status="CANCEL_REQUESTED",
                cancel_requested=1,
            )
        self.database.appendAuditEvent(
            sessionId,
            "EXPERIMENT",
            experimentId,
            "RUN_CANCEL_REQUESTED",
            {"previousStatus": experiment["status"]},
        )
        return self.publicExperiment(self.getExperiment(experimentId, sessionId))

    def continueCognitionWithRules(
        self,
        experimentId: str,
        sessionId: str,
    ) -> dict[str, Any]:
        experiment = self.getExperiment(experimentId, sessionId)
        if experiment.get("cognitionFallbackRequested"):
            return self.publicExperiment(experiment)
        runtime = copy.deepcopy(experiment.get("runtime") or {})
        if (
            experiment["status"] not in ACTIVE_STATUSES
            or runtime.get("phase") != "COGNITION"
            or experiment["request"].get("llmPolicy", {}).get("mode") != "HYBRID_LLM"
        ):
            raise ApiError(
                "COGNITION_RULE_CONTINUATION_UNAVAILABLE",
                409,
                "Rule continuation is available only while hybrid cognition is preparing.",
            )
        cognitionProgress = copy.deepcopy(runtime.get("cognitionProgress") or {})
        cognitionProgress.update(
            {
                "status": "RULE_CONTINUATION_REQUESTED",
                "userRequestedRuleContinuation": True,
                "updatedAt": utcNow(),
            }
        )
        runtime["cognitionProgress"] = cognitionProgress
        self.database.updateExperiment(
            experimentId,
            sessionId,
            cognition_fallback_requested=1,
            runtime_json=runtime,
        )
        self.database.appendAuditEvent(
            sessionId,
            "EXPERIMENT",
            experimentId,
            "COGNITION_RULE_CONTINUATION_REQUESTED",
            {
                "attemptedCalls": int(cognitionProgress.get("attemptedCalls", 0)),
                "completedCalls": int(cognitionProgress.get("completedCalls", 0)),
                "preserveValidatedSignals": True,
            },
        )
        return self.publicExperiment(self.getExperiment(experimentId, sessionId))

    def getResults(self, experimentId: str, sessionId: str) -> dict[str, Any]:
        experiment = self._completedExperiment(experimentId, sessionId)
        return experiment["result"]

    def getRuns(self, experimentId: str, sessionId: str) -> dict[str, Any]:
        experiment = self._completedExperiment(experimentId, sessionId)
        pairedRuns = experiment["result"]["pairedRuns"]
        return {
            "schemaVersion": "1.0.0",
            "experimentId": experimentId,
            "status": "COMPLETED",
            "validForResearchUse": True,
            "count": len(pairedRuns),
            "pairedRuns": pairedRuns,
        }

    def getMetrics(self, experimentId: str, sessionId: str) -> dict[str, Any]:
        experiment = self._completedExperiment(experimentId, sessionId)
        result = experiment["result"]
        return {
            "schemaVersion": "1.0.0",
            "experimentId": experimentId,
            "status": "COMPLETED",
            "validForResearchUse": True,
            "metricSummaries": result["metricSummaries"],
            "medianPaths": result["medianPaths"],
            "analysisDiagnostics": result["analysisDiagnostics"],
            "stoppingRule": result["stoppingRule"],
            "manifest": result["manifest"],
        }

    def getTraces(self, experimentId: str, sessionId: str) -> dict[str, Any]:
        experiment = self._completedExperiment(experimentId, sessionId)
        traces = experiment["result"]["traces"]
        return {
            "schemaVersion": "1.0.0",
            "experimentId": experimentId,
            "status": "COMPLETED",
            "validForResearchUse": True,
            "count": len(traces),
            "traces": traces,
        }

    def invalidateExperiment(
        self,
        experimentId: str,
        sessionId: str,
        *,
        reasonCode: str,
        reason: str,
    ) -> dict[str, Any]:
        experiment = self.getExperiment(experimentId, sessionId)
        if experiment["status"] == "INVALIDATED":
            return self.publicExperiment(experiment)
        if experiment["status"] != "COMPLETED" or experiment["result"] is None:
            raise ApiError(
                "EXPERIMENT_NOT_INVALIDATABLE",
                409,
                "Only a completed experiment with persisted results can be invalidated.",
            )
        resultHash = _hashJson(experiment["result"])
        manifest = experiment["result"].get("manifest", {})
        if not self.database.invalidateCompletedExperiment(
            experimentId,
            sessionId,
            reasonCode=reasonCode,
            reason=reason,
        ):
            latestExperiment = self.getExperiment(experimentId, sessionId)
            if latestExperiment["status"] == "INVALIDATED":
                return self.publicExperiment(latestExperiment)
            raise ApiError(
                "EXPERIMENT_INVALIDATION_CONFLICT",
                409,
                "Another request changed the experiment before it could be invalidated.",
            )
        self.database.appendAuditEvent(
            sessionId,
            "EXPERIMENT",
            experimentId,
            "EXPERIMENT_INVALIDATED",
            {
                "previousStatus": "COMPLETED",
                "reasonCode": reasonCode,
                "reason": reason,
                "resultHash": resultHash,
                "eventPackHash": manifest.get("eventPackHash"),
                "engineVersion": manifest.get("engineVersion"),
                "llmModel": manifest.get("llmModel"),
                "promptVersion": manifest.get("promptVersion"),
            },
        )
        return self.publicExperiment(self.getExperiment(experimentId, sessionId))

    def exportExperiment(self, experimentId: str, sessionId: str) -> bytes:
        experiment = self._completedExperiment(experimentId, sessionId)
        exportBytes = _buildExport(experiment)
        self.database.appendAuditEvent(
            sessionId,
            "EXPERIMENT",
            experimentId,
            "EXPORT_CREATED",
            {
                "contentHash": hashlib.sha256(exportBytes).hexdigest(),
                "byteLength": len(exportBytes),
            },
        )
        return exportBytes

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def getRuntimeMetrics(self) -> dict[str, Any]:
        return {
            "workerConcurrency": 1,
            "activeOrQueued": self._activeFutureCount(),
            "maximumActiveOrQueued": MAX_QUEUED_EXPERIMENTS,
            "maximumExperimentsPerSession": MAX_EXPERIMENTS_PER_SESSION,
        }

    def publicExperiment(self, experiment: dict[str, Any]) -> dict[str, Any]:
        public = {
            key: value
            for key, value in experiment.items()
            if key
            not in {
                "sessionId",
                "result",
                "cancelRequested",
                "checkpoint",
                "checkpointCorrupted",
            }
        }
        public.update(
            {
                "resultsAvailable": experiment["status"] == "COMPLETED",
                "resultsPreserved": bool(
                    experiment["status"] == "INVALIDATED" and experiment["result"] is not None
                ),
                "validForResearchUse": experiment["status"] == "COMPLETED",
            }
        )
        return public

    def _completedExperiment(self, experimentId: str, sessionId: str) -> dict[str, Any]:
        experiment = self.getExperiment(experimentId, sessionId)
        if experiment["status"] == "INVALIDATED":
            raise ApiError(
                "EXPERIMENT_INVALIDATED",
                409,
                "The experiment was invalidated and cannot be used or exported as valid research.",
            )
        if experiment["status"] != "COMPLETED" or experiment["result"] is None:
            raise ApiError("RESULTS_NOT_READY", 409, "Experiment results are not ready.")
        return experiment

    def _runExperiment(
        self,
        experimentId: str,
        sessionId: str,
        credentialSessionId: str,
    ) -> None:
        runtime: dict[str, Any] = {}
        try:
            experiment = self.getExperiment(experimentId, sessionId)
            requestData = experiment["request"]
            eventPack = self.eventPacks.getEventPack(requestData["eventPackId"], sessionId)
            seeds = [
                requestData["seedRoot"] + index * 1_009 for index in range(requestData["seedCount"])
            ]
            requestHash = _hashJson(requestData)
            eventPackHash = _hashJson(eventPack)
            seedListHash = _hashJson(seeds)
            restored = self._restoreExperimentCheckpoint(
                experiment,
                requestHash=requestHash,
                eventPackHash=eventPackHash,
                seedListHash=seedListHash,
                seeds=seeds,
            )
            runtime = copy.deepcopy(experiment.get("runtime") or {})
            if restored is not None:
                baselineRuns = restored["baselineRuns"]
                interventionRuns = restored["interventionRuns"]
                cognitionRun = restored["cognitionRun"]
                stoppingDecision = restored["stoppingDecision"]
                completedPairs = len(baselineRuns)
                runtime.update(
                    {
                        "phase": "RUNNING",
                        "resumedFromCheckpoint": True,
                        "checkpointPairs": completedPairs,
                    }
                )
                self._appendRuntimeLog(
                    runtime,
                    "INFO",
                    f"Resumed from a verified checkpoint after {completedPairs} matched pairs.",
                    code="EXPERIMENT_RESUMED_FROM_CHECKPOINT",
                    parameters={"completedPairs": completedPairs},
                )
                self.database.updateExperiment(
                    experimentId,
                    sessionId,
                    status="RUNNING",
                    progress=0.04 + completedPairs / requestData["seedCount"] * 0.86,
                    completed_pairs=completedPairs,
                    runtime_json=runtime,
                    started_at=utcNow(),
                )
                self.database.appendAuditEvent(
                    sessionId,
                    "EXPERIMENT",
                    experimentId,
                    "RUN_RESUMED_FROM_CHECKPOINT",
                    {
                        "completedPairs": completedPairs,
                        "requestHash": requestHash,
                        "eventPackHash": eventPackHash,
                        "seedListHash": seedListHash,
                        "frozenSignalsHash": cognitionRun.get("frozenSignalsHash"),
                    },
                )
            else:
                if experiment.get("checkpointCorrupted"):
                    raise RuntimeError("the persisted experiment checkpoint is corrupt")
                if experiment.get("completedPairs", 0) > 0:
                    raise RuntimeError("completed pairs exist without a valid matching checkpoint")
                baselineRuns = []
                interventionRuns = []
                stoppingDecision = self._initialStoppingDecision(requestData)
                runtime = {
                    "phase": "COGNITION",
                    "pairIndex": 0,
                    "currentSeed": None,
                    "lastCompletedSeed": runtime.get("lastCompletedSeed"),
                    "baseline": None,
                    "intervention": None,
                    "resumedFromCheckpoint": False,
                    "checkpointPairs": 0,
                    "logs": list(runtime.get("logs", [])),
                }
                self._appendRuntimeLog(
                    runtime,
                    "INFO",
                    "Preparing deterministic rule or frozen hybrid cognition signals.",
                    code="COGNITION_PREPARATION_STARTED",
                )
                self.database.updateExperiment(
                    experimentId,
                    sessionId,
                    status="RUNNING",
                    progress=0.0,
                    completed_pairs=0,
                    runtime_json=runtime,
                    started_at=utcNow(),
                )

                def persistCognitionProgress(progressState: dict[str, Any]) -> None:
                    runtime["phase"] = "COGNITION"
                    runtime["cognitionProgress"] = copy.deepcopy(progressState)
                    plannedCalls = max(0, int(progressState.get("plannedCalls", 0)))
                    completedCalls = max(0, int(progressState.get("completedCalls", 0)))
                    cognitionFraction = completedCalls / plannedCalls if plannedCalls > 0 else 0.0
                    self.database.updateExperiment(
                        experimentId,
                        sessionId,
                        progress=min(0.035, cognitionFraction * 0.035),
                        runtime_json=runtime,
                    )

                cognitionRun = self._prepareCognitiveSignals(
                    experimentId,
                    credentialSessionId,
                    requestData,
                    eventPack,
                    progressCallback=persistCognitionProgress,
                    ruleContinuationRequested=lambda: self.database.cognitionFallbackRequested(
                        experimentId, sessionId
                    ),
                )
                runtime["cognitionProgress"] = {
                    **copy.deepcopy(runtime.get("cognitionProgress") or {}),
                    "status": (
                        "COMPLETED_WITH_RULE_CONTINUATION"
                        if cognitionRun.get("userRequestedRuleContinuation")
                        else "COMPLETED"
                    ),
                    "plannedCalls": int(cognitionRun.get("plannedCalls", 0)),
                    "attemptedCalls": int(cognitionRun.get("attemptedCalls", 0)),
                    "completedCalls": int(cognitionRun.get("calls", 0)),
                    "fallbackCount": int(cognitionRun.get("fallbackCount", 0)),
                    "totalTokens": int(cognitionRun.get("totalTokens", 0)),
                    "structuredValidCalls": int(cognitionRun.get("structuredValidCalls", 0)),
                    "structuredSuccessRate": float(cognitionRun.get("structuredSuccessRate", 0.0)),
                    "structuredSuccessThreshold": float(
                        cognitionRun.get("structuredSuccessThreshold", 0.95)
                    ),
                    "structuredSuccessGateStatus": cognitionRun.get(
                        "structuredSuccessGateStatus",
                        "NOT_EVALUATED",
                    ),
                    "failureCategoryCounts": copy.deepcopy(
                        cognitionRun.get("failureCategoryCounts", {})
                    ),
                    "currentCostUsd": float(
                        cognitionRun.get("costBudget", {}).get(
                            "chargedUsdUpperBound",
                            0.0,
                        )
                    ),
                    "activeReservationUsd": float(
                        cognitionRun.get("costBudget", {}).get(
                            "activeReservationUsd",
                            0.0,
                        )
                    ),
                    "resolvedMode": cognitionRun.get("resolvedMode"),
                    "failureCode": cognitionRun.get("failureCode"),
                    "userRequestedRuleContinuation": bool(
                        cognitionRun.get("userRequestedRuleContinuation")
                    ),
                }
                self._appendRuntimeLog(
                    runtime,
                    "INFO",
                    "Cognition preparation completed.",
                    code="COGNITION_PREPARATION_COMPLETED",
                    parameters={
                        "resolvedMode": cognitionRun.get("resolvedMode"),
                        "attemptedCalls": int(cognitionRun.get("attemptedCalls", 0)),
                        "completedCalls": int(cognitionRun.get("calls", 0)),
                        "fallbackCount": int(cognitionRun.get("fallbackCount", 0)),
                        "userRequestedRuleContinuation": bool(
                            cognitionRun.get("userRequestedRuleContinuation")
                        ),
                    },
                )
                self.database.updateExperiment(
                    experimentId,
                    sessionId,
                    progress=0.04,
                    runtime_json=runtime,
                    checkpoint_blob=self._checkpointPayload(
                        requestHash=requestHash,
                        eventPackHash=eventPackHash,
                        seedListHash=seedListHash,
                        baselineRuns=baselineRuns,
                        interventionRuns=interventionRuns,
                        cognitionRun=cognitionRun,
                        stoppingDecision=stoppingDecision,
                    ),
                )
                self.database.appendAuditEvent(
                    sessionId,
                    "EXPERIMENT",
                    experimentId,
                    "MODEL_ROUTE_RESOLVED",
                    {key: value for key, value in cognitionRun.items() if key not in {"signals"}},
                )

            cancelPollCount = 0
            cancellationCached = False

            def shouldCancel() -> bool:
                nonlocal cancelPollCount, cancellationCached
                if cancellationCached:
                    return True
                cancelPollCount += 1
                # SQLite 是控制面而非逐事件队列；每 8 个仿真步轮询一次即可保持响应性。
                if cancelPollCount % 8 == 1:
                    cancellationCached = self.database.cancelRequested(experimentId, sessionId)
                return cancellationCached

            startIndex = len(baselineRuns)
            runIndexes = () if stoppingDecision.get("triggered") else range(startIndex, len(seeds))
            for index in runIndexes:
                seed = seeds[index]
                if self.database.cancelRequested(experimentId, sessionId):
                    self._finishCancelledRun(
                        experimentId,
                        sessionId,
                        runtime,
                        completedPairs=len(baselineRuns),
                        during="between-pairs",
                    )
                    return
                runtime.update(
                    {
                        "phase": "BASELINE",
                        "pairIndex": index + 1,
                        "currentSeed": seed,
                        "baseline": None,
                        "intervention": None,
                    }
                )
                self._appendRuntimeLog(
                    runtime,
                    "INFO",
                    f"Baseline path started for matched pair {index + 1}.",
                    seed=seed,
                    code="BASELINE_PATH_STARTED",
                    parameters={"pairIndex": index + 1},
                )
                self.database.updateExperiment(experimentId, sessionId, runtime_json=runtime)
                commonArguments = {
                    "seed": seed,
                    "populationSize": requestData["populationSize"],
                    "steps": requestData["steps"],
                    "parameter": requestData["intervention"]["parameter"],
                    "eventPack": eventPack,
                    "shouldCancel": shouldCancel,
                    "cognitiveSignals": cognitionRun["signals"],
                    "scenarioConfig": requestData,
                }
                baselineRun = runScenario(
                    **commonArguments,
                    value=requestData["intervention"]["baselineValue"],
                    onProgress=self._liveProgressCallback(
                        experimentId,
                        sessionId,
                        runtime,
                        arm="baseline",
                        completedPairs=len(baselineRuns),
                        totalPairs=requestData["seedCount"],
                    ),
                )
                if baselineRun["cancelled"]:
                    self._finishCancelledRun(
                        experimentId,
                        sessionId,
                        runtime,
                        completedPairs=len(baselineRuns),
                        during="baseline",
                    )
                    return
                runtime["phase"] = "INTERVENTION"
                self._appendRuntimeLog(
                    runtime,
                    "INFO",
                    f"Intervention path started for matched pair {index + 1}.",
                    seed=seed,
                    code="INTERVENTION_PATH_STARTED",
                    parameters={"pairIndex": index + 1},
                )
                self.database.updateExperiment(experimentId, sessionId, runtime_json=runtime)
                interventionRun = runScenario(
                    **commonArguments,
                    value=requestData["intervention"]["interventionValue"],
                    onProgress=self._liveProgressCallback(
                        experimentId,
                        sessionId,
                        runtime,
                        arm="intervention",
                        completedPairs=len(baselineRuns),
                        totalPairs=requestData["seedCount"],
                    ),
                )
                if interventionRun["cancelled"]:
                    self._finishCancelledRun(
                        experimentId,
                        sessionId,
                        runtime,
                        completedPairs=len(baselineRuns),
                        during="intervention",
                    )
                    return
                baselineRuns.append(baselineRun)
                interventionRuns.append(interventionRun)
                stoppingDecision = _stoppingDecision(
                    requestData,
                    baselineRuns,
                    interventionRuns,
                    previous=stoppingDecision,
                )
                runtime["checkpointPairs"] = len(baselineRuns)
                runtime["lastCompletedSeed"] = seed
                self._appendRuntimeLog(
                    runtime,
                    "INFO",
                    f"Matched pair {index + 1} completed and checkpointed.",
                    seed=seed,
                    code="MATCHED_PAIR_COMPLETED",
                    parameters={"pairIndex": index + 1},
                )
                self.database.updateExperiment(
                    experimentId,
                    sessionId,
                    progress=0.04 + len(baselineRuns) / requestData["seedCount"] * 0.86,
                    completed_pairs=len(baselineRuns),
                    runtime_json=runtime,
                    checkpoint_blob=self._checkpointPayload(
                        requestHash=requestHash,
                        eventPackHash=eventPackHash,
                        seedListHash=seedListHash,
                        baselineRuns=baselineRuns,
                        interventionRuns=interventionRuns,
                        cognitionRun=cognitionRun,
                        stoppingDecision=stoppingDecision,
                    ),
                )
                if stoppingDecision["triggered"]:
                    self.database.appendAuditEvent(
                        sessionId,
                        "EXPERIMENT",
                        experimentId,
                        "STOPPING_RULE_TRIGGERED",
                        stoppingDecision,
                    )
                    break

            runtime["phase"] = "AGGREGATING"
            self._appendRuntimeLog(
                runtime,
                "INFO",
                "Aggregating paired distributions, uncertainty, traces, and diagnostics.",
                code="RESULT_AGGREGATION_STARTED",
            )
            self.database.updateExperiment(
                experimentId,
                sessionId,
                status="AGGREGATING",
                progress=0.94,
                runtime_json=runtime,
            )
            aggregate = aggregatePairedResults(baselineRuns, interventionRuns)
            usedSeeds = seeds[: len(baselineRuns)]
            result = self._buildResult(
                experimentId,
                requestData,
                eventPack,
                usedSeeds,
                aggregate,
                cognitionRun,
                stoppingDecision,
            )
            runtime["phase"] = "COMPLETED"
            runtime["currentSeed"] = None
            self._appendRuntimeLog(
                runtime,
                "INFO",
                f"Experiment completed with {len(baselineRuns)} valid matched pairs.",
                code="EXPERIMENT_COMPLETED",
                parameters={"completedPairs": len(baselineRuns)},
            )
            self.database.updateExperiment(
                experimentId,
                sessionId,
                status="COMPLETED",
                result_json=result,
                progress=1.0,
                completed_pairs=len(baselineRuns),
                completed_at=utcNow(),
                runtime_json=runtime,
                checkpoint_blob=None,
            )
            self.database.appendAuditEvent(
                sessionId,
                "EXPERIMENT",
                experimentId,
                "RUN_COMPLETED",
                {
                    "validPairedSeeds": len(aggregate["pairedRuns"]),
                    "stoppingReason": stoppingDecision["reason"],
                    "manifestHash": _hashJson(result["manifest"]),
                },
            )
        except _ModelCredentialStorageUnavailableError:
            LOGGER.exception(
                "Experiment %s could not access the configured model credential",
                experimentId,
            )
            runtime["phase"] = "FAILED_RETRYABLE"
            self._appendRuntimeLog(
                runtime,
                "ERROR",
                (
                    "The encrypted model credential is unavailable. Re-save the "
                    "administrator credential and retry the experiment."
                ),
                code="LLM_CREDENTIAL_STORAGE_UNAVAILABLE",
            )
            self.database.updateExperiment(
                experimentId,
                sessionId,
                status="FAILED_RETRYABLE",
                error_code="LLM_CREDENTIAL_STORAGE_UNAVAILABLE",
                completed_at=utcNow(),
                runtime_json=runtime,
            )
            self.database.appendAuditEvent(
                sessionId,
                "EXPERIMENT",
                experimentId,
                "RUN_FAILED_RETRYABLE",
                {"errorCode": "LLM_CREDENTIAL_STORAGE_UNAVAILABLE"},
            )
        except Exception:
            LOGGER.exception("Experiment %s failed", experimentId)
            runtime["phase"] = "FAILED_FINAL"
            self._appendRuntimeLog(
                runtime,
                "ERROR",
                (
                    "The experiment stopped because a deterministic runtime or checkpoint "
                    "invariant failed."
                ),
                code="EXPERIMENT_FAILED",
            )
            self.database.updateExperiment(
                experimentId,
                sessionId,
                status="FAILED_FINAL",
                error_code="SIMULATION_FAILED",
                completed_at=utcNow(),
                runtime_json=runtime,
            )
            self.database.appendAuditEvent(
                sessionId,
                "EXPERIMENT",
                experimentId,
                "RUN_FAILED",
                {"errorCode": "SIMULATION_FAILED"},
            )

    @staticmethod
    def _initialStoppingDecision(requestData: dict[str, Any]) -> dict[str, Any]:
        stoppingRule = requestData["stoppingRule"]
        hasTarget = stoppingRule.get("targetCiHalfWidth") is not None
        conditionCodes = [
            "MINIMUM_PAIRS_REACHED",
            "MAXIMUM_PAIRS_REACHED" if hasTarget else "FIXED_PAIR_COUNT_REACHED",
        ]
        if hasTarget:
            conditionCodes.append("TARGET_CI_HALF_WIDTH_REACHED")
        return {
            "mode": ("TARGET_CI_HALF_WIDTH" if hasTarget else "FIXED_PAIR_COUNT"),
            "triggered": False,
            "reason": "MAXIMUM_PAIRS_REACHED",
            "primaryReason": "MAXIMUM_PAIRS_REACHED",
            "reasons": [],
            "primaryOutcome": requestData["primaryOutcome"],
            "minimumPairs": stoppingRule["minimumPairs"],
            "maximumPairs": requestData["seedCount"],
            "targetCiHalfWidth": stoppingRule.get("targetCiHalfWidth"),
            "observedCiHalfWidth": None,
            "bootstrapInterval95": None,
            "completedPairs": 0,
            "conditionEvaluations": [
                {
                    "code": code,
                    "evaluationOrder": index,
                    "satisfied": False,
                    "firstSatisfiedAtPair": None,
                }
                for index, code in enumerate(conditionCodes, start=1)
            ],
        }

    @staticmethod
    def _checkpointPayload(
        *,
        requestHash: str,
        eventPackHash: str,
        seedListHash: str,
        baselineRuns: list[dict[str, Any]],
        interventionRuns: list[dict[str, Any]],
        cognitionRun: dict[str, Any],
        stoppingDecision: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schemaVersion": EXPERIMENT_CHECKPOINT_SCHEMA_VERSION,
            "requestHash": requestHash,
            "eventPackHash": eventPackHash,
            "seedListHash": seedListHash,
            "completedPairs": len(baselineRuns),
            "baselineRuns": baselineRuns,
            "interventionRuns": interventionRuns,
            "cognitionRun": cognitionRun,
            "stoppingDecision": stoppingDecision,
            "writtenAt": utcNow(),
        }

    @staticmethod
    def _restoreExperimentCheckpoint(
        experiment: dict[str, Any],
        *,
        requestHash: str,
        eventPackHash: str,
        seedListHash: str,
        seeds: list[int],
    ) -> dict[str, Any] | None:
        checkpoint = experiment.get("checkpoint")
        if not isinstance(checkpoint, dict):
            return None
        if (
            checkpoint.get("schemaVersion") != EXPERIMENT_CHECKPOINT_SCHEMA_VERSION
            or checkpoint.get("requestHash") != requestHash
            or checkpoint.get("eventPackHash") != eventPackHash
            or checkpoint.get("seedListHash") != seedListHash
        ):
            return None
        baselineRuns = checkpoint.get("baselineRuns")
        interventionRuns = checkpoint.get("interventionRuns")
        cognitionRun = checkpoint.get("cognitionRun")
        stoppingDecision = checkpoint.get("stoppingDecision")
        if (
            not isinstance(baselineRuns, list)
            or not isinstance(interventionRuns, list)
            or len(baselineRuns) != len(interventionRuns)
            or len(baselineRuns) > len(seeds)
            or not isinstance(cognitionRun, dict)
            or not isinstance(cognitionRun.get("signals"), list)
            or not isinstance(stoppingDecision, dict)
        ):
            return None
        expectedSeeds = seeds[: len(baselineRuns)]
        if [run.get("seed") for run in baselineRuns] != expectedSeeds:
            return None
        if [run.get("seed") for run in interventionRuns] != expectedSeeds:
            return None
        return {
            "baselineRuns": baselineRuns,
            "interventionRuns": interventionRuns,
            "cognitionRun": cognitionRun,
            "stoppingDecision": stoppingDecision,
        }

    def _liveProgressCallback(
        self,
        experimentId: str,
        sessionId: str,
        runtime: dict[str, Any],
        *,
        arm: str,
        completedPairs: int,
        totalPairs: int,
    ) -> Callable[[dict[str, Any]], None]:
        def persist(snapshot: dict[str, Any]) -> None:
            runtime[arm] = snapshot
            runtime["phase"] = arm.upper()
            interval = max(1, int(snapshot["totalSteps"]) // 4)
            if int(snapshot["completedSteps"]) % interval != 0 and int(
                snapshot["completedSteps"]
            ) != int(snapshot["totalSteps"]):
                return
            armOffset = 0.0 if arm == "baseline" else 0.5
            withinArm = int(snapshot["completedSteps"]) / max(int(snapshot["totalSteps"]), 1)
            pairedProgress = completedPairs + armOffset + withinArm * 0.5
            self.database.updateExperiment(
                experimentId,
                sessionId,
                progress=min(0.9, 0.04 + pairedProgress / max(totalPairs, 1) * 0.86),
                runtime_json=runtime,
            )

        return persist

    def _finishCancelledRun(
        self,
        experimentId: str,
        sessionId: str,
        runtime: dict[str, Any],
        *,
        completedPairs: int,
        during: str,
    ) -> None:
        runtime["phase"] = "CANCELLED"
        self._appendRuntimeLog(
            runtime,
            "WARNING",
            f"Cancellation was applied during {during}.",
            seed=runtime.get("currentSeed"),
            code="EXPERIMENT_CANCELLED",
            parameters={"during": during},
        )
        self.database.updateExperiment(
            experimentId,
            sessionId,
            status="CANCELLED",
            completed_pairs=completedPairs,
            completed_at=utcNow(),
            runtime_json=runtime,
            checkpoint_blob=None,
        )
        self.database.appendAuditEvent(
            sessionId,
            "EXPERIMENT",
            experimentId,
            "RUN_CANCELLED",
            {"completedPairs": completedPairs, "during": during},
        )

    @staticmethod
    def _appendRuntimeLog(
        runtime: dict[str, Any],
        level: str,
        message: str,
        *,
        seed: int | None = None,
        code: str | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        logs = runtime.setdefault("logs", [])
        entry: dict[str, Any] = {
            "timestamp": utcNow(),
            "level": level,
            "message": message,
        }
        if seed is not None:
            entry["seed"] = seed
        if code is not None:
            entry["code"] = code
        if parameters:
            entry["parameters"] = copy.deepcopy(parameters)
        logs.append(entry)
        if len(logs) > MAX_RUNTIME_LOG_ENTRIES:
            del logs[: len(logs) - MAX_RUNTIME_LOG_ENTRIES]

    def _prepareCognitiveSignals(
        self,
        experimentId: str,
        credentialSessionId: str,
        requestData: dict[str, Any],
        eventPack: dict[str, Any],
        *,
        progressCallback: Callable[[dict[str, Any]], None] | None = None,
        ruleContinuationRequested: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        llmPolicy = requestData.get("llmPolicy", {})
        mode = llmPolicy.get("mode", "RULE_ONLY")
        hybridRequested = mode == "HYBRID_LLM"
        fallbackAllowed = bool(llmPolicy.get("fallbackToRules", True))
        costBudget = ModelCostBudget(float(llmPolicy.get("maxCostUsd", 10.0)))
        policyProvider = str(llmPolicy.get("provider", "zhipu"))
        policyModel = str(llmPolicy.get("modelId", "glm-5.2"))
        baseMetadata = {
            "requestedMode": mode,
            "resolvedMode": "RULE_ONLY",
            "externalModelUsed": False,
            "provider": None,
            "requestedProvider": policyProvider if hybridRequested else None,
            "requestedModel": policyModel if hybridRequested else None,
            "resolvedModel": None,
            "configuredButUnusedProvider": None,
            "configuredButUnusedModel": None,
            "promptVersion": "belief_v1.0.0",
            "promptSchemaVersion": "belief_decision_v1.0.0",
            "calls": 0,
            "totalTokens": 0,
            "fallbackCount": 0,
            "fallbackReasons": [],
            "signals": [],
            "failureCode": None,
            "promptTokens": 0,
            "completionTokens": 0,
            "cachedTokens": 0,
            "costControl": "PRE_DISPATCH_RESERVATION_AND_POST_RESPONSE_TOKEN_SETTLEMENT",
            "providerPriceEstimateAvailable": False,
            "costBudget": costBudget.snapshot(),
            "decisionScheduleMode": "NONE",
            "plannedCalls": 0,
            "attemptedCalls": 0,
            "structuredValidCalls": 0,
            "structuredSuccessRate": 0.0,
            "structuredSuccessThreshold": 0.95,
            "structuredSuccessGateStatus": "NOT_EVALUATED",
            "failureCategoryCounts": {},
        }

        def reportProgress(
            status: str,
            *,
            plannedCalls: int = 0,
            attemptedCalls: int = 0,
            completedCalls: int = 0,
            fallbackCount: int = 0,
            totalTokens: int = 0,
            structuredValidCalls: int = 0,
            failureCategoryCounts: dict[str, int] | None = None,
            decisionRound: int | None = None,
            representativeIndex: int | None = None,
            failureCode: str | None = None,
            modelStage: str | None = None,
            streamChunkCount: int = 0,
            answerChunkCount: int = 0,
            reasoningChunkCount: int = 0,
            repairAttempted: bool = False,
        ) -> None:
            if progressCallback is None:
                return
            budgetSnapshot = costBudget.snapshot()
            progressCallback(
                {
                    "status": status,
                    "plannedCalls": plannedCalls,
                    "attemptedCalls": attemptedCalls,
                    "completedCalls": completedCalls,
                    "fallbackCount": fallbackCount,
                    "totalTokens": totalTokens,
                    "structuredValidCalls": structuredValidCalls,
                    "structuredSuccessRate": (
                        structuredValidCalls / attemptedCalls if attemptedCalls else 0.0
                    ),
                    "structuredSuccessThreshold": 0.95,
                    "failureCategoryCounts": dict(sorted((failureCategoryCounts or {}).items())),
                    "currentCostUsd": float(budgetSnapshot["chargedUsdUpperBound"])
                    + float(budgetSnapshot["activeReservationUsd"]),
                    "settledCostUsd": float(budgetSnapshot["chargedUsdUpperBound"]),
                    "activeReservationUsd": float(budgetSnapshot["activeReservationUsd"]),
                    "decisionRound": decisionRound,
                    "representativeIndex": representativeIndex,
                    "failureCode": failureCode,
                    "modelStage": modelStage,
                    "streamChunkCount": streamChunkCount,
                    "answerChunkCount": answerChunkCount,
                    "reasoningChunkCount": reasoningChunkCount,
                    "repairAttempted": repairAttempted,
                    "updatedAt": utcNow(),
                }
            )

        if not hybridRequested:
            reportProgress("NOT_APPLICABLE")
            # 纯规则实验不得读取或解密任何供应商凭据。除了缩小明文暴露面，
            # 这也保证主密钥轮换或密文损坏不会使本来不需要 LLM 的实验失败。
            return baseMetadata
        try:
            runtimeConfig = (
                self.cognition.getConfig(credentialSessionId)
                if self.cognition is not None
                else None
            )
        except PersistentCredentialUnavailableError as error:
            if not fallbackAllowed:
                raise _ModelCredentialStorageUnavailableError(
                    "encrypted model credential storage is unavailable"
                ) from error
            return {
                **baseMetadata,
                "resolvedMode": "RULE_FALLBACK",
                "failureCode": "LLM_CREDENTIAL_STORAGE_UNAVAILABLE",
            }
        if runtimeConfig is None or not runtimeConfig.configured:
            if not fallbackAllowed:
                raise RuntimeError("hybrid LLM mode requires a configured session credential")
            return {
                **baseMetadata,
                "resolvedMode": "RULE_FALLBACK",
                "failureCode": "LLM_CREDENTIAL_NOT_CONFIGURED",
            }
        requestedProvider = policyProvider
        requestedModel = policyModel
        configuredProvider = str(getattr(runtimeConfig, "provider", "zhipu"))
        configuredModel = str(getattr(runtimeConfig, "model", requestedModel))
        if configuredProvider != requestedProvider or configuredModel != requestedModel:
            if not fallbackAllowed:
                raise RuntimeError(
                    "hybrid LLM scenario provider/model does not match the session credential"
                )
            return {
                **baseMetadata,
                "resolvedMode": "RULE_FALLBACK",
                "failureCode": "LLM_PROVIDER_MODEL_CONFIG_MISMATCH",
                "configuredButUnusedProvider": configuredProvider,
                "configuredButUnusedModel": configuredModel,
            }

        asOf = _parseUtc(eventPack.get("asOf"))
        if not self._approvedEvidence(eventPack, asOf):
            if not fallbackAllowed:
                raise RuntimeError("hybrid LLM mode requires at least one approved evidence item")
            return {
                **baseMetadata,
                "resolvedMode": "RULE_FALLBACK",
                "failureCode": "NO_APPROVED_EVIDENCE",
            }

        requestedCount = int(llmPolicy.get("representativeAgentCount", 8))
        callBudget = int(llmPolicy.get("callBudget", 24))
        try:
            tokenPrice = getTokenPrice(requestedProvider, requestedModel)
        except ValueError:
            tokenPrice = None
        if tokenPrice is None:
            if not fallbackAllowed:
                raise RuntimeError("hybrid LLM mode has no verified provider price")
            return {
                **baseMetadata,
                "resolvedMode": "RULE_FALLBACK",
                "failureCode": "MODEL_PRICING_UNAVAILABLE",
                "costBudget": costBudget.snapshot(),
            }
        baseMetadata["providerPriceEstimateAvailable"] = True
        representativeCount = max(
            0,
            min(
                requestedCount,
                int(requestData.get("population", {}).get("representativeLlmAgents", 8)),
                max(0, int(requestData.get("populationSize", 56)) - 1),
            ),
        )
        decisionInterval = int(llmPolicy.get("decisionIntervalSteps", 12))
        decisionRounds = math.ceil(int(requestData.get("steps", 120)) / decisionInterval)
        plannedCalls = min(callBudget, representativeCount * decisionRounds)
        reportProgress("INITIALIZING_PILOT", plannedCalls=plannedCalls)
        if representativeCount == 0 or plannedCalls == 0:
            return {
                **baseMetadata,
                "resolvedMode": "HYBRID_NO_REPRESENTATIVE_AGENTS",
                "decisionScheduleMode": "NO_MODEL_CALLS_REQUESTED",
                "plannedCalls": plannedCalls,
            }
        scenarioMarket = requestData.get("market", {})
        eventInstrument = eventPack.get("instrument", {})
        initialPrice = scenarioMarket.get("initialPrice")
        if not isinstance(initialPrice, (int, float)) and isinstance(eventInstrument, dict):
            initialPrice = eventInstrument.get("initialPrice", 135.0)
        if not isinstance(initialPrice, (int, float)):
            initialPrice = 135.0
        initialTicks = max(1, round(float(initialPrice) * PRICE_SCALE))
        tickSize = scenarioMarket.get("tickSize", 0.01)
        if not isinstance(tickSize, (int, float)):
            tickSize = 0.01
        tickSizeTicks = max(1, round(float(tickSize) * PRICE_SCALE))
        roles = (
            "event_risk_analyst",
            "momentum_trader",
            "value_investor",
            "market_maker",
            "passive_executor",
            "risk_controller",
            "institutional_trader",
            "deleveraging_trader",
        )
        pilotSeed = int(requestData.get("seedRoot", 2_026_070_700))
        pilotIdentity = _hashJson(
            {
                "request": requestData,
                "eventPackHash": _hashJson(eventPack),
                "pilotSeed": pilotSeed,
                "pilotArm": "BASELINE_REFERENCE",
            }
        )[:20]
        pilotBoundary = {
            "arm": "BASELINE_REFERENCE_ONLY",
            "initialRun": "RULE_ONLY",
            "marketObservationSource": "DETERMINISTIC_AGGREGATE_PATHS",
            "feedbackPath": "BELIEF_SIGNAL_TO_FIXED_ORDER_POLICY_TO_PILOT_MARKET",
            "llmMaySetPriceOrRawOrder": False,
            "modelGeneratedMessagesAreEvidence": False,
            "seedSpecificMatchedArmFeedback": False,
            "reuse": "ONE_FROZEN_SEQUENCE_FOR_BASELINE_INTERVENTION_AND_ALL_MATCHED_SEEDS",
        }
        signals: list[dict[str, Any]] = []
        totalTokens = 0
        promptTokens = 0
        completionTokens = 0
        cachedTokens = 0
        fallbackCount = 0
        fallbackReasons: list[str] = []
        resolvedModel: str | None = None
        failureCode: str | None = None
        attemptedCalls = 0
        completedCalls = 0
        structuredValidCalls = 0
        failureCategoryCounts: dict[str, int] = {}
        repeatedFailureCounts: dict[str, int] = {}
        userRequestedRuleContinuation = False
        try:
            currentPilot = self._runCognitionPilot(
                requestData=requestData,
                eventPack=eventPack,
                pilotSeed=pilotSeed,
                signals=(),
            )
            pilotIterations = [
                self._pilotIterationRecord(
                    currentPilot,
                    iterationIndex=0,
                    completedDecisionRound=None,
                    signalCount=0,
                )
            ]
            reportProgress("PILOT_READY", plannedCalls=plannedCalls)
        except Exception as error:
            # pilot 是模型与正式配对实验之间的安全边界；无法验证时绝不让模型信号进入市场。
            LOGGER.exception("Closed-loop cognition pilot initialization failed")
            if not fallbackAllowed:
                raise RuntimeError(
                    "closed-loop cognition pilot initialization failed while fallback was disabled"
                ) from error
            reportProgress(
                "FAILED_CLOSED",
                plannedCalls=plannedCalls,
                failureCode="CLOSED_LOOP_PILOT_FAILED",
            )
            return {
                **baseMetadata,
                "resolvedMode": "RULE_FALLBACK",
                "failureCode": "CLOSED_LOOP_PILOT_FAILED",
                "decisionScheduleMode": COGNITION_PILOT_SCHEDULE_MODE,
                "plannedCalls": plannedCalls,
                "costBudget": costBudget.snapshot(),
                "pilot": {
                    "status": "FAILED_CLOSED",
                    "seed": pilotSeed,
                    "identity": pilotIdentity,
                    "hash": None,
                    "iterations": [],
                    "boundary": pilotBoundary,
                    "failureStage": "INITIAL_RULE_ONLY_PILOT",
                    "frozenSignalsHash": _cognitiveSignalSequenceHash(()),
                },
            }

        callsRemaining = plannedCalls
        instrumentId = (
            eventPack.get("instrument", {}).get("id", scenarioMarket.get("instrumentId", "SPCX"))
            if isinstance(eventPack.get("instrument"), dict)
            else str(eventPack.get("instrument", scenarioMarket.get("instrumentId", "SPCX")))
        )
        pilotFailed = False
        for decisionRound in range(decisionRounds):
            callsThisRound = min(representativeCount, callsRemaining)
            if callsThisRound <= 0:
                break
            activeFromStep = decisionRound * decisionInterval
            observationTime = asOf + timedelta(seconds=activeFromStep * SIMULATION_STEP_SECONDS)
            pilotPathsHash = _hashJson(currentPilot["paths"])
            roundStartSignalCount = len(signals)
            modelGeneratedSocial = self._modelGeneratedSocialFeed(
                signals,
                decisionRound=decisionRound,
                observationTime=observationTime,
            )
            humanReviewedSocial = self._socialFeed(eventPack, observationTime)
            boundedSocialFeed = tuple([*humanReviewedSocial, *modelGeneratedSocial][:24])

            for representativeIndex in range(callsThisRound):
                if ruleContinuationRequested is not None and ruleContinuationRequested():
                    userRequestedRuleContinuation = True
                    failureCode = "COGNITION_RULE_CONTINUATION_REQUESTED"
                    reportProgress(
                        "RULE_CONTINUATION_REQUESTED",
                        plannedCalls=plannedCalls,
                        attemptedCalls=attemptedCalls,
                        completedCalls=completedCalls,
                        fallbackCount=fallbackCount,
                        totalTokens=totalTokens,
                        structuredValidCalls=structuredValidCalls,
                        failureCategoryCounts=failureCategoryCounts,
                        decisionRound=decisionRound,
                        representativeIndex=representativeIndex,
                        failureCode=failureCode,
                    )
                    break
                agentId = f"llm-agent-{representativeIndex:03d}"
                priorSignals = [item for item in signals if item["agentId"] == agentId]
                memory = (
                    (
                        MemorySummary(
                            memory_id=(f"memory-{representativeIndex:03d}-{decisionRound - 1:03d}"),
                            summary=(
                                "Previous bounded decision: "
                                + str(priorSignals[-1]["decisionSummary"])
                            )[:500],
                            salience=float(priorSignals[-1]["confidence"]),
                        ),
                    )
                    if priorSignals
                    else ()
                )
                marketObservation = self._marketObservationFromPilot(
                    currentPilot,
                    step=activeFromStep,
                    instrumentId=str(instrumentId),
                    tickSizeTicks=tickSizeTicks,
                    fallbackTicks=initialTicks,
                )
                observation = Observation(
                    observation_id=(
                        f"obs-pilot-{pilotIdentity}-{representativeIndex:03d}-{decisionRound:03d}"
                    ),
                    now=observationTime,
                    agent=AgentProfile(
                        id=agentId,
                        role=roles[representativeIndex % len(roles)],
                        risk_tolerance=round(
                            0.25 + (representativeIndex % 5) * 0.12,
                            6,
                        ),
                        loss_aversion=round(
                            1.1 + (representativeIndex % 4) * 0.35,
                            6,
                        ),
                        horizon_minutes=30 + (representativeIndex % 6) * 60,
                        confirmation_bias=round(
                            0.1 + (representativeIndex % 4) * 0.15,
                            6,
                        ),
                        trust_profile=TrustProfile(official=0.95, news=0.72, social=0.28),
                    ),
                    portfolio=PortfolioObservation(
                        cash_cents=10_000_000,
                        position=(representativeIndex % 5 - 2) * 4,
                        unrealized_pnl_pct=max(
                            -10.0,
                            min(
                                10.0,
                                marketObservation.mid_price_ticks / initialTicks - 1,
                            ),
                        ),
                        max_position=100,
                    ),
                    market=marketObservation,
                    new_evidence=tuple(self._approvedEvidence(eventPack, observationTime)),
                    social_feed=boundedSocialFeed,
                    memory_summary=memory,
                    allowed_actions=tuple(ActionPreference),
                )
                attemptedCalls += 1
                reportProgress(
                    "MODEL_CALL_IN_PROGRESS",
                    plannedCalls=plannedCalls,
                    attemptedCalls=attemptedCalls,
                    completedCalls=completedCalls,
                    fallbackCount=fallbackCount,
                    totalTokens=totalTokens,
                    structuredValidCalls=structuredValidCalls,
                    failureCategoryCounts=failureCategoryCounts,
                    decisionRound=decisionRound,
                    representativeIndex=representativeIndex,
                )

                async def streamProgress(
                    progress: ModelStreamProgress,
                    attemptedCallsForProgress: int = attemptedCalls,
                    completedCallsForProgress: int = completedCalls,
                    fallbackCountForProgress: int = fallbackCount,
                    totalTokensForProgress: int = totalTokens,
                    structuredValidCallsForProgress: int = structuredValidCalls,
                    failureCategoriesForProgress: dict[str, int] = failureCategoryCounts,
                    decisionRoundForProgress: int = decisionRound,
                    representativeIndexForProgress: int = representativeIndex,
                ) -> None:
                    stageStatus = {
                        ModelStreamStage.PREPARING: "MODEL_REQUESTING",
                        ModelStreamStage.PLANNING: "MODEL_REQUESTING",
                        ModelStreamStage.READING_RESULTS: "MODEL_REQUESTING",
                        ModelStreamStage.GENERATING: "MODEL_STREAM_RECEIVING",
                        ModelStreamStage.REASONING: "MODEL_STREAM_RECEIVING",
                        ModelStreamStage.VALIDATING: "MODEL_VALIDATING",
                        ModelStreamStage.REPAIRING: "MODEL_REPAIRING",
                        ModelStreamStage.COMPLETED: "MODEL_VALIDATING",
                    }[progress.stage]
                    reportProgress(
                        stageStatus,
                        plannedCalls=plannedCalls,
                        attemptedCalls=attemptedCallsForProgress,
                        completedCalls=completedCallsForProgress,
                        fallbackCount=fallbackCountForProgress,
                        totalTokens=totalTokensForProgress,
                        structuredValidCalls=structuredValidCallsForProgress,
                        failureCategoryCounts=failureCategoriesForProgress,
                        decisionRound=decisionRoundForProgress,
                        representativeIndex=representativeIndexForProgress,
                        modelStage=progress.stage.value,
                        streamChunkCount=progress.chunkCount,
                        answerChunkCount=progress.answerChunkCount,
                        reasoningChunkCount=progress.reasoningChunkCount,
                        repairAttempted=progress.repair,
                    )

                try:
                    beliefArguments: dict[str, Any] = {
                        "sessionId": credentialSessionId,
                        "observation": observation,
                        "costBudget": costBudget,
                        "allowRuleFallback": fallbackAllowed,
                    }
                    if isinstance(self.cognition, CognitionService):
                        beliefArguments["progressObserver"] = streamProgress
                    run = asyncio.run(self.cognition.generateBeliefDecision(**beliefArguments))
                except (
                    CredentialNotConfiguredError,
                    ModelGatewayError,
                    PersistentCredentialUnavailableError,
                ) as error:
                    if not fallbackAllowed:
                        if isinstance(error, PersistentCredentialUnavailableError):
                            raise _ModelCredentialStorageUnavailableError(
                                "encrypted model credential storage is unavailable"
                            ) from error
                        raise RuntimeError("the configured cognitive model failed") from error
                    failureCode = (
                        "LLM_CREDENTIAL_STORAGE_UNAVAILABLE"
                        if isinstance(error, PersistentCredentialUnavailableError)
                        else (
                            error.code.value
                            if isinstance(error, ModelGatewayError)
                            else "LLM_CREDENTIAL_EXPIRED"
                        )
                    )
                    failureCategory = _cognitionFailureCategory(failureCode)
                    failureCategoryCounts[failureCategory] = (
                        failureCategoryCounts.get(failureCategory, 0) + 1
                    )
                    repeatedFailureCounts[failureCode] = (
                        repeatedFailureCounts.get(failureCode, 0) + 1
                    )
                    reportProgress(
                        "MODEL_CALL_FAILED",
                        plannedCalls=plannedCalls,
                        attemptedCalls=attemptedCalls,
                        completedCalls=completedCalls,
                        fallbackCount=fallbackCount,
                        totalTokens=totalTokens,
                        structuredValidCalls=structuredValidCalls,
                        failureCategoryCounts=failureCategoryCounts,
                        decisionRound=decisionRound,
                        representativeIndex=representativeIndex,
                        failureCode=failureCode,
                    )
                    break
                # 注入式网关或测试替身也必须服从用户策略；不能只依赖供应商网关正确实现。
                if run.fallback_used and not fallbackAllowed:
                    raise RuntimeError(
                        "the configured cognitive model used a rule fallback while "
                        "fallback was disabled"
                    )
                resolvedModel = run.model
                totalTokens += run.total_tokens
                promptTokens += run.prompt_tokens
                completionTokens += run.completion_tokens
                cachedTokens += run.cached_tokens
                fallbackCount += int(run.fallback_used)
                if run.fallback_used:
                    fallbackReasons.append(run.fallback_reason or "RULE_FALLBACK_USED")
                    fallbackReason = run.fallback_reason or "RULE_FALLBACK_USED"
                    for category in {_cognitionFailureCategory(code) for code in run.failure_codes}:
                        failureCategoryCounts[category] = failureCategoryCounts.get(category, 0) + 1
                    repeatedFailureCounts[fallbackReason] = (
                        repeatedFailureCounts.get(fallbackReason, 0) + 1
                    )
                else:
                    structuredValidCalls += 1
                decision = run.decision
                evidenceIds = sorted(decision.evidenceIds())
                publicMessage = (
                    decision.public_message
                    if decision.public_message is not None and evidenceIds
                    else None
                )
                deterministicDecisionId = (
                    "decision-"
                    + _hashJson(
                        {
                            "pilotIdentity": pilotIdentity,
                            "representativeIndex": representativeIndex,
                            "decisionRound": decisionRound,
                            "observation": observation.model_dump(mode="json"),
                            "decision": decision.model_dump(mode="json"),
                        }
                    )[:24]
                )
                signals.append(
                    {
                        "agentId": agentId,
                        "representativeIndex": representativeIndex,
                        "role": observation.agent.role,
                        "observationId": observation.observation_id,
                        "observationAt": observation.now.isoformat(),
                        "observationHash": _hashJson(observation.model_dump(mode="json")),
                        "marketObservation": observation.market.model_dump(mode="json"),
                        "pilotIteration": len(pilotIterations) - 1,
                        "pilotEventLogHash": currentPilot["eventLogHash"],
                        "pilotPathsHash": pilotPathsHash,
                        "decisionId": deterministicDecisionId,
                        "decisionRound": decisionRound,
                        "activeFromStep": activeFromStep,
                        "decisionIntervalSteps": decisionInterval,
                        "evidenceCount": len(observation.new_evidence),
                        "socialPostCount": len(observation.social_feed),
                        "modelGeneratedSocialPostCount": len(modelGeneratedSocial),
                        "memoryCount": len(observation.memory_summary),
                        "direction": decision.direction.value,
                        "actionPreference": decision.action_preference.value,
                        "targetPositionFraction": decision.target_position_fraction,
                        "urgency": decision.urgency,
                        "uncertainty": decision.uncertainty,
                        "tailRisk": decision.perceived_tail_risk,
                        "confidence": decision.confidence,
                        "decisionSummary": decision.decision_summary,
                        "publicMessage": publicMessage,
                        "publicMessageLabel": (
                            "MODEL_GENERATED_NOT_NEW_EVIDENCE" if publicMessage else None
                        ),
                        "evidenceIds": evidenceIds,
                        "model": run.model,
                        "requestId": run.request_id,
                        "cacheHit": run.cache_hit,
                        "fallbackUsed": run.fallback_used,
                        "repairUsed": run.repair_used,
                        "thinkingPreferenceEnabled": run.thinking_preference_enabled,
                        "thinkingEnabled": run.thinking_enabled,
                        "failureReason": run.fallback_reason,
                        "failureCodes": list(run.failure_codes),
                        "transportAttempts": run.transport_attempts,
                        "latencyMs": run.latency_ms,
                        "totalTokens": run.total_tokens,
                        "promptTokens": run.prompt_tokens,
                        "completionTokens": run.completion_tokens,
                        "cachedTokens": run.cached_tokens,
                        "costUpperBoundUsd": run.cost_upper_bound_usd,
                    }
                )
                completedCalls += 1
                reportProgress(
                    "MODEL_CALL_COMPLETED",
                    plannedCalls=plannedCalls,
                    attemptedCalls=attemptedCalls,
                    completedCalls=completedCalls,
                    fallbackCount=fallbackCount,
                    totalTokens=totalTokens,
                    structuredValidCalls=structuredValidCalls,
                    failureCategoryCounts=failureCategoryCounts,
                    decisionRound=decisionRound,
                    representativeIndex=representativeIndex,
                )
                if run.fallback_used and repeatedFailureCounts[fallbackReason] >= 3:
                    failureCode = "COGNITION_REPEATED_FAILURE_CIRCUIT_OPEN"
                    reportProgress(
                        "CIRCUIT_BREAKER_OPEN",
                        plannedCalls=plannedCalls,
                        attemptedCalls=attemptedCalls,
                        completedCalls=completedCalls,
                        fallbackCount=fallbackCount,
                        totalTokens=totalTokens,
                        structuredValidCalls=structuredValidCalls,
                        failureCategoryCounts=failureCategoryCounts,
                        decisionRound=decisionRound,
                        representativeIndex=representativeIndex,
                        failureCode=failureCode,
                    )
                    break

            callsRemaining -= len(signals) - roundStartSignalCount
            if len(signals) > roundStartSignalCount:
                try:
                    currentPilot = self._runCognitionPilot(
                        requestData=requestData,
                        eventPack=eventPack,
                        pilotSeed=pilotSeed,
                        signals=signals,
                    )
                    pilotIterations.append(
                        self._pilotIterationRecord(
                            currentPilot,
                            iterationIndex=len(pilotIterations),
                            completedDecisionRound=decisionRound,
                            signalCount=len(signals),
                        )
                    )
                except Exception as error:
                    # 已产生的偏好也必须全部丢弃，避免未验证 pilot 的部分信号进入正式实验。
                    LOGGER.exception(
                        "Closed-loop cognition pilot feedback failed after round %s",
                        decisionRound,
                    )
                    if not fallbackAllowed:
                        raise RuntimeError(
                            "closed-loop cognition pilot feedback failed while "
                            "fallback was disabled"
                        ) from error
                    pilotFailed = True
                    failureCode = "CLOSED_LOOP_PILOT_FAILED"
                    reportProgress(
                        "FAILED_CLOSED",
                        plannedCalls=plannedCalls,
                        attemptedCalls=attemptedCalls,
                        completedCalls=completedCalls,
                        fallbackCount=fallbackCount,
                        totalTokens=totalTokens,
                        structuredValidCalls=structuredValidCalls,
                        failureCategoryCounts=failureCategoryCounts,
                        decisionRound=decisionRound,
                        failureCode=failureCode,
                    )
                    break
            if failureCode is not None:
                break

        if pilotFailed:
            discardedSignalCount = len(signals)
            discardedSignalHash = _cognitiveSignalSequenceHash(signals)
            signals = []
            return {
                **baseMetadata,
                "resolvedMode": "RULE_FALLBACK",
                "externalModelUsed": attemptedCalls > 0,
                "provider": requestedProvider if attemptedCalls > 0 else None,
                "resolvedModel": resolvedModel,
                "calls": discardedSignalCount,
                "attemptedCalls": attemptedCalls,
                "plannedCalls": plannedCalls,
                "totalTokens": totalTokens,
                "promptTokens": promptTokens,
                "completionTokens": completionTokens,
                "cachedTokens": cachedTokens,
                "fallbackCount": fallbackCount,
                "fallbackReasons": fallbackReasons,
                "structuredValidCalls": structuredValidCalls,
                "structuredSuccessRate": (
                    structuredValidCalls / attemptedCalls if attemptedCalls else 0.0
                ),
                "structuredSuccessThreshold": 0.95,
                "structuredSuccessGateStatus": (
                    "NOT_EVALUATED"
                    if attemptedCalls == 0
                    else "PASS"
                    if structuredValidCalls / attemptedCalls >= 0.95
                    else "FAIL"
                ),
                "failureCategoryCounts": dict(sorted(failureCategoryCounts.items())),
                "failureCode": failureCode,
                "costBudget": costBudget.snapshot(),
                "decisionScheduleMode": COGNITION_PILOT_SCHEDULE_MODE,
                "signals": signals,
                "pilot": {
                    "status": "FAILED_CLOSED",
                    "seed": pilotSeed,
                    "identity": pilotIdentity,
                    "hash": currentPilot["eventLogHash"],
                    "iterations": pilotIterations,
                    "boundary": pilotBoundary,
                    "failureStage": "POST_DECISION_FEEDBACK_RERUN",
                    "discardedSignalCount": discardedSignalCount,
                    "discardedSignalHash": discardedSignalHash,
                    "frozenSignalsHash": _cognitiveSignalSequenceHash(()),
                },
            }

        frozenSignalsHash = _cognitiveSignalSequenceHash(signals)
        pilotMetadata = {
            "status": "COMPLETED",
            "seed": pilotSeed,
            "identity": pilotIdentity,
            "hash": currentPilot["eventLogHash"],
            "pathsHash": _hashJson(currentPilot["paths"]),
            "iterations": pilotIterations,
            "iterationCount": len(pilotIterations),
            "boundary": pilotBoundary,
            "frozenSignalsHash": frozenSignalsHash,
        }
        if signals and fallbackCount == len(signals):
            resolvedMode = "RULE_FALLBACK"
        elif fallbackCount > 0 or (failureCode is not None and signals):
            resolvedMode = "HYBRID_LLM_PARTIAL_RULE_FALLBACK"
        elif failureCode is not None:
            resolvedMode = "RULE_FALLBACK"
        else:
            resolvedMode = "HYBRID_LLM"

        reportProgress(
            "COMPLETED",
            plannedCalls=plannedCalls,
            attemptedCalls=attemptedCalls,
            completedCalls=completedCalls,
            fallbackCount=fallbackCount,
            totalTokens=totalTokens,
            structuredValidCalls=structuredValidCalls,
            failureCategoryCounts=failureCategoryCounts,
            failureCode=failureCode,
        )
        return {
            **baseMetadata,
            "resolvedMode": resolvedMode,
            "externalModelUsed": attemptedCalls > 0,
            "provider": requestedProvider if attemptedCalls > 0 else None,
            "resolvedModel": resolvedModel,
            "calls": len(signals),
            "attemptedCalls": attemptedCalls,
            "plannedCalls": plannedCalls,
            "totalTokens": totalTokens,
            "promptTokens": promptTokens,
            "completionTokens": completionTokens,
            "cachedTokens": cachedTokens,
            "fallbackCount": fallbackCount,
            "fallbackReasons": fallbackReasons,
            "structuredValidCalls": structuredValidCalls,
            "structuredSuccessRate": (
                structuredValidCalls / attemptedCalls if attemptedCalls else 0.0
            ),
            "structuredSuccessThreshold": 0.95,
            "structuredSuccessGateStatus": (
                "NOT_EVALUATED"
                if attemptedCalls == 0
                else "PASS"
                if structuredValidCalls / attemptedCalls >= 0.95
                else "FAIL"
            ),
            "failureCategoryCounts": dict(sorted(failureCategoryCounts.items())),
            "failureCode": failureCode,
            "userRequestedRuleContinuation": userRequestedRuleContinuation,
            "costBudget": costBudget.snapshot(),
            "decisionScheduleMode": COGNITION_PILOT_SCHEDULE_MODE,
            "pilot": pilotMetadata,
            "frozenSignalsHash": frozenSignalsHash,
            "signals": signals,
        }

    @staticmethod
    def _runCognitionPilot(
        *,
        requestData: dict[str, Any],
        eventPack: dict[str, Any],
        pilotSeed: int,
        signals: tuple[Any, ...] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        intervention = requestData["intervention"]
        pilot = runScenario(
            seed=pilotSeed,
            populationSize=int(requestData["populationSize"]),
            steps=int(requestData["steps"]),
            parameter=str(intervention["parameter"]),
            value=float(intervention["baselineValue"]),
            eventPack=eventPack,
            cognitiveSignals=signals,
            scenarioConfig=requestData,
        )
        if pilot.get("cancelled") or not pilot.get("paths") or not pilot.get("eventLogHash"):
            raise RuntimeError("cognition pilot did not produce a complete deterministic run")
        return pilot

    @staticmethod
    def _pilotIterationRecord(
        pilot: dict[str, Any],
        *,
        iterationIndex: int,
        completedDecisionRound: int | None,
        signalCount: int,
    ) -> dict[str, Any]:
        return {
            "iterationIndex": iterationIndex,
            "completedDecisionRound": completedDecisionRound,
            "signalCount": signalCount,
            "eventLogHash": pilot["eventLogHash"],
            "pathsHash": _hashJson(pilot["paths"]),
            "completedSteps": pilot.get("completedSteps"),
            "cognitiveOrderCount": pilot.get("metrics", {}).get("cognitiveOrderCount", 0),
        }

    @staticmethod
    def _marketObservationFromPilot(
        pilot: dict[str, Any],
        *,
        step: int,
        instrumentId: str,
        tickSizeTicks: int,
        fallbackTicks: int,
    ) -> MarketObservation:
        paths = pilot["paths"]
        prices = [float(value) for value in paths.get("price", [])]
        if not prices:
            raise RuntimeError("cognition pilot has no price path")
        pathIndex = max(0, min(step, len(prices) - 1))
        midPriceTicks = max(1, round(prices[pathIndex] * PRICE_SCALE))

        def pathReturn(lookbackSteps: int) -> float:
            priorIndex = max(0, pathIndex - lookbackSteps)
            priorTicks = max(1, round(prices[priorIndex] * PRICE_SCALE))
            return max(-1.0, min(1.0, midPriceTicks / priorTicks - 1))

        spreadPath = paths.get("spreadBps", [])
        depthPath = paths.get("depth", [])
        sentimentPath = paths.get("sentiment", [])
        liquidityStressPath = paths.get("liquidityStress", [])
        spreadBps = max(
            0.0,
            min(
                10_000.0,
                float(spreadPath[min(pathIndex, len(spreadPath) - 1)]) if spreadPath else 0.0,
            ),
        )
        depth = max(
            0,
            int(depthPath[min(pathIndex, len(depthPath) - 1)]) if depthPath else 0,
        )
        orderImbalance = max(
            -1.0,
            min(
                1.0,
                float(sentimentPath[min(pathIndex, len(sentimentPath) - 1)])
                if sentimentPath
                else 0.0,
            ),
        )
        liquidityStress = (
            float(liquidityStressPath[min(pathIndex, len(liquidityStressPath) - 1)])
            if liquidityStressPath
            else spreadBps
        )
        oneMinuteReturn = pathReturn(max(1, round(60 / SIMULATION_STEP_SECONDS)))
        fifteenMinuteReturn = pathReturn(max(1, round(900 / SIMULATION_STEP_SECONDS)))
        recentStart = max(0, pathIndex - max(2, round(60 / SIMULATION_STEP_SECONDS)))
        recentReturns = [
            prices[index] / prices[index - 1] - 1
            for index in range(recentStart + 1, pathIndex + 1)
            if prices[index - 1] > 0
        ]
        localVolatility = statistics.pstdev(recentReturns) if len(recentReturns) >= 2 else 0.0
        if (
            abs(oneMinuteReturn) >= 0.03
            or localVolatility >= 0.015
            or spreadBps >= 150
            or liquidityStress >= 300
        ):
            volatilityRegime = VolatilityRegime.STRESSED
        elif abs(oneMinuteReturn) >= 0.01 or localVolatility >= 0.005 or spreadBps >= 50:
            volatilityRegime = VolatilityRegime.HIGH
        elif abs(oneMinuteReturn) < 0.001 and localVolatility < 0.0005 and spreadBps < 10:
            volatilityRegime = VolatilityRegime.LOW
        else:
            volatilityRegime = VolatilityRegime.NORMAL
        halfSpreadTicks = max(
            tickSizeTicks,
            round(midPriceTicks * spreadBps / 20_000),
        )
        bestBidTicks = max(1, midPriceTicks - halfSpreadTicks)
        bestAskTicks = max(bestBidTicks + 1, midPriceTicks + halfSpreadTicks)
        safeInstrumentId = re.sub(r"[^A-Z0-9._-]+", "-", instrumentId.upper()).strip("-")
        return MarketObservation(
            instrument_id=(safeInstrumentId[:32] or "SPCX"),
            mid_price_ticks=midPriceTicks if midPriceTicks > 0 else fallbackTicks,
            best_bid_ticks=bestBidTicks,
            best_ask_ticks=bestAskTicks,
            return_1m=oneMinuteReturn,
            return_15m=fifteenMinuteReturn,
            spread_bps=round(spreadBps, 6),
            depth_10bps=depth,
            order_imbalance=round(orderImbalance, 6),
            volatility_regime=volatilityRegime,
        )

    @staticmethod
    def _modelGeneratedSocialFeed(
        signals: list[dict[str, Any]],
        *,
        decisionRound: int,
        observationTime: datetime,
    ) -> list[SocialPost]:
        if decisionRound <= 0:
            return []
        posts: list[SocialPost] = []
        for signal in signals:
            if signal.get("decisionRound") != decisionRound - 1:
                continue
            publicMessage = signal.get("publicMessage")
            evidenceIds = signal.get("evidenceIds", [])
            if not isinstance(publicMessage, str) or not publicMessage.strip() or not evidenceIds:
                continue
            posts.append(
                SocialPost(
                    post_id=(
                        f"model-generated-r{decisionRound - 1:03d}-"
                        f"a{int(signal.get('representativeIndex', 0)):03d}"
                    ),
                    text=f"{MODEL_GENERATED_SOCIAL_LABEL} {publicMessage.strip()}"[:1_000],
                    author_trust=max(
                        0.0,
                        min(0.35, float(signal.get("confidence", 0.0)) * 0.35),
                    ),
                    seen_at=observationTime,
                )
            )
            if len(posts) >= 8:
                break
        return posts

    @staticmethod
    def _approvedEvidence(
        eventPack: dict[str, Any],
        asOf: datetime,
    ) -> list[EvidenceItem]:
        sources = {source.get("sourceId"): source for source in eventPack.get("sources", [])}
        evidence: list[EvidenceItem] = []
        for claim in eventPack.get("claims", []):
            reviewStatus = claim.get("preFreezeReviewStatus", claim.get("reviewStatus"))
            if reviewStatus not in {"HUMAN_APPROVED", "EDITED", "FROZEN"}:
                continue
            knownAt = _parseUtc(claim.get("knownAt", eventPack.get("asOf")))
            if knownAt > asOf:
                continue
            sourceIds = claim.get("sourceIds", [])
            source = sources.get(sourceIds[0], {}) if sourceIds else {}
            evidence.append(
                EvidenceItem(
                    evidence_id=claim["claimId"],
                    claim=claim["text"],
                    source_type=_evidenceSourceType(source),
                    known_at=knownAt,
                    credibility=_claimConfidence(claim),
                    human_approved=True,
                )
            )
            if len(evidence) >= 16:
                break
        return evidence

    @staticmethod
    def _socialFeed(
        eventPack: dict[str, Any],
        asOf: datetime,
    ) -> list[SocialPost]:
        """只把已审核的叙事型主张映射为无指令权限的社交观察。"""

        socialPosts: list[SocialPost] = []
        for claim in eventPack.get("claims", []):
            reviewStatus = claim.get("preFreezeReviewStatus", claim.get("reviewStatus"))
            if reviewStatus not in {"HUMAN_APPROVED", "EDITED", "FROZEN"}:
                continue
            knownAt = _parseUtc(claim.get("knownAt", eventPack.get("asOf")))
            if knownAt > asOf:
                continue
            claimType = str(claim.get("claimType", "")).upper()
            impactChannels = {str(item).casefold() for item in claim.get("impactChannels", [])}
            if not {"social", "narrative"} & impactChannels and not any(
                marker in claimType
                for marker in ("RUMOR", "NARRATIVE", "OPINION", "SCENARIO_ASSUMPTION")
            ):
                continue
            confidence = _claimConfidence(claim)
            socialPosts.append(
                SocialPost(
                    post_id=f"social-{claim['claimId']}"[:128],
                    text=str(claim.get("text", ""))[:1_000],
                    author_trust=max(0.0, min(1.0, confidence * 0.7)),
                    seen_at=knownAt,
                )
            )
            if len(socialPosts) >= 8:
                break
        return socialPosts

    def _buildResult(
        self,
        experimentId: str,
        requestData: dict[str, Any],
        eventPack: dict[str, Any],
        seeds: list[int],
        aggregate: dict[str, Any],
        cognitionRun: dict[str, Any],
        stoppingDecision: dict[str, Any],
    ) -> dict[str, Any]:
        intervention = requestData["intervention"]
        baselineScenario = {
            "eventPackId": requestData["eventPackId"],
            "populationSize": requestData["populationSize"],
            "steps": requestData["steps"],
            "parameter": intervention["parameter"],
            "value": intervention["baselineValue"],
        }
        interventionScenario = {
            **baselineScenario,
            "value": intervention["interventionValue"],
        }
        cognitionMetadata = {key: value for key, value in cognitionRun.items() if key != "signals"}
        analysisDiagnostics = _buildAnalysisDiagnostics(requestData, aggregate)
        cognitionLimitation = (
            {
                "code": "BOUNDED_LLM_COGNITION",
                "text": (
                    "The selected LLM produced evidence-bound belief and action "
                    "preferences for representative agents. Deterministic policy, risk, "
                    "and matching code alone converted them into orders and prices."
                ),
                "textZh": (
                    "所选 LLM 仅为代表性智能体产生受证据约束的信念与行动偏好；"
                    "只有确定性策略、风控和撮合代码能将其转换为订单与价格。"
                ),
            }
            if str(cognitionRun["resolvedMode"]).startswith("HYBRID_LLM")
            else {
                "code": "RULE_AGENTS_ONLY",
                "text": (
                    "This run used auditable rule agents and does not claim to "
                    "reproduce real investor cognition."
                ),
                "textZh": "本次运行使用可审计的规则智能体，不声称复现真实投资者认知。",
            }
        )
        limitations = [
            *eventPack["limitations"],
            cognitionLimitation,
            *(
                [
                    {
                        "code": "FROZEN_CLOSED_LOOP_PILOT_COGNITION",
                        "text": (
                            "Between decision rounds, the model observes aggregate market paths "
                            "from a deterministic baseline-reference pilot rerun with all prior "
                            "bounded signals. The resulting sequence is then frozen and reused "
                            "for both arms and every matched seed; the model does not observe or "
                            "adapt to arm-specific or seed-specific formal-run paths."
                        ),
                        "textZh": (
                            "在每轮决策之间，模型会观察确定性基准参考 pilot 在纳入此前全部受限信号"
                            "后重跑得到的聚合市场路径；随后整条序列被冻结，并在两组及所有匹配种子"
                            "间复用。模型不会观察或适应正式运行中分组特有、种子特有的路径。"
                        ),
                    }
                ]
                if str(cognitionRun["resolvedMode"]).startswith("HYBRID_LLM")
                else []
            ),
            {
                "code": "SIMPLIFIED_SPOT_MARKET",
                "text": (
                    "The engine models one simplified spot order book without "
                    "options or exchange-specific regulation."
                ),
                "textZh": "引擎只模拟一个简化现货订单簿，不包含期权或特定交易所制度。",
            },
        ]
        fallbackReasons = [
            str(reason) for reason in cognitionRun.get("fallbackReasons", []) if reason
        ]
        if cognitionRun["failureCode"] and cognitionRun["failureCode"] not in fallbackReasons:
            fallbackReasons.append(str(cognitionRun["failureCode"]))
        if cognitionRun["fallbackCount"] > 0 or cognitionRun["failureCode"]:
            reasonsText = ", ".join(fallbackReasons) if fallbackReasons else "not reported"
            reasonsTextZh = "、".join(fallbackReasons) if fallbackReasons else "未报告"
            partialFallback = str(cognitionRun["resolvedMode"]).startswith("HYBRID_LLM")
            limitations.append(
                {
                    "code": (
                        "LLM_PARTIAL_RULE_FALLBACK" if partialFallback else "LLM_RULE_FALLBACK"
                    ),
                    "text": (
                        "The hybrid run included a partial deterministic-rule fallback or "
                        f"model-routing failure. Recorded rule-fallback decisions: "
                        f"{cognitionRun['fallbackCount']}; reasons: {reasonsText}."
                        if partialFallback
                        else "The requested hybrid mode fell back to deterministic rules; "
                        f"reasons: {reasonsText}."
                    ),
                    "textZh": (
                        "本次混合运行包含部分确定性规则回退或模型路由失败。"
                        f"记录到的规则回退决策数：{cognitionRun['fallbackCount']}；"
                        f"原因：{reasonsTextZh}。"
                        if partialFallback
                        else f"请求的混合模式已回退为确定性规则；原因：{reasonsTextZh}。"
                    ),
                }
            )
        manifest = {
            "schemaVersion": "2.0.0",
            "experimentId": experimentId,
            "generatedAt": utcNow(),
            "baselineScenarioHash": _hashJson(baselineScenario),
            "interventionScenarioHash": _hashJson(interventionScenario),
            "completeConfigurationHash": _hashJson(requestData),
            "seedListHash": _hashJson(seeds),
            "eventPackHash": _hashJson(eventPack),
            "engineVersion": SIMULATION_ENGINE_VERSION,
            "pythonVersion": "3.12.13",
            "matchedSeedDesign": True,
            "validPairedSeeds": len(aggregate["pairedRuns"]),
            "requestedMaximumPairs": requestData["seedCount"],
            "stoppingRuleTriggered": stoppingDecision["triggered"],
            "synthetic": True,
            "agentMode": cognitionRun["resolvedMode"],
            "llmExternalModelUsed": cognitionRun.get("externalModelUsed", False),
            "llmProvider": cognitionRun["provider"],
            "llmModel": cognitionRun["resolvedModel"],
            "configuredButUnusedProvider": cognitionRun.get("configuredButUnusedProvider"),
            "configuredButUnusedModel": cognitionRun.get("configuredButUnusedModel"),
            "llmCalls": cognitionRun["calls"],
            "llmPlannedCalls": cognitionRun["plannedCalls"],
            "llmAttemptedCalls": cognitionRun["attemptedCalls"],
            "llmTotalTokens": cognitionRun["totalTokens"],
            "llmPromptTokens": cognitionRun["promptTokens"],
            "llmCompletionTokens": cognitionRun["completionTokens"],
            "llmCachedTokens": cognitionRun["cachedTokens"],
            "llmCostBudget": cognitionRun["costBudget"],
            "llmFallbackCount": cognitionRun["fallbackCount"],
            "llmFallbackReasons": fallbackReasons,
            "llmDecisionScheduleMode": cognitionRun["decisionScheduleMode"],
            "llmFrozenSignalSequenceHash": cognitionRun.get("frozenSignalsHash"),
            "llmPilotSeed": cognitionRun.get("pilot", {}).get("seed"),
            "llmPilotHash": cognitionRun.get("pilot", {}).get("hash"),
            "llmPilotIterationCount": cognitionRun.get("pilot", {}).get("iterationCount", 0),
            "llmPilotBoundary": cognitionRun.get("pilot", {}).get("boundary"),
            "promptVersion": cognitionRun["promptVersion"],
            "promptSchemaVersion": cognitionRun["promptSchemaVersion"],
            "marketSchemaVersion": "market_v1.0.0",
            "networkSchemaVersion": "network_v1.0.0",
            "portfolioLedgerVersion": "ledger_v1.0.0",
            "analysisDiagnosticsVersion": "analysis_diagnostics_v1.0.0",
        }
        result = {
            "experimentId": experimentId,
            "question": requestData["question"],
            "questionZh": requestData.get("questionZh"),
            "scenarioDiff": {
                "parameter": intervention["parameter"],
                "baselineValue": intervention["baselineValue"],
                "interventionValue": intervention["interventionValue"],
                "changedPaths": [f"intervention.{intervention['parameter']}"],
                "changeCount": 1,
            },
            "stoppingRule": stoppingDecision,
            "analysisDiagnostics": analysisDiagnostics,
            **aggregate,
            "cognition": {
                **cognitionMetadata,
                "decisions": cognitionRun["signals"],
            },
            "narrativeReport": _buildNarrativeReport(aggregate, intervention),
            "eventPackManifest": eventPack,
            "limitations": limitations,
            "manifest": manifest,
        }
        # 结果页与解释助手必须复用同一套服务端稳定排序，避免前端与模型各自
        # 计算“最强结果”后产生不一致。这里只保存指标 ID，不复制或改写统计量。
        result["strongestMetricIds"] = [
            item.metric_id for item in strongestMetricFacts(buildResultFactCatalog(result))
        ]
        return result

    def _activeFutureCount(self) -> int:
        with self.futureLock:
            return self._activeFutureCountUnlocked()

    def _activeFutureCountUnlocked(self) -> int:
        return sum(not future.done() for future in self.futures.values())

    def _removeFuture(self, experimentId: str) -> None:
        with self.futureLock:
            self.futures.pop(experimentId, None)


def _stoppingDecision(
    requestData: dict[str, Any],
    baselineRuns: list[dict[str, Any]],
    interventionRuns: list[dict[str, Any]],
    *,
    previous: dict[str, Any],
) -> dict[str, Any]:
    """按预注册主指标评估顺序停止，不读取次要指标做事后选择。"""

    completedPairs = len(baselineRuns)
    decision = {**previous, "completedPairs": completedPairs}
    stoppingRule = requestData["stoppingRule"]
    targetHalfWidth = stoppingRule.get("targetCiHalfWidth")
    minimumReached = completedPairs >= stoppingRule["minimumPairs"]
    maximumReached = completedPairs >= stoppingRule["maximumPairs"]
    targetReached = False
    intervalPayload: dict[str, Any] | None = None
    observedHalfWidth: float | None = None

    if targetHalfWidth is not None and minimumReached:
        primaryOutcome = requestData["primaryOutcome"]
        differences = [
            float(interventionRun["metrics"][primaryOutcome])
            - float(baselineRun["metrics"][primaryOutcome])
            for baselineRun, interventionRun in zip(
                baselineRuns,
                interventionRuns,
                strict=True,
            )
        ]
        bootstrapSeed = int.from_bytes(
            hashlib.blake2s(
                f"{requestData['seedRoot']}:{primaryOutcome}:stopping".encode(),
                digest_size=4,
            ).digest(),
            "big",
        )
        interval = bootstrap95ConfidenceInterval(
            differences,
            resamples=5_000,
            seed=bootstrapSeed,
        )
        observedHalfWidth = round((interval.upper - interval.lower) / 2, 6)
        targetReached = observedHalfWidth <= float(targetHalfWidth)
        intervalPayload = {
            "estimate": round(interval.estimate, 6),
            "lower": round(interval.lower, 6),
            "upper": round(interval.upper, 6),
            "confidenceLevel": interval.confidenceLevel,
            "resamples": interval.resamples,
            "seed": interval.seed,
        }

    hasTarget = targetHalfWidth is not None
    conditionStates = [
        ("MINIMUM_PAIRS_REACHED", minimumReached, stoppingRule["minimumPairs"]),
        (
            "MAXIMUM_PAIRS_REACHED" if hasTarget else "FIXED_PAIR_COUNT_REACHED",
            maximumReached,
            stoppingRule["maximumPairs"],
        ),
    ]
    if hasTarget:
        conditionStates.append(
            (
                "TARGET_CI_HALF_WIDTH_REACHED",
                targetReached,
                completedPairs if targetReached else None,
            )
        )
    previousEvaluations = {
        str(item.get("code")): item
        for item in previous.get("conditionEvaluations", [])
        if isinstance(item, dict)
    }
    conditionEvaluations = []
    for evaluationOrder, (code, satisfied, satisfiedAtPair) in enumerate(
        conditionStates,
        start=1,
    ):
        previousEvaluation = previousEvaluations.get(code, {})
        firstSatisfiedAtPair = previousEvaluation.get("firstSatisfiedAtPair")
        if firstSatisfiedAtPair is None and satisfied:
            firstSatisfiedAtPair = satisfiedAtPair
        conditionEvaluations.append(
            {
                "code": code,
                "evaluationOrder": evaluationOrder,
                "satisfied": satisfied,
                "firstSatisfiedAtPair": firstSatisfiedAtPair,
            }
        )

    terminalReasons: list[str] = []
    # 固定/最大样本条件优先于精度条件，确保 min=max 时不会被解释成提前停止。
    if maximumReached:
        terminalReasons.append("MAXIMUM_PAIRS_REACHED" if hasTarget else "FIXED_PAIR_COUNT_REACHED")
    if targetReached:
        terminalReasons.append("TARGET_CI_HALF_WIDTH_REACHED")
    primaryReason = (
        terminalReasons[0]
        if terminalReasons
        else str(previous.get("primaryReason") or previous.get("reason"))
    )
    return {
        **decision,
        "triggered": bool(terminalReasons),
        "reason": primaryReason,
        "primaryReason": primaryReason,
        "reasons": terminalReasons,
        "observedCiHalfWidth": observedHalfWidth
        if observedHalfWidth is not None
        else previous.get("observedCiHalfWidth"),
        "bootstrapInterval95": intervalPayload
        if intervalPayload is not None
        else previous.get("bootstrapInterval95"),
        "conditionEvaluations": conditionEvaluations,
    }


def _buildAnalysisDiagnostics(
    requestData: dict[str, Any],
    aggregate: dict[str, Any],
) -> dict[str, Any]:
    """把预注册的负对照、参数恢复、敏感性和多重比较接入实验结果。"""

    plan = requestData["analysisPlan"]
    outcomeIds = list(
        dict.fromkeys([requestData["primaryOutcome"], *requestData.get("secondaryOutcomes", [])])
    )
    pairedRuns = aggregate["pairedRuns"]
    primaryOutcome = requestData["primaryOutcome"]
    primaryBaseline = [float(run["baseline"][primaryOutcome]) for run in pairedRuns]
    primaryIntervention = [float(run["intervention"][primaryOutcome]) for run in pairedRuns]
    parameter = requestData["intervention"]["parameter"]
    baselineValue = float(requestData["intervention"]["baselineValue"])
    interventionValue = float(requestData["intervention"]["interventionValue"])

    negativeControl: dict[str, Any]
    if plan["runNegativeControl"]:
        negativeControl = {
            "status": "COMPLETED",
            "controlType": "IDENTICAL_SEED_SELF_COMPARISON",
            **asdict(
                evaluateNegativeControl(
                    f"{primaryOutcome}-baseline-self-control",
                    primaryBaseline,
                    primaryBaseline,
                    tolerance=float(plan["negativeControlTolerance"]),
                    bootstrapResamples=5_000,
                    seed=_diagnosticSeed(requestData, "negative-control"),
                )
            ),
            "interpretation": (
                "This detects paired-pipeline drift; it does not validate the market model."
            ),
        }
    else:
        negativeControl = {"status": "NOT_RUN", "reason": "Disabled in analysisPlan."}

    parameterRestoration: dict[str, Any]
    if plan["runParameterRestorationKnockout"]:
        parameterRestoration = {
            "status": "COMPLETED",
            "controlType": "RESTORE_CHANGED_PARAMETER_TO_BASELINE",
            **asdict(
                evaluateKnockout(
                    f"restore-{parameter}-to-baseline",
                    primaryBaseline,
                    primaryIntervention,
                    primaryBaseline,
                    minimumAttenuationFraction=float(plan["minimumKnockoutAttenuationFraction"]),
                    bootstrapResamples=5_000,
                    seed=_diagnosticSeed(requestData, "parameter-restoration"),
                )
            ),
            "interpretation": (
                "Restoring the only changed parameter is a necessary internal control, "
                "not independent proof that the corresponding real-world mechanism is causal."
            ),
        }
    else:
        parameterRestoration = {
            "status": "NOT_RUN",
            "reason": "Disabled in analysisPlan.",
        }

    localSensitivity: dict[str, Any]
    if plan["runLocalSensitivity"]:
        sensitivity = rankCorrelationSensitivity(
            {
                parameter: [baselineValue] * len(primaryBaseline)
                + [interventionValue] * len(primaryIntervention)
            },
            [*primaryBaseline, *primaryIntervention],
        )
        localSensitivity = {
            "status": "COMPLETED",
            "design": "TWO_LEVEL_MATCHED_LOCAL_SCREEN",
            "indices": [asdict(item) for item in sensitivity],
            "interpretation": (
                "A two-level rank screen is local and cannot substitute for a global "
                "Sobol or Latin-hypercube study."
            ),
        }
    else:
        localSensitivity = {"status": "NOT_RUN", "reason": "Disabled in analysisPlan."}

    rawPValues = {
        outcomeId: _twoSidedSignTestPValue(
            [
                float(run["intervention"][outcomeId]) - float(run["baseline"][outcomeId])
                for run in pairedRuns
                if run["intervention"].get(outcomeId) is not None
                and run["baseline"].get(outcomeId) is not None
            ]
        )
        for outcomeId in outcomeIds
    }
    family = holmBonferroni(
        rawPValues,
        alpha=float(plan["multipleComparisonAlpha"]),
    )
    return {
        "schemaVersion": "analysis_diagnostics_v1.0.0",
        "preregisteredPrimaryOutcome": primaryOutcome,
        "outcomeFamily": outcomeIds,
        "negativeControl": negativeControl,
        "parameterRestorationKnockout": parameterRestoration,
        "localSensitivity": localSensitivity,
        "multipleComparison": {
            "method": "HOLM_BONFERRONI_ON_EXACT_TWO_SIDED_SIGN_TESTS",
            "alpha": float(plan["multipleComparisonAlpha"]),
            "items": [asdict(item) for item in family],
        },
        "interpretationBoundary": "MODEL_INTERNAL_DIAGNOSTICS_NOT_EXTERNAL_CAUSAL_VALIDATION",
    }


def _twoSidedSignTestPValue(differences: list[float]) -> float:
    positiveCount = sum(value > 0 for value in differences)
    negativeCount = sum(value < 0 for value in differences)
    sampleSize = positiveCount + negativeCount
    if sampleSize == 0:
        return 1.0
    smallerTail = min(positiveCount, negativeCount)
    tailProbability = sum(math.comb(sampleSize, count) for count in range(smallerTail + 1)) / (
        2**sampleSize
    )
    return min(1.0, 2 * tailProbability)


def _diagnosticSeed(requestData: dict[str, Any], label: str) -> int:
    return int.from_bytes(
        hashlib.blake2s(
            f"{requestData['seedRoot']}:{requestData['primaryOutcome']}:{label}".encode(),
            digest_size=4,
        ).digest(),
        "big",
    )


def _hashJson(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _cognitiveSignalSequenceHash(signals: Any) -> str:
    """只哈希会影响认知闭环或确定性下单的稳定字段，排除请求 ID 与延迟。"""

    stableFields = (
        "agentId",
        "representativeIndex",
        "role",
        "observationId",
        "observationAt",
        "observationHash",
        "marketObservation",
        "pilotIteration",
        "pilotEventLogHash",
        "pilotPathsHash",
        "decisionId",
        "decisionRound",
        "activeFromStep",
        "decisionIntervalSteps",
        "direction",
        "actionPreference",
        "targetPositionFraction",
        "urgency",
        "uncertainty",
        "tailRisk",
        "confidence",
        "decisionSummary",
        "publicMessage",
        "publicMessageLabel",
        "evidenceIds",
    )
    stableSignals = [
        {field: signal.get(field) for field in stableFields}
        for signal in signals
        if isinstance(signal, dict)
    ]
    return _hashJson(stableSignals)


def _parseUtc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("a non-empty ISO 8601 timestamp is required")
    normalizedValue = value.strip().replace("Z", "+00:00")
    parsedValue = datetime.fromisoformat(normalizedValue)
    if parsedValue.tzinfo is None or parsedValue.utcoffset() is None:
        parsedValue = parsedValue.replace(tzinfo=UTC)
    return parsedValue.astimezone(UTC)


def _claimConfidence(claim: dict[str, Any]) -> float:
    """将未赋值的假设可信度映射为既有的中性默认值。"""

    rawConfidence = claim.get("confidence")
    return 0.5 if rawConfidence is None else float(rawConfidence)


def _evidenceSourceType(source: dict[str, Any]) -> EvidenceSourceType:
    sourceType = str(source.get("sourceType", "")).lower()
    publisherAndUrl = " ".join(
        str(source.get(key, "")).lower() for key in ("publisher", "url", "title")
    )
    if "sec" in publisherAndUrl or "filing" in sourceType:
        return EvidenceSourceType.FILING
    if "nasdaq" in publisherAndUrl or "exchange" in sourceType:
        return EvidenceSourceType.OFFICIAL_EXCHANGE
    if "spacex" in publisherAndUrl or "company" in sourceType:
        return EvidenceSourceType.OFFICIAL_COMPANY
    if sourceType in {"official", "regulator", "official_regulator"}:
        return EvidenceSourceType.OFFICIAL_REGULATOR
    if sourceType in {"reporting", "estimate", "reputable_news", "news"}:
        return EvidenceSourceType.REPUTABLE_NEWS
    if sourceType == "social":
        return EvidenceSourceType.SOCIAL
    if sourceType == "synthetic":
        return EvidenceSourceType.SYNTHETIC
    return EvidenceSourceType.OTHER


def _buildNarrativeReport(
    aggregate: dict[str, Any],
    intervention: dict[str, Any],
) -> dict[str, Any]:
    summaries = aggregate.get("metricSummaries", {})

    def metricSentence(metricKey: str, label: str, labelZh: str) -> tuple[str, str]:
        delta = summaries.get(metricKey, {}).get("delta", {})
        median = delta.get("median")
        interval = delta.get("interval95", {})
        lower = interval.get("lower")
        upper = interval.get("upper")
        if median is None:
            return (
                f"{label} did not have enough valid paired runs for a summary.",
                f"{labelZh}没有足够的有效配对运行可供汇总。",
            )
        direction = "increased" if median > 0 else "decreased" if median < 0 else "was unchanged"
        directionZh = "上升" if median > 0 else "下降" if median < 0 else "未变"
        return (
            f"{label} {direction} by a paired median of {median:.4f}; "
            f"the empirical 95% interval was [{lower}, {upper}].",
            f"{labelZh}的配对中位变化为 {median:.4f}，方向为{directionZh}；"
            f"经验 95% 区间为 [{lower}, {upper}]。",
        )

    spreadText, spreadTextZh = metricSentence(
        "maxSpreadBps", "Maximum quoted spread", "最大报价价差"
    )
    drawdownText, drawdownTextZh = metricSentence("maxDrawdownPct", "Maximum drawdown", "最大回撤")
    parameter = intervention["parameter"]
    baselineValue = intervention["baselineValue"]
    interventionValue = intervention["interventionValue"]
    return {
        "schemaVersion": "deterministic_report_v1.0.0",
        "headline": f"Internal scenario effect of changing {parameter}",
        "headlineZh": f"改变 {parameter} 的模型内部情景效应",
        "summary": (
            f"The intervention changed {parameter} from {baselineValue} to "
            f"{interventionValue}. {spreadText} {drawdownText}"
        ),
        "summaryZh": (
            f"干预将 {parameter} 从 {baselineValue} 改为 {interventionValue}。"
            f"{spreadTextZh}{drawdownTextZh}"
        ),
        "interpretationBoundary": (
            "This is a controlled scenario comparison within the declared synthetic model, "
            "data, and parameters. It cannot establish real-world causality and is not a "
            "forecast or investment advice."
        ),
        "interpretationBoundaryZh": (
            "这是在已声明的合成模型、数据与参数内进行的受控情景对比；"
            "它不能证明现实世界因果关系，也不是预测或投资建议。"
        ),
        "generatedBy": "DETERMINISTIC_TEMPLATE",
    }


def _buildExport(experiment: dict[str, Any]) -> bytes:
    result = experiment["result"]
    requestData = experiment["request"]
    # 生产导出只允许已完成实验；底层构建器也被结果级测试直接复用，
    # 这些调用没有数据库状态字段，因此按其既有“已完成结果”语义补齐默认值。
    experimentStatus = str(experiment.get("status") or "COMPLETED")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        _writeJson(
            archive,
            "manifest.json",
            {
                **result["manifest"],
                "bundleKind": "REPRODUCIBILITY_BUNDLE",
                "experimentStatus": experimentStatus,
            },
        )
        _writeJson(archive, "event_pack_manifest.json", result["eventPackManifest"])
        baselineScenario = {
            **requestData,
            "scenarioRole": "baseline",
            "activeValue": requestData["intervention"]["baselineValue"],
        }
        interventionScenario = {
            **requestData,
            "scenarioRole": "intervention",
            "activeValue": requestData["intervention"]["interventionValue"],
        }
        _writeJson(archive, "scenario_baseline.json", baselineScenario)
        _writeJson(archive, "scenario_intervention.json", interventionScenario)
        _writeJson(archive, "aggregate_metrics.json", result["metricSummaries"])
        _writeJson(
            archive,
            "analysis_diagnostics.json",
            result.get("analysisDiagnostics", {}),
        )
        parquetArtifacts = buildParquetArtifacts(result)
        for artifactName, artifactBytes in sorted(parquetArtifacts.items()):
            archive.writestr(f"parquet/{artifactName}", artifactBytes)
        _writeJson(
            archive,
            "parquet/schema_manifest.json",
            {
                "schemaVersion": "eventshock_parquet_v1.0.0",
                "artifacts": [
                    {
                        "path": f"parquet/{artifactName}",
                        "sha256": hashlib.sha256(artifactBytes).hexdigest(),
                        "byteLength": len(artifactBytes),
                    }
                    for artifactName, artifactBytes in sorted(parquetArtifacts.items())
                ],
            },
        )
        cognition = result.get("cognition", {})
        requestedMode = str(cognition.get("requestedMode", "RULE_ONLY"))
        resolvedMode = str(cognition.get("resolvedMode", "RULE_ONLY"))
        externalModelUsed = bool(
            cognition.get(
                "externalModelUsed",
                cognition.get("attemptedCalls", cognition.get("calls", 0)),
            )
        )
        fallbackReasons = [str(reason) for reason in cognition.get("fallbackReasons", []) if reason]
        failureCode = cognition.get("failureCode")
        if failureCode and str(failureCode) not in fallbackReasons:
            fallbackReasons.append(str(failureCode))
        _writeJson(
            archive,
            "model_and_prompt_versions.json",
            {
                "requestedMode": requestedMode,
                "resolvedMode": resolvedMode,
                "externalModelUsed": externalModelUsed,
                "provider": cognition.get("provider"),
                "requestedProvider": cognition.get("requestedProvider"),
                "requestedModel": cognition.get("requestedModel"),
                "resolvedModel": cognition.get("resolvedModel"),
                "configuredButUnusedProvider": cognition.get("configuredButUnusedProvider"),
                "configuredButUnusedModel": cognition.get("configuredButUnusedModel"),
                "promptVersion": cognition.get("promptVersion"),
                "promptSchemaVersion": cognition.get("promptSchemaVersion"),
                "calls": cognition.get("calls", 0),
                "plannedCalls": cognition.get("plannedCalls", 0),
                "attemptedCalls": cognition.get("attemptedCalls", 0),
                "totalTokens": cognition.get("totalTokens", 0),
                "promptTokens": cognition.get("promptTokens", 0),
                "completionTokens": cognition.get("completionTokens", 0),
                "cachedTokens": cognition.get("cachedTokens", 0),
                "costControl": cognition.get("costControl"),
                "costBudget": cognition.get("costBudget", {}),
                "fallbackCount": cognition.get("fallbackCount", 0),
                "fallbackReasons": fallbackReasons,
                "decisionScheduleMode": cognition.get("decisionScheduleMode"),
                "frozenSignalsHash": cognition.get("frozenSignalsHash"),
                "pilotSeed": cognition.get("pilot", {}).get("seed"),
                "pilotHash": cognition.get("pilot", {}).get("hash"),
                "pilotIterationCount": cognition.get("pilot", {}).get("iterationCount", 0),
                "pilotBoundary": cognition.get("pilot", {}).get("boundary"),
                "failureCode": cognition.get("failureCode"),
                "engineVersion": result["manifest"]["engineVersion"],
            },
        )
        _writeJson(
            archive,
            "cognition_closed_loop_pilot.json",
            cognition.get("pilot", {}),
        )
        _writeJson(
            archive,
            "cognitive_decisions.json",
            {
                "schemaVersion": cognition.get("promptSchemaVersion", "belief_decision_v1.0.0"),
                "mode": resolvedMode,
                "applicability": (
                    "NOT_APPLICABLE" if requestedMode == "RULE_ONLY" else "APPLICABLE"
                ),
                "reason": (NO_EXTERNAL_COGNITION_REASON if requestedMode == "RULE_ONLY" else None),
                "items": cognition.get("decisions", []),
            },
        )
        _writeJson(
            archive,
            "order_execution_summary.json",
            {
                "schemaVersion": "order_execution_summary_v1.0.0",
                "scope": "REPRESENTATIVE_MATCHED_SEED_PAIR",
                "interpretationBoundary": (
                    "Items aggregate requested, approved, filled, remaining, VWAP, "
                    "trade links, and final status for orders from the representative "
                    "matched-seed baseline/intervention pair; they are not all experiment orders."
                ),
                "items": result.get("orderExecutionSummary", []),
            },
        )

        sourceBuffer = io.StringIO()
        sourceWriter = csv.writer(sourceBuffer)
        sourceWriter.writerow(["sourceId", "sourceType", "contentHash"])
        for source in result["eventPackManifest"]["sources"]:
            sourceWriter.writerow([source["sourceId"], source["sourceType"], source["contentHash"]])
        archive.writestr("source_hashes.csv", sourceBuffer.getvalue())

        seedBuffer = io.StringIO()
        seedWriter = csv.writer(seedBuffer)
        seedWriter.writerow(["seed"])
        for pairedRun in result["pairedRuns"]:
            seedWriter.writerow([pairedRun["seed"]])
        archive.writestr("random_seeds.csv", seedBuffer.getvalue())

        runBuffer = io.StringIO()
        metricKeys = list(result["pairedRuns"][0]["delta"])
        runWriter = csv.writer(runBuffer)
        runWriter.writerow(
            [
                "seed",
                "baseline_event_log_hash",
                "intervention_event_log_hash",
                *[f"baseline_{key}" for key in metricKeys],
                *[f"intervention_{key}" for key in metricKeys],
                *[f"delta_{key}" for key in metricKeys],
            ]
        )
        for pairedRun in result["pairedRuns"]:
            runWriter.writerow(
                [
                    pairedRun["seed"],
                    pairedRun["baselineEventLogHash"],
                    pairedRun["interventionEventLogHash"],
                ]
                + [pairedRun["baseline"][key] for key in metricKeys]
                + [pairedRun["intervention"][key] for key in metricKeys]
                + [pairedRun["delta"][key] for key in metricKeys]
            )
        archive.writestr("run_level_metrics.csv", runBuffer.getvalue())
        archive.writestr(
            "selected_traces.jsonl",
            "\n".join(json.dumps(trace, ensure_ascii=False) for trace in result["traces"]),
        )
        archive.writestr(
            "limitations.md",
            "# Limitations / 限制\n\n"
            + "\n".join(
                f"- **{item['code']}**: {item['text']} / {item['textZh']}"
                for item in result["limitations"]
            ),
        )
        archive.writestr(
            "validation_report.md",
            "# Validation report / 验证报告\n\n"
            f"- Valid paired seeds: {result['manifest']['validPairedSeeds']}\n"
            f"- Event Pack hash: `{result['manifest']['eventPackHash']}`\n"
            f"- Preregistered primary outcome: "
            f"`{result['analysisDiagnostics']['preregisteredPrimaryOutcome']}`\n"
            "- Negative control, parameter-restoration knockout, local sensitivity, "
            "and Holm-adjusted sign tests are recorded in `analysis_diagnostics.json`.\n"
            "- Baseline and intervention use identical seed lists and differ by "
            "exactly one registered parameter.\n"
            "- 基准与干预使用相同种子列表，并且只改变一个已登记参数。\n"
            "- This is a synthetic mechanism validation, not external historical validation.\n"
            "- 这是合成机制验证，不是外部历史验证。\n",
        )
        archive.writestr(
            "README_REPRODUCE.md",
            "# EventShock Lab reproducibility bundle\n\n"
            "This bundle records scenarios, matched seeds, run-level metrics, "
            "event-log hashes, typed Parquet tables, selected traces, representative "
            "order/trade execution summaries, and limitations. "
            "`cognitive_decisions.json` remains present under the fixed export contract; "
            f"when its applicability is `NOT_APPLICABLE`, `{NO_EXTERNAL_COGNITION_REASON}`. "
            "From the repository root, verify it with `python scripts/replay-bundle.py "
            "<export.zip>`. Re-run it only with engine version "
            f"`{result['manifest']['engineVersion']}` and CPython 3.12.13.\n\n"
            "本压缩包记录场景、配对种子、逐次指标、事件日志哈希、抽样追踪、"
            "代表性订单/成交执行摘要与限制。固定导出契约会始终保留 "
            "`cognitive_decisions.json`；`NOT_APPLICABLE` 表示本次未请求外部认知。"
            "在仓库根目录运行 `python scripts/replay-bundle.py <export.zip>` 核验；"
            "只应使用相同引擎版本和 CPython 3.12.13 重放。\n",
        )
    return buffer.getvalue()


def _writeJson(archive: zipfile.ZipFile, name: str, value: Any) -> None:
    archive.writestr(name, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
