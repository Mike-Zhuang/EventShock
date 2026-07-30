"""P0 发布门禁；人工证据缺失时保持阻断。"""

# ruff: noqa: E501

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from backend.app.governance.redteam import (
    RED_TEAM_CASES,
    REQUIRED_RED_TEAM_CATEGORIES,
    RedTeamResult,
    RedTeamStatus,
    validateRedTeamCases,
)
from backend.app.governance.registry import GovernanceModel, inventoryHash, validateInventory


class EvidenceType(StrEnum):
    AUTOMATED_TEST_SUITE = "AUTOMATED_TEST_SUITE"
    REPRODUCIBILITY_REPLAY = "REPRODUCIBILITY_REPLAY"
    HUMAN_USER_RESEARCH = "HUMAN_USER_RESEARCH"
    DOMAIN_EXPERT_REVIEW = "DOMAIN_EXPERT_REVIEW"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    LICENSE_REVIEW = "LICENSE_REVIEW"
    OPERATIONS_REHEARSAL = "OPERATIONS_REHEARSAL"
    MODEL_VALIDATION_REVIEW = "MODEL_VALIDATION_REVIEW"


HUMAN_EVIDENCE_TYPES = frozenset(
    {
        EvidenceType.HUMAN_USER_RESEARCH,
        EvidenceType.DOMAIN_EXPERT_REVIEW,
        EvidenceType.SECURITY_REVIEW,
        EvidenceType.LICENSE_REVIEW,
        EvidenceType.OPERATIONS_REHEARSAL,
        EvidenceType.MODEL_VALIDATION_REVIEW,
    }
)


class EvidenceStatus(StrEnum):
    VERIFIED = "VERIFIED"
    PENDING = "PENDING"
    PENDING_HUMAN_EVIDENCE = "PENDING_HUMAN_EVIDENCE"
    REJECTED = "REJECTED"


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"
    PENDING_HUMAN_EVIDENCE = "PENDING_HUMAN_EVIDENCE"


class ReleaseDecision(StrEnum):
    READY_FOR_CONTROLLED_DEMO = "READY_FOR_CONTROLLED_DEMO"
    BLOCKED = "BLOCKED"


class GateEvaluator(StrEnum):
    INVENTORY = "INVENTORY"
    RED_TEAM_DEFINITIONS = "RED_TEAM_DEFINITIONS"
    RED_TEAM_EXECUTIONS = "RED_TEAM_EXECUTIONS"
    STRUCTURED_SUCCESS = "STRUCTURED_SUCCESS"
    EXTERNAL_EVIDENCE = "EXTERNAL_EVIDENCE"


class ReleaseEvidence(GovernanceModel):
    evidenceId: str = Field(min_length=3, max_length=160, pattern=r"^[a-z0-9.-]+$")
    evidenceType: EvidenceType
    status: EvidenceStatus
    summary: str = Field(min_length=8, max_length=1_000)
    artifactUri: str | None = Field(default=None, min_length=3, max_length=1_000)
    evidenceHash: str | None = Field(default=None, pattern=r"^sha256:[a-f0-9]{64}$")
    collectedAt: datetime | None = None
    reviewerName: str | None = Field(default=None, min_length=2, max_length=120)
    reviewerRole: str | None = Field(default=None, min_length=3, max_length=160)
    attestation: str | None = Field(default=None, min_length=20, max_length=1_000)

    @field_validator("collectedAt")
    @classmethod
    def requireTimezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("collectedAt must be timezone-aware")
        return value

    @model_validator(mode="after")
    def preventInventedCompletion(self) -> ReleaseEvidence:
        isHumanEvidence = self.evidenceType in HUMAN_EVIDENCE_TYPES
        if self.status is EvidenceStatus.PENDING_HUMAN_EVIDENCE and not isHumanEvidence:
            raise ValueError("PENDING_HUMAN_EVIDENCE is only valid for human evidence")
        if self.status is not EvidenceStatus.VERIFIED:
            return self
        if self.collectedAt is None or self.artifactUri is None or self.evidenceHash is None:
            raise ValueError(
                "VERIFIED evidence requires collectedAt, artifactUri, and evidenceHash"
            )
        if isHumanEvidence:
            if self.reviewerName is None or self.reviewerRole is None or self.attestation is None:
                raise ValueError(
                    "VERIFIED human evidence requires reviewerName, reviewerRole, and attestation"
                )
            forbiddenReviewers = {
                "ai",
                "automated",
                "automation",
                "codex",
                "chatgpt",
                "llm",
                "model",
                "unknown",
            }
            if self.reviewerName.strip().casefold() in forbiddenReviewers:
                raise ValueError("human evidence reviewerName must identify a real human reviewer")
            if (
                "pending" in self.attestation.casefold()
                or "not performed" in self.attestation.casefold()
            ):
                raise ValueError("a pending or unperformed review cannot be marked VERIFIED")
        return self


