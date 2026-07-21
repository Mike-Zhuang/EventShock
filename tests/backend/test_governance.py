from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.cognition.catalog import listModels
from backend.app.cognition.prompts import PROMPT_REGISTRY
from backend.app.governance.redteam import (
    RED_TEAM_CASES,
    REQUIRED_RED_TEAM_CATEGORIES,
    HumanEvidenceStatus,
    RedTeamCategory,
    RedTeamExecution,
    RedTeamStatus,
    redTeamCaseById,
    scoreRedTeamCase,
    scoreRedTeamSuite,
    validateRedTeamCases,
)
from backend.app.governance.registry import (
    COMPONENT_INVENTORY,
    ApprovalStatus,
    ComponentKind,
    inventoryHash,
    inventorySnapshot,
    listComponents,
    validateInventory,
)
from backend.app.governance.release_gate import (
    HUMAN_EVIDENCE_TYPES,
    P0_GATES,
    EvidenceStatus,
    EvidenceType,
    GateStatus,
    ReleaseContext,
    ReleaseDecision,
    ReleaseEvidence,
    evaluateP0Release,
)

EXECUTED_AT = datetime(2026, 7, 16, 4, 0, tzinfo=UTC)


def test_component_inventory_is_strict_complete_and_runtime_aligned() -> None:
    assert validateInventory() == ()
    componentIds = [record.componentId for record in COMPONENT_INVENTORY]
    assert len(componentIds) == len(set(componentIds))

    requiredKinds = {
        ComponentKind.RULE_AGENT,
        ComponentKind.MATCHING_ENGINE,
        ComponentKind.INFORMATION_NETWORK,
        ComponentKind.PROVIDER_MODEL,
        ComponentKind.PROMPT,
        ComponentKind.METRIC_COMPONENT,
        ComponentKind.VALIDATION_COMPONENT,
    }
    assert requiredKinds.issubset({record.kind for record in COMPONENT_INVENTORY})

    providerModelRoutes = {
        (record.modelDetails.provider, record.modelDetails.modelId)
        for record in listComponents(kind=ComponentKind.PROVIDER_MODEL)
        if record.modelDetails is not None
    }
    assert providerModelRoutes == {(model.provider, model.model_id) for model in listModels()}
    assert {provider for provider, _model in providerModelRoutes} == {
        "zhipu",
        "openai",
        "anthropic",
        "google",
        "deepseek",
        "alibaba",
        "moonshot",
    }
    assert all(
        record.approvalStatus is ApprovalStatus.PENDING_HUMAN_EVIDENCE
        for record in listComponents(kind=ComponentKind.PROVIDER_MODEL)
    )

    promptHashes = {
        record.promptDetails.promptHash
        for record in listComponents(kind=ComponentKind.PROMPT)
        if record.promptDetails is not None
    }
    assert promptHashes == {prompt.promptHash for prompt in PROMPT_REGISTRY}
    assert len(inventoryHash()) == 64
    assert all(character in "0123456789abcdef" for character in inventoryHash())

    snapshot = inventorySnapshot()
    assert snapshot
    assert all("schema" in item for item in snapshot)
    assert all("schemaRef" not in item for item in snapshot)
    for item in snapshot:
        for requiredField in (
            "owner",
            "purpose",
            "materiality",
            "version",
            "schema",
            "inputs",
            "outputs",
            "validation",
            "limitations",
            "fallback",
            "approvalStatus",
        ):
            assert item[requiredField]


def test_red_team_registry_covers_every_required_attack_category() -> None:
    assert validateRedTeamCases() == ()
    assert {case.category for case in RED_TEAM_CASES} == REQUIRED_RED_TEAM_CATEGORIES
    assert len(RED_TEAM_CASES) >= 10
    componentIds = {record.componentId for record in COMPONENT_INVENTORY}
    assert all(set(case.targetComponentIds) <= componentIds for case in RED_TEAM_CASES)
    assert all(
        "cognition.zhipu-rest-gateway" not in case.targetComponentIds for case in RED_TEAM_CASES
    )
    assert {category.value for category in RedTeamCategory} == {
        "PROMPT_INJECTION",
        "FUTURE_LEAKAGE",
        "UNKNOWN_EVIDENCE",
        "ACTION_OVERREACH",
        "SCHEMA_DRIFT",
        "CROSS_SESSION",
        "COST_EXHAUSTION",
        "SOURCE_TIER_PROMOTION",
        "EXPORT_TRAVERSAL",
        "SECRET_DISCLOSURE",
    }


def test_red_team_validation_rejects_a_stale_component_target() -> None:
    staleCase = RED_TEAM_CASES[0].model_copy(
        update={"targetComponentIds": ("cognition.retired-provider-gateway",)}
    )
    errors = validateRedTeamCases((staleCase, *RED_TEAM_CASES[1:]))

    assert errors == (
        "red-team case rt-prompt-injection-001 targets unknown components: "
        "cognition.retired-provider-gateway",
    )


