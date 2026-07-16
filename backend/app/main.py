"""EventShock Lab FastAPI 单体入口。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend.app.cognition import (
    CNY_PER_USD_BUDGET_FLOOR,
    FX_SOURCE_URL,
    OFFICIAL_FX_SNAPSHOT_CNY_PER_USD,
    PRICING_SNAPSHOT_VERSION,
    CognitionService,
    CredentialNotConfiguredError,
    EvalSample,
    ExternalEvidenceSource,
    ModelGatewayError,
    getZhipuTokenPrice,
)
from backend.app.cognition.golden_suite import (
    builtInEvalCases,
    codeGraderSelfTestSamples,
)
from backend.app.config import loadSettings
from backend.app.database import Database
from backend.app.errors import ApiError
from backend.app.governance.redteam import RED_TEAM_CASES, scoreRedTeamSuite
from backend.app.governance.registry import inventoryHash, inventorySnapshot
from backend.app.governance.release_gate import P0_GATES, ReleaseContext, evaluateP0Release
from backend.app.observability import RuntimeMetrics
from backend.app.rate_limit import RateLimitExceeded, RateLimitRule, SlidingWindowRateLimiter
from backend.app.scenario_service import ScenarioService
from backend.app.schemas import (
    ClaimReviewRequest,
    EvalRunRequest,
    EventPackCreateRequest,
    EventPackExtractRequest,
    EventSourceInput,
    ExperimentInvalidateRequest,
    ExperimentRequest,
    LlmConfigRequest,
    ScenarioDiffRequest,
    ScenarioSaveRequest,
    ScenarioUpdateRequest,
    ScenarioValidateRequest,
)
from backend.app.security import (
    ContentPolicyDecision,
    redactReviewableText,
    scanEventPackContent,
)
from backend.app.service import EventPackService, ExperimentService
from backend.app.study.api_models import StudyDesignPreviewRequest, StudyRunApiRequest
from backend.app.study.api_service import StudyApiService

SESSION_PATTERN = re.compile(r"^[A-Za-z0-9._-]{12,128}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def createApp(dataDir: Path | None = None, frontendDist: Path | None = None) -> FastAPI:
    settings = loadSettings(dataDir)
    rateLimiter = SlidingWindowRateLimiter()
    runtimeMetrics = RuntimeMetrics()

    @asynccontextmanager
    async def lifespan(appInstance: FastAPI):
        database = Database(settings.databasePath)
        database.initialize()
        cognitionService = CognitionService()
        eventPackService = EventPackService(
            database,
            settings.projectRoot,
            cognitionService,
        )
        scenarioService = ScenarioService(database, eventPackService)
        experimentService = ExperimentService(database, eventPackService, cognitionService)
        studyService = StudyApiService(database)
        appInstance.state.database = database
        appInstance.state.eventPackService = eventPackService
        appInstance.state.cognitionService = cognitionService
        appInstance.state.scenarioService = scenarioService
        appInstance.state.experimentService = experimentService
        appInstance.state.studyService = studyService
        yield
        experimentService.shutdown()

    appInstance = FastAPI(
        title="EventShock Lab API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.production else "/docs",
        redoc_url=None if settings.production else "/redoc",
        openapi_url=None if settings.production else "/openapi.json",
    )

    @appInstance.middleware("http")
    async def traceMiddleware(request: Request, callNext):
        requestStartedAt = time.perf_counter()
        traceId = request.headers.get("X-Trace-ID") or f"http-{uuid.uuid4().hex}"
        request.state.traceId = traceId[:128]
        try:
            rateLimitRules = _rateLimitRules(request)
            if rateLimitRules:
                rateLimiter.check(rateLimitRules)
        except RateLimitExceeded as error:
            response = JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many write requests. Retry later.",
                        "traceId": request.state.traceId,
                    }
                },
                headers={
                    "Retry-After": str(error.retryAfterSeconds),
                    "Cache-Control": "no-store",
                },
            )
            _addSecurityHeaders(response, request.state.traceId)
            runtimeMetrics.record(
                durationMs=(time.perf_counter() - requestStartedAt) * 1_000,
                statusCode=response.status_code,
            )
            return response
        response = await callNext(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        _addSecurityHeaders(response, request.state.traceId)
        runtimeMetrics.record(
            durationMs=(time.perf_counter() - requestStartedAt) * 1_000,
            statusCode=response.status_code,
        )
        return response

    @appInstance.exception_handler(ApiError)
    async def apiErrorHandler(request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.statusCode,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "traceId": getattr(request.state, "traceId", None),
                }
            },
        )

    @appInstance.exception_handler(RequestValidationError)
    async def requestValidationHandler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        fields = [
            {
                "location": [str(part) for part in item["loc"]],
                "type": item["type"],
            }
            for item in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "REQUEST_VALIDATION_ERROR",
                    "message": "The request does not match the API schema.",
                    "fields": fields,
                    "traceId": getattr(request.state, "traceId", None),
                }
            },
        )

    @appInstance.exception_handler(Exception)
    async def internalErrorHandler(request: Request, _error: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "The server could not complete the request.",
                    "traceId": getattr(request.state, "traceId", None),
                }
            },
        )

    @appInstance.get("/api/health")
    async def getHealth(request: Request) -> dict[str, Any]:
        database: Database = request.app.state.database
        databaseHealthy = database.ping()
        if not databaseHealthy:
            raise ApiError("DATABASE_UNAVAILABLE", 503, "The database is unavailable.")
        return {
            "status": "ok",
            "service": "eventshock-api",
            "version": "0.1.0",
            "releaseCommit": settings.releaseCommit,
            "database": "ok",
            "simulationConcurrency": 1,
        }

    @appInstance.get("/api/v1/system/metrics")
    async def getSystemMetrics(request: Request) -> dict[str, Any]:
        database: Database = request.app.state.database
        experiments: ExperimentService = request.app.state.experimentService
        cognition: CognitionService = request.app.state.cognitionService
        return {
            "service": "eventshock-api",
            "version": "0.1.0",
            "releaseCommit": settings.releaseCommit,
            "runtime": runtimeMetrics.snapshot(),
            "experiments": experiments.getRuntimeMetrics(),
            "storage": {
                "database": "ok" if database.ping() else "unavailable",
                "retainedExperiments": database.countExperiments(),
                "maximumRetainedExperiments": 500,
            },
            "cognition": cognition.getTelemetry().model_dump(mode="json"),
            "sloTargets": {
                "availability": 0.99,
                "apiP95Milliseconds": 800,
                "status": "TARGETS_NOT_PRODUCTION_EVIDENCE",
            },
        }

    @appInstance.get("/api/v1/cases")
    async def getCases(
        request: Request,
        sessionId: Annotated[str | None, Header(alias="X-Session-ID")] = None,
    ) -> dict[str, Any]:
        service: EventPackService = request.app.state.eventPackService
        return {"items": service.listCases(_optionalSessionId(sessionId))}

    @appInstance.post("/api/v1/event-packs", status_code=201)
    async def createEventPack(
        eventPack: EventPackCreateRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        validatedSessionId = _sessionId(sessionId)
        service: EventPackService = request.app.state.eventPackService
        cognition: CognitionService = request.app.state.cognitionService
        contentSecurity = _scanEventPackSources(
            eventPack.sources,
            acknowledged=eventPack.acknowledgedContentReview,
            eventPackMetadata={
                "title": eventPack.title,
                "titleZh": eventPack.titleZh or "",
                "summary": eventPack.summary,
                "summaryZh": eventPack.summaryZh or "",
                "value": eventPack.instrument,
            },
        )
        eventPack = _sanitizeAcknowledgedEventPack(eventPack, contentSecurity)
        claims = None
        extractionMode = "RULE_FALLBACK_NO_LLM_CONFIG"
        if cognition.getConfig(validatedSessionId).configured:
            try:
                extraction = await cognition.extractEventClaims(
                    sessionId=validatedSessionId,
                    sources=_cognitionSources(eventPack.sources),
                    maximumClaims=16,
                )
                if extraction.event_pack_claims:
                    claims = list(extraction.event_pack_claims)
                    extractionMode = (
                        f"ZHIPU_{extraction.model}_FALLBACK"
                        if extraction.fallback_used
                        else f"ZHIPU_{extraction.model}"
                    )
                else:
                    extractionMode = f"ZHIPU_{extraction.model}_ABSTAINED_RULE_FALLBACK"
            except CredentialNotConfiguredError:
                extractionMode = "RULE_FALLBACK_LLM_CONFIG_EXPIRED"
            except ModelGatewayError as error:
                extractionMode = f"RULE_FALLBACK_{error.code.value}"
        return service.createEventPack(
            eventPack,
            validatedSessionId,
            claims=claims,
            extractionMode=extractionMode,
            contentSecurity=contentSecurity,
        )

    @appInstance.get("/api/v1/models")
    async def listModels(request: Request) -> dict[str, Any]:
        cognition: CognitionService = request.app.state.cognitionService
        models: list[dict[str, Any]] = []
        for model in cognition.getModelCatalog():
            price = getZhipuTokenPrice(model.model_id)
            models.append(
                {
                    "id": model.model_id,
                    "name": model.display_name,
                    "contextTokens": model.context_tokens,
                    "maxOutputTokens": model.max_output_tokens,
                    "supportsJsonObject": model.supports_json_object,
                    "supportsFunctionCalling": model.supports_function_calling,
                    "supportsThinking": model.supports_thinking,
                    "recommended": model.recommended,
                    "freeTier": model.free_tier,
                    "legacy": model.legacy,
                    "deprecationNote": model.deprecation_note,
                    "pricingStatus": (
                        "VERIFIED_UPPER_BOUND" if price is not None else "UNAVAILABLE_FAIL_CLOSED"
                    ),
                    "billingCurrency": "CNY" if price is not None else None,
                    "inputRateUpperCnyPerMillion": (
                        float(price.inputCnyPerMillion) if price is not None else None
                    ),
                    "outputRateUpperCnyPerMillion": (
                        float(price.outputCnyPerMillion) if price is not None else None
                    ),
                    "pricingVerifiedAt": price.verifiedAt if price is not None else None,
                    "pricingNote": price.pricingNote if price is not None else None,
                }
            )
        return {
            "provider": "zhipu",
            "providerName": "Zhipu AI",
            "baseUrl": "https://open.bigmodel.cn/api/paas/v4/",
            "documentationUrl": "https://docs.bigmodel.cn/cn/guide/start/model-overview",
            "pricingUrl": "https://bigmodel.cn/pricing",
            "pricingSnapshotVersion": PRICING_SNAPSHOT_VERSION,
            "fxSourceUrl": FX_SOURCE_URL,
            "officialFxSnapshotCnyPerUsd": float(OFFICIAL_FX_SNAPSHOT_CNY_PER_USD),
            "cnyPerUsdBudgetFloor": float(CNY_PER_USD_BUDGET_FLOOR),
            "costCapSemantics": (
                "Verified public CNY list-price upper bounds converted with a conservative "
                "frozen FX floor; unknown prices fail closed before dispatch."
            ),
            "models": models,
        }

    @appInstance.get("/api/v1/prompts")
    async def listPrompts(request: Request) -> dict[str, Any]:
        cognition: CognitionService = request.app.state.cognitionService
        return {
            "items": [prompt.model_dump(mode="json") for prompt in cognition.getPromptRegistry()]
        }

    @appInstance.get("/api/v1/llm/config")
    async def getLlmConfig(
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        cognition: CognitionService = request.app.state.cognitionService
        return cognition.getConfig(_sessionId(sessionId)).model_dump(mode="json")

    @appInstance.put("/api/v1/llm/config")
    async def saveLlmConfig(
        config: LlmConfigRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        validatedSessionId = _sessionId(sessionId)
        cognition: CognitionService = request.app.state.cognitionService
        database: Database = request.app.state.database
        try:
            view = cognition.setConfig(
                sessionId=validatedSessionId,
                apiKey=config.apiKey,
                model=config.model,
                thinkingEnabled=config.thinkingEnabled,
                maxTokens=config.maxTokens,
            )
        except ValueError as error:
            raise ApiError("INVALID_LLM_CONFIG", 422, str(error)) from error
        database.appendAuditEvent(
            validatedSessionId,
            "MODEL_CONFIG",
            "zhipu-session-config",
            "CONFIGURED",
            {
                "provider": config.provider,
                "model": config.model,
                "thinkingEnabled": config.thinkingEnabled,
                "maxTokens": config.maxTokens,
            },
        )
        return view.model_dump(mode="json")

    @appInstance.delete("/api/v1/llm/config")
    async def clearLlmConfig(
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        validatedSessionId = _sessionId(sessionId)
        cognition: CognitionService = request.app.state.cognitionService
        database: Database = request.app.state.database
        cleared = cognition.clearConfig(validatedSessionId)
        database.appendAuditEvent(
            validatedSessionId,
            "MODEL_CONFIG",
            "zhipu-session-config",
            "CLEARED",
            {"credentialWasPresent": cleared},
        )
        return cognition.getConfig(validatedSessionId).model_dump(mode="json")

    @appInstance.post("/api/v1/llm/test")
    async def testLlmConfig(
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        validatedSessionId = _sessionId(sessionId)
        cognition: CognitionService = request.app.state.cognitionService
        try:
            result = await cognition.testConnection(validatedSessionId)
        except CredentialNotConfiguredError as error:
            raise ApiError(
                "LLM_CREDENTIAL_NOT_CONFIGURED",
                409,
                "Configure a session API key before testing the model connection.",
            ) from error
        except ModelGatewayError as error:
            raise ApiError(error.code.value, 502, str(error)) from error
        return {
            "ok": True,
            "provider": result.provider,
            "model": result.model,
            "structuredOutputValidated": True,
            "responseSchemaVersion": result.schema_version,
            "latencyMs": result.latency_ms,
            "message": "The provider returned JSON that passed strict local schema validation.",
        }

    @appInstance.get("/api/v1/llm/telemetry")
    async def getLlmTelemetry(request: Request) -> dict[str, Any]:
        cognition: CognitionService = request.app.state.cognitionService
        return cognition.getTelemetry().model_dump(mode="json")

    @appInstance.get("/api/v1/evals")
    async def getEvalSummary(request: Request) -> dict[str, Any]:
        cognition: CognitionService = request.app.state.cognitionService
        return cognition.getEvalSummary().model_dump(mode="json")

    @appInstance.post("/api/v1/evals/run")
    async def runCognitionEvaluation(
        evaluation: EvalRunRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        validatedSessionId = _sessionId(sessionId)
        cognition: CognitionService = request.app.state.cognitionService
        cases = builtInEvalCases()[: evaluation.maximumCases]
        modelRuns: list[dict[str, Any]] = []
        if evaluation.mode == "CODE_GRADER_SELF_TEST":
            samples = codeGraderSelfTestSamples(cases)
            evaluatedSystem = "DETERMINISTIC_CODE_GRADER"
        else:
            if not cognition.getConfig(validatedSessionId).configured:
                raise ApiError(
                    "LLM_CREDENTIAL_NOT_CONFIGURED",
                    409,
                    "Configure a session-scoped Zhipu API key before running the live suite.",
                )
            liveSamples: list[EvalSample] = []
            for case in cases:
                try:
                    modelRun = await cognition.generateBeliefDecision(
                        sessionId=validatedSessionId,
                        observation=case.observation,
                    )
                except CredentialNotConfiguredError as error:
                    raise ApiError(
                        "LLM_CREDENTIAL_NOT_CONFIGURED",
                        409,
                        "The session credential expired before the evaluation completed.",
                    ) from error
                except ModelGatewayError as error:
                    raise ApiError(error.code.value, 502, str(error)) from error
                liveSamples.append(EvalSample(case=case, rawDecision=modelRun.decision))
                modelRuns.append(
                    {
                        "caseId": case.case_id,
                        "model": modelRun.model,
                        "requestId": modelRun.request_id,
                        "cacheHit": modelRun.cache_hit,
                        "fallbackUsed": modelRun.fallback_used,
                        "repairUsed": modelRun.repair_used,
                        "latencyMs": modelRun.latency_ms,
                        "totalTokens": modelRun.total_tokens,
                    }
                )
            samples = tuple(liveSamples)
            evaluatedSystem = "LIVE_CONFIGURED_ZHIPU_MODEL"
        result = cognition.runEvaluation(samples)
        database: Database = request.app.state.database
        database.appendAuditEvent(
            validatedSessionId,
            "COGNITION_EVALUATION",
            f"eval-{uuid.uuid4().hex[:16]}",
            "EVALUATION_COMPLETED",
            {
                "mode": evaluation.mode,
                "evaluatedCases": result.total_cases,
                "passedCases": result.passed_cases,
                "passRate": result.pass_rate,
            },
        )
        return {
            "mode": evaluation.mode,
            "evaluatedSystem": evaluatedSystem,
            "suiteVersion": "cognition_golden_v1.0.0",
            "result": result.model_dump(mode="json"),
            "modelRuns": modelRuns,
            "interpretationBoundary": (
                "CODE_GRADER_SELF_TEST validates grader wiring only; LIVE_CONFIGURED_MODEL "
                "evaluates the selected model on three fixed cases but does not replace "
                "human or domain-expert review."
            ),
        }

    @appInstance.get("/api/v1/governance/components")
    async def getGovernanceComponents() -> dict[str, Any]:
        return {
            "inventoryHash": inventoryHash(),
            "items": list(inventorySnapshot()),
        }

    @appInstance.get("/api/v1/governance/red-team")
    async def getRedTeamRegistry() -> dict[str, Any]:
        results = scoreRedTeamSuite(())
        return {
            "definitions": [item.model_dump(mode="json", by_alias=True) for item in RED_TEAM_CASES],
            "results": [item.model_dump(mode="json", by_alias=True) for item in results],
            "notice": (
                "Definitions are executable specifications, not evidence that the "
                "attacks were run. Every result remains NOT_RUN until evidence is attached."
            ),
        }

    @appInstance.get("/api/v1/governance/release-gate")
    async def getReleaseGate() -> dict[str, Any]:
        evaluatedAt = datetime.now(UTC)
        report = evaluateP0Release(
            ReleaseContext(
                releaseId=f"runtime-readiness-{evaluatedAt:%Y%m%dT%H%M%SZ}",
                evaluatedAt=evaluatedAt,
            )
        )
        return {
            "report": report.model_dump(mode="json", by_alias=True),
            "definitions": [item.model_dump(mode="json", by_alias=True) for item in P0_GATES],
            "interpretationBoundary": (
                "A blocked readiness report does not disable the educational demo; "
                "it prevents presenting the system as externally validated or production-ready."
            ),
        }

    @appInstance.get("/api/v1/validation/ladder")
    async def getValidationLadder() -> dict[str, Any]:
        return {
            "highestAllowedClaim": "MECHANISM_DEMONSTRATION",
            "levels": [
                {
                    "level": "L0",
                    "title": "Code and ledger invariants",
                    "status": "AUTOMATED_EVIDENCE_AVAILABLE",
                    "boundary": (
                        "Unit and property tests are present; attach a dated CI artifact "
                        "for release evidence."
                    ),
                },
                {
                    "level": "L1",
                    "title": "Market microstructure modules",
                    "status": "AUTOMATED_EVIDENCE_AVAILABLE",
                    "boundary": (
                        "Matching, queue, risk, and accounting behavior are code-tested only."
                    ),
                },
                {
                    "level": "L2",
                    "title": "Rule-agent aggregate behavior",
                    "status": "IMPLEMENTED_AWAITING_EMPIRICAL_STUDY",
                    "boundary": (
                        "Synthetic behavior is reproducible but not evidence of real "
                        "investor behavior."
                    ),
                },
                {
                    "level": "L3",
                    "title": "LLM cognition and tool behavior",
                    "status": "IMPLEMENTED_AWAITING_LIVE_MODEL_REVIEW",
                    "boundary": (
                        "Schema and fallback tests exist; live multilingual model validation "
                        "remains human work."
                    ),
                },
                {
                    "level": "L4",
                    "title": "Market statistics and stylized facts",
                    "status": "IMPLEMENTED_AWAITING_CALIBRATION_EVIDENCE",
                    "boundary": (
                        "Metrics are computed, but empirical tolerance results are not yet "
                        "approved."
                    ),
                },
                {
                    "level": "L5",
                    "title": "Historical event response",
                    "status": "NOT_COMPLETED",
                    "boundary": (
                        "CrowdStrike and GameStop independent validation evidence is not attached."
                    ),
                },
                {
                    "level": "L6",
                    "title": "Counterfactual robustness",
                    "status": "IMPLEMENTED_AWAITING_STUDY_EXECUTION",
                    "boundary": (
                        "Sensitivity, negative-control, and knockout code does not replace "
                        "executed studies."
                    ),
                },
                {
                    "level": "L7",
                    "title": "User comprehension and usability",
                    "status": "PENDING_HUMAN_EVIDENCE",
                    "boundary": "No target-user study is claimed or fabricated.",
                },
                {
                    "level": "L8",
                    "title": "Operations, cost, security, and governance",
                    "status": "PENDING_HUMAN_EVIDENCE",
                    "boundary": (
                        "Security review, license review, and incident rehearsal remain pending."
                    ),
                },
            ],
        }

    @appInstance.get("/api/v1/studies/presets")
    async def getStudyPresets(request: Request) -> dict[str, Any]:
        service: StudyApiService = request.app.state.studyService
        return service.presets()

    @appInstance.post("/api/v1/studies/design-preview")
    async def previewStudyDesign(
        design: StudyDesignPreviewRequest,
        request: Request,
    ) -> dict[str, Any]:
        service: StudyApiService = request.app.state.studyService
        return service.preview(design)

    @appInstance.post("/api/v1/studies/run", status_code=201)
    async def runStudy(
        study: StudyRunApiRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        validatedSessionId = _sessionId(sessionId)
        eventPacks: EventPackService = request.app.state.eventPackService
        studies: StudyApiService = request.app.state.studyService
        eventPack = eventPacks.getEventPack(study.eventPackId, validatedSessionId)
        return await run_in_threadpool(
            studies.run,
            study,
            sessionId=validatedSessionId,
            eventPack=eventPack,
        )

    @appInstance.get("/api/v1/studies")
    async def listStudies(
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: StudyApiService = request.app.state.studyService
        return {"items": service.listRuns(_sessionId(sessionId))}

    @appInstance.get("/api/v1/studies/{runId}")
    async def getStudyRun(
        runId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: StudyApiService = request.app.state.studyService
        return service.getRun(runId, _sessionId(sessionId))

    @appInstance.get("/api/v1/event-packs/{eventPackId}")
    async def getEventPack(
        eventPackId: str,
        request: Request,
        sessionId: Annotated[str | None, Header(alias="X-Session-ID")] = None,
    ) -> dict[str, Any]:
        validatedSessionId = _optionalSessionId(sessionId)
        service: EventPackService = request.app.state.eventPackService
        return service.getEventPack(eventPackId, validatedSessionId)

    @appInstance.post("/api/v1/event-packs/{eventPackId}/claims/{claimId}/review")
    async def reviewClaim(
        eventPackId: str,
        claimId: str,
        review: ClaimReviewRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: EventPackService = request.app.state.eventPackService
        return service.reviewClaim(eventPackId, claimId, _sessionId(sessionId), review)

    @appInstance.post("/api/v1/event-packs/{eventPackId}/freeze")
    async def freezeEventPack(
        eventPackId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: EventPackService = request.app.state.eventPackService
        return service.freezeEventPack(eventPackId, _sessionId(sessionId))

    @appInstance.post("/api/v1/event-packs/{eventPackId}/extract")
    async def extractEventPackClaims(
        eventPackId: str,
        extraction: EventPackExtractRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        validatedSessionId = _sessionId(sessionId)
        service: EventPackService = request.app.state.eventPackService
        currentPack = service.getEventPack(eventPackId, validatedSessionId)
        if not extraction.sources:
            raise ApiError(
                "EXTRACTION_SOURCES_REQUIRED",
                422,
                "Re-extraction requires source text because raw uploads are not retained.",
            )
        # 在内容进入任何外部模型前执行 PIT 截止时间校验，避免未来信息泄漏。
        service.validateSourcesAtCutoff(extraction.sources, currentPack["asOf"])
        contentSecurity = _scanEventPackSources(
            extraction.sources,
            acknowledged=extraction.acknowledgedContentReview,
        )
        extraction = extraction.model_copy(
            update={
                "sources": _sanitizeAcknowledgedSources(
                    extraction.sources,
                    contentSecurity,
                )
            }
        )
        extractionInput = EventPackCreateRequest(
            title=currentPack["title"],
            titleZh=currentPack.get("titleZh"),
            summary=currentPack["summary"],
            summaryZh=currentPack.get("summaryZh"),
            asOf=currentPack["asOf"],
            instrument=(
                currentPack.get("instrument", "CUSTOM")
                if isinstance(currentPack.get("instrument", "CUSTOM"), str)
                else currentPack.get("instrument", {}).get("symbol", "CUSTOM")
            ),
            sources=extraction.sources,
            acknowledgedContentReview=extraction.acknowledgedContentReview,
        )
        cognition: CognitionService = request.app.state.cognitionService
        claims = None
        extractionMode = "RULE_ONLY"
        if extraction.useLlm and cognition.getConfig(validatedSessionId).configured:
            try:
                llmExtraction = await cognition.extractEventClaims(
                    sessionId=validatedSessionId,
                    sources=_cognitionSources(extraction.sources),
                    maximumClaims=extraction.maximumClaims,
                )
                if llmExtraction.event_pack_claims:
                    claims = list(llmExtraction.event_pack_claims)
                    extractionMode = (
                        f"ZHIPU_{llmExtraction.model}_FALLBACK"
                        if llmExtraction.fallback_used
                        else f"ZHIPU_{llmExtraction.model}"
                    )
                else:
                    extractionMode = f"ZHIPU_{llmExtraction.model}_ABSTAINED_RULE_FALLBACK"
            except CredentialNotConfiguredError:
                extractionMode = "RULE_FALLBACK_LLM_CONFIG_EXPIRED"
            except ModelGatewayError as error:
                extractionMode = f"RULE_FALLBACK_{error.code.value}"
        elif extraction.useLlm:
            extractionMode = "RULE_FALLBACK_NO_LLM_CONFIG"
        if claims is None:
            claims = service.extractCandidateClaims(
                extractionInput,
                extraction.maximumClaims,
            )
        return service.saveExtractedClaims(
            eventPackId,
            validatedSessionId,
            claims,
            extractionMode,
            sources=extraction.sources,
            contentSecurity=contentSecurity,
        )

    @appInstance.get("/api/v1/scenarios")
    async def listScenarios(
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        return {"items": service.listScenarios(_sessionId(sessionId))}

    @appInstance.post("/api/v1/scenarios", status_code=201)
    async def createScenario(
        scenario: ScenarioSaveRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        return service.createScenario(scenario, _sessionId(sessionId))

    @appInstance.get("/api/v1/scenarios/{scenarioId}")
    async def getScenario(
        scenarioId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        return service.getScenario(scenarioId, _sessionId(sessionId))

    @appInstance.put("/api/v1/scenarios/{scenarioId}")
    async def updateScenario(
        scenarioId: str,
        scenario: ScenarioUpdateRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        return service.updateScenario(scenarioId, scenario, _sessionId(sessionId))

    @appInstance.delete("/api/v1/scenarios/{scenarioId}", status_code=204)
    async def deleteScenario(
        scenarioId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> Response:
        service: ScenarioService = request.app.state.scenarioService
        service.deleteScenario(scenarioId, _sessionId(sessionId))
        return Response(status_code=204)

    @appInstance.post("/api/v1/scenarios/{scenarioId}/clone", status_code=201)
    async def cloneScenario(
        scenarioId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        return service.cloneScenario(scenarioId, _sessionId(sessionId))

    @appInstance.post("/api/v1/scenarios/{scenarioId}/freeze")
    async def freezeScenario(
        scenarioId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        return service.freezeScenario(scenarioId, _sessionId(sessionId))

    @appInstance.post("/api/v1/scenarios/diff")
    async def diffScenarios(scenarios: ScenarioDiffRequest) -> dict[str, Any]:
        return ScenarioService.diffConfigs(scenarios.baseline, scenarios.intervention)

    @appInstance.post("/api/v1/scenarios/validate")
    async def validateScenario(
        scenario: ScenarioValidateRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: EventPackService = request.app.state.eventPackService
        return service.validateExperiment(scenario, _sessionId(sessionId))

    @appInstance.get("/api/v1/experiments")
    async def listExperiments(
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return {"items": service.listExperiments(_sessionId(sessionId))}

    @appInstance.get("/api/v1/audit-events")
    async def listAuditEvents(
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        database: Database = request.app.state.database
        return {"items": database.listAuditEvents(_sessionId(sessionId))}

    @appInstance.get("/api/v1/audit-events/verify")
    async def verifyAuditEvents(
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        database: Database = request.app.state.database
        return database.verifyAuditChain(_sessionId(sessionId))

    @appInstance.post("/api/v1/experiments")
    async def createExperiment(
        experiment: ExperimentRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
        idempotencyKey: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> Response:
        service: ExperimentService = request.app.state.experimentService
        createdExperiment, created = service.createExperiment(
            experiment,
            _sessionId(sessionId),
            _idempotencyKey(idempotencyKey),
        )
        return JSONResponse(status_code=201 if created else 200, content=createdExperiment)

    @appInstance.get("/api/v1/experiments/{experimentId}")
    async def getExperiment(
        experimentId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.publicExperiment(service.getExperiment(experimentId, _sessionId(sessionId)))

    @appInstance.get("/api/v1/experiments/{experimentId}/events")
    async def streamExperimentEvents(
        experimentId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> StreamingResponse:
        validatedSessionId = _sessionId(sessionId)
        service: ExperimentService = request.app.state.experimentService
        service.getExperiment(experimentId, validatedSessionId)

        async def eventStream():
            previousHash = ""
            sequence = 0
            startedAt = time.monotonic()
            lastHeartbeatAt = startedAt
            terminalStatuses = {
                "COMPLETED",
                "FAILED_FINAL",
                "FAILED_RETRYABLE",
                "CANCELLED",
                "INVALIDATED",
            }
            while time.monotonic() - startedAt < 300:
                if await request.is_disconnected():
                    return
                experiment = service.publicExperiment(
                    service.getExperiment(experimentId, validatedSessionId)
                )
                serialized = json.dumps(
                    experiment,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                eventHash = hashlib.sha256(serialized.encode()).hexdigest()
                if eventHash != previousHash:
                    sequence += 1
                    yield (f"id: {sequence}\nevent: experiment\ndata: {serialized}\n\n")
                    previousHash = eventHash
                    lastHeartbeatAt = time.monotonic()
                if experiment["status"] in terminalStatuses:
                    return
                if time.monotonic() - lastHeartbeatAt >= 10:
                    yield ": keep-alive\n\n"
                    lastHeartbeatAt = time.monotonic()
                await asyncio.sleep(0.5)
            yield (
                "event: stream-timeout\n"
                'data: {"retryWithPolling":true,"reason":"STREAM_WINDOW_EXPIRED"}\n\n'
            )

        return StreamingResponse(
            eventStream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @appInstance.post("/api/v1/experiments/{experimentId}/start")
    async def startExperiment(
        experimentId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.startExperiment(experimentId, _sessionId(sessionId))

    @appInstance.post("/api/v1/experiments/{experimentId}/cancel")
    async def cancelExperiment(
        experimentId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.cancelExperiment(experimentId, _sessionId(sessionId))

    @appInstance.post("/api/v1/experiments/{experimentId}/invalidate")
    async def invalidateExperiment(
        experimentId: str,
        invalidation: ExperimentInvalidateRequest,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.invalidateExperiment(
            experimentId,
            _sessionId(sessionId),
            reasonCode=invalidation.reasonCode.value,
            reason=invalidation.reason,
        )

    @appInstance.get("/api/v1/experiments/{experimentId}/results")
    async def getExperimentResults(
        experimentId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.getResults(experimentId, _sessionId(sessionId))

    @appInstance.get("/api/v1/experiments/{experimentId}/runs")
    async def getExperimentRuns(
        experimentId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.getRuns(experimentId, _sessionId(sessionId))

    @appInstance.get("/api/v1/experiments/{experimentId}/metrics")
    async def getExperimentMetrics(
        experimentId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.getMetrics(experimentId, _sessionId(sessionId))

    @appInstance.get("/api/v1/experiments/{experimentId}/traces")
    async def getExperimentTraces(
        experimentId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.getTraces(experimentId, _sessionId(sessionId))

    async def exportResponse(experimentId: str, request: Request, sessionId: str) -> Response:
        service: ExperimentService = request.app.state.experimentService
        exportBytes = service.exportExperiment(experimentId, _sessionId(sessionId))
        return Response(
            content=exportBytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="eventshock-{experimentId}.zip"'
            },
        )

    @appInstance.get("/api/v1/experiments/{experimentId}/export")
    async def exportExperimentGet(
        experimentId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> Response:
        return await exportResponse(experimentId, request, sessionId)

    @appInstance.post("/api/v1/experiments/{experimentId}/export")
    async def exportExperimentPost(
        experimentId: str,
        request: Request,
        sessionId: Annotated[str, Header(alias="X-Session-ID")],
    ) -> Response:
        return await exportResponse(experimentId, request, sessionId)

    @appInstance.api_route(
        "/api",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    @appInstance.api_route(
        "/api/{apiPath:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def apiNotFound(apiPath: str = "") -> dict[str, Any]:
        raise ApiError("API_ROUTE_NOT_FOUND", 404, "The requested API route does not exist.")

    _registerFrontendFallback(appInstance, frontendDist or settings.frontendDist)
    return appInstance


def _sessionId(sessionId: str) -> str:
    if not SESSION_PATTERN.fullmatch(sessionId):
        raise ApiError(
            "INVALID_SESSION_ID",
            400,
            "X-Session-ID must be 12-128 URL-safe characters.",
        )
    return sessionId


def _optionalSessionId(sessionId: str | None) -> str | None:
    return _sessionId(sessionId) if sessionId is not None else None


def _idempotencyKey(idempotencyKey: str | None) -> str | None:
    if idempotencyKey is None:
        return None
    if not IDEMPOTENCY_PATTERN.fullmatch(idempotencyKey):
        raise ApiError(
            "INVALID_IDEMPOTENCY_KEY",
            400,
            "Idempotency-Key must be 8-128 URL-safe characters.",
        )
    return idempotencyKey


def _cognitionSources(
    sources: list[EventSourceInput],
) -> tuple[ExternalEvidenceSource, ...]:
    return tuple(
        ExternalEvidenceSource(
            sourceId=source.sourceId,
            rawText=source.rawText,
            sourceType=source.sourceType,
            knownAt=source.knownAt,
        )
        for source in sources
    )


def _scanEventPackSources(
    sources: list[EventSourceInput],
    *,
    acknowledged: bool,
    eventPackMetadata: dict[str, object] | None = None,
) -> dict[str, Any]:
    """在任何抽取逻辑之前执行确定性扫描，且只返回可安全持久化的摘要。"""

    sourceSummaries: list[dict[str, Any]] = []
    safeFindings: list[dict[str, Any]] = []
    decisions: set[ContentPolicyDecision] = set()
    totalFindingCount = 0
    metadataSummary: dict[str, Any] | None = None
    if eventPackMetadata is not None:
        metadataResult = scanEventPackContent("", eventPackMetadata, locale="en")
        decisions.add(metadataResult.decision)
        totalFindingCount += len(metadataResult.findings)
        metadataSummary = {
            "decision": metadataResult.decision.value,
            "findingCount": len(metadataResult.findings),
        }
        for finding in metadataResult.findings:
            if len(safeFindings) >= 64:
                break
            safeFindings.append(
                {
                    "sourceId": "event-pack-metadata",
                    "code": finding.code,
                    "severity": finding.severity.value,
                    "field": finding.field,
                    "offset": finding.offset,
                }
            )
    for source in sources:
        result = scanEventPackContent(
            source.rawText,
            {
                "sourceId": source.sourceId,
                "title": source.title,
                "publisher": source.publisher,
                "url": source.url,
                "sourceType": source.sourceType,
                "publishedAt": source.publishedAt.isoformat(),
                "knownAt": source.knownAt.isoformat(),
            },
            locale="en",
        )
        decisions.add(result.decision)
        totalFindingCount += len(result.findings)
        sourceSummaries.append(
            {
                "sourceId": source.sourceId,
                "decision": result.decision.value,
                "sourceReviewLabel": result.sourceReviewLabel.value,
                "officialHost": result.officialHost,
                "findingCount": len(result.findings),
            }
        )
        for finding in result.findings:
            if len(safeFindings) >= 64:
                break
            # 不写 redactedExcerpt 或 recommendedAction，进一步缩小日志泄露面。
            safeFindings.append(
                {
                    "sourceId": source.sourceId,
                    "code": finding.code,
                    "severity": finding.severity.value,
                    "field": finding.field,
                    "offset": finding.offset,
                }
            )

    if ContentPolicyDecision.BLOCK in decisions:
        decision = ContentPolicyDecision.BLOCK
    elif ContentPolicyDecision.REVIEW in decisions:
        decision = ContentPolicyDecision.REVIEW
    else:
        decision = ContentPolicyDecision.ALLOW

    codes = sorted({item["code"] for item in safeFindings})
    codeSummary = ", ".join(codes[:8]) or "UNSPECIFIED_CONTENT_POLICY_FINDING"
    if decision is ContentPolicyDecision.BLOCK:
        raise ApiError(
            "EVENT_PACK_CONTENT_BLOCKED",
            422,
            f"Upload blocked by content safety policy: {codeSummary}.",
        )
    if decision is ContentPolicyDecision.REVIEW and not acknowledged:
        raise ApiError(
            "EVENT_PACK_CONTENT_REVIEW_REQUIRED",
            409,
            f"Human acknowledgement is required before processing: {codeSummary}.",
        )

    return {
        "schemaVersion": "1.0.0",
        "decision": decision.value,
        "acknowledged": bool(acknowledged and decision is ContentPolicyDecision.REVIEW),
        "sourceCount": len(sources),
        "findingCount": totalFindingCount,
        "findingsTruncated": totalFindingCount > len(safeFindings),
        "findings": safeFindings,
        "sources": sourceSummaries,
        "eventPackMetadata": metadataSummary,
        "rawContentRetained": False,
    }


def _sanitizeAcknowledgedSources(
    sources: list[EventSourceInput],
    contentSecurity: dict[str, Any],
) -> list[EventSourceInput]:
    if not contentSecurity.get("acknowledged"):
        return sources
    sanitized: list[EventSourceInput] = []
    for source in sources:
        safeUrl = redactReviewableText(source.url) if source.url else None
        if safeUrl and safeUrl != source.url:
            safeUrl = None
        sanitized.append(
            source.model_copy(
                update={
                    "title": redactReviewableText(source.title),
                    "publisher": redactReviewableText(source.publisher),
                    "url": safeUrl,
                    "rawText": redactReviewableText(source.rawText),
                }
            )
        )
    return sanitized


def _sanitizeAcknowledgedEventPack(
    eventPack: EventPackCreateRequest,
    contentSecurity: dict[str, Any],
) -> EventPackCreateRequest:
    if not contentSecurity.get("acknowledged"):
        return eventPack
    return eventPack.model_copy(
        update={
            "title": redactReviewableText(eventPack.title),
            "titleZh": (redactReviewableText(eventPack.titleZh) if eventPack.titleZh else None),
            "summary": redactReviewableText(eventPack.summary),
            "summaryZh": (
                redactReviewableText(eventPack.summaryZh) if eventPack.summaryZh else None
            ),
            "instrument": redactReviewableText(eventPack.instrument),
            "sources": _sanitizeAcknowledgedSources(eventPack.sources, contentSecurity),
        }
    )


def _rateLimitRules(request: Request) -> list[RateLimitRule]:
    if request.method not in {"POST", "PUT", "DELETE"}:
        return []
    path = request.url.path.rstrip("/")
    isExperimentCreate = path == "/api/v1/experiments"
    isStudyRun = path == "/api/v1/studies/run"
    isLimitedWrite = (
        isExperimentCreate
        or isStudyRun
        or any(
            re.fullmatch(pattern, path)
            for pattern in (
                r"/api/v1/event-packs",
                r"/api/v1/event-packs/[^/]+/extract",
                r"/api/v1/event-packs/[^/]+/claims/[^/]+/review",
                r"/api/v1/event-packs/[^/]+/freeze",
                r"/api/v1/scenarios(?:/[^/]+(?:/(?:clone|freeze))?)?",
                r"/api/v1/llm/(?:config|test)",
                r"/api/v1/evals/run",
                r"/api/v1/experiments/[^/]+/(start|cancel|invalidate|export)",
            )
        )
    )
    if not isLimitedWrite:
        return []

    clientIp = _clientIp(request)
    rawSessionId = request.headers.get("X-Session-ID", "missing-session")[:128]
    sessionDigest = hashlib.blake2s(rawSessionId.encode(), digest_size=8).hexdigest()
    rules = [
        RateLimitRule(key=f"write:ip:{clientIp}", limit=30),
        RateLimitRule(key=f"write:session:{sessionDigest}", limit=30),
    ]
    if isExperimentCreate:
        rules.extend(
            (
                RateLimitRule(key=f"experiment-create:ip:{clientIp}", limit=5),
                RateLimitRule(key=f"experiment-create:session:{sessionDigest}", limit=5),
            )
        )
    if isStudyRun:
        rules.extend(
            (
                RateLimitRule(key=f"study-run:ip:{clientIp}", limit=2),
                RateLimitRule(key=f"study-run:session:{sessionDigest}", limit=2),
            )
        )
    return rules


def _clientIp(request: Request) -> str:
    forwardedFor = request.headers.get("X-Forwarded-For")
    if forwardedFor:
        firstAddress = forwardedFor.split(",", maxsplit=1)[0].strip()
        if firstAddress:
            return firstAddress[:64]
    return (request.client.host if request.client else "unknown-client")[:64]


def _addSecurityHeaders(response: Response, traceId: str) -> None:
    response.headers["X-Trace-ID"] = traceId
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; "
        "form-action 'self'; object-src 'none'; img-src 'self' data:; "
        "font-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'"
    )


def _registerFrontendFallback(appInstance: FastAPI, frontendDist: Path) -> None:
    indexPath = frontendDist / "index.html"
    if not indexPath.is_file():
        return
    resolvedRoot = frontendDist.resolve()

    @appInstance.api_route("/{frontendPath:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def frontendFallback(frontendPath: str) -> Response:
        requestedPath = (resolvedRoot / frontendPath).resolve()
        if requestedPath.is_relative_to(resolvedRoot) and requestedPath.is_file():
            return FileResponse(requestedPath)
        if frontendPath == "":
            return FileResponse(indexPath)
        return Response(status_code=404)


app = createApp()
