import random
import statistics
from copy import deepcopy

import pytest

from backend.app.simulation.agents import AgentType, buildPopulation
from backend.app.simulation.analytics import aggregatePairedResults
from backend.app.simulation.engine import (
    INITIAL_PRICE_TICKS,
    SimulationState,
    _refreshMarketMakerQuotes,
    _seedOpeningBook,
    runScenario,
)
from backend.app.simulation.order_book import LimitOrderBook


def runCapacity(seed: int, value: float) -> dict:
    return runScenario(
        seed=seed,
        populationSize=28,
        steps=60,
        parameter="marketMakerCapacity",
        value=value,
    )


def executableScenarioConfig() -> dict:
    return {
        "market": {
            "instrumentId": "SPCX",
            "benchmarkId": "NDX_SYNTHETIC",
            "tickSize": 0.01,
            "initialPrice": 135.0,
            "feeBps": 0.3,
            "latencyMs": 25,
            "openingAuction": True,
            "volatilityHalt": True,
            "priceCollarBps": 180.0,
        },
        "population": {
            "profileId": "mixed-event-risk-v1",
            "representativeLlmAgents": 8,
            "institutionalShare": 0.2,
            "leverageEnabled": True,
            "shortSellingEnabled": True,
        },
        "network": {
            "topology": "WATTS_STROGATZ",
            "averageDegree": 6,
            "rewiringProbability": 0.12,
            "echoChamberStrength": 0.35,
            "correctionReach": 0.7,
        },
    }


def runConfigured(
    config: dict,
    *,
    seed: int = 909,
    cognitiveSignals: list[dict] | None = None,
) -> dict:
    return runScenario(
        seed=seed,
        populationSize=28,
        steps=60,
        parameter="marketMakerCapacity",
        value=1.0,
        scenarioConfig=config,
        cognitiveSignals=cognitiveSignals,
    )


def test_same_seed_replay_is_byte_stable() -> None:
    firstRun = runCapacity(42, 1.0)
    secondRun = runCapacity(42, 1.0)

    assert firstRun == secondRun
    assert firstRun["eventLogHash"] == secondRun["eventLogHash"]
    eventTypes = {trace["eventType"] for trace in firstRun["traces"]}
    assert {"FACT_ARRIVED", "CLARIFICATION_ARRIVED", "SYSTEM_ORDER_SUBMITTED"}.issubset(eventTypes)
    assert firstRun["invariants"]["allTradesRecorded"] is True
    assert firstRun["invariants"]["selfTradePrevented"] is True
    assert firstRun["invariants"]["netPosition"] == 0
    assert firstRun["invariants"]["netCashChangeCents"] == 0


def test_baseline_compared_with_itself_has_zero_delta() -> None:
    runs = [runCapacity(seed, 1.0) for seed in (11, 22, 33)]
    aggregate = aggregatePairedResults(runs, runs)

    for pairedRun in aggregate["pairedRuns"]:
        assert all(value in (0, 0.0, None) for value in pairedRun["delta"].values())
    assert aggregate["metricSummaries"]["maxSpreadBps"]["delta"]["median"] == 0


def test_lower_liquidity_widens_spread_and_reduces_depth_across_seeds() -> None:
    seeds = [101, 202, 303, 404, 505, 606]
    normalRuns = [runCapacity(seed, 1.0) for seed in seeds]
    lowCapacityRuns = [runCapacity(seed, 0.4) for seed in seeds]

    normalSpread = statistics.median(run["metrics"]["maxSpreadBps"] for run in normalRuns)
    lowSpread = statistics.median(run["metrics"]["maxSpreadBps"] for run in lowCapacityRuns)
    normalDepth = statistics.median(run["metrics"]["minDepth"] for run in normalRuns)
    lowDepth = statistics.median(run["metrics"]["minDepth"] for run in lowCapacityRuns)

    assert lowSpread > normalSpread
    assert lowDepth < normalDepth
    assert (
        normalRuns[0]["paths"]["fundamentalPrice"]
        == lowCapacityRuns[0]["paths"]["fundamentalPrice"]
    )