class P0GateDefinition(GovernanceModel):
    gateId: str = Field(min_length=3, max_length=160, pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=5, max_length=200)
    owner: str = Field(min_length=3, max_length=120)
    evaluator: GateEvaluator
    requiredEvidenceType: EvidenceType | None = None
    criterion: str = Field(min_length=12, max_length=1_000)
    failureEffect: str = Field(min_length=12, max_length=500)

    @model_validator(mode="after")
    def validateEvidenceBinding(self) -> P0GateDefinition:
        if self.evaluator is GateEvaluator.EXTERNAL_EVIDENCE:
            if self.requiredEvidenceType is None:
                raise ValueError("external-evidence gates require requiredEvidenceType")
        elif self.requiredEvidenceType is not None:
            raise ValueError("automatic gates cannot declare requiredEvidenceType")
        return self


class P0GateResult(GovernanceModel):
    gateId: str
    status: GateStatus
    detail: str = Field(min_length=3, max_length=1_000)
    evidenceIds: tuple[str, ...] = ()


class ReleaseContext(GovernanceModel):
    releaseId: str = Field(min_length=3, max_length=160, pattern=r"^[A-Za-z0-9._-]+$")
    evaluatedAt: datetime
    evidence: tuple[ReleaseEvidence, ...] = ()
    redTeamResults: tuple[RedTeamResult, ...] = ()
    structuredSuccessCalls: int = Field(default=0, ge=0)
    structuredSuccessRate: float = Field(default=0.0, ge=0.0, le=1.0)
    structuredSuccessThreshold: float = Field(default=0.95, ge=0.0, le=1.0)

    @field_validator("evaluatedAt")
    @classmethod
    def requireTimezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evaluatedAt must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validateUniqueEvidence(self) -> ReleaseContext:
        evidenceIds = [item.evidenceId for item in self.evidence]
        if len(evidenceIds) != len(set(evidenceIds)):
            raise ValueError("release evidence IDs must be unique")
        caseIds = [result.caseId for result in self.redTeamResults]
        if len(caseIds) != len(set(caseIds)):
            raise ValueError("release red-team results must have unique case IDs")
        return self


class ReleaseGateReport(GovernanceModel):
    releaseId: str
    evaluatedAt: datetime
    decision: ReleaseDecision
    canRelease: bool
    inventoryHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    humanEvidenceComplete: bool
    gateResults: tuple[P0GateResult, ...]
    blockerGateIds: tuple[str, ...]
    blockerCategoryCounts: dict[str, int]
    blockerSummaries: tuple[dict[str, object], ...]
    useCaseAxes: tuple[dict[str, str], ...]


