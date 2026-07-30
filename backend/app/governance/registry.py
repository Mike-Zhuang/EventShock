"""严格类型、可哈希的模型与关键组件清单。"""

# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.cognition.catalog import (
    ModelDescriptor,
    ProviderId,
    getProvider,
    listModels,
)
from backend.app.cognition.prompts import PROMPT_REGISTRY, PromptSpec
from backend.app.simulation.analytics import METRIC_KEYS


class GovernanceModel(BaseModel):
    """治理对象拒绝未知字段并在验证后不可变。"""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        populate_by_name=True,
    )


class ComponentKind(StrEnum):
    RULE_AGENT = "RULE_AGENT"
    ORDER_POLICY = "ORDER_POLICY"
    MATCHING_ENGINE = "MATCHING_ENGINE"
    LEDGER = "LEDGER"
    EVENT_QUEUE = "EVENT_QUEUE"
    INFORMATION_NETWORK = "INFORMATION_NETWORK"
    POINT_IN_TIME_STORE = "POINT_IN_TIME_STORE"
    MODEL_GATEWAY = "MODEL_GATEWAY"
    PROVIDER_MODEL = "PROVIDER_MODEL"
    PROMPT = "PROMPT"
    METRIC_COMPONENT = "METRIC_COMPONENT"
    VALIDATION_COMPONENT = "VALIDATION_COMPONENT"
    SECRET_CONTROL = "SECRET_CONTROL"


class Materiality(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ApprovalStatus(StrEnum):
    APPROVED_FOR_DEMO = "APPROVED_FOR_DEMO"
    APPROVED_WITH_LIMITATIONS = "APPROVED_WITH_LIMITATIONS"
    PENDING_HUMAN_EVIDENCE = "PENDING_HUMAN_EVIDENCE"
    NOT_APPROVED = "NOT_APPROVED"


class ValidationStatus(StrEnum):
    CODE_VERIFIED = "CODE_VERIFIED"
    TEST_VERIFIED = "TEST_VERIFIED"
    DOCUMENTED_ONLY = "DOCUMENTED_ONLY"
    PENDING_HUMAN_EVIDENCE = "PENDING_HUMAN_EVIDENCE"


class TrustBoundary(StrEnum):
    TRUSTED_INTERNAL = "TRUSTED_INTERNAL"
    VALIDATED_EXTERNAL = "VALIDATED_EXTERNAL"
    UNTRUSTED_EXTERNAL = "UNTRUSTED_EXTERNAL"
    SECRET = "SECRET"


class InterfaceContract(GovernanceModel):
    name: str = Field(min_length=2, max_length=100)
    schemaRef: str = Field(alias="schema", min_length=2, max_length=200)
    trustBoundary: TrustBoundary
    containsSecrets: bool = False
    description: str = Field(min_length=8, max_length=500)


class ValidationControl(GovernanceModel):
    controlId: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9-]+$")
    method: str = Field(min_length=8, max_length=500)
    status: ValidationStatus
    automated: bool
    evidenceRefs: tuple[str, ...] = Field(min_length=1, max_length=20)


class FallbackDefinition(GovernanceModel):
    triggers: tuple[str, ...] = Field(min_length=1, max_length=20)
    behavior: str = Field(min_length=8, max_length=500)
    safetyEffect: str = Field(min_length=8, max_length=500)
    deterministic: bool


class ModelDetails(GovernanceModel):
    provider: ProviderId
    modelId: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
    contextTokens: int = Field(ge=16_000)
    maxOutputTokens: int | None = Field(default=None, ge=1_024)
    supportsJsonObject: bool
    supportsJsonSchema: bool
    supportsFunctionCalling: bool
    supportsThinking: bool
    recommended: bool
    legacy: bool
    metadataReviewedDate: Literal["2026-07-20"] = "2026-07-20"


class PromptDetails(GovernanceModel):
    promptName: str = Field(min_length=3, max_length=80)
    promptHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    schemaVersion: str = Field(min_length=3, max_length=100)


class MetricDetails(GovernanceModel):
    metricNames: tuple[str, ...] = Field(min_length=1, max_length=100)
    comparisonDesign: str = Field(min_length=8, max_length=300)