def test_market_maker_refresh_is_post_only_even_with_extreme_inventory_skew() -> None:
    population = buildPopulation(28)
    marketMakers = [agent for agent in population if agent.agentType == AgentType.MARKET_MAKER]
    for index, marketMaker in enumerate(marketMakers):
        marketMaker.position = -180 if index % 2 == 0 else 180
    state = SimulationState(
        seed=77,
        population=population,
        orderBook=LimitOrderBook("SPCX"),
        parameter="marketMakerCapacity",
        value=1.0,
        steps=60,
    )
    _seedOpeningBook(state)

    _refreshMarketMakerQuotes(state, INITIAL_PRICE_TICKS, random.Random(77), step=0)

    assert state.orderBook.tradeCounter == 0
    assert state.orderBook.bestBid() < state.orderBook.bestAsk()


def test_rejected_clarification_claim_removes_information_event_and_recovery() -> None:
    def eventPack(preFreezeReviewStatus: str) -> dict:
        return {
            "id": "test-pack",
            "mechanismRules": {"clarificationClaimId": "claim-clarification"},
            "claims": [
                {
                    "claimId": "claim-clarification",
                    "reviewStatus": "FROZEN",
                    "preFreezeReviewStatus": preFreezeReviewStatus,
                }
            ],
        }

    acceptedRun = runScenario(
        seed=808,
        populationSize=28,
        steps=60,
        parameter="clarificationDelay",
        value=1.0,
        eventPack=eventPack("HUMAN_APPROVED"),
    )
    rejectedRun = runScenario(
        seed=808,
        populationSize=28,
        steps=60,
        parameter="clarificationDelay",
        value=1.0,
        eventPack=eventPack("REJECTED"),
    )

    acceptedTypes = {trace["eventType"] for trace in acceptedRun["traces"]}
    rejectedTypes = {trace["eventType"] for trace in rejectedRun["traces"]}
    assert "CLARIFICATION_ARRIVED" in acceptedTypes
    assert "CLARIFICATION_ARRIVED" not in rejectedTypes
    assert rejectedRun["paths"]["sentiment"][-1] < acceptedRun["paths"]["sentiment"][-1]


def test_extended_engine_preserves_legacy_defaults_and_reports_auditable_state() -> None:
    arguments = {
        "seed": 909,
        "populationSize": 28,
        "steps": 60,
        "parameter": "marketMakerCapacity",
        "value": 1.0,
    }
    legacyRun = runScenario(**arguments)
    explicitRun = runScenario(
        **arguments,
        cognitiveSignals=None,
        scenarioConfig=None,
    )

    assert legacyRun == explicitRun
    assert legacyRun["eventQueueAudit"]["monotonicTimestampPrioritySequence"] is True
    assert legacyRun["invariants"]["scientificLedgerValid"] is True
    assert legacyRun["invariants"]["reservationsValid"] is True
    assert legacyRun["invariants"]["borrowInventoryValid"] is True
    assert set(AgentType).issubset(legacyRun["agentFlows"])
    assert {
        "networkReach",
        "liquidityStress",
        "tailRisk",
        "systemEquityCents",
    }.issubset(legacyRun["paths"])
    assert {
        "networkReachRate",
        "informationDelaySteps",
        "liquidityStressIndex",
        "tailLossProbability",
        "agentPnlDispersionCents",
        "systemEquityChangeCents",
        "forcedLiquidationVolume",
        "ledgerRejectedOrders",
        "cognitiveOrderCount",
    }.issubset(legacyRun["metrics"])
    assert len(legacyRun["agentPnl"]) == arguments["populationSize"]


