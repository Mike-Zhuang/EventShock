from types import SimpleNamespace

import pytest

from backend.app.guided_workflow.models import GuidedStage
from backend.app.prepared_guided_path_cli import (
    INTERPRETATION_QUESTION,
    INTERPRETATION_REQUIRED_TERMS,
    _eventMetadata,
    _stageCopy,
    _validatePreparedInterpretation,
)


def test_prepared_gold_path_matches_bilingual_presentation_story() -> None:
    metadata = _eventMetadata()
    copy = _stageCopy(provider="zhipu", model="glm-5.2")

    assert "5,600" in str(metadata["summary"])
    assert "4,675" in str(metadata["summary"])
    assert "避险需求" in str(metadata["summaryZh"])
    assert len(copy["en"][GuidedStage.SOURCE_REVIEW.value]["reviewItems"]) == 5
    assert len(copy["zh-CN"][GuidedStage.SOURCE_REVIEW.value]["reviewItems"]) == 5
    assert len(copy["en"][GuidedStage.CLAIM_REVIEW.value]["reviewItems"]) == 9
    assert len(copy["zh-CN"][GuidedStage.CLAIM_REVIEW.value]["reviewItems"]) == 9


def test_prepared_path_exposes_stage_specific_selectable_replies() -> None:
    copy = _stageCopy(provider="zhipu", model="glm-5.2")
    replies = [
        copy["en"][stage.value]["nextQuestionOptions"][0]
        for stage in GuidedStage
        if stage is not GuidedStage.COMPLETED
    ]

    assert len(replies) == len(set(replies))
    assert all(len(reply) > 40 for reply in replies)
    assert "five" in copy["en"][GuidedStage.SOURCE_REVIEW.value]["nextQuestionOptions"][0]
    assert (
        "zero rule fallback"
        in copy["en"][GuidedStage.PREFLIGHT.value]["nextQuestionOptions"][0]
    )


def _interpretationRun(*, deterministicFallbackUsed: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        provider="zhipu",
        model="glm-5.2",
        deterministic_fallback_used=deterministicFallbackUsed,
        semantic_validation_status=(
            "DETERMINISTIC_FALLBACK" if deterministicFallbackUsed else "PASSED"
        ),
        interpretation=SimpleNamespace(
            answer=(
                "Xiaoming saw gold move from 5,600 to 4,675 as safe-haven demand competed "
                "with liquidity stress, an oil shock, forced selling, and lower market-making "
                "capacity. [result:overview]"
            ),
            grounding_references=("result:overview",),
        ),
    )


def test_prepared_interpretation_is_grounded_in_the_presentation_story() -> None:
    assert "5,600" in INTERPRETATION_QUESTION
    assert "4,675" in INTERPRETATION_QUESTION
    assert "Xiaoming" in INTERPRETATION_QUESTION
    assert {"5,600", "4,675", "xiaoming"}.issubset(INTERPRETATION_REQUIRED_TERMS)
    _validatePreparedInterpretation(
        _interpretationRun(),
        provider="zhipu",
        model="glm-5.2",
    )


def test_prepared_interpretation_rejects_server_fallback_text() -> None:
    with pytest.raises(ValueError, match="deterministic fallback"):
        _validatePreparedInterpretation(
            _interpretationRun(deterministicFallbackUsed=True),
            provider="zhipu",
            model="glm-5.2",
        )
