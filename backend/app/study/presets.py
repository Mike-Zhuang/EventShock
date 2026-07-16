"""蓝图要求的负对照与消融规格预设。"""

from __future__ import annotations

from collections.abc import Mapping

from backend.app.study.models import (
    AblationKind,
    AblationSpec,
    ControlExpectation,
    EvidenceBasis,
    NegativeControlKind,
    NegativeControlSpec,
    OutcomeSpec,
    OutcomeTolerance,
    ParameterSetting,
)


def buildRequiredNegativeControls(
    primaryOutcomes: tuple[OutcomeSpec, ...],
    *,
    nullToleranceByOutcome: Mapping[str, float],
) -> tuple[NegativeControlSpec, ...]:
    """构造 14.13 的完整控制集合，容忍度必须由研究者预注册。"""

    expectedIds = {outcome.outcomeId for outcome in primaryOutcomes}
    if set(nullToleranceByOutcome) != expectedIds:
        raise ValueError("nullToleranceByOutcome must exactly match primary outcome IDs")
    tolerances = tuple(
        OutcomeTolerance(
            outcomeId=outcome.outcomeId,
            unit=outcome.unit,
            absoluteTolerance=nullToleranceByOutcome[outcome.outcomeId],
        )
        for outcome in primaryOutcomes
    )

    return (
        NegativeControlSpec(
            controlId="baseline-self",
            kind=NegativeControlKind.BASELINE_SELF,
            settings=(),
            tolerances=tolerances,
            rationale="Repeat the unchanged baseline with identical seeds.",
            expectation=ControlExpectation.NULL_EFFECT,
        ),
        NegativeControlSpec(
            controlId="irrelevant-event",
            kind=NegativeControlKind.IRRELEVANT_EVENT,
            settings=(
                _syntheticBooleanSetting(
                    "control.irrelevant_event_injected",
                    "Inject a declared synthetic event unrelated to the modeled asset.",
                ),
            ),
            tolerances=tolerances,
            rationale="An unrelated event should not systematically move preregistered outcomes.",
            expectation=ControlExpectation.NULL_EFFECT,
        ),
        NegativeControlSpec(
            controlId="misplaced-event-time",
            kind=NegativeControlKind.MISPLACED_EVENT_TIME,
            settings=(
                _syntheticBooleanSetting(
                    "control.seeded_event_time_placebo",
                    "Move event time using the run seed while preserving the event payload.",
                ),
            ),
            tolerances=tolerances,
            rationale="A seeded time placebo tests whether any timestamp creates an effect.",
            expectation=ControlExpectation.NULL_EFFECT,
        ),
        NegativeControlSpec(
            controlId="label-swap-text-held",
            kind=NegativeControlKind.LABEL_SWAP_TEXT_HELD,
            settings=(
                _syntheticBooleanSetting(
                    "control.label_swap_text_held",
                    "Swap the declared label while holding source text constant.",
                ),
            ),
            tolerances=tolerances,
            rationale="A text-bound model should not react only to an arbitrary label.",
            expectation=ControlExpectation.NULL_EFFECT,
        ),
        NegativeControlSpec(
            controlId="disable-social-control",
            kind=NegativeControlKind.DISABLE_SOCIAL,
            settings=(
                _syntheticBooleanSetting(
                    "network.social_enabled",
                    "Disable social propagation while leaving external facts unchanged.",
                    value=False,
                ),
            ),
            tolerances=(),
            rationale="Diagnose the model-internal contribution of social propagation.",
            expectation=ControlExpectation.MECHANISM_DIAGNOSTIC,
        ),
        NegativeControlSpec(
            controlId="disable-llm-control",
            kind=NegativeControlKind.DISABLE_LLM,
            settings=(
                _syntheticBooleanSetting(
                    "cognition.llm_enabled",
                    "Disable LLM cognition while retaining deterministic market mechanics.",
                    value=False,
                ),
            ),
            tolerances=(),
            rationale="Diagnose the model-internal contribution of LLM cognition.",
            expectation=ControlExpectation.MECHANISM_DIAGNOSTIC,
        ),
        NegativeControlSpec(
            controlId="disable-mm-inventory-control",
            kind=NegativeControlKind.DISABLE_MM_INVENTORY_CONSTRAINT,
            settings=(
                _syntheticBooleanSetting(
                    "market_maker.inventory_constraint_enabled",
                    "Disable the market-maker inventory constraint only.",
                    value=False,
                ),
            ),
            tolerances=(),
            rationale="Diagnose the inventory-feedback channel without claiming real causality.",
            expectation=ControlExpectation.MECHANISM_DIAGNOSTIC,
        ),
        NegativeControlSpec(
            controlId="non-event-day",
            kind=NegativeControlKind.NON_EVENT_DAY,
            settings=(
                _syntheticBooleanSetting(
                    "control.non_event_day",
                    "Run the same configuration on a declared synthetic non-event day.",
                ),
            ),
            tolerances=tolerances,
            rationale="The same setup should not manufacture an event effect on a non-event day.",
            expectation=ControlExpectation.NULL_EFFECT,
        ),
    )