def test_market_configuration_fields_drive_auditable_executable_mechanisms() -> None:
    baseConfig = executableScenarioConfig()
    baseRun = runConfigured(baseConfig)

    benchmarkConfig = deepcopy(baseConfig)
    benchmarkConfig["market"]["benchmarkId"] = "RUSSELL2000_SYNTHETIC"
    benchmarkRun = runConfigured(benchmarkConfig)
    assert benchmarkRun["runtimeConfiguration"]["benchmark"]["benchmarkId"] == (
        "RUSSELL2000_SYNTHETIC"
    )
    assert benchmarkRun["paths"]["benchmark"] != baseRun["paths"]["benchmark"]
    assert (
        benchmarkRun["metrics"]["benchmarkReturnPct"] != (baseRun["metrics"]["benchmarkReturnPct"])
    )

    tickConfig = deepcopy(baseConfig)
    tickConfig["market"]["tickSize"] = 0.05
    tickRun = runConfigured(tickConfig)
    tickSizeTicks = tickRun["runtimeConfiguration"]["tickSizeTicks"]
    assert tickSizeTicks == 500
    assert all(
        trace["payload"]["priceTicks"] % tickSizeTicks == 0
        for trace in tickRun["traces"]
        if trace["eventType"] == "TRADE_EXECUTED"
    )

    latencyConfig = deepcopy(baseConfig)
    latencyConfig["market"]["latencyMs"] = 5_000
    latencyRun = runConfigured(latencyConfig)
    arrivalTrace = next(
        trace for trace in latencyRun["traces"] if trace["eventType"] == "ORDER_ARRIVED"
    )
    assert arrivalTrace["payload"]["latencyMs"] == 5_000
    assert (
        arrivalTrace["payload"]["arrivalTimestampMs"]
        - (arrivalTrace["payload"]["activationTimestampMs"])
        == 5_000
    )
    assert latencyRun["marketMechanisms"]["latencyExpiredOrders"] > 0

    continuousOpenConfig = deepcopy(baseConfig)
    continuousOpenConfig["market"]["openingAuction"] = False
    continuousOpenRun = runConfigured(continuousOpenConfig)
    assert baseRun["marketMechanisms"]["openingAuctionVolume"] > 0
    assert continuousOpenRun["marketMechanisms"]["openingAuctionVolume"] == 0
    assert "OPENING_AUCTION_CLEARED" not in {
        trace["eventType"] for trace in continuousOpenRun["traces"]
    }

    noHaltConfig = deepcopy(baseConfig)
    noHaltConfig["market"]["volatilityHalt"] = False
    noHaltRun = runConfigured(noHaltConfig)
    assert baseRun["marketMechanisms"]["volatilityHaltCount"] > 0
    assert noHaltRun["marketMechanisms"]["volatilityHaltCount"] == 0
    assert "VOLATILITY_HALT_TRIGGERED" in {trace["eventType"] for trace in baseRun["traces"]}

    zeroFeeConfig = deepcopy(baseConfig)
    zeroFeeConfig["market"]["feeBps"] = 0.0
    zeroFeeRun = runConfigured(zeroFeeConfig)
    assert baseRun["runtimeConfiguration"]["feeMicroBps"] == 300_000
    assert baseRun["marketMechanisms"]["totalFeesPaidCents"] > 0
    assert zeroFeeRun["marketMechanisms"]["totalFeesPaidCents"] == 0

    changedRuns = (
        benchmarkRun,
        tickRun,
        latencyRun,
        continuousOpenRun,
        noHaltRun,
        zeroFeeRun,
    )
    assert all(run["eventLogHash"] != baseRun["eventLogHash"] for run in changedRuns)