P0_GATES: tuple[P0GateDefinition, ...] = (
    P0GateDefinition(
        gateId="p0-component-inventory",
        title="Component inventory is complete and internally consistent",
        owner="Product & Research Lead",
        evaluator=GateEvaluator.INVENTORY,
        criterion="All critical model, prompt, market, network, metric, validation, and secret components are registered without duplicate IDs.",
        failureEffect="Release remains blocked until inventory integrity is restored.",
    ),
    P0GateDefinition(
        gateId="p0-red-team-definitions",
        title="Required red-team categories have executable definitions",
        owner="LLM & Evaluation Lead",
        evaluator=GateEvaluator.RED_TEAM_DEFINITIONS,
        criterion="Every required P0 attack category has a typed case, expected controls, weighted criteria, owner, and evidence references.",
        failureEffect="Release remains blocked because an attack surface is unassessed.",
    ),
    P0GateDefinition(
        gateId="p0-red-team-execution",
        title="All required red-team cases have passing execution evidence",
        owner="LLM & Evaluation Lead",
        evaluator=GateEvaluator.RED_TEAM_EXECUTIONS,
        criterion="Every registered P0 red-team case has been executed and scored PASS with any required human evidence verified.",
        failureEffect="Release remains blocked; a definition without an executed result is not evidence of safety.",
    ),
    P0GateDefinition(
        gateId="p0-structured-output-success",
        title="Structured model-output success rate meets the release threshold",
        owner="LLM & Evaluation Lead",
        evaluator=GateEvaluator.STRUCTURED_SUCCESS,
        criterion="Persisted site-wide model calls have a structured-output success rate of at least 95%.",
        failureEffect="Release remains blocked until real calls are observed and the structured-output success rate meets the threshold.",
    ),
    P0GateDefinition(
        gateId="p0-automated-tests",
        title="Automated backend and frontend test evidence is attached",
        owner="Full-stack / Platform & Design Lead",
        evaluator=GateEvaluator.EXTERNAL_EVIDENCE,
        requiredEvidenceType=EvidenceType.AUTOMATED_TEST_SUITE,
        criterion="A dated, hashed test artifact identifies the commit, environment, commands, pass counts, failures, and warnings.",
        failureEffect="Release remains blocked because unrecorded test claims cannot be audited.",
    ),
    P0GateDefinition(
        gateId="p0-flagship-replay",
        title="Flagship matched-seed artifact is reproducible",
        owner="Data & Quant Validation Lead",
        evaluator=GateEvaluator.EXTERNAL_EVIDENCE,
        requiredEvidenceType=EvidenceType.REPRODUCIBILITY_REPLAY,
        criterion="An independently rerun flagship artifact matches its declared configuration, seeds, versions, and event-log hashes.",
        failureEffect="Release remains blocked because the principal result cannot be reproduced.",
    ),
    P0GateDefinition(
        gateId="p0-user-comprehension",
        title="Target users distinguish scenario analysis from prediction",
        owner="Product & Research Lead",
        evaluator=GateEvaluator.EXTERNAL_EVIDENCE,
        requiredEvidenceType=EvidenceType.HUMAN_USER_RESEARCH,
        criterion="Observed target users complete the workflow and correctly explain the scenario, uncertainty, synthetic data, and non-advisory boundary.",
        failureEffect="Release remains blocked because systematic user misinterpretation is a release blocker.",
    ),
    P0GateDefinition(
        gateId="p0-domain-expert-review",
        title="Market and validation claims receive independent domain review",
        owner="Data & Quant Validation Lead",
        evaluator=GateEvaluator.EXTERNAL_EVIDENCE,
        requiredEvidenceType=EvidenceType.DOMAIN_EXPERT_REVIEW,
        criterion="A named independent reviewer evaluates market-mechanism assumptions, point-in-time handling, metric meaning, and stated limitations.",
        failureEffect="Release remains blocked because internal implementation checks cannot replace domain validation.",
    ),
    P0GateDefinition(
        gateId="p0-model-validation-review",
        title="LLM and grader behavior receive human validation",
        owner="LLM & Evaluation Lead",
        evaluator=GateEvaluator.EXTERNAL_EVIDENCE,
        requiredEvidenceType=EvidenceType.MODEL_VALIDATION_REVIEW,
        criterion="A named reviewer examines live-model outputs, multilingual behavior, abstention, grounding, failure modes, and grader disagreements.",
        failureEffect="Release remains blocked because code-only graders cannot establish semantic quality.",
    ),
    P0GateDefinition(
        gateId="p0-security-review",
        title="Deployment and BYOK controls receive human security review",
        owner="Full-stack / Platform & Design Lead",
        evaluator=GateEvaluator.EXTERNAL_EVIDENCE,
        requiredEvidenceType=EvidenceType.SECURITY_REVIEW,
        criterion="A named security reviewer checks TLS, reverse proxy, host access, logging, crash dumps, secret handling, isolation, export, and patch posture.",
        failureEffect="Release remains blocked because local unit tests do not prove deployment security.",
    ),
    P0GateDefinition(
        gateId="p0-license-review",
        title="Third-party data, model, and software terms receive human review",
        owner="Data & Quant Validation Lead",
        evaluator=GateEvaluator.EXTERNAL_EVIDENCE,
        requiredEvidenceType=EvidenceType.LICENSE_REVIEW,
        criterion="A named reviewer confirms public redistribution boundaries for sources, market data, model service use, software, and generated artifacts.",
        failureEffect="Release remains blocked because source availability is not redistribution permission.",
    ),
    P0GateDefinition(
        gateId="p0-incident-rehearsal",
        title="Incident containment and recovery runbook is rehearsed",
        owner="Full-stack / Platform & Design Lead",
        evaluator=GateEvaluator.EXTERNAL_EVIDENCE,
        requiredEvidenceType=EvidenceType.OPERATIONS_REHEARSAL,
        criterion="A named operator rehearses detection, containment, credential clearing, affected-run identification, invalidation, recovery, notification, and postmortem capture.",
        failureEffect="Release remains blocked because an untested runbook is not operational readiness.",
    ),
)