def test_red_team_case_scoring_is_deterministic_and_critical_failure_blocks() -> None:
    case = redTeamCaseById("rt-prompt-injection-001")
    passingExecution = RedTeamExecution(
        caseId=case.caseId,
        executedAt=EXECUTED_AT,
        instructionFollowed=False,
        unauthorizedActionOccurred=False,
        secretExposed=False,
        artifactRefs=("test-artifact://prompt-injection-pass",),
    )
    passing = scoreRedTeamCase(case, passingExecution)
    repeated = scoreRedTeamCase(case, passingExecution)

    assert passing == repeated
    assert passing.status is RedTeamStatus.PASS
    assert passing.passed is True
    assert passing.score == 1.0

    failing = scoreRedTeamCase(
        case,
        passingExecution.model_copy(update={"instructionFollowed": True}),
    )
    assert failing.status is RedTeamStatus.FAIL
    assert failing.passed is False
    assert failing.score < 1.0


def test_red_team_suite_does_not_treat_unexecuted_definitions_as_evidence() -> None:
    results = scoreRedTeamSuite(())

    assert len(results) == len(RED_TEAM_CASES)
    assert all(result.status is RedTeamStatus.NOT_RUN for result in results)
    assert all(result.passed is False for result in results)


def test_secret_disclosure_case_requires_real_human_evidence() -> None:
    case = redTeamCaseById("rt-secret-disclosure-001")
    automatedOnly = scoreRedTeamCase(
        case,
        RedTeamExecution(
            caseId=case.caseId,
            executedAt=EXECUTED_AT,
            secretExposed=False,
            secretRedacted=True,
            humanEvidenceStatus=HumanEvidenceStatus.PENDING_HUMAN_EVIDENCE,
            artifactRefs=("test-artifact://automated-secret-scan",),
        ),
    )

    assert automatedOnly.score == 1.0
    assert automatedOnly.passed is False
    assert automatedOnly.status is RedTeamStatus.PENDING_HUMAN_EVIDENCE


def test_verified_human_evidence_cannot_omit_reviewer_or_artifact() -> None:
    with pytest.raises(ValidationError):
        ReleaseEvidence(
            evidenceId="human-review-invalid",
            evidenceType=EvidenceType.HUMAN_USER_RESEARCH,
            status=EvidenceStatus.VERIFIED,
            summary="This invalid fixture lacks reviewer and artifact evidence.",
        )

    with pytest.raises(ValidationError):
        ReleaseEvidence(
            evidenceId="human-review-ai-reviewer",
            evidenceType=EvidenceType.SECURITY_REVIEW,
            status=EvidenceStatus.VERIFIED,
            summary="This invalid fixture attempts to use an AI as the reviewer.",
            artifactUri="test-artifact://invalid-ai-review",
            evidenceHash=f"sha256:{'a' * 64}",
            collectedAt=EXECUTED_AT,
            reviewerName="Codex",
            reviewerRole="Automated model",
            attestation="I completed a human security review of the deployment controls.",
        )

    pending = ReleaseEvidence(
        evidenceId="human-review-pending",
        evidenceType=EvidenceType.DOMAIN_EXPERT_REVIEW,
        status=EvidenceStatus.PENDING_HUMAN_EVIDENCE,
        summary="Independent domain-expert review has not yet been performed.",
    )
    assert pending.status is EvidenceStatus.PENDING_HUMAN_EVIDENCE


def test_default_release_gate_is_blocked_and_preserves_pending_human_state() -> None:
    context = ReleaseContext(
        releaseId="governance-test-release",
        evaluatedAt=EXECUTED_AT,
    )
    report = evaluateP0Release(context)

    assert report.decision is ReleaseDecision.BLOCKED
    assert report.canRelease is False
    assert report.humanEvidenceComplete is False
    assert len(report.gateResults) == len(P0_GATES)

    byGateId = {result.gateId: result for result in report.gateResults}
    assert byGateId["p0-component-inventory"].status is GateStatus.PASS
    assert byGateId["p0-red-team-definitions"].status is GateStatus.PASS
    assert byGateId["p0-red-team-execution"].status is GateStatus.NOT_EVALUATED
    for gate in P0_GATES:
        if gate.requiredEvidenceType in HUMAN_EVIDENCE_TYPES:
            assert byGateId[gate.gateId].status is GateStatus.PENDING_HUMAN_EVIDENCE


def test_automated_test_artifact_cannot_satisfy_human_release_gates() -> None:
    automatedEvidence = ReleaseEvidence(
        evidenceId="automated-tests-fixture",
        evidenceType=EvidenceType.AUTOMATED_TEST_SUITE,
        status=EvidenceStatus.VERIFIED,
        summary="Synthetic unit-test fixture proving only the release-gate evidence contract.",
        artifactUri="test-artifact://pytest-fixture",
        evidenceHash=f"sha256:{'b' * 64}",
        collectedAt=EXECUTED_AT,
    )
    report = evaluateP0Release(
        ReleaseContext(
            releaseId="automated-evidence-only",
            evaluatedAt=EXECUTED_AT,
            evidence=(automatedEvidence,),
        )
    )
    byGateId = {result.gateId: result for result in report.gateResults}

    assert byGateId["p0-automated-tests"].status is GateStatus.PASS
    assert byGateId["p0-user-comprehension"].status is GateStatus.PENDING_HUMAN_EVIDENCE
    assert byGateId["p0-domain-expert-review"].status is GateStatus.PENDING_HUMAN_EVIDENCE
    assert report.canRelease is False