def test_population_fields_control_profile_cohort_and_cognitive_capacity() -> None:
    baseConfig = executableScenarioConfig()
    baseRun = runConfigured(baseConfig)

    profileConfig = deepcopy(baseConfig)
    profileConfig["population"]["profileId"] = "retail-narrative-v1"
    profileRun = runConfigured(profileConfig)
    assert profileRun["populationSummary"]["profileId"] == "retail-narrative-v1"
    assert (
        profileRun["populationSummary"]["typeCounts"]
        != (baseRun["populationSummary"]["typeCounts"])
    )

    institutionalConfig = deepcopy(baseConfig)
    institutionalConfig["population"]["institutionalShare"] = 0.6
    institutionalRun = runConfigured(institutionalConfig)
    assert institutionalRun["populationSummary"]["institutionalCount"] == 17
    assert institutionalRun["populationSummary"]["realizedInstitutionalShare"] == (
        pytest.approx(17 / 28, abs=1e-6)
    )
    assert (
        institutionalRun["populationSummary"]["typeCounts"]
        != (baseRun["populationSummary"]["typeCounts"])
    )

    signal = {
        "representativeIndex": 0,
        "decisionId": "decision-representative-capacity",
        "role": "event_risk_analyst",
        "direction": "NEGATIVE",
        "actionPreference": "REDUCE",
        "targetPositionFraction": -0.8,
        "urgency": 0.95,
        "uncertainty": 0.1,
        "tailRisk": 0.9,
        "confidence": 0.95,
        "decisionSummary": "Approved evidence supports a bounded downside belief.",
        "evidenceIds": ["claim-risk-off"],
    }
    disabledConfig = deepcopy(baseConfig)
    disabledConfig["population"]["representativeLlmAgents"] = 0
    disabledRun = runConfigured(disabledConfig, seed=314, cognitiveSignals=[signal])
    enabledConfig = deepcopy(baseConfig)
    enabledConfig["population"]["representativeLlmAgents"] = 1
    enabledRun = runConfigured(enabledConfig, seed=314, cognitiveSignals=[signal])
    assert disabledRun["populationSummary"]["assignedCognitiveAgents"] == 0
    assert disabledRun["metrics"]["cognitiveOrderCount"] == 0
    assert enabledRun["populationSummary"]["assignedCognitiveAgents"] == 1
    assert enabledRun["metrics"]["cognitiveOrderCount"] == 1

    assert profileRun["eventLogHash"] != baseRun["eventLogHash"]
    assert institutionalRun["eventLogHash"] != baseRun["eventLogHash"]
    assert enabledRun["eventLogHash"] != disabledRun["eventLogHash"]


def test_new_interventions_change_their_registered_mechanisms() -> None:
    seeds = (121, 232, 343)

    normalDepthRuns = [
        runScenario(
            seed=seed,
            populationSize=28,
            steps=60,
            parameter="liquidityDepthMultiplier",
            value=1.0,
        )
        for seed in seeds
    ]
    lowDepthRuns = [
        runScenario(
            seed=seed,
            populationSize=28,
            steps=60,
            parameter="liquidityDepthMultiplier",
            value=0.35,
        )
        for seed in seeds
    ]
    assert statistics.median(run["metrics"]["minDepth"] for run in lowDepthRuns) < (
        statistics.median(run["metrics"]["minDepth"] for run in normalDepthRuns)
    )

    normalPassiveRuns = [
        runScenario(
            seed=seed,
            populationSize=28,
            steps=60,
            parameter="passiveFlowMultiplier",
            value=1.0,
        )
        for seed in seeds
    ]
    highPassiveRuns = [
        runScenario(
            seed=seed,
            populationSize=28,
            steps=60,
            parameter="passiveFlowMultiplier",
            value=2.0,
        )
        for seed in seeds
    ]
    assert statistics.median(run["metrics"]["totalVolume"] for run in highPassiveRuns) > (
        statistics.median(run["metrics"]["totalVolume"] for run in normalPassiveRuns)
    )

    normalLatencyRuns = [
        runScenario(
            seed=seed,
            populationSize=28,
            steps=60,
            parameter="informationLatency",
            value=1.0,
        )
        for seed in seeds
    ]
    highLatencyRuns = [
        runScenario(
            seed=seed,
            populationSize=28,
            steps=60,
            parameter="informationLatency",
            value=3.0,
        )
        for seed in seeds
    ]
    assert statistics.median(
        run["metrics"]["informationDelaySteps"] for run in highLatencyRuns
    ) > statistics.median(run["metrics"]["informationDelaySteps"] for run in normalLatencyRuns)


