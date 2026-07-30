from __future__ import annotations

from datetime import UTC, datetime

from backend.app.event_pack_claims import (
    buildLlmClaimQualityMetadata,
    extractRuleFallbackClaims,
    inferImpactChannels,
    preprocessSourceText,
)
from backend.app.schemas import EventSourceInput

FAA_TEXT = """\
AIRWORTHINESS DIRECTIVE
www.faa.gov/aircraft/safety/alerts/
DATE: January 6, 2024
Emergency Airworthiness Directive (AD) 2024-02-51 is sent to owners and operators of The
Boeing Company Model 737-9 airplanes.
This emergency AD was prompted by a report of an in-flight departure of a mid cabin door
plug, which resulted in a rapid decompression of the airplane.
The FAA is issuing this AD to address
the potential in-flight loss of a mid cabin door plug, which could result in injury to passengers
and
crew, the door impacting the airplane, and/or loss of control of the airplane.
This AD prohibits further flight of affected airplanes, until the airplane is inspected and all
applicable corrective actions have been performed using a method approved by the Manager.
The FAA considers this AD to be an interim action.
"""


def source(rawText: str = FAA_TEXT) -> EventSourceInput:
    timestamp = datetime(2024, 1, 6, 23, 59, tzinfo=UTC)
    return EventSourceInput(
        sourceId="faa-ad-2024-02-51",
        title="Emergency Airworthiness Directive 2024-02-51",
        publisher="Federal Aviation Administration",
        url="https://www.faa.gov/aircraft/safety/alerts/",
        sourceType="OFFICIAL",
        publishedAt=timestamp,
        knownAt=timestamp,
        rawText=rawText,
    )


def test_preprocessing_removes_document_noise_and_joins_wrapped_sentences() -> None:
    sentences = preprocessSourceText(FAA_TEXT)

    assert sentences
    assert all("www.faa.gov" not in item for item in sentences)
    assert all(item != "DATE: January 6, 2024" for item in sentences)
    assert all(item != "AIRWORTHINESS DIRECTIVE" for item in sentences)
    assert any("The Boeing Company Model 737-9 airplanes." in item for item in sentences)
    assert any("door plug, which resulted in a rapid decompression" in item for item in sentences)
    assert any(
        "injury to passengers and crew, the door impacting the airplane" in item
        for item in sentences
    )
    assert all(not item.endswith(("The", "door", "and")) for item in sentences)


def test_rule_fallback_claims_are_review_only_and_not_mechanically_all_channel() -> None:
    claims = extractRuleFallbackClaims([source()], maximumClaims=16)

    assert 3 <= len(claims) < 16
    assert all(item["extractionQuality"] == "RULE_FALLBACK_REVIEW_REQUIRED" for item in claims)
    assert all(item["bulkApprovalEligible"] is False for item in claims)
    assert all(
        item["confidenceMeaning"] == "EXTRACTION_FIDELITY_NOT_EVENT_PROBABILITY" for item in claims
    )
    assert all(1 <= len(item["impactChannels"]) <= 2 for item in claims)
    assert all(
        len(item["impactChannelRationale"]) == len(item["impactChannels"]) for item in claims
    )
    assert any(item["impactChannels"] == ["belief"] for item in claims)
    assert any("liquidity" in item["impactChannels"] for item in claims)
    assert all(item["confidence"] < 0.99 for item in claims)


def test_semantic_duplicate_sentences_are_collapsed() -> None:
    duplicateText = (
        "The agency suspended affected operations until the required inspection was completed.\n"
        "The agency suspended affected operations until the required inspection was completed.\n"
    )

    claims = extractRuleFallbackClaims([source(duplicateText)], maximumClaims=10)

    assert len(claims) == 1


def test_impact_channel_inference_uses_explicit_mechanism_language() -> None:
    passive = inferImpactChannels(
        "The ETF will rebalance after benchmark inclusion and create passive fund flows."
    )
    stopLoss = inferImpactChannels(
        "A margin call can trigger forced liquidation after the price threshold is crossed."
    )

    assert passive == ["passiveFlow"]
    assert stopLoss == ["stopLoss"]


def test_llm_claim_quality_separates_model_score_from_local_quality() -> None:
    timestamp = datetime(2024, 1, 6, 23, 59, tzinfo=UTC)

    metadata = buildLlmClaimQualityMetadata(
        (
            "This AD prohibits further flight until the airplane is inspected and "
            "applicable corrective actions are completed."
        ),
        sourceTypes=("OFFICIAL",),
        publishedAt=timestamp,
        knownAt=timestamp,
        requestedImpactChannels=("belief", "liquidity", "passiveFlow", "stopLoss"),
        modelReportedConfidence=0.99,
    )

    assert metadata["modelReportedConfidence"] == 0.99
    assert metadata["confidence"] < 0.99
    assert metadata["confidenceMeaning"] == "EXTRACTION_FIDELITY_NOT_EVENT_PROBABILITY"
    assert metadata["impactChannels"] == ["liquidity"]
    assert metadata["channelMappingIsInference"] is True
    assert len(metadata["impactChannelRationale"]) == 1
