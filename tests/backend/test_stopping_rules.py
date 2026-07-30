from __future__ import annotations

from typing import Any

from backend.app.service import ExperimentService, _stoppingDecision


def _request(*, minimumPairs: int, maximumPairs: int, targetHalfWidth: float) -> dict[str, Any]:
    return {
        "primaryOutcome": "maxSpreadBps",
        "seedRoot": 123_000,
        "seedCount": maximumPairs,
        "stoppingRule": {
            "minimumPairs": minimumPairs,
            "maximumPairs": maximumPairs,
            "targetCiHalfWidth": targetHalfWidth,
        },
    }


def _runs(pairCount: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    baseline = [{"metrics": {"maxSpreadBps": 10.0 + index}} for index in range(pairCount)]
    intervention = [{"metrics": {"maxSpreadBps": 12.0 + index}} for index in range(pairCount)]
    return baseline, intervention


def test_minimum_equal_maximum_records_simultaneous_terminal_reasons_in_order() -> None:
    request = _request(minimumPairs=10, maximumPairs=10, targetHalfWidth=0.01)
    previous = ExperimentService._initialStoppingDecision(request)

    for pairCount in range(1, 11):
        baseline, intervention = _runs(pairCount)
        previous = _stoppingDecision(
            request,
            baseline,
            intervention,
            previous=previous,
        )

    assert previous["triggered"] is True
    assert previous["reason"] == "MAXIMUM_PAIRS_REACHED"
    assert previous["primaryReason"] == "MAXIMUM_PAIRS_REACHED"
    assert previous["reasons"] == [
        "MAXIMUM_PAIRS_REACHED",
        "TARGET_CI_HALF_WIDTH_REACHED",
    ]
    assert previous["conditionEvaluations"] == [
        {
            "code": "MINIMUM_PAIRS_REACHED",
            "evaluationOrder": 1,
            "satisfied": True,
            "firstSatisfiedAtPair": 10,
        },
        {
            "code": "MAXIMUM_PAIRS_REACHED",
            "evaluationOrder": 2,
            "satisfied": True,
            "firstSatisfiedAtPair": 10,
        },
        {
            "code": "TARGET_CI_HALF_WIDTH_REACHED",
            "evaluationOrder": 3,
            "satisfied": True,
            "firstSatisfiedAtPair": 10,
        },
    ]


def test_precision_target_before_maximum_remains_the_only_terminal_reason() -> None:
    request = _request(minimumPairs=5, maximumPairs=10, targetHalfWidth=0.01)
    previous = ExperimentService._initialStoppingDecision(request)
    baseline, intervention = _runs(5)

    decision = _stoppingDecision(
        request,
        baseline,
        intervention,
        previous=previous,
    )

    assert decision["triggered"] is True
    assert decision["reason"] == "TARGET_CI_HALF_WIDTH_REACHED"
    assert decision["reasons"] == ["TARGET_CI_HALF_WIDTH_REACHED"]
    maximum = next(
        item for item in decision["conditionEvaluations"] if item["code"] == "MAXIMUM_PAIRS_REACHED"
    )
    assert maximum["satisfied"] is False
    assert maximum["firstSatisfiedAtPair"] is None