def test_cognitive_signal_cannot_inject_price_and_retains_full_causal_chain() -> None:
    signal = {
        "decisionId": "decision-cognitive-price-boundary",
        "role": "event_risk_analyst",
        "direction": "NEGATIVE",
        "actionPreference": "REDUCE",
        "targetPositionFraction": -0.8,
        "urgency": 0.95,
        "uncertainty": 0.1,
        "tailRisk": 0.9,
        "confidence": 0.95,
        "decisionSummary": "Approved evidence supports a bounded downside belief.",
        "evidenceIds": ["claim-risk-off"],
    }
    arguments = {
        "seed": 314,
        "populationSize": 28,
        "steps": 60,
        "parameter": "marketMakerCapacity",
        "value": 1.0,
    }
    normalRun = runScenario(**arguments, cognitiveSignals=[signal])
    attemptedInjectionRun = runScenario(
        **arguments,
        cognitiveSignals=[
            {
                **signal,
                "limitPriceTicks": 1,
                "price": 1,
                "quantity": 999_999,
                "orderType": "UNBOUNDED_MARKET",
            }
        ],
    )

    assert attemptedInjectionRun == normalRun
    assert normalRun["metrics"]["cognitiveOrderCount"] == 1
    cognitiveIntent = next(
        trace
        for trace in normalRun["traces"]
        if trace["eventType"] == "ACTION_INTENT_CREATED"
        and trace["payload"].get("cognitive") is True
    )
    cognitiveOrder = next(
        trace
        for trace in normalRun["traces"]
        if trace["eventType"] == "ORDER_SUBMITTED" and trace["payload"].get("cognitive") is True
    )
    assert cognitiveIntent["payload"]["generatedLimitPriceTicks"] != 1
    assert (
        cognitiveOrder["payload"]["limitPriceTicks"]
        == cognitiveIntent["payload"]["generatedLimitPriceTicks"]
    )
    assert any(
        item["step"] == "PRICE_PROTECTION" for item in cognitiveIntent["payload"]["policyTrace"]
    )

    tracesById = {trace["traceId"]: trace for trace in normalRun["traces"]}
    cognitiveTrade = next(
        trace
        for trace in normalRun["traces"]
        if trace["eventType"] == "TRADE_EXECUTED"
        and trace["parentTraceId"] == cognitiveOrder["traceId"]
    )
    causalChain = []
    cursor = cognitiveTrade
    while cursor is not None:
        causalChain.append(cursor["eventType"])
        parentTraceId = cursor["parentTraceId"]
        cursor = tracesById.get(parentTraceId) if parentTraceId else None
    causalChain.reverse()
    requiredChain = (
        "FACT_ARRIVED",
        "SOCIAL_PROPAGATED",
        "OBSERVATION_CREATED",
        "BELIEF_UPDATED",
        "ACTION_INTENT_CREATED",
        "RISK_CHECK",
        "ORDER_SUBMITTED",
        "TRADE_EXECUTED",
    )
    searchOffset = 0
    for eventType in requiredChain:
        searchOffset = causalChain.index(eventType, searchOffset) + 1


def test_scheduled_cognitive_decisions_are_consumed_at_their_point_in_time_steps() -> None:
    baseSignal = {
        "representativeIndex": 0,
        "role": "event_risk_analyst",
        "direction": "NEGATIVE",
        "actionPreference": "REDUCE",
        "targetPositionFraction": -0.4,
        "urgency": 0.7,
        "uncertainty": 0.25,
        "tailRisk": 0.8,
        "confidence": 0.8,
        "decisionSummary": "Approved evidence supports a bounded downside belief.",
        "evidenceIds": ["claim-risk-off"],
    }
    run = runScenario(
        seed=315,
        populationSize=28,
        steps=60,
        parameter="marketMakerCapacity",
        value=1.0,
        cognitiveSignals=[
            {
                **baseSignal,
                "decisionId": "decision-round-zero",
                "decisionRound": 0,
                "activeFromStep": 0,
            },
            {
                **baseSignal,
                "decisionId": "decision-round-one",
                "decisionRound": 1,
                "activeFromStep": 24,
            },
        ],
    )

    assert run["systemMetrics"]["cognitiveSignalsConsumed"] == 2
    assert run["systemMetrics"]["cognitiveAgentsUsed"] == 1
    cognitiveBeliefs = [
        trace
        for trace in run["traces"]
        if trace["eventType"] == "BELIEF_UPDATED"
        and trace["payload"].get("source") == "LLM_BELIEF_SIGNAL"
    ]
    assert [trace["payload"]["decisionRound"] for trace in cognitiveBeliefs] == [0, 1]
    assert cognitiveBeliefs[1]["step"] >= 24