def buildRequiredAblations() -> tuple[AblationSpec, ...]:
    """构造 15.9 的十个必做消融臂。"""

    definitions: tuple[
        tuple[AblationKind, tuple[ParameterSetting, ...], str, str],
        ...,
    ] = (
        (
            AblationKind.RULE_ONLY,
            (_categoricalSetting("cognition.mode", "RULE_ONLY"),),
            "Does LLM cognition add measurable behavioral differences?",
            "Rule-only cognition is a model arm, not evidence of historical realism.",
        ),
        (
            AblationKind.LLM_REPRESENTATIVES_MIN_LIQUIDITY,
            (
                _categoricalSetting(
                    "cognition.mode",
                    "LLM_REPRESENTATIVES_MIN_LIQUIDITY",
                ),
            ),
            "Does an LLM-heavy arm become unstable without a broad rule population?",
            "Minimum rule liquidity remains a proxy and prevents an empty order book.",
        ),
        (
            AblationKind.HYBRID,
            (_categoricalSetting("cognition.mode", "HYBRID"),),
            "How does the target hybrid architecture behave?",
            "This is the target model arm, not an externally validated benchmark.",
        ),
        (
            AblationKind.NO_SOCIAL,
            (_booleanSetting("network.social_enabled", False),),
            "What is the incremental role of social propagation?",
            "Only the modeled social channel is removed.",
        ),
        (
            AblationKind.NO_MEMORY,
            (_booleanSetting("cognition.memory_enabled", False),),
            "What is the incremental role of path-dependent memory?",
            "Only modeled agent memory is removed.",
        ),
        (
            AblationKind.NO_MM_INVENTORY_CONSTRAINT,
            (_booleanSetting("market_maker.inventory_constraint_enabled", False),),
            "What is the role of market-maker inventory feedback?",
            "This removes a simplified inventory proxy, not real dealer constraints.",
        ),
        (
            AblationKind.NO_PASSIVE_FUND,
            (_booleanSetting("population.passive_fund_enabled", False),),
            "What is the incremental role of passive demand?",
            "The passive fund is a modeled representative agent.",
        ),
        (
            AblationKind.FIXED_LLM_DECISIONS,
            (_booleanSetting("cognition.fixed_llm_decisions", True),),
            "How much variation comes from LLM decision sampling?",
            "A fixed decision tape separates model sampling from market randomness.",
        ),
        (
            AblationKind.NO_RISK_OFF_FACTOR,
            (_booleanSetting("market.risk_off_factor_enabled", False),),
            "Can the company-event channel be separated from market background?",
            "The risk-off factor is a scenario proxy, not an observed causal treatment.",
        ),
        (
            AblationKind.NO_PRICE_IMPACT_SLIPPAGE,
            (
                _booleanSetting("execution.price_impact_enabled", False),
                _booleanSetting("execution.slippage_enabled", False),
            ),
            "How sensitive are findings to execution-cost assumptions?",
            "Removing impact and slippage creates a deliberately unrealistic diagnostic arm.",
        ),
    )
    return tuple(
        AblationSpec(
            ablationId=kind.value.lower().replace("_", "-"),
            kind=kind,
            settings=settings,
            question=question,
            modelBoundary=modelBoundary,
        )
        for kind, settings, question, modelBoundary in definitions
    )


def _syntheticBooleanSetting(
    path: str,
    rationale: str,
    *,
    value: bool = True,
) -> ParameterSetting:
    return ParameterSetting(
        path=path,
        value=value,
        unit="boolean",
        rationale=rationale,
        evidenceBasis=EvidenceBasis.SYNTHETIC,
    )


def _booleanSetting(path: str, value: bool) -> ParameterSetting:
    return _syntheticBooleanSetting(
        path,
        "Apply one preregistered model-mechanism switch for this ablation.",
        value=value,
    )


def _categoricalSetting(path: str, value: str) -> ParameterSetting:
    return ParameterSetting(
        path=path,
        value=value,
        unit="category",
        rationale="Select the preregistered cognition architecture for this study arm.",
        evidenceBasis=EvidenceBasis.SYNTHETIC,
    )