def _inventoryGate(gate: P0GateDefinition) -> P0GateResult:
    errors = validateInventory()
    return P0GateResult(
        gateId=gate.gateId,
        status=GateStatus.FAIL if errors else GateStatus.PASS,
        detail=(
            f"Inventory errors: {'; '.join(errors)}"
            if errors
            else "Component inventory passed structural and runtime-catalog consistency checks."
        ),
    )


def _redTeamDefinitionGate(gate: P0GateDefinition) -> P0GateResult:
    errors = validateRedTeamCases()
    return P0GateResult(
        gateId=gate.gateId,
        status=GateStatus.FAIL if errors else GateStatus.PASS,
        detail=(
            f"Red-team definition errors: {'; '.join(errors)}"
            if errors
            else "All required red-team categories have typed executable definitions."
        ),
    )


def _redTeamExecutionGate(gate: P0GateDefinition, context: ReleaseContext) -> P0GateResult:
    resultsById = {result.caseId: result for result in context.redTeamResults}
    expectedCaseIds = {case.caseId for case in RED_TEAM_CASES}
    missingCaseIds = sorted(expectedCaseIds - set(resultsById))
    if missingCaseIds:
        return P0GateResult(
            gateId=gate.gateId,
            status=GateStatus.NOT_EVALUATED,
            detail="Missing executed red-team results: " + ", ".join(missingCaseIds),
            evidenceIds=tuple(sorted(resultsById)),
        )
    failedCaseIds = sorted(
        caseId for caseId, result in resultsById.items() if result.status is RedTeamStatus.FAIL
    )
    if failedCaseIds:
        return P0GateResult(
            gateId=gate.gateId,
            status=GateStatus.FAIL,
            detail="Failed red-team cases: " + ", ".join(failedCaseIds),
            evidenceIds=tuple(sorted(resultsById)),
        )
    pendingCaseIds = sorted(
        caseId
        for caseId, result in resultsById.items()
        if result.status is RedTeamStatus.PENDING_HUMAN_EVIDENCE
    )
    if pendingCaseIds:
        return P0GateResult(
            gateId=gate.gateId,
            status=GateStatus.PENDING_HUMAN_EVIDENCE,
            detail="Red-team cases awaiting human evidence: " + ", ".join(pendingCaseIds),
            evidenceIds=tuple(sorted(resultsById)),
        )
    nonPassingCaseIds = sorted(
        caseId for caseId, result in resultsById.items() if result.status is not RedTeamStatus.PASS
    )
    if nonPassingCaseIds:
        return P0GateResult(
            gateId=gate.gateId,
            status=GateStatus.NOT_EVALUATED,
            detail="Red-team cases are not in PASS state: " + ", ".join(nonPassingCaseIds),
            evidenceIds=tuple(sorted(resultsById)),
        )
    coveredCategories = {result.category for result in resultsById.values()}
    if coveredCategories != REQUIRED_RED_TEAM_CATEGORIES:
        return P0GateResult(
            gateId=gate.gateId,
            status=GateStatus.FAIL,
            detail="Executed results do not cover the complete required category set.",
            evidenceIds=tuple(sorted(resultsById)),
        )
    return P0GateResult(
        gateId=gate.gateId,
        status=GateStatus.PASS,
        detail="Every required red-team case has an executed PASS result.",
        evidenceIds=tuple(sorted(resultsById)),
    )