def test_rule_fallback_cognitive_trace_preserves_provenance() -> None:
    signal = {
        "decisionId": "decision-rule-fallback",
        "representativeIndex": 0,
        "role": "event_risk_analyst",
        "direction": "NEUTRAL",
        "actionPreference": "ABSTAIN",
        "targetPositionFraction": 0.0,
        "urgency": 0.0,
        "uncertainty": 1.0,
        "tailRisk": 1.0,
        "confidence": 0.0,
        "decisionSummary": "A deterministic safe fallback abstained.",
        "evidenceIds": [],
        "fallbackUsed": True,
        "repairUsed": True,
        "failureReason": "SCHEMA_INVALID",
        "failureCodes": ["SCHEMA_INVALID", "RULE_FALLBACK_USED"],
        "transportAttempts": 2,
    }

    run = runScenario(
        seed=316,
        populationSize=28,
        steps=60,
        parameter="marketMakerCapacity",
        value=1.0,
        cognitiveSignals=[signal],
    )

    belief = next(
        trace
        for trace in run["traces"]
        if trace["eventType"] == "BELIEF_UPDATED"
        and trace["payload"].get("decisionId") == "decision-rule-fallback"
    )
    assert belief["payload"]["source"] == "RULE_FALLBACK_BELIEF_SIGNAL"
    assert belief["payload"]["fallbackUsed"] is True
    assert belief["payload"]["repairUsed"] is True
    assert belief["payload"]["failureReason"] == "SCHEMA_INVALID"
    assert belief["payload"]["failureCodes"] == ["SCHEMA_INVALID", "RULE_FALLBACK_USED"]
    assert "transportAttempts" not in belief["payload"]


def test_event_pack_clock_enforces_point_in_time_claim_boundaries() -> None:
    futurePack = {
        "id": "future-pack",
        "asOf": "2026-07-07T13:30:00Z",
        "mechanismRules": {
            "riskOffClaimId": "claim-risk-off",
            "clarificationClaimId": "claim-clarification",
        },
        "claims": [
            {
                "claimId": "claim-risk-off",
                "text": "A future approved stress fact.",
                "textZh": "一条未来才可见的已批准压力事实。",
                "knownAt": "2026-07-07T13:50:00Z",
                "synthetic": False,
                "sourceIds": ["source-future"],
                "reviewStatus": "HUMAN_APPROVED",
            },
            {
                "claimId": "claim-clarification",
                "text": "A scheduled clarification.",
                "textZh": "一条定时澄清。",
                "knownAt": "2026-07-07T13:40:00Z",
                "scheduledAt": "2026-07-07T13:45:00Z",
                "synthetic": True,
                "sourceIds": ["source-scheduled"],
                "reviewStatus": "HUMAN_APPROVED",
            },
        ],
    }
    futureRun = runScenario(
        seed=515,
        populationSize=28,
        steps=60,
        parameter="marketMakerCapacity",
        value=1.0,
        eventPack=futurePack,
    )
    futureEventTypes = {trace["eventType"] for trace in futureRun["traces"]}
    assert "FACT_ARRIVED" not in futureEventTypes
    assert "SOCIAL_PROPAGATED" not in futureEventTypes
    assert "CLARIFICATION_ARRIVED" not in futureEventTypes
    assert futureRun["networkMetrics"]["scheduledReachCount"] == 0
    assert not any(
        trace["payload"].get("networkEvidenceAvailable")
        for trace in futureRun["traces"]
        if trace["eventType"] == "OBSERVATION_CREATED"
    )

    visiblePack = {
        **futurePack,
        "id": "visible-pack",
        "claims": [
            {
                **futurePack["claims"][0],
                "text": "Human-approved event text used by the trace.",
                "textZh": "追踪使用的人类批准事件文本。",
                "knownAt": "2026-07-07T13:30:00Z",
            },
            futurePack["claims"][1],
        ],
    }
    visibleRun = runScenario(
        seed=515,
        populationSize=28,
        steps=60,
        parameter="marketMakerCapacity",
        value=1.0,
        eventPack=visiblePack,
    )
    factTrace = next(
        trace for trace in visibleRun["traces"] if trace["eventType"] == "FACT_ARRIVED"
    )
    assert factTrace["summary"] == "Human-approved event text used by the trace."
    assert factTrace["summaryZh"] == "追踪使用的人类批准事件文本。"
    assert factTrace["payload"]["synthetic"] is False
    assert "CLARIFICATION_ARRIVED" not in {trace["eventType"] for trace in visibleRun["traces"]}
    receivedAt = next(
        trace["payload"]["receivedAt"]
        for trace in visibleRun["traces"]
        if trace["eventType"] == "SOCIAL_PROPAGATED"
    )
    assert receivedAt.startswith("2026-07-07T")

    with pytest.raises(ValueError, match="explicit UTC offset"):
        runScenario(
            seed=515,
            populationSize=28,
            steps=60,
            parameter="marketMakerCapacity",
            value=1.0,
            eventPack={**visiblePack, "asOf": "2026-07-07T14:30:00+01:00"},
        )