class ComponentRecord(GovernanceModel):
    componentId: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9._-]+$")
    name: str = Field(min_length=3, max_length=160)
    kind: ComponentKind
    owner: str = Field(min_length=3, max_length=120)
    purpose: str = Field(min_length=12, max_length=600)
    materiality: Materiality
    version: str = Field(min_length=1, max_length=120)
    schemaRef: str = Field(alias="schema", min_length=2, max_length=300)
    inputs: tuple[InterfaceContract, ...] = Field(min_length=1, max_length=20)
    outputs: tuple[InterfaceContract, ...] = Field(min_length=1, max_length=20)
    validation: tuple[ValidationControl, ...] = Field(min_length=1, max_length=20)
    limitations: tuple[str, ...] = Field(min_length=1, max_length=30)
    fallback: FallbackDefinition
    approvalStatus: ApprovalStatus
    sourceFiles: tuple[str, ...] = Field(min_length=1, max_length=20)
    external: bool = False
    modelDetails: ModelDetails | None = None
    promptDetails: PromptDetails | None = None
    metricDetails: MetricDetails | None = None

    @model_validator(mode="after")
    def validateKindDetails(self) -> ComponentRecord:
        if self.kind is ComponentKind.PROVIDER_MODEL and self.modelDetails is None:
            raise ValueError("provider models require modelDetails")
        if self.kind is not ComponentKind.PROVIDER_MODEL and self.modelDetails is not None:
            raise ValueError("only provider models may set modelDetails")
        if self.kind is ComponentKind.PROMPT and self.promptDetails is None:
            raise ValueError("prompt components require promptDetails")
        if self.kind is not ComponentKind.PROMPT and self.promptDetails is not None:
            raise ValueError("only prompt components may set promptDetails")
        if self.kind is ComponentKind.METRIC_COMPONENT and self.metricDetails is None:
            raise ValueError("metric components require metricDetails")
        if self.kind is not ComponentKind.METRIC_COMPONENT and self.metricDetails is not None:
            raise ValueError("only metric components may set metricDetails")
        return self


def _input(
    name: str,
    schemaRef: str,
    description: str,
    *,
    trustBoundary: TrustBoundary = TrustBoundary.TRUSTED_INTERNAL,
    containsSecrets: bool = False,
) -> InterfaceContract:
    return InterfaceContract(
        name=name,
        schemaRef=schemaRef,
        trustBoundary=trustBoundary,
        containsSecrets=containsSecrets,
        description=description,
    )


def _control(
    controlId: str,
    method: str,
    status: ValidationStatus,
    automated: bool,
    *evidenceRefs: str,
) -> ValidationControl:
    return ValidationControl(
        controlId=controlId,
        method=method,
        status=status,
        automated=automated,
        evidenceRefs=tuple(evidenceRefs),
    )


def _fallback(
    triggers: tuple[str, ...],
    behavior: str,
    safetyEffect: str,
    *,
    deterministic: bool = True,
) -> FallbackDefinition:
    return FallbackDefinition(
        triggers=triggers,
        behavior=behavior,
        safetyEffect=safetyEffect,
        deterministic=deterministic,
    )


def _modelComponent(model: ModelDescriptor) -> ComponentRecord:
    provider = getProvider(model.provider)
    limitations = [
        "Provider behavior may change under a stable model identifier.",
        "No completed live-provider quality, latency, multilingual, or cost study is stored in this repository.",
        "Structured JSON support reduces but does not eliminate invalid or unsafe output.",
    ]
    if model.legacy:
        limitations.append("The catalog marks this model as legacy or approaching retirement.")
    return ComponentRecord(
        componentId=f"{model.provider}.{model.model_id}",
        name=f"{provider.display_name} {model.display_name}",
        kind=ComponentKind.PROVIDER_MODEL,
        owner="LLM & Evaluation Lead",
        purpose="Produce schema-constrained extraction or simulated belief outputs through the provider-neutral model gateway.",
        materiality=Materiality.HIGH,
        version=model.model_id,
        schemaRef="event_extraction_v1.0.0 | belief_decision_v1.0.0",
        inputs=(
            _input(
                "messages",
                f"{provider.api_style} request",
                "Versioned system prompt plus delimited untrusted user evidence.",
                trustBoundary=TrustBoundary.VALIDATED_EXTERNAL,
            ),
        ),
        outputs=(
            _input(
                "structuredResponse",
                "EventExtractionResult | BeliefDecision",
                "Provider JSON that must pass strict local schema, evidence, and action validation.",
                trustBoundary=TrustBoundary.UNTRUSTED_EXTERNAL,
            ),
        ),
        validation=(
            _control(
                "provider-response-schema",
                "Strict Pydantic parsing rejects unknown keys, wrong versions, and invalid ranges.",
                ValidationStatus.TEST_VERIFIED,
                True,
                "tests/backend/test_cognition.py",
            ),
            _control(
                "provider-live-evaluation",
                "Live provider quality, latency, cost, and language behavior require recorded evaluation evidence.",
                ValidationStatus.PENDING_HUMAN_EVIDENCE,
                False,
                "docs/governance/validation-report.md",
            ),
        ),
        limitations=tuple(limitations),
        fallback=_fallback(
            ("timeout", "rate limit", "provider error", "invalid response", "unknown evidence"),
            "Return a deterministic ABSTAIN or empty-extraction rule fallback after bounded retry and one repair attempt.",
            "Prevents an unvalidated provider response from becoming a belief or candidate fact.",
        ),
        approvalStatus=ApprovalStatus.PENDING_HUMAN_EVIDENCE,
        sourceFiles=(
            "backend/app/cognition/catalog.py",
            (
                "backend/app/cognition/zhipu.py"
                if model.provider == "zhipu"
                else "backend/app/cognition/provider_gateways.py"
            ),
        ),
        external=True,
        modelDetails=ModelDetails(
            provider=model.provider,
            modelId=model.model_id,
            contextTokens=model.context_tokens,
            maxOutputTokens=model.max_output_tokens,
            supportsJsonObject=model.supports_json_object,
            supportsJsonSchema=model.supports_json_schema,
            supportsFunctionCalling=model.supports_function_calling,
            supportsThinking=model.supports_thinking,
            recommended=model.recommended,
            legacy=model.legacy,
        ),
    )


