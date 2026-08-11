from __future__ import annotations

from typing import Any

from backend.app.cognition.models import ResultInterpretationAnswer
from backend.app.cognition.result_semantics import (
    SemanticViolationCode,
    buildResultFactCatalog,
    deterministicInterpretationFallback,
    strongestMetricFacts,
    validateInterpretationSemantics,
)


def sampleResult() -> dict[str, Any]:
    return {
        "metricSummaries": {
            "maxSpreadBps": {
                "baseline": {"median": 10.0},
                "intervention": {"median": 11.5},
                "delta": {
                    "median": 1.5,
                    "validN": 10,
                    "directionConsistencyRate": 0.7,
                    "bootstrap95": {
                        "lower": -0.2,
                        "upper": 3.1,
                        "containsZero": True,
                    },
                },
            },
            "minDepth": {
                "baseline": {"median": 55.0},
                "intervention": {"median": 38.0},
                "delta": {
                    "median": -17.0,
                    "validN": 10,
                    "directionConsistencyRate": 1.0,
                    "bootstrap95": {
                        "lower": -28.0,
                        "upper": -7.0,
                        "containsZero": False,
                    },
                },
            },
        },
        "analysisDiagnostics": {
            "preregisteredPrimaryOutcome": "maxSpreadBps",
        },
        "manifest": {"validPairedSeeds": 10},
        "stoppingRule": {"reason": "FIXED_PAIR_COUNT_REACHED"},
        "cognition": {
            "calls": 2,
            "fallbackCount": 1,
            "validCognitionDecisionCount": 4,
            "cognitionSignalConsumedCount": 4,
            "cognitionChangedIntentCount": 0,
            "cognitionInfluencedOrderCount": 0,
            "cognitionBlockedByRiskCount": 0,
            "cognitionNoActionCount": 4,
            "decisions": [
                {"decisionRound": 0},
                {"decisionRound": 0},
                {"decisionRound": 1},
                {"decisionRound": 2},
            ],
        },
    }


def answer(text: str) -> ResultInterpretationAnswer:
    return ResultInterpretationAnswer(
        answer=f"{text} [result:metric-summary]",
        grounding_references=("result:metric-summary",),
    )


def violationCodes(text: str) -> set[SemanticViolationCode]:
    report = validateInterpretationSemantics(
        answer(text),
        sampleResult(),
        requirePrimaryFinding=False,
    )
    return set(report.violation_codes)


def test_fact_catalog_preserves_server_computed_metric_facts() -> None:
    catalog = buildResultFactCatalog(sampleResult())

    spread = catalog.metric("maxSpreadBps")
    assert spread is not None
    assert spread.paired_difference_median == 1.5
    assert spread.interval_lower == -0.2
    assert spread.interval_upper == 3.1
    assert spread.contains_zero is True
    assert spread.direction_consistency == 0.7
    assert spread.valid_n == 10
    assert spread.preregistered_primary is True
    assert catalog.valid_paired_seeds == 10
    assert catalog.stopping_reason == "FIXED_PAIR_COUNT_REACHED"


def test_strongest_metrics_keep_primary_first_then_non_crossing_interval() -> None:
    strongest = strongestMetricFacts(buildResultFactCatalog(sampleResult()))

    assert [item.metric_id for item in strongest] == ["maxSpreadBps", "minDepth"]


def test_semantic_validator_rejects_strong_claim_when_interval_crosses_zero() -> None:
    codes = violationCodes(
        "The maxSpreadBps increase is statistically significant; its paired median is 1.5."
    )

    assert SemanticViolationCode.INTERVAL_CROSSES_ZERO_STRONG_CLAIM in codes


def test_semantic_validator_rejects_wrong_metric_direction() -> None:
    codes = violationCodes("The maxSpreadBps decreased by 1.5.")

    assert SemanticViolationCode.DIRECTION_MISMATCH in codes


def test_semantic_validator_rejects_wrong_direction_consistency() -> None:
    codes = violationCodes(
        "The maxSpreadBps paired median is 1.5 and direction consistency is 80%."
    )

    assert SemanticViolationCode.DIRECTION_CONSISTENCY_MISMATCH in codes


def test_semantic_validator_rejects_unsupported_metric_number() -> None:
    report = validateInterpretationSemantics(
        answer("The maxSpreadBps paired median increased by 9.9."),
        sampleResult(),
        requirePrimaryFinding=False,
    )

    assert SemanticViolationCode.METRIC_NUMBER_UNSUPPORTED in report.violation_codes
    assert SemanticViolationCode.METRIC_NUMBER_UNSUPPORTED in report.advisory_violation_codes
    assert report.valid is True


def test_semantic_validator_rejects_negative_delta_described_as_raw_depth() -> None:
    codes = violationCodes("The minimum market depth was -17.")

    assert SemanticViolationCode.DELTA_VALUE_MISREPRESENTED_AS_RAW in codes


def test_semantic_validator_rejects_denial_of_available_interval() -> None:
    codes = violationCodes(
        "No confidence interval is available for maxSpreadBps, whose paired median is 1.5."
    )

    assert SemanticViolationCode.AVAILABLE_INTERVAL_DENIED in codes