def test_paired_analytics_include_new_paths_flows_and_robust_statistics() -> None:
    seeds = (818, 919, 1020)
    baselineRuns = [runCapacity(seed, 1.0) for seed in seeds]
    interventionRuns = [runCapacity(seed, 0.65) for seed in seeds]
    aggregate = aggregatePairedResults(baselineRuns, interventionRuns)

    assert "networkReachRate" in aggregate["metricSummaries"]
    assert "networkReach" in aggregate["medianPaths"]["baseline"]
    assert "liquidityStress" in aggregate["medianPaths"]["baseline"]
    assert "realizedPnlCents" in aggregate["agentFlows"]["marketMaker"]["baseline"]
    assert aggregate["agentPnl"]["marketMaker"]["equityChangeCents"]["delta"]["validN"] == len(
        seeds
    )
    assert {
        "networkMetrics",
        "liquidityMetrics",
        "tailRiskMetrics",
        "systemMetrics",
    } == set(aggregate["runSummaries"])
    spreadDiagnostics = aggregate["metricSummaries"]["maxSpreadBps"]["delta"]
    assert spreadDiagnostics["bootstrap95"]["resamples"] == 5_000
    assert "cohensDz" in spreadDiagnostics["effectSize"]
    assert 0 <= spreadDiagnostics["positiveTailProbability"] <= 1
    assert 0 <= spreadDiagnostics["negativeTailProbability"] <= 1


def test_progress_callback_receives_real_market_snapshots_without_changing_result() -> None:
    snapshots: list[dict[str, object]] = []
    arguments = {
        "seed": 8_800_123,
        "populationSize": 24,
        "steps": 40,
        "parameter": "marketMakerCapacity",
        "value": 0.8,
    }

    observed = runScenario(**arguments, onProgress=snapshots.append)
    replayed = runScenario(**arguments)

    assert len(snapshots) == observed["completedSteps"] == 40
    assert snapshots[0]["step"] == 0
    assert snapshots[-1]["step"] == 39
    assert snapshots[-1]["completedSteps"] == 40
    assert snapshots[-1]["totalSteps"] == 40
    assert snapshots[-1]["marketState"] in {"CONTINUOUS", "HALTED"}
    assert snapshots[-1]["price"] == observed["paths"]["price"][-1]
    assert snapshots[-1]["spreadBps"] == observed["paths"]["spreadBps"][-1]
    assert snapshots[-1]["depth"] == observed["paths"]["depth"][-1]
    assert observed["eventLogHash"] == replayed["eventLogHash"]


def test_volatility_halt_resume_is_not_mislabeled_as_an_auction() -> None:
    result = runScenario(
        seed=7_701,
        populationSize=28,
        steps=80,
        parameter="marketMakerCapacity",
        value=0.25,
        scenarioConfig={
            "market": {
                "instrumentId": "HALT",
                "benchmarkId": "SYNTH-HALT",
                "tickSize": 0.01,
                "initialPrice": 42.0,
                "feeBps": 0.3,
                "latencyMs": 250,
                "openingAuction": True,
                "volatilityHalt": True,
                "priceCollarBps": 250,
            }
        },
    )
    eventTypes = {trace["eventType"] for trace in result["traces"]}

    if "VOLATILITY_HALT_TRIGGERED" in eventTypes:
        assert "REOPEN_AUCTION_CLEARED" not in eventTypes
        ended = [
            trace for trace in result["traces"] if trace["eventType"] == "VOLATILITY_HALT_ENDED"
        ]
        assert all(trace["payload"]["resumeMechanism"] == "CONTINUOUS_REQUOTE" for trace in ended)