def _promptComponent(prompt: PromptSpec) -> ComponentRecord:
    return ComponentRecord(
        componentId=f"prompt.{prompt.name}",
        name=f"Prompt: {prompt.name}",
        kind=ComponentKind.PROMPT,
        owner="LLM & Evaluation Lead",
        purpose="Constrain untrusted evidence processing to a versioned JSON schema and a bounded authority model.",
        materiality=Materiality.CRITICAL,
        version=prompt.version,
        schemaRef=prompt.schemaVersion,
        inputs=(
            _input(
                "untrustedEvidence",
                "Delimited canonical JSON",
                "Uploaded text or observation data enclosed in explicit untrusted-data markers.",
                trustBoundary=TrustBoundary.UNTRUSTED_EXTERNAL,
            ),
        ),
        outputs=(
            _input(
                "modelJson",
                prompt.schemaVersion,
                "Exactly one JSON object that still requires deterministic validation.",
                trustBoundary=TrustBoundary.UNTRUSTED_EXTERNAL,
            ),
        ),
        validation=(
            _control(
                "prompt-hash",
                "SHA-256 binds each request and cache key to the exact system prompt text.",
                ValidationStatus.TEST_VERIFIED,
                True,
                "backend/app/cognition/prompts.py",
                "tests/backend/test_cognition.py",
            ),
            _control(
                "prompt-human-outcome-review",
                "Representative users and a domain reviewer must assess misleading or overconfident outputs.",
                ValidationStatus.PENDING_HUMAN_EVIDENCE,
                False,
                "docs/governance/responsible-ai-check.md",
            ),
        ),
        limitations=(
            "Prompt text cannot guarantee resistance to every direct or indirect injection.",
            "Prompt changes alter behavior and require a version bump and renewed evaluation.",
            "No human multilingual outcome review is recorded yet.",
        ),
        fallback=_fallback(
            ("schema failure", "injection signal", "unknown evidence", "provider refusal"),
            "Reject the output and use a deterministic non-action fallback.",
            "Keeps unvalidated text outside the order and Event Pack state transitions.",
        ),
        approvalStatus=ApprovalStatus.PENDING_HUMAN_EVIDENCE,
        sourceFiles=("backend/app/cognition/prompts.py",),
        promptDetails=PromptDetails(
            promptName=prompt.name,
            promptHash=prompt.promptHash,
            schemaVersion=prompt.schemaVersion,
        ),
    )


