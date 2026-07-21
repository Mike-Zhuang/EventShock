"""确定性、事件驱动、带组合账本的单资产事件冲击仿真。"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from backend.app.information.models import (
    InformationItem,
    InformationTimes,
    InformationType,
    PointInTimeInformationStore,
    SourceTier,
)
from backend.app.information.network import (
    GraphSpec,
    GraphType,
    InformationNetwork,
    PropagationConfig,
    buildSocialGraph,
)
from backend.app.simulation.agents import (
    AgentState,
    AgentType,
    MarketContext,
    OrderIntent,
    buildPopulation,
    makeCognitiveOrderIntent,
    makeOrderIntent,
)
from backend.app.simulation.event_queue import DeterministicEventQueue, EventPriority
from backend.app.simulation.ledger import (
    LedgerSide,
    OrderRiskResult,
    PortfolioLedger,
    RiskDecision,
)
from backend.app.simulation.order_book import (
    ExecutionReport,
    LimitOrderBook,
    Side,
    TimeInForce,
    Trade,
)

SUPPORTED_PARAMETERS = {
    "marketMakerCapacity",
    "socialAmplification",
    "stopLossSensitivity",
    "clarificationDelay",
    "liquidityDepthMultiplier",
    "passiveFlowMultiplier",
    "informationLatency",
}
PRICE_SCALE = 10_000
INITIAL_PRICE_TICKS = 1_350_000
PRICE_COLLAR_BPS = 180.0
INSTRUMENT_ID = "SPCX"
SIMULATION_START = datetime(2026, 1, 1, tzinfo=UTC)
SIMULATION_STEP_SECONDS = 5
SIMULATION_STEP_MILLISECONDS = SIMULATION_STEP_SECONDS * 1_000
FEE_MICRO_BPS_SCALE = 1_000_000
SYSTEM_ACCOUNT_IDS = (
    "opening-liquidity",
    "opening-auction-buyer",
    "opening-auction-seller",
    "synthetic-event-flow",
)


@dataclass(slots=True, frozen=True)
class ScenarioRuntimeConfig:
    instrumentId: str = INSTRUMENT_ID
    benchmarkId: str = "NDX_SYNTHETIC"
    benchmarkProfile: str = "TECH_SYNTHETIC"
    benchmarkBeta: float = 1.2
    benchmarkShockBps: float = -20.0
    benchmarkDriftBps: float = 0.0
    benchmarkOpeningBps: float = -1.0
    priceScale: int = PRICE_SCALE
    tickSizeTicks: int = 100
    tickSize: float = 0.01
    initialPriceTicks: int = INITIAL_PRICE_TICKS
    priceCollarBps: float = PRICE_COLLAR_BPS
    tradeFeeMicroBps: int = 0
    tradeFeeBps: float = 0.0
    latencyMs: int = 25
    openingAuction: bool = True
    volatilityHalt: bool = True
    volatilityHaltThresholdBps: float = 20.0
    volatilityHaltDurationSteps: int = 2
    maximumVolatilityHalts: int = 2
    profileId: str = "mixed-event-risk-v1"
    representativeLlmAgents: int = 8
    institutionalShare: float = 0.2
    allowShortSelling: bool = True
    leverageEnabled: bool = True
    graphType: GraphType = GraphType.WS
    averageDegree: int = 6
    rewiringProbability: float = 0.12
    echoChamberStrength: float = 0.35
    correctionReach: float = 0.7


@dataclass(slots=True)
class SimulationState:
    seed: int
    population: list[AgentState]
    orderBook: LimitOrderBook
    parameter: str
    value: float
    steps: int
    runtime: ScenarioRuntimeConfig = field(default_factory=ScenarioRuntimeConfig)
    simulationStart: datetime = SIMULATION_START
    ledger: PortfolioLedger | None = None
    prices: list[float] = field(default_factory=list)
    fundamentals: list[float] = field(default_factory=list)
    spreadBps: list[float] = field(default_factory=list)
    depths: list[int] = field(default_factory=list)
    volumes: list[int] = field(default_factory=list)
    sentiments: list[float] = field(default_factory=list)
    networkReachPath: list[float] = field(default_factory=list)
    liquidityStressPath: list[float] = field(default_factory=list)
    tailRiskPath: list[float] = field(default_factory=list)
    systemEquityPath: list[int] = field(default_factory=list)
    traces: list[dict[str, Any]] = field(default_factory=list)
    agentFlows: dict[str, dict[str, int | float]] = field(default_factory=dict)
    totalBuyVolume: int = 0
    totalSellVolume: int = 0
    stopLossVolume: int = 0
    forcedLiquidationVolume: int = 0
    protectedUnfilled: int = 0
    orderCounter: int = 0
    traceCounter: int = 0
    importantTraceIds: set[str] = field(default_factory=set)
    recordedTradeCount: int = 0
    ledgerPositions: dict[str, int] = field(default_factory=dict)
    ledgerCashChangeCents: dict[str, int] = field(default_factory=dict)
    ledgerRejectedOrders: int = 0
    ledgerModifiedOrders: int = 0
    cognitiveOrderCount: int = 0
    cognitiveAssignments: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    cognitiveUseCount: dict[str, int] = field(default_factory=dict)
    latestInformationTraceByAgent: dict[str, str] = field(default_factory=dict)
    receiptTraceIds: dict[str, str] = field(default_factory=dict)
    factTraceId: str | None = None
    networkDeliveredNodes: set[str] = field(default_factory=set)
    networkDeliverySteps: list[int] = field(default_factory=list)
    nodeToAgentId: dict[str, str] = field(default_factory=dict)
    networkMetrics: dict[str, Any] = field(default_factory=dict)
    processedEvents: list[tuple[int, int, int, str]] = field(default_factory=list)
    initialEquityByAccount: dict[str, int] = field(default_factory=dict)
    benchmarkLevels: list[float] = field(default_factory=list)
    benchmarkReturnBps: list[float] = field(default_factory=list)
    openingReferencePriceTicks: int = INITIAL_PRICE_TICKS
    openingAuctionVolume: int = 0
    marketState: str = "PRE_OPEN"
    haltReferencePriceTicks: float = float(INITIAL_PRICE_TICKS)
    haltUntilStep: int | None = None
    haltCount: int = 0
    haltedSteps: int = 0
    latencyScheduledOrders: int = 0
    latencyExpiredOrders: int = 0
    haltRejectedOrders: int = 0


def runScenario(
    *,
    seed: int,
    populationSize: int,
    steps: int,
    parameter: str,
    value: float,
    eventPack: dict[str, Any] | None = None,
    shouldCancel: Callable[[], bool] | None = None,
    onProgress: Callable[[dict[str, Any]], None] | None = None,
    cognitiveSignals: Sequence[Mapping[str, Any]] | None = None,
    scenarioConfig: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """运行一次场景；外部信念只能经确定性政策、账本风控和订单簿影响结果。"""

    _validateInputs(populationSize, steps, parameter, value)
    runtime = _scenarioRuntimeConfig(scenarioConfig)
    simulationStart = _eventPackAsOf(eventPack)
    population = buildPopulation(
        populationSize,
        profileId=runtime.profileId,
        institutionalShare=runtime.institutionalShare,
        initialPriceTicks=runtime.initialPriceTicks,
    )
    state = SimulationState(
        seed=seed,
        population=population,
        orderBook=LimitOrderBook(runtime.instrumentId, tickSizeTicks=runtime.tickSizeTicks),
        parameter=parameter,
        value=value,
        steps=steps,
        runtime=runtime,
        simulationStart=simulationStart,
        cognitiveAssignments=_assignCognitiveSignals(
            population,
            cognitiveSignals,
            maximumAgents=runtime.representativeLlmAgents,
        ),
        openingReferencePriceTicks=runtime.initialPriceTicks,
        haltReferencePriceTicks=float(runtime.initialPriceTicks),
    )
    _initializeFlows(state)
    _initializeLedger(state)
    _recordTrace(
        state,
        step=0,
        eventType="SCENARIO_CONFIGURATION_APPLIED",
        agentId=None,
        parentTraceId=None,
        summary="The simulator resolved market and population fields into executable mechanisms.",
        summaryZh="仿真器已将市场与人口字段解析为可执行机制。",
        payload=_runtimeConfiguration(state),
    )

    agentById = {agent.agentId: agent for agent in population}
    _openMarket(state, agentById)
    _seedOpeningBook(state)

    randomStreams = {"marketNoise": random.Random(_derivedSeed(seed, "marketNoise"))}
    randomStreams["benchmark"] = random.Random(
        _derivedSeed(seed, f"benchmark:{runtime.benchmarkId}")
    )
    shockStep = max(4, round(steps * 0.22))
    mechanismRules = (eventPack or {}).get("mechanismRules", {})
    riskOffClaimId = mechanismRules.get("riskOffClaimId", "claim-risk-off")
    riskOffClaim = _resolveScenarioClaim(
        eventPack,
        riskOffClaimId,
        defaultText="A synthetic risk-off condition enters the simulated market.",
        defaultTextZh="一条合成风险规避条件进入模拟市场。",
    )
    riskOffStep = _claimReleaseStep(
        riskOffClaim,
        baseStep=shockStep,
        simulationStart=simulationStart,
        steps=steps,
    )
    informationDelaySteps = _informationDelaySteps(state)
    sentimentShockStep = (
        min(steps - 1, riskOffStep + informationDelaySteps)
        if riskOffStep is not None
        else steps + 1
    )
    clarificationClaimId = mechanismRules.get(
        "clarificationClaimId",
        "claim-clarification",
    )
    clarificationClaim = _resolveScenarioClaim(
        eventPack,
        clarificationClaimId,
        defaultText=(
            "A synthetic clarification reduces narrative uncertainty without setting prices."
        ),
        defaultTextZh="一条合成澄清降低叙事不确定性，但不直接设定价格。",
    )
    clarificationBaseStep = min(
        steps - 1,
        shockStep + max(1, round(steps * 0.14 * _parameterValue(state, "clarificationDelay"))),
    )
    clarificationStep = _claimReleaseStep(
        clarificationClaim,
        baseStep=clarificationBaseStep,
        simulationStart=simulationStart,
        steps=steps,
    )
    networkDeliveries = _prepareInformationNetwork(
        state,
        riskOffStep,
        riskOffClaim,
        scenarioConfig,
    )
    eventQueue = _buildEventQueue(
        steps=steps,
        shockStep=shockStep,
        factStep=riskOffStep,
        clarificationStep=clarificationStep,
        factPayload=_claimTracePayload(riskOffClaim, simulationStart),
        clarificationPayload=_claimTracePayload(clarificationClaim, simulationStart),
        networkDeliveries=networkDeliveries,
        latencyMs=runtime.latencyMs,
    )

    fundamentalPriceTicks = float(runtime.initialPriceTicks)
    benchmarkLevel = 100.0
    sentiment = 0.03
    cancelled = False

    for event in eventQueue.drain():
        state.processedEvents.append(
            (event.timestamp, event.priority, event.sequence, event.eventType)
        )
        step = min(steps - 1, event.timestamp // SIMULATION_STEP_MILLISECONDS)
        if event.eventType == "MARKET_STATE_UPDATED":
            if shouldCancel is not None and shouldCancel():
                cancelled = True
                break
            priorPrice = (
                state.prices[-1] if state.prices else float(state.openingReferencePriceTicks)
            )
            benchmarkLevel, benchmarkReturnBps = _advanceBenchmark(
                benchmarkLevel,
                step,
                shockStep,
                runtime,
                randomStreams["benchmark"],
            )
            state.benchmarkLevels.append(benchmarkLevel)
            state.benchmarkReturnBps.append(benchmarkReturnBps)
            fundamentalPriceTicks = _advanceFundamental(
                fundamentalPriceTicks,
                step,
                shockStep,
                benchmarkReturnBps,
                runtime,
                randomStreams["marketNoise"],
            )
            sentiment = _advanceSentiment(
                sentiment,
                step,
                sentimentShockStep,
                clarificationStep if clarificationStep is not None else steps + 1,
                _parameterValue(state, "socialAmplification"),
                randomStreams["marketNoise"],
            )
            halted = _updateMarketState(state, step, priorPrice)
            if not halted:
                _refreshMarketMakerQuotes(
                    state,
                    priorPrice,
                    random.Random(_derivedSeed(seed, f"quoteJitter:{step}")),
                    step,
                )
        elif event.eventType == "FACT_RELEASED":
            claimPayload = dict(event.payload)
            summary = str(claimPayload.pop("text"))
            summaryZh = str(claimPayload.pop("textZh"))
            state.factTraceId = _recordTrace(
                state,
                step=step,
                eventType="FACT_ARRIVED",
                agentId=None,
                parentTraceId=None,
                summary=summary,
                summaryZh=summaryZh,
                payload=claimPayload,
            )
        elif event.eventType == "CLARIFICATION_RELEASED":
            claimPayload = dict(event.payload)
            summary = str(claimPayload.pop("text"))
            summaryZh = str(claimPayload.pop("textZh"))
            _recordTrace(
                state,
                step=step,
                eventType="CLARIFICATION_ARRIVED",
                agentId=None,
                parentTraceId=state.factTraceId,
                summary=summary,
                summaryZh=summaryZh,
                payload=claimPayload,
            )
        elif event.eventType == "NETWORK_INFORMATION_DELIVERED":
            _recordNetworkDelivery(state, step, event.payload)
        elif event.eventType == "AGENTS_ACTIVATED":
            if state.marketState != "HALTED":
                _activateAgents(
                    state,
                    step,
                    event.timestamp,
                    fundamentalPriceTicks,
                    sentiment,
                    randomStreams,
                    agentById,
                    eventQueue,
                )
        elif event.eventType == "AGENT_ORDER_ARRIVED":
            _processAgentOrderArrival(state, step, event.payload, agentById)
        elif event.eventType == "SYSTEM_FLOW_ARRIVED":
            quantity = int(event.payload["quantity"])
            if state.marketState == "HALTED":
                state.haltRejectedOrders += 1
                _recordHaltRejection(
                    state,
                    step,
                    "synthetic-event-flow",
                    None,
                    quantity,
                )
            else:
                _submitSystemFlow(
                    state,
                    step,
                    Side.SELL,
                    quantity,
                    str(event.payload["reason"]),
                    agentById,
                )
        elif event.eventType == "METRICS_CAPTURED":
            _captureSnapshot(state, fundamentalPriceTicks, sentiment)
            if onProgress is not None:
                onProgress(_liveProgressSnapshot(state, step))
        else:
            raise RuntimeError(f"unknown simulation event type: {event.eventType}")

    agentPnl = _finalizeAgentAccounting(state)
    metrics = _calculateMetrics(state, shockStep, agentPnl)
    invariants = _validateLedgerInvariants(state)
    paths = {
        "step": list(range(len(state.prices))),
        "price": [round(priceTicks / runtime.priceScale, 4) for priceTicks in state.prices],
        "fundamentalPrice": [
            round(priceTicks / runtime.priceScale, 4) for priceTicks in state.fundamentals
        ],
        "benchmark": [round(level, 6) for level in state.benchmarkLevels],
        "spreadBps": [round(pathValue, 4) for pathValue in state.spreadBps],
        "depth": state.depths,
        "volume": state.volumes,
        "sentiment": [round(pathValue, 6) for pathValue in state.sentiments],
        "networkReach": [round(pathValue, 6) for pathValue in state.networkReachPath],
        "liquidityStress": [round(pathValue, 6) for pathValue in state.liquidityStressPath],
        "tailRisk": [round(pathValue, 6) for pathValue in state.tailRiskPath],
        "systemEquityCents": state.systemEquityPath,
    }
    systemMetrics = _systemMetrics(state, agentPnl)
    eventQueueAudit = _eventQueueAudit(state)
    deterministicArtifact = {
        "seed": seed,
        "parameter": parameter,
        "value": value,
        "simulationStart": simulationStart.isoformat(),
        "metrics": metrics,
        "paths": paths,
        "agentFlows": state.agentFlows,
        "agentPnl": agentPnl,
        "networkMetrics": state.networkMetrics,
        "runtimeConfiguration": _runtimeConfiguration(state),
        "populationSummary": _populationSummary(state),
        "marketMechanisms": _marketMechanismSummary(state),
        "liquidityMetrics": {
            "maximumStressIndex": metrics["liquidityStressIndex"],
            "minimumDepth": metrics["minDepth"],
            "maximumSpreadBps": metrics["maxSpreadBps"],
            "protectedUnfilledQuantity": state.protectedUnfilled,
        },
        "tailRiskMetrics": {
            "tailLossProbability": metrics["tailLossProbability"],
            "maximumDrawdownPct": metrics["maxDrawdownPct"],
            "cascadeScore": metrics["cascadeScore"],
            "forcedLiquidationVolume": state.forcedLiquidationVolume,
        },
        "systemMetrics": systemMetrics,
        "eventQueueAudit": eventQueueAudit,
        "traces": state.traces,
        "invariants": invariants,
    }
    eventLogHash = hashlib.sha256(
        json.dumps(deterministicArtifact, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        **deterministicArtifact,
        "eventLogHash": eventLogHash,
        "cancelled": cancelled,
        "completedSteps": len(state.prices),
        "protectedUnfilledQuantity": state.protectedUnfilled,
        "eventPackId": eventPack.get("id") if eventPack else None,
    }


def _liveProgressSnapshot(state: SimulationState, step: int) -> dict[str, Any]:
    """生成不含订单、身份或上传原文的轻量实时快照。"""

    price = (
        round(state.prices[-1] / state.runtime.priceScale, 4)
        if state.prices
        else round(state.openingReferencePriceTicks / state.runtime.priceScale, 4)
    )
    return {
        "step": step,
        "completedSteps": len(state.prices),
        "totalSteps": state.steps,
        "price": price,
        "spreadBps": round(state.spreadBps[-1], 4) if state.spreadBps else None,
        "depth": state.depths[-1] if state.depths else 0,
        "volume": state.volumes[-1] if state.volumes else 0,
        "sentiment": round(state.sentiments[-1], 6) if state.sentiments else None,
        "marketState": state.marketState,
        "haltCount": state.haltCount,
        "activeCognitiveAgents": len(state.cognitiveAssignments),
    }


def _validateInputs(populationSize: int, steps: int, parameter: str, value: float) -> None:
    if not 14 <= populationSize <= 250:
        raise ValueError("populationSize must be between 14 and 250")
    if not 30 <= steps <= 300:
        raise ValueError("steps must be between 30 and 300")
    if parameter not in SUPPORTED_PARAMETERS:
        raise ValueError(f"unsupported intervention parameter: {parameter}")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("intervention value must be a positive finite number")


def _scenarioRuntimeConfig(
    scenarioConfig: Mapping[str, Any] | None,
) -> ScenarioRuntimeConfig:
    config = scenarioConfig or {}
    market = config.get("market") if isinstance(config.get("market"), Mapping) else {}
    population = config.get("population") if isinstance(config.get("population"), Mapping) else {}
    network = config.get("network") if isinstance(config.get("network"), Mapping) else {}
    initialPrice = _finiteNumber(market.get("initialPrice"), 135.0, 0.01, 1_000_000.0)
    topology = str(network.get("topology", "WATTS_STROGATZ"))
    graphTypeByName = {
        "ERDOS_RENYI": GraphType.ER,
        "WATTS_STROGATZ": GraphType.WS,
        "BARABASI_ALBERT": GraphType.BA,
        "STOCHASTIC_BLOCK": GraphType.SBM,
        "ECHO_CHAMBER": GraphType.ECHO_CHAMBER,
        "CORE_PERIPHERY": GraphType.CORE_PERIPHERY,
    }
    instrumentId = str(market.get("instrumentId", INSTRUMENT_ID))[:32] or INSTRUMENT_ID
    benchmarkId = str(market.get("benchmarkId", "NDX_SYNTHETIC"))[:64] or "NDX_SYNTHETIC"
    benchmarkParameters = _benchmarkParameters(benchmarkId)
    tickSize = _finiteNumber(market.get("tickSize"), 0.01, 0.0001, 10.0)
    tickSizeTicks = max(
        1,
        int((Decimal(str(tickSize)) * PRICE_SCALE).to_integral_value(rounding=ROUND_HALF_UP)),
    )
    rawInitialPriceTicks = max(
        1,
        int((Decimal(str(initialPrice)) * PRICE_SCALE).to_integral_value(rounding=ROUND_HALF_UP)),
    )
    initialPriceTicks = _snapToTick(rawInitialPriceTicks, tickSizeTicks, "nearest")
    feeBps = _finiteNumber(market.get("feeBps"), 0.0, 0.0, 1_000.0)
    feeMicroBps = int(
        (Decimal(str(feeBps)) * FEE_MICRO_BPS_SCALE).to_integral_value(rounding=ROUND_HALF_UP)
    )
    latencyValue = market.get("latencyMs", 25)
    latencyMs = (
        max(0, min(60_000, latencyValue))
        if isinstance(latencyValue, int) and not isinstance(latencyValue, bool)
        else 25
    )
    profileId = str(population.get("profileId", "mixed-event-risk-v1"))[:100]
    if not profileId:
        profileId = "mixed-event-risk-v1"
    representativeValue = population.get("representativeLlmAgents", 8)
    representativeLlmAgents = (
        max(0, min(100, representativeValue))
        if isinstance(representativeValue, int) and not isinstance(representativeValue, bool)
        else 8
    )
    institutionalShare = _finiteNumber(
        population.get("institutionalShare"),
        0.2,
        0.0,
        1.0,
    )
    priceCollarBps = _finiteNumber(
        market.get("priceCollarBps"),
        PRICE_COLLAR_BPS,
        1.0,
        5_000.0,
    )
    return ScenarioRuntimeConfig(
        instrumentId=instrumentId,
        benchmarkId=benchmarkId,
        benchmarkProfile=str(benchmarkParameters["profile"]),
        benchmarkBeta=float(benchmarkParameters["beta"]),
        benchmarkShockBps=float(benchmarkParameters["shockBps"]),
        benchmarkDriftBps=float(benchmarkParameters["driftBps"]),
        benchmarkOpeningBps=float(benchmarkParameters["openingBps"]),
        priceScale=PRICE_SCALE,
        tickSizeTicks=tickSizeTicks,
        tickSize=tickSizeTicks / PRICE_SCALE,
        initialPriceTicks=initialPriceTicks,
        priceCollarBps=priceCollarBps,
        tradeFeeMicroBps=feeMicroBps,
        tradeFeeBps=feeMicroBps / FEE_MICRO_BPS_SCALE,
        latencyMs=latencyMs,
        openingAuction=bool(market.get("openingAuction", True)),
        volatilityHalt=bool(market.get("volatilityHalt", True)),
        volatilityHaltThresholdBps=max(10.0, min(50.0, priceCollarBps / 9.0)),
        profileId=profileId,
        representativeLlmAgents=representativeLlmAgents,
        institutionalShare=institutionalShare,
        allowShortSelling=bool(population.get("shortSellingEnabled", True)),
        leverageEnabled=bool(population.get("leverageEnabled", True)),
        graphType=graphTypeByName.get(topology, GraphType.WS),
        averageDegree=max(2, min(50, int(network.get("averageDegree", 6)))),
        rewiringProbability=_finiteNumber(
            network.get("rewiringProbability"),
            0.12,
            0.0,
            1.0,
        ),
        echoChamberStrength=_finiteNumber(
            network.get("echoChamberStrength"),
            0.35,
            0.0,
            1.0,
        ),
        correctionReach=_finiteNumber(
            network.get("correctionReach"),
            0.7,
            0.0,
            1.0,
        ),
    )


def _finiteNumber(value: object, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    resolved = float(value)
    if not math.isfinite(resolved):
        return default
    return max(minimum, min(maximum, resolved))


def _benchmarkParameters(benchmarkId: str) -> dict[str, str | float]:
    normalized = benchmarkId.upper()
    digest = hashlib.blake2s(normalized.encode("utf-8"), digest_size=8).digest()
    signedBias = (int.from_bytes(digest[:2], "big") / 65_535 - 0.5) * 2
    if normalized in {"NONE", "NO_BENCHMARK", "CASH"}:
        return {
            "profile": "NO_BENCHMARK",
            "beta": 0.0,
            "shockBps": 0.0,
            "driftBps": 0.0,
            "openingBps": 0.0,
        }
    if any(token in normalized for token in ("NDX", "NASDAQ", "TECH")):
        profile = "TECH_SYNTHETIC"
        beta = 1.2 + signedBias * 0.08
        shockBps = -22.0 + signedBias * 2.0
    elif any(token in normalized for token in ("RUSSELL", "RUT", "SMALL")):
        profile = "SMALL_CAP_SYNTHETIC"
        beta = 0.92 + signedBias * 0.08
        shockBps = -30.0 + signedBias * 2.5
    elif any(token in normalized for token in ("SPX", "S&P", "BROAD")):
        profile = "BROAD_MARKET_SYNTHETIC"
        beta = 1.0 + signedBias * 0.06
        shockBps = -16.0 + signedBias * 1.5
    else:
        profile = "CUSTOM_SYNTHETIC"
        beta = 0.8 + int.from_bytes(digest[2:4], "big") / 65_535 * 0.4
        shockBps = -12.0 - int.from_bytes(digest[4:6], "big") / 65_535 * 18.0
    return {
        "profile": profile,
        "beta": round(beta, 6),
        "shockBps": round(shockBps, 6),
        "driftBps": round(signedBias * 0.08, 6),
        "openingBps": round(signedBias * 2.0, 6),
    }


def _snapToTick(priceTicks: int | float, tickSizeTicks: int, direction: str) -> int:
    rawPrice = max(1, round(priceTicks))
    if direction == "ceil":
        aligned = ((rawPrice + tickSizeTicks - 1) // tickSizeTicks) * tickSizeTicks
    elif direction == "floor":
        aligned = (rawPrice // tickSizeTicks) * tickSizeTicks
    elif direction == "nearest":
        aligned = ((rawPrice + tickSizeTicks // 2) // tickSizeTicks) * tickSizeTicks
    else:
        raise ValueError(f"unsupported tick alignment direction: {direction}")
    return max(tickSizeTicks, aligned)


def _assignCognitiveSignals(
    population: list[AgentState],
    cognitiveSignals: Sequence[Mapping[str, Any]] | None,
    *,
    maximumAgents: int,
) -> dict[str, list[dict[str, Any]]]:
    if not cognitiveSignals or maximumAgents <= 0:
        return {}
    eligibleAgents = [
        agent for agent in population if agent.agentType is not AgentType.MARKET_MAKER
    ][:maximumAgents]
    assignments: dict[str, list[dict[str, Any]]] = {}
    for fallbackIndex, signal in enumerate(cognitiveSignals):
        if not isinstance(signal, Mapping):
            continue
        representativeIndex = signal.get("representativeIndex", fallbackIndex)
        if isinstance(representativeIndex, bool) or not isinstance(representativeIndex, int):
            continue
        if representativeIndex < 0 or representativeIndex >= len(eligibleAgents):
            continue
        agentId = eligibleAgents[representativeIndex].agentId
        assignments.setdefault(agentId, []).append(dict(signal))
    for signals in assignments.values():
        signals.sort(
            key=lambda signal: (
                int(signal.get("activeFromStep", 0)),
                str(signal.get("decisionId", "")),
            )
        )
    return assignments


def _initializeFlows(state: SimulationState) -> None:
    for agentType in AgentType:
        state.agentFlows[agentType.value] = {
            "buyVolume": 0,
            "sellVolume": 0,
            "netVolume": 0,
            "orderCount": 0,
            "riskRejectedCount": 0,
            "forcedVolume": 0,
            "realizedPnlCents": 0,
            "unrealizedPnlCents": 0,
            "endingEquityCents": 0,
        }


def _runtimeConfiguration(state: SimulationState) -> dict[str, Any]:
    runtime = state.runtime
    return {
        "instrumentId": runtime.instrumentId,
        "benchmark": {
            "benchmarkId": runtime.benchmarkId,
            "profile": runtime.benchmarkProfile,
            "assetBeta": runtime.benchmarkBeta,
            "shockBps": runtime.benchmarkShockBps,
            "driftBpsPerStep": runtime.benchmarkDriftBps,
            "openingBps": runtime.benchmarkOpeningBps,
        },
        "priceScale": runtime.priceScale,
        "tickSize": runtime.tickSize,
        "tickSizeTicks": runtime.tickSizeTicks,
        "initialPrice": round(runtime.initialPriceTicks / runtime.priceScale, 4),
        "initialPriceTicks": runtime.initialPriceTicks,
        "feeBps": runtime.tradeFeeBps,
        "feeMicroBps": runtime.tradeFeeMicroBps,
        "latencyMs": runtime.latencyMs,
        "openingAuction": runtime.openingAuction,
        "volatilityHalt": runtime.volatilityHalt,
        "volatilityHaltThresholdBps": runtime.volatilityHaltThresholdBps,
        "volatilityHaltDurationSteps": runtime.volatilityHaltDurationSteps,
        "maximumVolatilityHalts": runtime.maximumVolatilityHalts,
        "priceCollarBps": runtime.priceCollarBps,
        "populationProfileId": runtime.profileId,
        "institutionalShare": runtime.institutionalShare,
        "representativeLlmAgents": runtime.representativeLlmAgents,
        "shortSellingEnabled": runtime.allowShortSelling,
        "leverageEnabled": runtime.leverageEnabled,
    }


def _populationSummary(state: SimulationState) -> dict[str, Any]:
    typeCounts = {
        agentType.value: sum(agent.agentType is agentType for agent in state.population)
        for agentType in AgentType
    }
    institutionalCount = sum(agent.institutional for agent in state.population)
    return {
        "profileId": state.runtime.profileId,
        "populationSize": len(state.population),
        "requestedInstitutionalShare": state.runtime.institutionalShare,
        "institutionalCount": institutionalCount,
        "realizedInstitutionalShare": round(
            institutionalCount / max(len(state.population), 1),
            6,
        ),
        "typeCounts": typeCounts,
        "configuredRepresentativeLlmAgents": state.runtime.representativeLlmAgents,
        "assignedCognitiveAgents": len(state.cognitiveAssignments),
    }


def _marketMechanismSummary(state: SimulationState) -> dict[str, Any]:
    return {
        "marketState": state.marketState,
        "openingAuctionEnabled": state.runtime.openingAuction,
        "openingAuctionVolume": state.openingAuctionVolume,
        "openingReferencePrice": round(
            state.openingReferencePriceTicks / state.runtime.priceScale,
            4,
        ),
        "volatilityHaltEnabled": state.runtime.volatilityHalt,
        "volatilityHaltCount": state.haltCount,
        "haltedSteps": state.haltedSteps,
        "ordersRejectedDuringHalt": state.haltRejectedOrders,
        "latencyMs": state.runtime.latencyMs,
        "latencyScheduledOrders": state.latencyScheduledOrders,
        "latencyExpiredOrders": state.latencyExpiredOrders,
        "totalFeesPaidCents": state.ledger.feeCollectorCashCents if state.ledger else 0,
    }


def _initializeLedger(state: SimulationState) -> None:
    ledger = PortfolioLedger(
        tradeFeeMicroBps=state.runtime.tradeFeeMicroBps,
        initialMarginRateBps=5_000 if state.runtime.leverageEnabled else 10_000,
        priceScale=state.runtime.priceScale,
    )
    for agent in state.population:
        initialPositions = (
            {state.runtime.instrumentId: (agent.position, state.runtime.initialPriceTicks)}
            if agent.position > 0
            else None
        )
        ledger.registerAccount(
            agent.agentId,
            agent.cashCents,
            initialLongPositions=initialPositions,
        )
    ledger.registerAccount(
        "opening-liquidity",
        100_000_000,
        initialLongPositions={
            state.runtime.instrumentId: (100_000, state.runtime.initialPriceTicks)
        },
    )
    ledger.registerAccount("opening-auction-buyer", 100_000_000)
    ledger.registerAccount(
        "opening-auction-seller",
        100_000_000,
        initialLongPositions={
            state.runtime.instrumentId: (100_000, state.runtime.initialPriceTicks)
        },
    )
    ledger.registerAccount(
        "synthetic-event-flow",
        100_000_000,
        initialLongPositions={
            state.runtime.instrumentId: (100_000, state.runtime.initialPriceTicks)
        },
    )
    ledger.configureBorrowPool(state.runtime.instrumentId, 1_000_000)
    state.ledger = ledger
    for accountId in ledger.accounts:
        valuation = ledger.markToMarket(
            accountId,
            {state.runtime.instrumentId: state.runtime.initialPriceTicks},
        )
        state.initialEquityByAccount[accountId] = valuation.equityCents


def _derivedSeed(seed: int, streamName: str) -> int:
    digest = hashlib.blake2b(f"eventshock:{seed}:{streamName}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def _parameterValue(state: SimulationState, parameter: str) -> float:
    return state.value if state.parameter == parameter else 1.0


def _informationDelaySteps(state: SimulationState) -> int:
    multiplier = _parameterValue(state, "informationLatency")
    return max(0, round(max(0.0, multiplier - 1.0) * max(1, state.steps * 0.04)))


def _eventPackAsOf(eventPack: Mapping[str, Any] | None) -> datetime:
    if eventPack is None or "asOf" not in eventPack:
        return SIMULATION_START
    return _parseUtcTimestamp(eventPack["asOf"], "eventPack.asOf")


def _parseUtcTimestamp(value: object, fieldName: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError(f"{fieldName} must be a valid ISO-8601 UTC timestamp") from error
    else:
        raise ValueError(f"{fieldName} must be a valid ISO-8601 UTC timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{fieldName} must include an explicit UTC offset")
    return parsed.astimezone(UTC)


def _resolveScenarioClaim(
    eventPack: dict[str, Any] | None,
    claimId: object,
    *,
    defaultText: str,
    defaultTextZh: str,
) -> dict[str, Any] | None:
    resolvedClaimId = str(claimId)
    if eventPack is None:
        return {
            "claimId": resolvedClaimId,
            "text": defaultText,
            "textZh": defaultTextZh,
            "synthetic": True,
            "sourceIds": [],
        }
    if not _eventClaimAccepted(eventPack, resolvedClaimId):
        return None
    claim = next(
        (item for item in eventPack.get("claims", []) if item.get("claimId") == resolvedClaimId),
        None,
    )
    if claim is None:
        return None
    return {
        **claim,
        "text": str(claim.get("text") or defaultText),
        "textZh": str(claim.get("textZh") or defaultTextZh),
    }


def _claimReleaseStep(
    claim: Mapping[str, Any] | None,
    *,
    baseStep: int,
    simulationStart: datetime,
    steps: int,
) -> int | None:
    if claim is None:
        return None
    releaseAt = simulationStart
    for fieldName in ("knownAt", "scheduledAt"):
        if claim.get(fieldName) is not None:
            releaseAt = max(
                releaseAt,
                _parseUtcTimestamp(claim[fieldName], f"claim.{fieldName}"),
            )
    secondsAfterStart = max(0.0, (releaseAt - simulationStart).total_seconds())
    pointInTimeStep = math.ceil(secondsAfterStart / SIMULATION_STEP_SECONDS)
    releaseStep = max(baseStep, pointInTimeStep)
    return releaseStep if releaseStep < steps else None


def _claimTracePayload(
    claim: Mapping[str, Any] | None,
    simulationStart: datetime,
) -> dict[str, Any]:
    if claim is None:
        return {}
    knownAt = (
        _parseUtcTimestamp(claim["knownAt"], "claim.knownAt")
        if claim.get("knownAt") is not None
        else simulationStart
    )
    payload: dict[str, Any] = {
        "claimId": str(claim.get("claimId", "scenario-claim")),
        "text": str(claim.get("text", "Scenario information arrived.")),
        "textZh": str(claim.get("textZh", "场景信息已到达。")),
        "knownAt": knownAt.isoformat(),
        "synthetic": bool(claim.get("synthetic", True)),
        "sourceIds": [
            str(sourceId) for sourceId in claim.get("sourceIds", []) if isinstance(sourceId, str)
        ],
    }
    if claim.get("scheduledAt") is not None:
        payload["scheduledAt"] = _parseUtcTimestamp(
            claim["scheduledAt"],
            "claim.scheduledAt",
        ).isoformat()
    return payload


def _eventClaimAccepted(eventPack: dict[str, Any] | None, claimId: str) -> bool:
    if eventPack is None:
        return True
    claim = next(
        (item for item in eventPack.get("claims", []) if item.get("claimId") == claimId),
        None,
    )
    if claim is None:
        return False
    reviewStatus = claim.get("preFreezeReviewStatus", claim.get("reviewStatus"))
    return reviewStatus in {"HUMAN_APPROVED", "EDITED", "FROZEN"}


def _prepareInformationNetwork(
    state: SimulationState,
    riskOffStep: int | None,
    riskOffClaim: Mapping[str, Any] | None,
    scenarioConfig: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], ...]:
    nodeCount = len(state.population)
    neighborCount = min(max(2, state.runtime.averageDegree), nodeCount - 1)
    if neighborCount % 2:
        neighborCount -= 1
    neighborCount = max(2, neighborCount)
    graphSpec = GraphSpec(
        graphType=state.runtime.graphType,
        nodeCount=nodeCount,
        seed=_derivedSeed(state.seed, "informationGraph"),
        edgeProbability=min(1.0, state.runtime.averageDegree / max(nodeCount - 1, 1)),
        neighborCount=neighborCount,
        rewiringProbability=state.runtime.rewiringProbability,
        attachmentEdges=max(1, min(nodeCount - 1, state.runtime.averageDegree // 2)),
        communityCount=max(1, min(4, nodeCount)),
        withinCommunityProbability=min(
            0.95,
            0.45 + state.runtime.echoChamberStrength * 0.5,
        ),
        betweenCommunityProbability=max(
            0.01,
            0.18 * (1 - state.runtime.echoChamberStrength),
        ),
    )
    graph = buildSocialGraph(graphSpec)
    graphMetrics = graph.metrics()
    for nodeId, agent in zip(graph.nodeIds, state.population, strict=True):
        state.nodeToAgentId[nodeId] = agent.agentId

    latencyMultiplier = _parameterValue(state, "informationLatency")
    scenarioTopology = (
        (scenarioConfig or {})
        .get("network", {})
        .get(
            "topology",
            "WATTS_STROGATZ",
        )
        if isinstance((scenarioConfig or {}).get("network"), Mapping)
        else "WATTS_STROGATZ"
    )
    baseNetworkMetrics = {
        "topology": state.runtime.graphType.value,
        "nodeCount": graphMetrics.nodeCount,
        "edgeCount": graphMetrics.edgeCount,
        "averageDegree": round(graphMetrics.averageDegree, 6),
        "clusteringCoefficient": round(graphMetrics.clusteringCoefficient, 6),
        "averagePathLength": (
            round(graphMetrics.averagePathLength, 6)
            if graphMetrics.averagePathLength is not None
            else None
        ),
        "connected": graphMetrics.connected,
        "modularity": round(graphMetrics.modularity, 6),
        "homophily": round(graphMetrics.homophily, 6),
        "maxInfluenceConcentration": round(graphMetrics.maxInfluenceConcentration, 6),
        "informationLatencyMultiplier": latencyMultiplier,
        "scenarioTopology": scenarioTopology,
    }
    if riskOffStep is None or riskOffClaim is None:
        state.networkMetrics = {
            **baseNetworkMetrics,
            "scheduledReachCount": 0,
            "scheduledReachRate": 0.0,
            "maximumHopCount": 0,
        }
        return ()

    knownAt = state.simulationStart + timedelta(seconds=riskOffStep * SIMULATION_STEP_SECONDS)
    times = InformationTimes(
        eventTime=knownAt,
        publishedAt=knownAt,
        knownAt=knownAt,
        ingestedAt=knownAt,
    )
    information = InformationItem(
        infoId="synthetic-risk-off-information",
        type=InformationType.MARKET_SIGNAL,
        claim=str(riskOffClaim["text"]),
        entityIds=(state.runtime.instrumentId,),
        times=times,
        sourceId=(
            str(riskOffClaim.get("sourceIds", ["synthetic-scenario-engine"])[0])
            if riskOffClaim.get("sourceIds")
            else "synthetic-scenario-engine"
        ),
        sourceTier=SourceTier.T5,
        credibilityPrior=1.0,
        novelty=0.9,
        severity=0.9,
    )
    store = PointInTimeInformationStore((information,))
    network = InformationNetwork(graph, store, seed=_derivedSeed(state.seed, "propagation"))
    socialAmplification = _parameterValue(state, "socialAmplification")
    baseDelaySeconds = max(0, round(max(0.0, latencyMultiplier - 1.0) * 10))
    propagationConfig = PropagationConfig(
        baseForwardProbability=min(0.95, 0.42 * socialAmplification),
        minimumDelaySeconds=max(0, round(latencyMultiplier)),
        maximumDelaySeconds=max(1, round(12 * latencyMultiplier)),
        maximumHops=6,
        distortionProbability=min(0.5, 0.04 * socialAmplification),
        correctionCoverage=state.runtime.correctionReach,
        rumorMultiplier=min(3.0, socialAmplification),
    )
    agentToNode = {agentId: nodeId for nodeId, agentId in state.nodeToAgentId.items()}
    cognitiveSeedNodes = tuple(
        agentToNode[agentId] for agentId in state.cognitiveAssignments if agentId in agentToNode
    )
    seedNodeIds = cognitiveSeedNodes or (graph.nodeIds[0],)
    propagation = network.propagate(
        infoId=information.infoId,
        seedNodeIds=seedNodeIds,
        startAt=knownAt + timedelta(seconds=baseDelaySeconds),
        config=propagationConfig,
    )
    state.networkMetrics = {
        **baseNetworkMetrics,
        "scheduledReachCount": propagation.reachedNodeCount,
        "scheduledReachRate": round(propagation.reachedNodeCount / nodeCount, 6),
        "maximumHopCount": propagation.maximumHopCount,
    }
    deliveries = []
    for receipt in propagation.receipts:
        secondsAfterKnown = max(0.0, (receipt.receivedAt - knownAt).total_seconds())
        deliveryStep = min(
            state.steps - 1,
            riskOffStep + math.ceil(secondsAfterKnown / SIMULATION_STEP_SECONDS),
        )
        deliveries.append(
            {
                "step": deliveryStep,
                "receiptId": receipt.receiptId,
                "parentReceiptId": receipt.parentReceiptId,
                "nodeId": receipt.nodeId,
                "senderNodeId": receipt.senderNodeId,
                "hopCount": receipt.hopCount,
                "distorted": receipt.distorted,
                "receivedAt": receipt.receivedAt.isoformat(),
            }
        )
    return tuple(deliveries)


def _buildEventQueue(
    *,
    steps: int,
    shockStep: int,
    factStep: int | None,
    clarificationStep: int | None,
    factPayload: Mapping[str, Any],
    clarificationPayload: Mapping[str, Any],
    networkDeliveries: tuple[dict[str, Any], ...],
    latencyMs: int,
) -> DeterministicEventQueue:
    queue = DeterministicEventQueue()
    simulationEndTimestamp = steps * SIMULATION_STEP_MILLISECONDS
    for step in range(steps):
        stepStart = step * SIMULATION_STEP_MILLISECONDS
        queue.schedule(
            timestamp=stepStart,
            priority=EventPriority.MARKET_STATE,
            eventType="MARKET_STATE_UPDATED",
            eventId=f"market-{step:04d}",
        )
        if factStep is not None and step == factStep:
            queue.schedule(
                timestamp=stepStart,
                priority=EventPriority.INFORMATION_RELEASE,
                eventType="FACT_RELEASED",
                payload=factPayload,
                eventId="fact-risk-off",
            )
        if clarificationStep is not None and step == clarificationStep:
            queue.schedule(
                timestamp=stepStart,
                priority=EventPriority.INFORMATION_RELEASE,
                eventType="CLARIFICATION_RELEASED",
                payload=clarificationPayload,
                eventId="fact-clarification",
            )
        queue.schedule(
            timestamp=stepStart,
            priority=EventPriority.AGENT_ACTIVATION,
            eventType="AGENTS_ACTIVATED",
            eventId=f"agents-{step:04d}",
        )
        if shockStep <= step < shockStep + 4:
            arrivalTimestamp = stepStart + latencyMs
            if arrivalTimestamp < simulationEndTimestamp:
                queue.schedule(
                    timestamp=arrivalTimestamp,
                    priority=EventPriority.ORDER_ARRIVAL,
                    eventType="SYSTEM_FLOW_ARRIVED",
                    payload={
                        "quantity": 22 + (step - shockStep) * 3,
                        "reason": "risk-off-flow",
                        "activatedAtMs": stepStart,
                        "arrivedAtMs": arrivalTimestamp,
                    },
                    eventId=f"system-flow-{step:04d}",
                )
        queue.schedule(
            timestamp=stepStart + SIMULATION_STEP_MILLISECONDS - 1,
            priority=EventPriority.METRIC_AND_CHECKPOINT,
            eventType="METRICS_CAPTURED",
            eventId=f"metrics-{step:04d}",
        )
    for index, delivery in enumerate(networkDeliveries):
        queue.schedule(
            timestamp=int(delivery["step"]) * SIMULATION_STEP_MILLISECONDS,
            priority=EventPriority.NETWORK_DELIVERY,
            eventType="NETWORK_INFORMATION_DELIVERED",
            payload=delivery,
            eventId=f"network-{index:06d}",
        )
    return queue


def _openMarket(state: SimulationState, agentById: dict[str, AgentState]) -> None:
    if not state.runtime.openingAuction:
        state.marketState = "CONTINUOUS"
        state.openingReferencePriceTicks = state.runtime.initialPriceTicks
        state.haltReferencePriceTicks = float(state.openingReferencePriceTicks)
        return

    auctionTraceId = _recordTrace(
        state,
        step=0,
        eventType="OPENING_AUCTION_STARTED",
        agentId=None,
        parentTraceId=None,
        summary="The simplified research opening auction accepted executable system interest.",
        summaryZh="研究用简化开盘集合竞价已接收可执行系统委托。",
        payload={
            "benchmarkOpeningBps": state.runtime.benchmarkOpeningBps,
            "institutionalShare": state.runtime.institutionalShare,
        },
    )
    cohortPressureBps = (state.runtime.institutionalShare - 0.2) * 4.0
    clearingPriceTicks = _snapToTick(
        state.runtime.initialPriceTicks
        * (1 + (state.runtime.benchmarkOpeningBps + cohortPressureBps) / 10_000),
        state.runtime.tickSizeTicks,
        "nearest",
    )
    auctionQuantity = max(
        4,
        round(len(state.population) * (0.25 + state.runtime.institutionalShare * 0.4)),
    )
    sellReport, sellRisk = _submitLimitWithRisk(
        state,
        orderId="opening-auction-sell",
        agentId="opening-auction-seller",
        side=Side.SELL,
        priceTicks=clearingPriceTicks,
        quantity=auctionQuantity,
        step=0,
        timeInForce=TimeInForce.GTC,
        maxOrderQuantity=100_000,
        maxAbsolutePosition=500_000,
        allowShortSelling=False,
    )
    buyReport, buyRisk = _submitLimitWithRisk(
        state,
        orderId="opening-auction-buy",
        agentId="opening-auction-buyer",
        side=Side.BUY,
        priceTicks=clearingPriceTicks,
        quantity=auctionQuantity,
        step=0,
        timeInForce=TimeInForce.IOC,
        maxOrderQuantity=100_000,
        maxAbsolutePosition=500_000,
    )
    if (
        sellReport is None
        or buyReport is None
        or sellRisk.decision is RiskDecision.REJECT
        or buyRisk.decision is RiskDecision.REJECT
    ):
        raise RuntimeError("opening auction failed deterministic ledger risk checks")
    _applyTrades(state, buyReport.trades, agentById, auctionTraceId)
    _releaseIocRemainder(state, buyReport)
    state.openingAuctionVolume = sum(trade.quantity for trade in buyReport.trades)
    state.openingReferencePriceTicks = clearingPriceTicks
    state.haltReferencePriceTicks = float(clearingPriceTicks)
    state.marketState = "CONTINUOUS"
    _recordTrace(
        state,
        step=0,
        eventType="OPENING_AUCTION_CLEARED",
        agentId=None,
        parentTraceId=auctionTraceId,
        summary="The opening auction produced a tick-aligned opening reference price.",
        summaryZh="开盘集合竞价形成了符合最小价位网格的开盘参考价。",
        payload={
            "clearingPriceTicks": clearingPriceTicks,
            "clearingPrice": round(clearingPriceTicks / state.runtime.priceScale, 4),
            "executedQuantity": state.openingAuctionVolume,
        },
    )


def _seedOpeningBook(state: SimulationState) -> None:
    depthMultiplier = max(0.1, min(_parameterValue(state, "liquidityDepthMultiplier"), 3.0))
    referencePriceTicks = state.openingReferencePriceTicks
    for level in range(1, 5):
        quantity = max(1, round((20 - level * 2) * depthMultiplier))
        for side, priceTicks in (
            (
                Side.BUY,
                referencePriceTicks - level * 3 * state.runtime.tickSizeTicks,
            ),
            (
                Side.SELL,
                referencePriceTicks + level * 3 * state.runtime.tickSizeTicks,
            ),
        ):
            state.orderCounter += 1
            orderId = f"opening-{side.value.lower()}-{state.orderCounter}"
            report, risk = _submitLimitWithRisk(
                state,
                orderId=orderId,
                agentId="opening-liquidity",
                side=side,
                priceTicks=priceTicks,
                quantity=quantity,
                step=-1,
                timeInForce=TimeInForce.GTC,
                maxOrderQuantity=100_000,
                maxAbsolutePosition=500_000,
            )
            if report is None or risk.decision is RiskDecision.REJECT:
                raise RuntimeError("opening liquidity failed deterministic ledger risk checks")


def _advanceBenchmark(
    currentLevel: float,
    step: int,
    shockStep: int,
    runtime: ScenarioRuntimeConfig,
    benchmarkRandom: random.Random,
) -> tuple[float, float]:
    if runtime.benchmarkProfile == "NO_BENCHMARK":
        return currentLevel, 0.0
    returnBps = runtime.benchmarkDriftBps + benchmarkRandom.gauss(0, 0.85)
    if step == shockStep:
        returnBps += runtime.benchmarkShockBps
    elif step > shockStep + 8:
        returnBps += 0.18
    nextLevel = max(1.0, currentLevel * math.exp(returnBps / 10_000))
    return nextLevel, returnBps


def _advanceFundamental(
    currentPriceTicks: float,
    step: int,
    shockStep: int,
    benchmarkReturnBps: float,
    runtime: ScenarioRuntimeConfig,
    marketRandom: random.Random,
) -> float:
    oneCentTicks = runtime.priceScale / 100
    innovation = marketRandom.gauss(0, 1.15 * oneCentTicks)
    benchmarkComponent = currentPriceTicks * benchmarkReturnBps / 10_000 * runtime.benchmarkBeta
    idiosyncraticJump = -8.0 * oneCentTicks if step == shockStep else 0.0
    slowRecovery = 0.32 * oneCentTicks if step > shockStep + 8 else 0.0
    return max(
        runtime.tickSizeTicks,
        currentPriceTicks + innovation + benchmarkComponent + idiosyncraticJump + slowRecovery,
    )


def _advanceSentiment(
    currentSentiment: float,
    step: int,
    shockStep: int,
    clarificationStep: int,
    socialAmplification: float,
    marketRandom: random.Random,
) -> float:
    commonNoise = marketRandom.gauss(0, 0.012)
    if step == shockStep:
        return max(-1.0, -0.48 * socialAmplification + commonNoise)
    if shockStep < step < clarificationStep:
        propagated = currentSentiment * (0.88 + min(socialAmplification, 3.0) * 0.025)
        return max(-1.0, min(1.0, propagated - 0.012 * socialAmplification + commonNoise))
    if step >= clarificationStep:
        return max(-1.0, min(1.0, currentSentiment * 0.72 + 0.025 + commonNoise))
    return max(-1.0, min(1.0, currentSentiment * 0.9 + commonNoise))


def _updateMarketState(
    state: SimulationState,
    step: int,
    observedPriceTicks: float,
) -> bool:
    if state.marketState == "HALTED":
        state.haltedSteps += 1
        if state.haltUntilStep is not None and step >= state.haltUntilStep:
            state.marketState = "CONTINUOUS"
            state.haltUntilStep = None
            state.haltReferencePriceTicks = observedPriceTicks
            _recordTrace(
                state,
                step=step,
                eventType="VOLATILITY_HALT_ENDED",
                agentId=None,
                parentTraceId=None,
                summary="The research volatility halt ended and continuous trading resumed.",
                summaryZh="研究用波动停牌结束，连续交易恢复。",
                payload={
                    "reopenReferencePriceTicks": round(observedPriceTicks),
                    "haltCount": state.haltCount,
                    "resumeMechanism": "CONTINUOUS_REQUOTE",
                },
            )
            return False
        return True

    if (
        not state.runtime.volatilityHalt
        or state.haltCount >= state.runtime.maximumVolatilityHalts
        or step <= 0
        or not state.prices
    ):
        return False
    observedMoveBps = abs(observedPriceTicks / max(state.haltReferencePriceTicks, 1.0) - 1) * 10_000
    if observedMoveBps < state.runtime.volatilityHaltThresholdBps:
        return False

    # 研究用 halt 保留已经在簿的 GTC 委托，只阻止新订单与连续撮合；复牌时
    # 做市商刷新会按正常撤单路径释放这些预留资源。
    cancelledOrders = 0
    state.marketState = "HALTED"
    state.haltCount += 1
    state.haltedSteps += 1
    state.haltUntilStep = min(
        state.steps - 1,
        step + state.runtime.volatilityHaltDurationSteps,
    )
    _recordTrace(
        state,
        step=step,
        eventType="VOLATILITY_HALT_TRIGGERED",
        agentId=None,
        parentTraceId=None,
        summary="The simplified research volatility threshold paused continuous trading.",
        summaryZh="研究用简化波动阈值触发，连续交易暂停。",
        payload={
            "observedMoveBps": round(observedMoveBps, 6),
            "thresholdBps": state.runtime.volatilityHaltThresholdBps,
            "resumeStep": state.haltUntilStep,
            "cancelledRestingOrders": cancelledOrders,
        },
    )
    return True


def _recordHaltRejection(
    state: SimulationState,
    step: int,
    agentId: str,
    parentTraceId: str | None,
    quantity: int,
) -> None:
    _recordTrace(
        state,
        step=step,
        eventType="ORDER_REJECTED_MARKET_HALTED",
        agentId=agentId,
        parentTraceId=parentTraceId,
        summary="The market-state gate rejected an order that arrived during a halt.",
        summaryZh="市场状态门拒绝了停牌期间到达的订单。",
        payload={
            "requestedQuantity": quantity,
            "marketState": state.marketState,
            "haltCount": state.haltCount,
        },
    )


def _refreshMarketMakerQuotes(
    state: SimulationState,
    priorPriceTicks: float,
    quoteRandom: random.Random,
    step: int,
) -> None:
    if step == 0:
        _cancelAgentOrders(state, "opening-liquidity")
    capacity = max(0.15, min(_parameterValue(state, "marketMakerCapacity"), 3.0))
    depthMultiplier = max(0.1, min(_parameterValue(state, "liquidityDepthMultiplier"), 3.0))
    effectiveCapacity = math.sqrt(capacity * depthMultiplier)
    marketMakers = [
        agent for agent in state.population if agent.agentType == AgentType.MARKET_MAKER
    ]
    recentMove = abs(state.prices[-1] - state.prices[-2]) if len(state.prices) >= 2 else 0.0
    recentMoveInTicks = recentMove / state.runtime.tickSizeTicks
    halfSpreadInTicks = max(
        2,
        round(1.4 + 4.2 / effectiveCapacity + min(recentMoveInTicks / 3, 7)),
    )
    baseQuantity = max(2, round(13 * capacity * depthMultiplier))

    for makerIndex, marketMaker in enumerate(marketMakers):
        _cancelAgentOrders(state, marketMaker.agentId)
        inventorySkewTicks = round(marketMaker.position / max(12 * effectiveCapacity, 1))
        quoteCenter = _snapToTick(
            priorPriceTicks
            - inventorySkewTicks * state.runtime.tickSizeTicks
            + quoteRandom.choice((-1, 0, 1)) * state.runtime.tickSizeTicks,
            state.runtime.tickSizeTicks,
            "nearest",
        )
        for level in range(3):
            levelDistance = state.runtime.tickSizeTicks * (
                halfSpreadInTicks + level * max(2, round(2.5 / effectiveCapacity))
            )
            levelQuantity = max(1, baseQuantity - level * 2)
            plannedBidTicks = max(1, quoteCenter - levelDistance)
            bestAskTicks = state.orderBook.bestAsk()
            bidPriceTicks = (
                min(plannedBidTicks, bestAskTicks - state.runtime.tickSizeTicks)
                if bestAskTicks is not None
                else plannedBidTicks
            )
            if bidPriceTicks > 0:
                state.orderCounter += 1
                bidReport, _ = _submitLimitWithRisk(
                    state,
                    orderId=f"mm-{step}-{makerIndex}-b-{state.orderCounter}",
                    agentId=marketMaker.agentId,
                    side=Side.BUY,
                    priceTicks=bidPriceTicks,
                    quantity=levelQuantity,
                    step=step,
                    timeInForce=TimeInForce.GTC,
                    maxOrderQuantity=100,
                    maxAbsolutePosition=marketMaker.maxAbsolutePosition,
                )
                if bidReport is not None and bidReport.trades:
                    raise RuntimeError("post-only market-maker bid unexpectedly traded")

            plannedAskTicks = max(state.runtime.tickSizeTicks, quoteCenter + levelDistance)
            bestBidTicks = state.orderBook.bestBid()
            askPriceTicks = (
                max(plannedAskTicks, bestBidTicks + state.runtime.tickSizeTicks)
                if bestBidTicks is not None
                else plannedAskTicks
            )
            state.orderCounter += 1
            askReport, _ = _submitLimitWithRisk(
                state,
                orderId=f"mm-{step}-{makerIndex}-s-{state.orderCounter}",
                agentId=marketMaker.agentId,
                side=Side.SELL,
                priceTicks=askPriceTicks,
                quantity=levelQuantity,
                step=step,
                timeInForce=TimeInForce.GTC,
                maxOrderQuantity=100,
                maxAbsolutePosition=marketMaker.maxAbsolutePosition,
                allowShortSelling=False,
            )
            if askReport is not None and askReport.trades:
                raise RuntimeError("post-only market-maker ask unexpectedly traded")


def _submitSystemFlow(
    state: SimulationState,
    step: int,
    side: Side,
    quantity: int,
    reason: str,
    agentById: dict[str, AgentState],
) -> None:
    state.orderCounter += 1
    orderId = f"system-{step}-{state.orderCounter}"
    referencePriceTicks = round(
        state.orderBook.midPrice(
            round(state.prices[-1]) if state.prices else state.runtime.initialPriceTicks
        )
    )
    protectedPriceTicks = _protectedPrice(
        side,
        referencePriceTicks,
        state.runtime.priceCollarBps,
        state.runtime.tickSizeTicks,
    )
    report, risk = _submitLimitWithRisk(
        state,
        orderId=orderId,
        agentId="synthetic-event-flow",
        side=side,
        priceTicks=protectedPriceTicks,
        quantity=quantity,
        step=step,
        timeInForce=TimeInForce.IOC,
        maxOrderQuantity=1_000,
        maxAbsolutePosition=500_000,
    )
    riskTraceId = _recordRiskTrace(
        state,
        step=step,
        agentId="synthetic-event-flow",
        parentTraceId=state.factTraceId,
        risk=risk,
    )
    if report is None:
        return
    orderTraceId = _recordTrace(
        state,
        step=step,
        eventType="SYSTEM_ORDER_SUBMITTED",
        agentId="synthetic-event-flow",
        parentTraceId=riskTraceId,
        summary="A declared synthetic scenario flow submitted a protected order.",
        summaryZh="已声明的合成场景资金流提交了带价格保护的订单。",
        payload={
            "side": side.value,
            "requestedQuantity": quantity,
            "approvedQuantity": report.order.quantity,
            "limitPriceTicks": report.order.priceTicks,
            "reasonCode": reason,
        },
    )
    _applyTrades(state, report.trades, agentById, orderTraceId)
    state.protectedUnfilled += quantity - sum(trade.quantity for trade in report.trades)
    _releaseIocRemainder(state, report)


def _recordNetworkDelivery(
    state: SimulationState,
    step: int,
    payload: Mapping[str, Any],
) -> None:
    nodeId = str(payload["nodeId"])
    receiptId = str(payload["receiptId"])
    parentReceiptId = payload.get("parentReceiptId")
    parentTraceId = (
        state.receiptTraceIds.get(str(parentReceiptId))
        if parentReceiptId is not None
        else state.factTraceId
    )
    agentId = state.nodeToAgentId[nodeId]
    traceId = _recordTrace(
        state,
        step=step,
        eventType="SOCIAL_PROPAGATED",
        agentId=agentId,
        parentTraceId=parentTraceId,
        summary="The synthetic information network delivered an evidence-linked message.",
        summaryZh="合成信息网络送达了一条带证据链的消息。",
        payload={
            "receiptId": receiptId,
            "nodeId": nodeId,
            "senderNodeId": payload.get("senderNodeId"),
            "hopCount": int(payload["hopCount"]),
            "distorted": bool(payload["distorted"]),
            "receivedAt": payload["receivedAt"],
        },
    )
    state.receiptTraceIds[receiptId] = traceId
    state.latestInformationTraceByAgent[agentId] = traceId
    state.networkDeliveredNodes.add(nodeId)
    state.networkDeliverySteps.append(step)


def _activateAgents(
    state: SimulationState,
    step: int,
    activationTimestampMs: int,
    fundamentalPriceTicks: float,
    sentiment: float,
    randomStreams: dict[str, random.Random],
    agentById: dict[str, AgentState],
    eventQueue: DeterministicEventQueue,
) -> None:
    fallbackPrice = round(state.prices[-1]) if state.prices else state.runtime.initialPriceTicks
    currentMid = state.orderBook.midPrice(fallbackPrice)
    recentPrices = tuple((state.prices or [float(state.runtime.initialPriceTicks)])[-10:])
    context = MarketContext(
        step=step,
        steps=state.steps,
        midPriceTicks=currentMid,
        fundamentalPriceTicks=fundamentalPriceTicks,
        recentPricesTicks=recentPrices,
        sentiment=sentiment,
        stopLossSensitivity=_parameterValue(state, "stopLossSensitivity"),
        passiveFlowMultiplier=_parameterValue(state, "passiveFlowMultiplier"),
        bestBidTicks=state.orderBook.bestBid(),
        bestAskTicks=state.orderBook.bestAsk(),
        depthWithinTenBps=state.orderBook.depth(3),
        priceCollarBps=round(state.runtime.priceCollarBps),
        instrumentId=state.runtime.instrumentId,
        simTime=state.simulationStart + timedelta(seconds=step * SIMULATION_STEP_SECONDS),
    )
    for agent in state.population:
        if agent.agentType == AgentType.MARKET_MAKER:
            continue
        cognitiveSignals = state.cognitiveAssignments.get(agent.agentId, [])
        cognitiveUseIndex = state.cognitiveUseCount.get(agent.agentId, 0)
        cognitiveSignal = (
            cognitiveSignals[cognitiveUseIndex]
            if cognitiveUseIndex < len(cognitiveSignals)
            else None
        )
        activeFromStep = (
            int(cognitiveSignal.get("activeFromStep", 0)) if cognitiveSignal is not None else 0
        )
        cognitiveReady = (
            cognitiveSignal is not None
            and step >= activeFromStep
            and agent.agentId in state.latestInformationTraceByAgent
        )
        activationProbability = _activationProbability(agent, state, step, sentiment)
        activationDraw = random.Random(
            _derivedSeed(state.seed, f"activation:{step}:{agent.agentId}")
        ).random()
        if not cognitiveReady and activationDraw > activationProbability:
            continue

        parentTraceId = state.latestInformationTraceByAgent.get(agent.agentId)
        observationTraceId = _recordTrace(
            state,
            step=step,
            eventType="OBSERVATION_CREATED",
            agentId=agent.agentId,
            parentTraceId=parentTraceId,
            summary="The agent received a point-in-time market and information observation.",
            summaryZh="智能体收到了一份时点安全的市场与信息观察。",
            payload={
                "agentType": agent.agentType.value,
                "midPriceTicks": round(currentMid),
                "fundamentalPriceTicks": round(fundamentalPriceTicks),
                "sentiment": round(sentiment, 6),
                "networkEvidenceAvailable": parentTraceId is not None,
                "cognitive": cognitiveReady,
            },
        )
        if cognitiveReady and cognitiveSignal is not None:
            intent = makeCognitiveOrderIntent(agent, context, cognitiveSignal)
            state.cognitiveUseCount[agent.agentId] = cognitiveUseIndex + 1
            fallbackUsed = bool(cognitiveSignal.get("fallbackUsed", False))
            beliefPayload = {
                "source": ("RULE_FALLBACK_BELIEF_SIGNAL" if fallbackUsed else "LLM_BELIEF_SIGNAL"),
                "decisionId": cognitiveSignal.get("decisionId"),
                "decisionRound": cognitiveSignal.get("decisionRound"),
                "activeFromStep": activeFromStep,
                "direction": cognitiveSignal.get("direction"),
                "actionPreference": cognitiveSignal.get("actionPreference"),
                "evidenceIds": cognitiveSignal.get("evidenceIds", []),
                "confidence": cognitiveSignal.get("confidence"),
                "uncertainty": cognitiveSignal.get("uncertainty"),
                "fallbackUsed": fallbackUsed,
                "repairUsed": bool(cognitiveSignal.get("repairUsed", False)),
                "failureReason": cognitiveSignal.get("failureReason"),
                "failureCodes": cognitiveSignal.get("failureCodes", []),
            }
        else:
            behaviorRandom = random.Random(
                _derivedSeed(state.seed, f"behavior:{step}:{agent.agentId}")
            )
            orderSizeRandom = random.Random(
                _derivedSeed(state.seed, f"orderSize:{step}:{agent.agentId}")
            )
            intent = makeOrderIntent(agent, context, behaviorRandom, orderSizeRandom)
            beliefPayload = {
                "source": "RULE_AGENT",
                "agentType": agent.agentType.value,
                "actionPreference": intent.side.value if intent is not None else "HOLD",
                "confidence": round(intent.urgency, 6) if intent is not None else 0.0,
            }

        if intent is not None and intent.limitPriceTicks is not None:
            intent = replace(
                intent,
                limitPriceTicks=_snapToTick(
                    intent.limitPriceTicks,
                    state.runtime.tickSizeTicks,
                    "ceil" if intent.side is Side.BUY else "floor",
                ),
            )

        beliefTraceId = _recordTrace(
            state,
            step=step,
            eventType="BELIEF_UPDATED",
            agentId=agent.agentId,
            parentTraceId=observationTraceId,
            summary="The bounded cognitive or rule layer produced an action preference.",
            summaryZh="受约束的认知层或规则层生成了行动偏好。",
            payload=beliefPayload,
        )
        if intent is None:
            _recordTrace(
                state,
                step=step,
                eventType="ACTION_INTENT_CREATED",
                agentId=agent.agentId,
                parentTraceId=beliefTraceId,
                summary="Deterministic policy produced a no-order intent.",
                summaryZh="确定性策略生成了不下单意图。",
                payload={"proposedQuantity": 0, "status": "NO_ORDER"},
            )
            continue

        intentTraceId = _recordTrace(
            state,
            step=step,
            eventType="ACTION_INTENT_CREATED",
            agentId=agent.agentId,
            parentTraceId=beliefTraceId,
            summary="Deterministic policy translated the preference into a bounded intent.",
            summaryZh="确定性策略将偏好转换为有界行动意图。",
            payload={
                "side": intent.side.value,
                "proposedQuantity": intent.quantity,
                "urgency": round(intent.urgency, 6),
                "reasonCode": intent.reason,
                "sourceDecisionId": intent.sourceDecisionId,
                "generatedLimitPriceTicks": intent.limitPriceTicks,
                "policyTrace": list(intent.policyTrace),
                "cognitive": intent.cognitive,
            },
        )
        arrivalTimestampMs = activationTimestampMs + state.runtime.latencyMs
        simulationEndTimestamp = state.steps * SIMULATION_STEP_MILLISECONDS
        if arrivalTimestampMs >= simulationEndTimestamp:
            state.latencyExpiredOrders += 1
            _recordTrace(
                state,
                step=step,
                eventType="ORDER_EXPIRED_BEFORE_ARRIVAL",
                agentId=agent.agentId,
                parentTraceId=intentTraceId,
                summary="Configured order latency placed the intent beyond the simulation window.",
                summaryZh="配置的订单延迟使意图到达时间超出仿真窗口。",
                payload={
                    "latencyMs": state.runtime.latencyMs,
                    "arrivalTimestampMs": arrivalTimestampMs,
                    "simulationEndTimestampMs": simulationEndTimestamp,
                },
            )
            continue
        state.latencyScheduledOrders += 1
        eventQueue.schedule(
            timestamp=arrivalTimestampMs,
            priority=EventPriority.ORDER_ARRIVAL,
            eventType="AGENT_ORDER_ARRIVED",
            payload={
                "agentId": agent.agentId,
                "intent": intent,
                "intentTraceId": intentTraceId,
                "referencePriceTicks": round(currentMid),
                "activationStep": step,
                "activationTimestampMs": activationTimestampMs,
                "arrivalTimestampMs": arrivalTimestampMs,
                "latencyMs": state.runtime.latencyMs,
            },
            eventId=f"agent-arrival-{state.latencyScheduledOrders:08d}",
        )


def _processAgentOrderArrival(
    state: SimulationState,
    step: int,
    payload: Mapping[str, Any],
    agentById: dict[str, AgentState],
) -> None:
    agentId = str(payload["agentId"])
    agent = agentById[agentId]
    intent = payload["intent"]
    if not isinstance(intent, OrderIntent):
        raise RuntimeError("scheduled agent order contains an invalid intent")
    intentTraceId = str(payload["intentTraceId"])
    if state.marketState == "HALTED":
        state.haltRejectedOrders += 1
        _recordHaltRejection(
            state,
            step,
            agentId,
            intentTraceId,
            intent.quantity,
        )
        return
    _recordTrace(
        state,
        step=step,
        eventType="ORDER_ARRIVED",
        agentId=agentId,
        parentTraceId=intentTraceId,
        summary="The configured market latency elapsed and the order reached the exchange.",
        summaryZh="配置的市场延迟结束，订单已到达交易所。",
        payload={
            "activationStep": payload["activationStep"],
            "activationTimestampMs": payload["activationTimestampMs"],
            "arrivalTimestampMs": payload["arrivalTimestampMs"],
            "latencyMs": payload["latencyMs"],
        },
    )
    _submitAgentIntent(
        state,
        step,
        agent,
        intent,
        intentTraceId,
        agentById,
        int(payload["referencePriceTicks"]),
    )


def _activationProbability(
    agent: AgentState,
    state: SimulationState,
    step: int,
    sentiment: float,
) -> float:
    probability = 0.18
    inclusionWindow = round(state.steps * 0.28) <= step <= round(state.steps * 0.58)
    if agent.agentType == AgentType.PASSIVE and inclusionWindow:
        probability = min(0.95, 0.7 * _parameterValue(state, "passiveFlowMultiplier"))
    elif agent.agentType == AgentType.INSTITUTIONAL and inclusionWindow:
        probability = min(0.9, 0.55 * _parameterValue(state, "passiveFlowMultiplier"))
    elif agent.agentType == AgentType.DELEVERAGING and sentiment <= -0.12:
        probability = 0.72
    elif agent.agentType == AgentType.LIQUIDATION and sentiment <= -0.3:
        probability = 0.9
    elif agent.agentType == AgentType.ARBITRAGE:
        probability = 0.35
    return max(0.0, min(1.0, probability))


def _submitAgentIntent(
    state: SimulationState,
    step: int,
    agent: AgentState,
    intent: OrderIntent,
    intentTraceId: str,
    agentById: dict[str, AgentState],
    referencePriceTicks: int,
) -> None:
    _cancelAgentOrders(state, agent.agentId)
    state.orderCounter += 1
    orderId = f"agent-{step}-{state.orderCounter}"
    if intent.limitPriceTicks is not None:
        priceTicks = _snapToTick(
            intent.limitPriceTicks,
            state.runtime.tickSizeTicks,
            "ceil" if intent.side is Side.BUY else "floor",
        )
        timeInForce = TimeInForce.IOC if intent.timeInForce == "IOC" else TimeInForce.GTC
    elif intent.useMarket:
        priceTicks = _protectedPrice(
            intent.side,
            referencePriceTicks,
            state.runtime.priceCollarBps,
            state.runtime.tickSizeTicks,
        )
        timeInForce = TimeInForce.IOC
    else:
        offset = state.runtime.tickSizeTicks * (1 + round((1 - intent.urgency) * 3))
        rawPriceTicks = (
            max(state.runtime.tickSizeTicks, referencePriceTicks - offset)
            if intent.side is Side.BUY
            else referencePriceTicks + offset
        )
        priceTicks = _snapToTick(
            rawPriceTicks,
            state.runtime.tickSizeTicks,
            "floor" if intent.side is Side.BUY else "ceil",
        )
        timeInForce = TimeInForce.GTC

    report, risk = _submitLimitWithRisk(
        state,
        orderId=orderId,
        agentId=agent.agentId,
        side=intent.side,
        priceTicks=priceTicks,
        quantity=intent.quantity,
        step=step,
        timeInForce=timeInForce,
        maxOrderQuantity=80,
        maxAbsolutePosition=agent.maxAbsolutePosition,
    )
    riskTraceId = _recordRiskTrace(
        state,
        step=step,
        agentId=agent.agentId,
        parentTraceId=intentTraceId,
        risk=risk,
    )
    flow = state.agentFlows[agent.agentType.value]
    if report is None:
        flow["riskRejectedCount"] += 1
        return
    flow["orderCount"] += 1
    if intent.cognitive:
        state.cognitiveOrderCount += 1
    orderTraceId = _recordTrace(
        state,
        step=step,
        eventType="ORDER_SUBMITTED",
        agentId=agent.agentId,
        parentTraceId=riskTraceId,
        summary=f"A {agent.agentType.value} agent submitted a risk-approved order.",
        summaryZh=f"一个 {agent.agentType.value} 智能体提交了通过风控的订单。",
        payload={
            "agentType": agent.agentType.value,
            "side": intent.side.value,
            "requestedQuantity": intent.quantity,
            "approvedQuantity": report.order.quantity,
            "orderType": "MARKETABLE_LIMIT" if timeInForce is TimeInForce.IOC else "LIMIT",
            "timeInForce": timeInForce.value,
            "limitPriceTicks": priceTicks,
            "reasonCode": intent.reason,
            "cognitive": intent.cognitive,
        },
    )
    _applyTrades(state, report.trades, agentById, orderTraceId)
    executedQuantity = sum(
        trade.quantity for trade in report.trades if trade.takerAgentId == agent.agentId
    )
    if intent.reason == "stop-loss-triggered-sell":
        state.stopLossVolume += executedQuantity
    if intent.forced:
        state.forcedLiquidationVolume += executedQuantity
        flow["forcedVolume"] += executedQuantity
    if timeInForce is TimeInForce.IOC:
        state.protectedUnfilled += intent.quantity - executedQuantity
        _releaseIocRemainder(state, report)


def _submitLimitWithRisk(
    state: SimulationState,
    *,
    orderId: str,
    agentId: str,
    side: Side,
    priceTicks: int,
    quantity: int,
    step: int,
    timeInForce: TimeInForce,
    maxOrderQuantity: int,
    maxAbsolutePosition: int,
    allowShortSelling: bool | None = None,
) -> tuple[ExecutionReport | None, OrderRiskResult]:
    if state.ledger is None:
        risk = OrderRiskResult(
            decision=RiskDecision.ACCEPT,
            requestedQuantity=quantity,
            approvedQuantity=quantity,
        )
    else:
        risk = state.ledger.evaluateAndReserveOrder(
            orderId=orderId,
            accountId=agentId,
            instrumentId=state.runtime.instrumentId,
            side=LedgerSide.BUY if side is Side.BUY else LedgerSide.SELL,
            quantity=quantity,
            limitPriceTicks=priceTicks,
            maxOrderQuantity=maxOrderQuantity,
            maxAbsolutePosition=maxAbsolutePosition,
            allowShortSelling=(
                state.runtime.allowShortSelling if allowShortSelling is None else allowShortSelling
            ),
        )
    if risk.decision is RiskDecision.REJECT:
        state.ledgerRejectedOrders += 1
        return None, risk
    if risk.decision is RiskDecision.MODIFY:
        state.ledgerModifiedOrders += 1
    report = state.orderBook.submitLimit(
        orderId=orderId,
        agentId=agentId,
        side=side,
        priceTicks=priceTicks,
        quantity=risk.approvedQuantity,
        step=step,
        timeInForce=timeInForce,
    )
    return report, risk


def _recordRiskTrace(
    state: SimulationState,
    *,
    step: int,
    agentId: str,
    parentTraceId: str | None,
    risk: OrderRiskResult,
) -> str:
    return _recordTrace(
        state,
        step=step,
        eventType="RISK_CHECK",
        agentId=agentId,
        parentTraceId=parentTraceId,
        summary="The deterministic portfolio ledger approved, modified, or rejected the intent.",
        summaryZh="确定性组合账本对意图进行了批准、修改或拒绝。",
        payload={
            "decision": risk.decision.value,
            "requestedQuantity": risk.requestedQuantity,
            "approvedQuantity": risk.approvedQuantity,
            "modifications": list(risk.modifications),
            "rejectionReason": risk.rejectionReason,
        },
    )


def _cancelAgentOrders(state: SimulationState, agentId: str) -> int:
    orderIds = sorted(
        orderId for orderId, order in state.orderBook.orderIndex.items() if order.agentId == agentId
    )
    cancelled = 0
    for orderId in orderIds:
        if state.orderBook.cancelOrder(orderId):
            cancelled += 1
            if state.ledger is not None and orderId in state.ledger.reservations:
                state.ledger.releaseOrder(orderId)
    return cancelled


def _releaseIocRemainder(state: SimulationState, report: ExecutionReport) -> None:
    orderId = report.order.orderId
    if state.ledger is not None and orderId in state.ledger.reservations:
        state.ledger.releaseOrder(orderId)


def _protectedPrice(
    side: Side,
    referencePriceTicks: int,
    collarBps: float,
    tickSizeTicks: int,
) -> int:
    multiplier = collarBps / 10_000
    if side is Side.BUY:
        return _snapToTick(
            referencePriceTicks * (1 + multiplier),
            tickSizeTicks,
            "ceil",
        )
    return _snapToTick(
        referencePriceTicks * (1 - multiplier),
        tickSizeTicks,
        "floor",
    )


def _applyTrades(
    state: SimulationState,
    trades: list[Trade],
    agentById: dict[str, AgentState],
    parentTraceId: str,
) -> None:
    for trade in trades:
        if trade.buyerAgentId == trade.sellerAgentId:
            raise RuntimeError("self-trade prevention invariant failed")
        if state.ledger is not None:
            state.ledger.applyTrade(
                buyOrderId=trade.buyOrderId,
                sellOrderId=trade.sellOrderId,
                priceTicks=trade.priceTicks,
                quantity=trade.quantity,
            )
        state.recordedTradeCount += 1
        state.ledgerPositions[trade.buyerAgentId] = (
            state.ledgerPositions.get(trade.buyerAgentId, 0) + trade.quantity
        )
        state.ledgerPositions[trade.sellerAgentId] = (
            state.ledgerPositions.get(trade.sellerAgentId, 0) - trade.quantity
        )
        cashTransferred = (
            state.ledger.notionalCents(trade.priceTicks, trade.quantity)
            if state.ledger is not None
            else round(trade.priceTicks * trade.quantity * 100 / state.runtime.priceScale)
        )
        state.ledgerCashChangeCents[trade.buyerAgentId] = (
            state.ledgerCashChangeCents.get(trade.buyerAgentId, 0) - cashTransferred
        )
        state.ledgerCashChangeCents[trade.sellerAgentId] = (
            state.ledgerCashChangeCents.get(trade.sellerAgentId, 0) + cashTransferred
        )
        buyer = agentById.get(trade.buyerAgentId)
        seller = agentById.get(trade.sellerAgentId)
        _syncAgentFromLedger(state, buyer)
        _syncAgentFromLedger(state, seller)

        if buyer is not None:
            buyerFlow = state.agentFlows[buyer.agentType.value]
            buyerFlow["buyVolume"] += trade.quantity
            buyerFlow["netVolume"] += trade.quantity
        if seller is not None:
            sellerFlow = state.agentFlows[seller.agentType.value]
            sellerFlow["sellVolume"] += trade.quantity
            sellerFlow["netVolume"] -= trade.quantity

        if trade.aggressiveSide == Side.BUY:
            state.totalBuyVolume += trade.quantity
        else:
            state.totalSellVolume += trade.quantity
        _recordTrace(
            state,
            step=trade.step,
            eventType="TRADE_EXECUTED",
            agentId=trade.takerAgentId,
            parentTraceId=parentTraceId,
            summary="The order matched at the resting order price and settled in the ledger.",
            summaryZh="订单按在簿订单价格成交并在账本中完成结算。",
            payload={
                "tradeId": trade.tradeId,
                "priceTicks": trade.priceTicks,
                "quantity": trade.quantity,
                "aggressiveSide": trade.aggressiveSide.value,
                "makerAgentId": trade.makerAgentId,
                "takerAgentId": trade.takerAgentId,
                "buyOrderId": trade.buyOrderId,
                "sellOrderId": trade.sellOrderId,
            },
        )


def _syncAgentFromLedger(state: SimulationState, agent: AgentState | None) -> None:
    if agent is None or state.ledger is None:
        return
    account = state.ledger.accounts[agent.agentId]
    agent.position = account.getPosition(state.runtime.instrumentId).quantity
    agent.cashCents = account.cashCents


def _captureSnapshot(
    state: SimulationState,
    fundamentalPriceTicks: float,
    sentiment: float,
) -> None:
    fallbackPrice = round(state.prices[-1]) if state.prices else state.runtime.initialPriceTicks
    snapshot = state.orderBook.snapshot(fallbackPrice, levels=3)
    priceTicks = float(
        snapshot["lastTradePriceTicks"] or snapshot["midPriceTicks"] or fallbackPrice
    )
    spreadBps = float(snapshot["spreadBps"] or 0.0)
    priorCumulativeVolume = sum(state.volumes)
    cumulativeVolume = state.totalBuyVolume + state.totalSellVolume
    stepVolume = max(0, cumulativeVolume - priorCumulativeVolume)
    depth = int(snapshot["depth"] or 0)
    networkReach = len(state.networkDeliveredNodes) / max(len(state.population), 1)
    liquidityStress = spreadBps * (1 + 25 / max(depth, 1))
    priorPeak = max([*state.prices, priceTicks], default=priceTicks)
    drawdown = max(0.0, (priorPeak - priceTicks) / max(priorPeak, 1.0))
    tailRisk = min(
        1.0,
        drawdown * 12 + max(0.0, -sentiment) * 0.45 + state.protectedUnfilled / 2_000,
    )
    state.prices.append(priceTicks)
    state.fundamentals.append(fundamentalPriceTicks)
    state.spreadBps.append(spreadBps)
    state.depths.append(depth)
    state.volumes.append(stepVolume)
    state.sentiments.append(sentiment)
    state.networkReachPath.append(networkReach)
    state.liquidityStressPath.append(liquidityStress)
    state.tailRiskPath.append(tailRisk)
    state.systemEquityPath.append(_totalSystemEquity(state, round(priceTicks)))


def _totalSystemEquity(state: SimulationState, markPriceTicks: int) -> int:
    if state.ledger is None:
        return sum(
            agent.cashCents
            + round(agent.position * markPriceTicks * 100 / state.runtime.priceScale)
            for agent in state.population
        )
    return (
        sum(
            state.ledger.markToMarket(
                accountId,
                {state.runtime.instrumentId: markPriceTicks},
            ).equityCents
            for accountId in state.ledger.accounts
        )
        + state.ledger.feeCollectorCashCents
    )


def _finalizeAgentAccounting(state: SimulationState) -> list[dict[str, Any]]:
    markPrice = round(state.prices[-1]) if state.prices else state.runtime.initialPriceTicks
    rows: list[dict[str, Any]] = []
    for agent in state.population:
        if state.ledger is None:
            equity = agent.cashCents + round(
                agent.position * markPrice * 100 / state.runtime.priceScale
            )
            initialEquity = 10_000_000 + round(
                agent.initialPosition
                * state.runtime.initialPriceTicks
                * 100
                / state.runtime.priceScale
            )
            realized = 0
            unrealized = equity - initialEquity
        else:
            valuation = state.ledger.markToMarket(
                agent.agentId,
                {state.runtime.instrumentId: markPrice},
            )
            equity = valuation.equityCents
            initialEquity = state.initialEquityByAccount[agent.agentId]
            realized = valuation.realizedPnlCents
            unrealized = valuation.unrealizedPnlCents
        pnl = equity - initialEquity
        flow = state.agentFlows[agent.agentType.value]
        flow["realizedPnlCents"] += realized
        flow["unrealizedPnlCents"] += unrealized
        flow["endingEquityCents"] += equity
        rows.append(
            {
                "agentId": agent.agentId,
                "agentType": agent.agentType.value,
                "institutional": agent.institutional,
                "endingPosition": agent.position,
                "realizedPnlCents": realized,
                "unrealizedPnlCents": unrealized,
                "endingEquityCents": equity,
                "equityChangeCents": pnl,
            }
        )
    return rows


def _calculateMetrics(
    state: SimulationState,
    shockStep: int,
    agentPnl: list[dict[str, Any]],
) -> dict[str, float | int | None]:
    prices = state.prices or [float(state.runtime.initialPriceTicks)]
    returns = [
        math.log(prices[index] / prices[index - 1])
        for index in range(1, len(prices))
        if prices[index] > 0 and prices[index - 1] > 0
    ]
    runningPeak = prices[0]
    maxDrawdown = 0.0
    for price in prices:
        runningPeak = max(runningPeak, price)
        maxDrawdown = max(maxDrawdown, (runningPeak - price) / runningPeak)
    realizedVolatility = (
        statistics.pstdev(returns) * math.sqrt(max(len(returns), 1)) * 100 if returns else 0.0
    )
    totalVolume = state.totalBuyVolume + state.totalSellVolume
    orderImbalance = (
        (state.totalBuyVolume - state.totalSellVolume) / totalVolume if totalVolume else 0.0
    )
    directionConcentration = abs(orderImbalance)
    stopLossShare = state.stopLossVolume / max(totalVolume, 1)
    forcedShare = state.forcedLiquidationVolume / max(totalVolume, 1)
    cascadeScore = min(
        100.0,
        (
            directionConcentration * 45
            + stopLossShare * 65
            + forcedShare * 75
            + max(0, -min(state.sentiments, default=0)) * 35
        ),
    )
    recoverySteps = _recoverySteps(state, shockStep)
    tailThreshold = -0.003
    tailLossProbability = (
        sum(pathReturn <= tailThreshold for pathReturn in returns) / len(returns)
        if returns
        else 0.0
    )
    pnlChanges = [float(row["equityChangeCents"]) for row in agentPnl]
    averageInformationDelay = (
        statistics.fmean(max(0, step - shockStep) for step in state.networkDeliverySteps)
        if state.networkDeliverySteps
        else 0.0
    )
    initialSystemEquity = sum(state.initialEquityByAccount.values())
    endingSystemEquity = (
        state.systemEquityPath[-1] if state.systemEquityPath else initialSystemEquity
    )
    benchmarkReturnPct = (
        (state.benchmarkLevels[-1] / state.benchmarkLevels[0] - 1) * 100
        if len(state.benchmarkLevels) >= 2
        else 0.0
    )
    assetReturnPct = (prices[-1] / prices[0] - 1) * 100 if len(prices) >= 2 else 0.0
    return {
        "maxDrawdownPct": round(maxDrawdown * 100, 6),
        "realizedVolatilityPct": round(realizedVolatility, 6),
        "maxSpreadBps": round(max(state.spreadBps, default=0.0), 6),
        "minDepth": min(state.depths, default=0),
        "recoverySteps": recoverySteps,
        "totalVolume": totalVolume,
        "orderImbalance": round(orderImbalance, 6),
        "cascadeScore": round(cascadeScore, 6),
        "networkReachRate": round(
            len(state.networkDeliveredNodes) / max(len(state.population), 1),
            6,
        ),
        "informationDelaySteps": round(averageInformationDelay, 6),
        "liquidityStressIndex": round(max(state.liquidityStressPath, default=0.0), 6),
        "tailLossProbability": round(tailLossProbability, 6),
        "agentPnlDispersionCents": round(
            statistics.pstdev(pnlChanges) if len(pnlChanges) > 1 else 0.0,
            6,
        ),
        "systemEquityChangeCents": endingSystemEquity - initialSystemEquity,
        "forcedLiquidationVolume": state.forcedLiquidationVolume,
        "ledgerRejectedOrders": state.ledgerRejectedOrders,
        "cognitiveOrderCount": state.cognitiveOrderCount,
        "benchmarkReturnPct": round(benchmarkReturnPct, 6),
        "abnormalReturnPct": round(
            assetReturnPct - state.runtime.benchmarkBeta * benchmarkReturnPct,
            6,
        ),
        "haltCount": state.haltCount,
        "haltedSteps": state.haltedSteps,
        "totalFeesPaidCents": state.ledger.feeCollectorCashCents if state.ledger else 0,
    }


def _recoverySteps(state: SimulationState, shockStep: int) -> int | None:
    if len(state.prices) <= shockStep + 2:
        return None
    preShockPrice = statistics.median(state.prices[max(0, shockStep - 4) : shockStep])
    preShockSpread = statistics.median(state.spreadBps[max(0, shockStep - 4) : shockStep])
    postShockPrices = state.prices[shockStep:]
    troughOffset = min(range(len(postShockPrices)), key=postShockPrices.__getitem__)
    troughStep = shockStep + troughOffset
    for step in range(troughStep + 1, len(state.prices)):
        priceRecovered = state.prices[step] >= preShockPrice * 0.995
        spreadRecovered = state.spreadBps[step] <= max(
            preShockSpread * 1.35,
            preShockSpread + 1,
        )
        if priceRecovered and spreadRecovered:
            return step - troughStep
    return None


def _systemMetrics(
    state: SimulationState,
    agentPnl: list[dict[str, Any]],
) -> dict[str, Any]:
    initialEquity = sum(state.initialEquityByAccount.values())
    endingEquity = state.systemEquityPath[-1] if state.systemEquityPath else initialEquity
    profitableAgents = sum(row["equityChangeCents"] > 0 for row in agentPnl)
    return {
        "initialEquityCents": initialEquity,
        "endingEquityCents": endingEquity,
        "equityChangeCents": endingEquity - initialEquity,
        "profitableAgentShare": round(profitableAgents / max(len(agentPnl), 1), 6),
        "ledgerRejectedOrders": state.ledgerRejectedOrders,
        "ledgerModifiedOrders": state.ledgerModifiedOrders,
        "outstandingReservations": len(state.ledger.reservations) if state.ledger else 0,
        "recordedTradeCount": state.recordedTradeCount,
        "cognitiveOrders": state.cognitiveOrderCount,
        "cognitiveSignalsConsumed": sum(state.cognitiveUseCount.values()),
        "cognitiveAgentsUsed": len(state.cognitiveUseCount),
        "feeBps": state.runtime.tradeFeeBps,
        "feeCollectorCashCents": state.ledger.feeCollectorCashCents if state.ledger else 0,
        "volatilityHaltCount": state.haltCount,
        "haltedSteps": state.haltedSteps,
        "latencyScheduledOrders": state.latencyScheduledOrders,
        "latencyExpiredOrders": state.latencyExpiredOrders,
    }


def _eventQueueAudit(state: SimulationState) -> dict[str, Any]:
    serialized = [
        {
            "timestamp": timestamp,
            "priority": priority,
            "sequence": sequence,
            "eventType": eventType,
        }
        for timestamp, priority, sequence, eventType in state.processedEvents
    ]
    sequenceHash = hashlib.sha256(
        json.dumps(serialized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    monotonic = all(
        left[:3] <= right[:3]
        for left, right in zip(state.processedEvents, state.processedEvents[1:], strict=False)
    )
    return {
        "processedEventCount": len(serialized),
        "sequenceHash": sequenceHash,
        "monotonicTimestampPrioritySequence": monotonic,
        "firstEvents": serialized[:24],
    }


def _validateLedgerInvariants(state: SimulationState) -> dict[str, int | bool]:
    netPosition = sum(state.ledgerPositions.values())
    netCashChangeCents = sum(state.ledgerCashChangeCents.values())
    unrecordedTradeCount = state.orderBook.tradeCounter - state.recordedTradeCount
    if netPosition != 0 or netCashChangeCents != 0 or unrecordedTradeCount != 0:
        raise RuntimeError("simulation ledger invariant failed")
    scientificLedgerValid = True
    cashConserved = True
    positionsConserved = True
    reservationsValid = True
    borrowInventoryValid = True
    if state.ledger is not None:
        report = state.ledger.checkInvariants()
        scientificLedgerValid = report.isValid
        cashConserved = report.cashConserved
        positionsConserved = report.positionsConserved
        reservationsValid = report.reservationsValid
        borrowInventoryValid = report.borrowInventoryValid
        if not scientificLedgerValid:
            raise RuntimeError(f"portfolio ledger invariant failed: {report.violations}")
    return {
        "positionConserved": positionsConserved,
        "cashConserved": cashConserved,
        "allTradesRecorded": True,
        "selfTradePrevented": True,
        "scientificLedgerValid": scientificLedgerValid,
        "reservationsValid": reservationsValid,
        "borrowInventoryValid": borrowInventoryValid,
        "recordedTradeCount": state.recordedTradeCount,
        "netPosition": netPosition,
        "netCashChangeCents": netCashChangeCents,
        "unrecordedTradeCount": unrecordedTradeCount,
    }


def _recordTrace(
    state: SimulationState,
    *,
    step: int,
    eventType: str,
    agentId: str | None,
    parentTraceId: str | None,
    summary: str,
    summaryZh: str,
    payload: dict[str, Any],
) -> str:
    state.traceCounter += 1
    traceDigest = hashlib.blake2s(
        f"{state.seed}:{step}:{state.traceCounter}:{eventType}".encode(),
        digest_size=8,
    ).hexdigest()
    traceId = f"trace-{traceDigest}"
    importantEventTypes = {
        "FACT_ARRIVED",
        "CLARIFICATION_ARRIVED",
        "SYSTEM_ORDER_SUBMITTED",
        "VOLATILITY_HALT_TRIGGERED",
        "VOLATILITY_HALT_ENDED",
        "REOPEN_AUCTION_CLEARED",
    }
    isImportant = eventType in importantEventTypes or parentTraceId in state.importantTraceIds
    if isImportant:
        state.importantTraceIds.add(traceId)
    shouldRetain = (
        isImportant
        or len(state.traces) < 160
        or (len(state.traces) < 240 and state.traceCounter % 40 == 0)
    )
    if shouldRetain:
        state.traces.append(
            {
                "traceId": traceId,
                "parentTraceId": parentTraceId,
                "step": step,
                "eventType": eventType,
                "agentId": agentId,
                "summary": summary,
                "summaryZh": summaryZh,
                "important": isImportant,
                "payload": payload,
            }
        )
    return traceId