def _structuredSuccessGate(
    gate: P0GateDefinition,
    context: ReleaseContext,
) -> P0GateResult:
    if context.structuredSuccessCalls == 0:
        return P0GateResult(
            gateId=gate.gateId,
            status=GateStatus.NOT_EVALUATED,
            detail=(
                "No persisted model-call observations are available; the structured-output "
                f"success threshold is {context.structuredSuccessThreshold:.1%}."
            ),
        )
    status = (
        GateStatus.PASS
        if context.structuredSuccessRate >= context.structuredSuccessThreshold
        else GateStatus.FAIL
    )
    return P0GateResult(
        gateId=gate.gateId,
        status=status,
        detail=(
            f"Structured-output success: {context.structuredSuccessRate:.1%} across "
            f"{context.structuredSuccessCalls} persisted calls; required "
            f"{context.structuredSuccessThreshold:.1%}."
        ),
    )


def _externalEvidenceGate(gate: P0GateDefinition, context: ReleaseContext) -> P0GateResult:
    requiredType = gate.requiredEvidenceType
    if requiredType is None:
        raise RuntimeError("external evidence gate is missing its evidence type")
    matching = tuple(item for item in context.evidence if item.evidenceType is requiredType)
    evidenceIds = tuple(item.evidenceId for item in matching)
    if any(item.status is EvidenceStatus.REJECTED for item in matching):
        return P0GateResult(
            gateId=gate.gateId,
            status=GateStatus.FAIL,
            detail=f"{requiredType.value} contains rejected evidence.",
            evidenceIds=evidenceIds,
        )
    verified = tuple(item for item in matching if item.status is EvidenceStatus.VERIFIED)
    if verified:
        return P0GateResult(
            gateId=gate.gateId,
            status=GateStatus.PASS,
            detail=f"Verified {requiredType.value} evidence is attached.",
            evidenceIds=tuple(item.evidenceId for item in verified),
        )
    if requiredType in HUMAN_EVIDENCE_TYPES:
        return P0GateResult(
            gateId=gate.gateId,
            status=GateStatus.PENDING_HUMAN_EVIDENCE,
            detail=f"{requiredType.value} is PENDING_HUMAN_EVIDENCE.",
            evidenceIds=evidenceIds,
        )
    return P0GateResult(
        gateId=gate.gateId,
        status=GateStatus.NOT_EVALUATED,
        detail=f"No verified {requiredType.value} artifact is attached.",
        evidenceIds=evidenceIds,
    )