def _coreComponents() -> tuple[ComponentRecord, ...]:
    return (
        ComponentRecord(
            componentId="simulation.rule-agent-archetypes",
            name="Rule-based market-agent archetypes",
            kind=ComponentKind.RULE_AGENT,
            owner="Market Microstructure Lead",
            purpose="Generate deterministic strategy scores and bounded order intents for synthetic market participants.",
            materiality=Materiality.HIGH,
            version="eventshock-simulation-mvp-0.1.0",
            schemaRef="AgentState + MarketContext -> OrderIntent",
            inputs=(
                _input(
                    "marketContext",
                    "backend.app.simulation.agents.MarketContext",
                    "Synthetic market state, sentiment, price, and step information.",
                ),
            ),
            outputs=(
                _input(
                    "orderIntent",
                    "backend.app.simulation.agents.OrderIntent",
                    "A bounded synthetic intent that is submitted through deterministic market rules.",
                ),
            ),
            validation=(
                _control(
                    "rule-agent-replay",
                    "Identical seed and configuration must produce byte-stable event-log output.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_simulation.py",
                ),
            ),
            limitations=(
                "Archetypes are synthetic and do not represent identified investors or portfolios.",
                "Behavior parameters are not validated estimates of real SPCX holder behavior.",
            ),
            fallback=_fallback(
                ("score below activation threshold", "invalid market context"),
                "Emit no order intent or stop the invalid run.",
                "Avoids inventing an action when the deterministic strategy cannot justify one.",
            ),
            approvalStatus=ApprovalStatus.APPROVED_WITH_LIMITATIONS,
            sourceFiles=("backend/app/simulation/agents.py",),
        ),
        ComponentRecord(
            componentId="cognition.deterministic-order-policy",
            name="Belief-to-order deterministic policy",
            kind=ComponentKind.ORDER_POLICY,
            owner="LLM & Evaluation Lead",
            purpose="Translate a validated belief preference into a bounded synthetic order intent without allowing the LLM to set executable order fields directly.",
            materiality=Materiality.CRITICAL,
            version="belief_order_policy_v1.0.0",
            schemaRef="BeliefDecision + Observation -> CognitiveOrderIntent",
            inputs=(
                _input(
                    "beliefDecision",
                    "belief_decision_v1.0.0",
                    "A locally validated model or rule-fallback belief decision.",
                    trustBoundary=TrustBoundary.VALIDATED_EXTERNAL,
                ),
                _input(
                    "observation",
                    "observation_v1.0.0",
                    "Portfolio, market, allowed-action, and evidence constraints.",
                ),
            ),
            outputs=(
                _input(
                    "orderIntent",
                    "CognitiveOrderIntent",
                    "A capped deterministic intent; ABSTAIN, HOLD, and POST_ONLY produce no order.",
                ),
            ),
            validation=(
                _control(
                    "order-policy-bounds",
                    "Quantity, participation, short-sale, confidence, and slippage constraints are schema and code checked.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_cognition.py",
                ),
            ),
            limitations=(
                "The policy is a simulation rule and is not suitable for real trading.",
                "Policy parameters are not calibrated to a broker, exchange, or investor mandate.",
            ),
            fallback=_fallback(
                ("ABSTAIN", "HOLD", "low confidence", "zero delta", "disallowed short"),
                "Return a NO_ACTION or BLOCKED intent with zero approved quantity.",
                "Ensures a model failure or weak belief cannot create an order.",
            ),
            approvalStatus=ApprovalStatus.APPROVED_WITH_LIMITATIONS,
            sourceFiles=("backend/app/cognition/policy.py",),
        ),
        ComponentRecord(
            componentId="simulation.limit-order-book",
            name="Price-time-priority limit order book",
            kind=ComponentKind.MATCHING_ENGINE,
            owner="Market Microstructure Lead",
            purpose="Match synthetic limit and protected market orders with deterministic price-time priority and integer price ticks.",
            materiality=Materiality.CRITICAL,
            version="eventshock-simulation-mvp-0.1.0",
            schemaRef="Order -> ExecutionReport + Trade",
            inputs=(
                _input("order", "LimitOrderBook.submitLimit", "Validated synthetic order fields."),
            ),
            outputs=(
                _input(
                    "executionReport",
                    "ExecutionReport",
                    "Trades, remaining quantity, status, and protected unfilled quantity.",
                ),
            ),
            validation=(
                _control(
                    "matching-properties",
                    "Tests cover resting-order price, FIFO, self-trade prevention, IOC handling, and conservation.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_order_book.py",
                    "tests/backend/test_ledger.py",
                ),
            ),
            limitations=(
                "The book is a single-process educational simulator, not an exchange emulator.",
                "It omits hidden liquidity, auctions, venue fragmentation, and many order types.",
            ),
            fallback=_fallback(
                ("invalid order", "invariant failure", "price collar breach"),
                "Reject the order or fail the run; protected unfilled quantity remains explicit.",
                "Prevents silent quantity loss and invalid trades from entering results.",
            ),
            approvalStatus=ApprovalStatus.APPROVED_FOR_DEMO,
            sourceFiles=("backend/app/simulation/order_book.py",),
        ),
        ComponentRecord(
            componentId="simulation.portfolio-ledger",
            name="Synthetic portfolio ledger and risk controls",
            kind=ComponentKind.LEDGER,
            owner="Market Microstructure Lead",
            purpose="Track synthetic cash, positions, reservations, borrow capacity, and accounting invariants for simulated accounts.",
            materiality=Materiality.CRITICAL,
            version="ledger-v1.0.0",
            schemaRef="AccountState + Trade -> LedgerInvariantReport",
            inputs=(_input("trade", "Trade", "A match produced by the deterministic order book."),),
            outputs=(
                _input(
                    "ledgerState",
                    "AccountState + LedgerInvariantReport",
                    "Updated synthetic accounts and conservation checks.",
                ),
            ),
            validation=(
                _control(
                    "ledger-conservation",
                    "Property and unit tests verify cash, position, reservation, and borrow invariants.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_ledger.py",
                    "tests/backend/test_simulation.py",
                ),
            ),
            limitations=(
                "No real account, custody, margin agreement, settlement system, or money movement exists.",
                "The educational ledger does not model every fee, tax, corporate action, or settlement failure.",
            ),
            fallback=_fallback(
                ("risk check failure", "conservation failure", "invalid reservation"),
                "Block the order or abort and invalidate the run.",
                "Never repairs accounting inconsistencies by inventing cash or positions.",
            ),
            approvalStatus=ApprovalStatus.APPROVED_FOR_DEMO,
            sourceFiles=("backend/app/simulation/ledger.py",),
        ),
        ComponentRecord(
            componentId="simulation.deterministic-event-queue",
            name="Deterministic simulation event queue",
            kind=ComponentKind.EVENT_QUEUE,
            owner="Market Microstructure Lead",
            purpose="Order simultaneous synthetic events by timestamp, priority, and insertion sequence while enforcing a monotonic clock.",
            materiality=Materiality.CRITICAL,
            version="event-queue-v1.0.0",
            schemaRef="ScheduledEvent",
            inputs=(
                _input(
                    "scheduledEvent", "ScheduledEvent", "Timestamped event payload and priority."
                ),
            ),
            outputs=(
                _input(
                    "orderedEvent", "ScheduledEvent", "Next immutable event in deterministic order."
                ),
            ),
            validation=(
                _control(
                    "event-ordering",
                    "Tests cover stable ordering, cancellation, duplicate IDs, snapshots, and monotonic time.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_event_queue.py",
                ),
            ),
            limitations=(
                "Simulation timestamps are integer logical times unless mapped by the scenario layer.",
                "The queue does not provide distributed exactly-once execution guarantees.",
            ),
            fallback=_fallback(
                ("past event", "duplicate event ID", "invalid priority"),
                "Reject scheduling and fail validation before execution.",
                "Prevents time reversal and ambiguous replay ordering.",
            ),
            approvalStatus=ApprovalStatus.APPROVED_FOR_DEMO,
            sourceFiles=("backend/app/simulation/event_queue.py",),
        ),
        ComponentRecord(
            componentId="information.social-network",
            name="Synthetic information-propagation network",
            kind=ComponentKind.INFORMATION_NETWORK,
            owner="Data & Quant Validation Lead",
            purpose="Build seeded social graphs and propagate typed information through a bounded synthetic network.",
            materiality=Materiality.HIGH,
            version="information-network-v1.0.0",
            schemaRef="GraphSpec + InformationItem -> PropagationResult",
            inputs=(
                _input("graphSpec", "GraphSpec", "Seeded topology and propagation parameters."),
                _input("information", "InformationItem", "Point-in-time typed evidence item."),
            ),
            outputs=(
                _input(
                    "propagationResult",
                    "PropagationResult",
                    "Receipts, visibility, and graph metrics for the synthetic network.",
                ),
            ),
            validation=(
                _control(
                    "network-replay",
                    "Graph and propagation tests require stable output under identical seed and configuration.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_information_network.py",
                ),
            ),
            limitations=(
                "Topology and node traits are synthetic and are not reconstructed from real social users.",
                "Network parameters have not received external empirical validation for the "
                "people or institutions represented by the selected Event Pack.",
            ),
            fallback=_fallback(
                ("invalid graph", "unknown node", "propagation limit"),
                "Reject the graph or stop propagation at the validated boundary.",
                "Avoids silently repairing topology or inventing recipients.",
            ),
            approvalStatus=ApprovalStatus.APPROVED_WITH_LIMITATIONS,
            sourceFiles=("backend/app/information/network.py",),
        ),
        ComponentRecord(
            componentId="information.point-in-time-store",
            name="Point-in-time information store",
            kind=ComponentKind.POINT_IN_TIME_STORE,
            owner="Data & Quant Validation Lead",
            purpose="Expose only evidence whose knownAt is visible at the requested simulation time and retain source-tier semantics.",
            materiality=Materiality.CRITICAL,
            version="point-in-time-information-v1.0.0",
            schemaRef="InformationItem + asOf -> visible InformationItem tuple",
            inputs=(
                _input(
                    "informationItems", "InformationItem", "Timezone-aware typed source records."
                ),
                _input("asOf", "timezone-aware datetime", "Simulation observation time."),
            ),
            outputs=(
                _input(
                    "visibleItems",
                    "tuple[InformationItem]",
                    "Stable sorted evidence that is visible at the requested point in time.",
                ),
            ),
            validation=(
                _control(
                    "future-leak-check",
                    "Schema validation and assertNoFutureLeak reject future or expired evidence.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_information_network.py",
                    "tests/backend/test_spacex_event_pack.py",
                ),
            ),
            limitations=(
                "Correctness depends on source timestamps and timezone normalization supplied by the Event Pack.",
                "A wrong knownAt in source data cannot be detected from content alone.",
            ),
            fallback=_fallback(
                ("future evidence", "naive datetime", "unknown information ID"),
                "Reject the observation or omit the non-visible evidence.",
                "Prevents future information from entering a simulated belief update.",
            ),
            approvalStatus=ApprovalStatus.APPROVED_FOR_DEMO,
            sourceFiles=("backend/app/information/models.py",),
        ),
        ComponentRecord(
            componentId="cognition.provider-rest-gateway",
            name="Allowlisted multi-provider structured-output REST gateway",
            kind=ComponentKind.MODEL_GATEWAY,
            owner="LLM & Evaluation Lead",
            purpose="Call fixed official provider endpoints with bounded retries, schema-constrained output, local validation, caching, and safe fallback.",
            materiality=Materiality.CRITICAL,
            version="provider-rest-gateway-v2.0.0",
            schemaRef="ModelRequest -> ModelResult[BaseModel]",
            inputs=(
                _input(
                    "modelRequest",
                    "ModelRequest",
                    "Versioned prompt, evidence IDs, allowed actions, sampling bounds, and session BYOK credential.",
                    trustBoundary=TrustBoundary.VALIDATED_EXTERNAL,
                    containsSecrets=True,
                ),
            ),
            outputs=(
                _input(
                    "modelResult",
                    "ModelResult[EventExtractionResult | BeliefDecision]",
                    "Validated structured data with hashes, usage, latency, retry, cache, and fallback metadata.",
                    trustBoundary=TrustBoundary.VALIDATED_EXTERNAL,
                ),
            ),
            validation=(
                _control(
                    "gateway-mock-contract",
                    "Mock-transport tests cover authentication errors, malformed JSON, repair, retry, evidence validation, and rule fallback.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_cognition.py",
                ),
                _control(
                    "gateway-live-provider",
                    "No repository artifact currently proves live-provider behavior, cost, retention, or availability.",
                    ValidationStatus.PENDING_HUMAN_EVIDENCE,
                    False,
                    "docs/governance/validation-report.md",
                ),
            ),
            limitations=(
                "Live provider evaluation and operational budget evidence are not complete.",
                "A provider may change behavior or retire a model identifier.",
                "The gateway is for simulated cognition and extraction, not real trading or autonomous tools.",
            ),
            fallback=_fallback(
                (
                    "timeout",
                    "transport error",
                    "rate limit",
                    "quota",
                    "invalid JSON",
                    "invalid evidence",
                ),
                "Use bounded retry, one schema repair, immutable cache when available, then deterministic rule fallback.",
                "Prevents provider failure from bypassing local authority, evidence, or schema controls.",
            ),
            approvalStatus=ApprovalStatus.PENDING_HUMAN_EVIDENCE,
            sourceFiles=(
                "backend/app/cognition/gateway.py",
                "backend/app/cognition/provider_gateways.py",
                "backend/app/cognition/zhipu.py",
            ),
            external=True,
        ),
        ComponentRecord(
            componentId="cognition.session-byok-store",
            name="In-memory session-scoped BYOK store",
            kind=ComponentKind.SECRET_CONTROL,
            owner="Full-stack / Platform & Design Lead",
            purpose="Hold user-provided provider credentials in process memory with expiry and return only a masked configuration view.",
            materiality=Materiality.CRITICAL,
            version="session-config-store-v1.0.0",
            schemaRef="sessionId + apiKey -> RuntimeProviderConfig | masked view",
            inputs=(
                _input(
                    "apiKey",
                    "opaque provider credential",
                    "User-provided model-provider API key scoped to one application session.",
                    trustBoundary=TrustBoundary.SECRET,
                    containsSecrets=True,
                ),
            ),
            outputs=(
                _input(
                    "configView",
                    "SessionProviderConfigView",
                    "Provider, model, expiry, and final-four-character credential hint only.",
                ),
            ),
            validation=(
                _control(
                    "byok-session-isolation",
                    "Tests cover session scoping, expiry, clearing, masking, and secret-free representation.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_cognition.py",
                ),
                _control(
                    "byok-production-security-review",
                    "A human security review of logs, crash dumps, TLS termination, memory exposure, and host access is not complete.",
                    ValidationStatus.PENDING_HUMAN_EVIDENCE,
                    False,
                    "docs/governance/security.md",
                ),
            ),
            limitations=(
                "Process memory is not a hardware-backed secret vault.",
                "A process restart clears credentials and interrupts live-model use.",
                "Production host, proxy, logging, and memory-access controls need human security review.",
            ),
            fallback=_fallback(
                ("missing key", "expired key", "cleared session", "provider disabled"),
                "Disable live provider calls and use cached or rule-only cognition paths.",
                "No credential is persisted to SQLite, logs, exports, or the repository.",
            ),
            approvalStatus=ApprovalStatus.PENDING_HUMAN_EVIDENCE,
            sourceFiles=("backend/app/cognition/config_store.py",),
        ),
        ComponentRecord(
            componentId="analytics.matched-seed-metrics",
            name="Matched-seed metric aggregation",
            kind=ComponentKind.METRIC_COMPONENT,
            owner="Data & Quant Validation Lead",
            purpose="Compare baseline and single-intervention runs under identical seeds and report distributions, empirical intervals, paths, flows, and representative traces.",
            materiality=Materiality.CRITICAL,
            version="matched-seed-analytics-v1.0.0",
            schemaRef="paired run artifacts -> metric summaries",
            inputs=(
                _input(
                    "pairedRuns",
                    "list[runScenario result]",
                    "Equal-length baseline and intervention results with identical seed ordering.",
                ),
            ),
            outputs=(
                _input(
                    "aggregate",
                    "pairedRuns + metricSummaries + medianPaths + traces",
                    "Empirical paired differences and visible sample sizes.",
                ),
            ),
            validation=(
                _control(
                    "matched-seed-integrity",
                    "Aggregation rejects empty, unequal, or seed-mismatched input and is tested against zero-difference controls.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_simulation.py",
                ),
            ),
            limitations=(
                "The interval is an empirical finite-seed interval, not a guaranteed population confidence interval.",
                "Ten default seeds are suitable for a demo but can yield unstable tails.",
                "Representative traces are explanatory examples and do not replace the full distribution.",
            ),
            fallback=_fallback(
                ("seed mismatch", "empty runs", "missing metric"),
                "Reject aggregation or preserve a null metric rather than imputing a result.",
                "Prevents unmatched or fabricated values from appearing as paired effects.",
            ),
            approvalStatus=ApprovalStatus.APPROVED_WITH_LIMITATIONS,
            sourceFiles=("backend/app/simulation/analytics.py",),
            metricDetails=MetricDetails(
                metricNames=tuple(METRIC_KEYS),
                comparisonDesign="Baseline and intervention use identical seed values; delta equals intervention minus baseline.",
            ),
        ),
        ComponentRecord(
            componentId="validation.cognition-code-grader",
            name="Provider-neutral cognition code grader",
            kind=ComponentKind.VALIDATION_COMPONENT,
            owner="LLM & Evaluation Lead",
            purpose="Score schema validity, evidence grounding, time integrity, action bounds, prompt-injection phrases, and action-target consistency without another model.",
            materiality=Materiality.HIGH,
            version="cognition-code-grader-v1.0.0",
            schemaRef="CognitionEvalCase + raw decision -> CodeGradeResult",
            inputs=(
                _input(
                    "evalSample",
                    "EvalSample",
                    "A versioned observation, expected constraints, and raw decision.",
                ),
            ),
            outputs=(
                _input(
                    "grade",
                    "CodeGradeResult",
                    "Per-check pass values, aggregate score, and parsed decision when valid.",
                ),
            ),
            validation=(
                _control(
                    "grader-unit-tests",
                    "Tests exercise valid decisions, unknown evidence, injection phrases, schema rejection, and unsafe action selection.",
                    ValidationStatus.TEST_VERIFIED,
                    True,
                    "tests/backend/test_cognition.py",
                ),
                _control(
                    "grader-human-correlation",
                    "Agreement with domain-expert and user judgments has not been measured.",
                    ValidationStatus.PENDING_HUMAN_EVIDENCE,
                    False,
                    "docs/governance/validation-report.md",
                ),
            ),
            limitations=(
                "Code graders detect declared properties but cannot judge all semantic truth or harmful framing.",
                "No measured inter-rater agreement or expert benchmark is available.",
            ),
            fallback=_fallback(
                ("invalid schema", "grader exception", "missing expected constraint"),
                "Return a failed grade and exclude the sample from approved model evidence.",
                "Validation failure cannot be converted into a passing evaluation result.",
            ),
            approvalStatus=ApprovalStatus.PENDING_HUMAN_EVIDENCE,
            sourceFiles=("backend/app/cognition/evaluation.py",),
        ),
    )