def test_semantic_validator_requires_preregistered_primary_finding() -> None:
    report = validateInterpretationSemantics(
        answer("The minDepth paired median decreased by 17."),
        sampleResult(),
        requirePrimaryFinding=True,
    )

    assert SemanticViolationCode.REQUIRED_PRIMARY_FINDING_OMITTED in report.violation_codes
    assert report.valid is True


def test_semantic_validator_rejects_empty_metric_answer_on_initial_turn() -> None:
    report = validateInterpretationSemantics(
        answer("This experiment should be read cautiously."),
        sampleResult(),
        requirePrimaryFinding=True,
    )

    assert SemanticViolationCode.REQUIRED_PRIMARY_FINDING_OMITTED in report.violation_codes
    assert SemanticViolationCode.REQUIRED_STRONGEST_FINDING_OMITTED in report.violation_codes
    assert report.valid is True


def test_semantic_validator_requires_non_crossing_strongest_finding() -> None:
    report = validateInterpretationSemantics(
        answer(
            "The maxSpreadBps paired median increased by 1.5, while the empirical "
            "95% interval [-0.2, 3.1] crosses zero and direction consistency is 70%."
        ),
        sampleResult(),
        requirePrimaryFinding=True,
    )

    assert SemanticViolationCode.REQUIRED_STRONGEST_FINDING_OMITTED in report.violation_codes


def test_semantic_validator_rejects_wrong_stopping_reason() -> None:
    codes = violationCodes(
        "The experiment stopped because the target confidence interval half-width was reached."
    )

    assert SemanticViolationCode.STOPPING_REASON_UNSUPPORTED in codes


def test_semantic_validator_rejects_sample_savings_when_target_and_maximum_coincide() -> None:
    result = sampleResult()
    result["stoppingRule"] = {
        "reason": "MAXIMUM_PAIRS_REACHED",
        "primaryReason": "MAXIMUM_PAIRS_REACHED",
        "reasons": [
            "MAXIMUM_PAIRS_REACHED",
            "TARGET_CI_HALF_WIDTH_REACHED",
        ],
        "completedPairs": 10,
        "maximumPairs": 10,
    }

    catalog = buildResultFactCatalog(result)
    assert catalog.stopping_reasons == (
        "MAXIMUM_PAIRS_REACHED",
        "TARGET_CI_HALF_WIDTH_REACHED",
    )
    report = validateInterpretationSemantics(
        answer("The target stopped the experiment early and saved five sample pairs."),
        result,
        requirePrimaryFinding=False,
    )

    assert SemanticViolationCode.STOPPING_REASON_UNSUPPORTED in report.violation_codes


def test_semantic_validator_keeps_negative_control_and_restoration_distinct() -> None:
    conflated = violationCodes(
        "The negative control is the parameter-restoration knockout validation."
    )
    distinguished = violationCodes(
        "The negative control and parameter-restoration knockout are distinct checks."
    )

    assert SemanticViolationCode.DIAGNOSTIC_TYPE_CONFLATED in conflated
    assert SemanticViolationCode.DIAGNOSTIC_TYPE_CONFLATED not in distinguished


def test_semantic_validator_rejects_wrong_cognition_counts_and_effect_claim() -> None:
    codes = violationCodes(
        "There were 6 LLM calls and 4 decision rounds, and the LLM changed orders "
        "in the simulated market."
    )

    assert SemanticViolationCode.COGNITION_COUNT_MISMATCH in codes
    assert SemanticViolationCode.COGNITION_EFFECT_UNSUPPORTED in codes


def test_semantic_validator_rejects_direct_order_boundary_as_zero_effect_cause() -> None:
    codes = violationCodes("This means the LLM did not submit direct orders.")

    assert SemanticViolationCode.COGNITION_ZERO_EFFECT_CAUSE_UNSUPPORTED in codes


def test_semantic_validator_accepts_supported_cautious_facts() -> None:
    report = validateInterpretationSemantics(
        answer(
            "The maxSpreadBps paired median increased by 1.5, while the empirical "
            "95% interval [-0.2, 3.1] crosses zero and direction consistency is 70%. "
            "The minDepth paired difference was -17, with an empirical interval "
            "[-28, -7] that does not cross zero."
        ),
        sampleResult(),
        requirePrimaryFinding=True,
    )

    assert report.valid is True
    assert report.violation_codes == ()


def test_deterministic_fallback_uses_only_catalog_facts_and_allowed_references() -> None:
    fallback = deterministicInterpretationFallback(
        sampleResult(),
        language="zh-CN",
        includeAnalysisSummary=True,
    )

    assert "maxSpreadBps" in fallback.answer
    assert "1.5" in fallback.answer
    assert "[-0.2, 3.1]" in fallback.answer
    assert "区间跨过零" in fallback.answer
    assert fallback.grounding_references == (
        "result:metric-summary",
        "result:overview",
        "result:limitations",
    )
    assert fallback.analysis_summary is not None