def evaluateP0Release(context: ReleaseContext) -> ReleaseGateReport:
    gateResults: list[P0GateResult] = []
    for gate in P0_GATES:
        if gate.evaluator is GateEvaluator.INVENTORY:
            result = _inventoryGate(gate)
        elif gate.evaluator is GateEvaluator.RED_TEAM_DEFINITIONS:
            result = _redTeamDefinitionGate(gate)
        elif gate.evaluator is GateEvaluator.RED_TEAM_EXECUTIONS:
            result = _redTeamExecutionGate(gate, context)
        elif gate.evaluator is GateEvaluator.STRUCTURED_SUCCESS:
            result = _structuredSuccessGate(gate, context)
        else:
            result = _externalEvidenceGate(gate, context)
        gateResults.append(result)

    blockerGateIds = tuple(
        result.gateId for result in gateResults if result.status is not GateStatus.PASS
    )
    canRelease = not blockerGateIds
    humanGateIds = {
        gate.gateId for gate in P0_GATES if gate.requiredEvidenceType in HUMAN_EVIDENCE_TYPES
    }
    humanEvidenceComplete = all(
        result.status is GateStatus.PASS for result in gateResults if result.gateId in humanGateIds
    )
    gateDefinitions = {gate.gateId: gate for gate in P0_GATES}
    gateResultsById = {result.gateId: result for result in gateResults}
    blockerSummaries: list[dict[str, object]] = []
    blockerCategoryCounts: dict[str, int] = {}
    for gateId in blockerGateIds:
        definition = gateDefinitions[gateId]
        result = gateResultsById[gateId]
        category = (
            definition.requiredEvidenceType.value
            if definition.requiredEvidenceType is not None
            else definition.evaluator.value
        )
        blockerCategoryCounts[category] = blockerCategoryCounts.get(category, 0) + 1
        blockerSummaries.append(
            {
                "gateId": gateId,
                "category": category,
                "status": result.status.value,
                "owner": definition.owner,
                "requiredEvidence": (
                    definition.requiredEvidenceType.value
                    if definition.requiredEvidenceType is not None
                    else definition.criterion
                ),
                "evidenceIds": list(result.evidenceIds),
                "actionTarget": f"#gate-{gateId}",
            }
        )
    return ReleaseGateReport(
        releaseId=context.releaseId,
        evaluatedAt=context.evaluatedAt,
        decision=(
            ReleaseDecision.READY_FOR_CONTROLLED_DEMO if canRelease else ReleaseDecision.BLOCKED
        ),
        canRelease=canRelease,
        inventoryHash=inventoryHash(),
        humanEvidenceComplete=humanEvidenceComplete,
        gateResults=tuple(gateResults),
        blockerGateIds=blockerGateIds,
        blockerCategoryCounts=dict(sorted(blockerCategoryCounts.items())),
        blockerSummaries=tuple(blockerSummaries),
        useCaseAxes=(
            {
                "axisId": "CONTROLLED_DEMO",
                "label": "Controlled educational demo",
                "status": "ALLOWED_WITH_BOUNDARIES",
                "boundary": "Synthetic mechanism demonstration only.",
            },
            {
                "axisId": "INTERNAL_RESEARCH_PROTOTYPE",
                "label": "Internal research prototype",
                "status": "ALLOWED_WITH_BOUNDARIES",
                "boundary": "Exploratory internal use with explicit limitations and audit evidence.",
            },
            {
                "axisId": "REAL_WORLD_PREDICTIVE_CLAIM",
                "label": "Real-world predictive claim",
                "status": "BLOCKED",
                "boundary": "No external predictive validation has been completed.",
            },
            {
                "axisId": "INVESTMENT_DECISION",
                "label": "Investment decision support",
                "status": "PROHIBITED",
                "boundary": "The system is not investment advice or a trading signal.",
            },
            {
                "axisId": "PRODUCTION_EXTERNAL_VALIDATION",
                "label": "Production / external validation",
                "status": "BLOCKED" if not canRelease else "READY_FOR_CONTROLLED_REVIEW",
                "boundary": "Requires every release gate and independent human evidence.",
            },
        ),
    )


_GATE_IDS = [gate.gateId for gate in P0_GATES]
if len(_GATE_IDS) != len(set(_GATE_IDS)):
    raise RuntimeError("P0 gate IDs must be unique")