def _buildInventory() -> tuple[ComponentRecord, ...]:
    records = (
        *_coreComponents(),
        *(_promptComponent(prompt) for prompt in PROMPT_REGISTRY),
        *(_modelComponent(model) for model in listModels()),
    )
    ordered = tuple(sorted(records, key=lambda record: record.componentId))
    errors = validateInventory(ordered)
    if errors:
        raise RuntimeError(f"invalid component inventory: {'; '.join(errors)}")
    return ordered


def validateInventory(records: tuple[ComponentRecord, ...] | None = None) -> tuple[str, ...]:
    resolved = records if records is not None else COMPONENT_INVENTORY
    errors: list[str] = []
    componentIds = [record.componentId for record in resolved]
    duplicateIds = sorted(
        componentId for componentId in set(componentIds) if componentIds.count(componentId) > 1
    )
    if duplicateIds:
        errors.append(f"duplicate component IDs: {', '.join(duplicateIds)}")
    if not any(record.kind is ComponentKind.MATCHING_ENGINE for record in resolved):
        errors.append("matching engine is missing")
    if not any(record.kind is ComponentKind.RULE_AGENT for record in resolved):
        errors.append("rule agent is missing")
    if not any(record.kind is ComponentKind.INFORMATION_NETWORK for record in resolved):
        errors.append("information network is missing")
    if not any(record.kind is ComponentKind.METRIC_COMPONENT for record in resolved):
        errors.append("metric component is missing")
    if not any(record.kind is ComponentKind.VALIDATION_COMPONENT for record in resolved):
        errors.append("validation component is missing")
    modelRoutes = {
        (record.modelDetails.provider, record.modelDetails.modelId)
        for record in resolved
        if record.modelDetails is not None
    }
    expectedModelRoutes = {(model.provider, model.model_id) for model in listModels()}
    if modelRoutes != expectedModelRoutes:
        errors.append("provider-model inventory does not match the runtime catalog")
    promptHashes = {
        record.promptDetails.promptHash for record in resolved if record.promptDetails is not None
    }
    expectedPromptHashes = {prompt.promptHash for prompt in PROMPT_REGISTRY}
    if promptHashes != expectedPromptHashes:
        errors.append("prompt inventory does not match the runtime prompt registry")
    return tuple(errors)


def listComponents(*, kind: ComponentKind | None = None) -> tuple[ComponentRecord, ...]:
    if kind is None:
        return COMPONENT_INVENTORY
    return tuple(record for record in COMPONENT_INVENTORY if record.kind is kind)


def componentById(componentId: str) -> ComponentRecord:
    for record in COMPONENT_INVENTORY:
        if record.componentId == componentId:
            return record
    raise KeyError(f"unknown governance component: {componentId}")


def inventorySnapshot() -> tuple[dict[str, object], ...]:
    return tuple(record.model_dump(mode="json", by_alias=True) for record in COMPONENT_INVENTORY)


def inventoryHash() -> str:
    payload = json.dumps(
        inventorySnapshot(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


COMPONENT_INVENTORY = _buildInventory()
