"""EventShock Lab FastAPI 单体入口。"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from backend.app.auth import (
    AuthContext,
    AuthenticationError,
    AuthorizationError,
    AuthRepository,
    AuthService,
    ChallengeCooldownError,
    ChallengePurpose,
    ChallengeVerificationError,
    CsrfValidationError,
    DuplicateUserError,
    MailDeliveryError,
    PasswordPolicyError,
    PublicUser,
    SmtpVerificationMailer,
    UserRole,
    normalizeEmail,
)
from backend.app.auth.api_models import (
    AuthLoginRequest,
    AuthPasswordResetRequest,
    AuthRegistrationRequest,
    LegalConsentRequest,
    UserPreferencesRequest,
    UserStatusRequest,
    VerificationCodeRequest,
)
from backend.app.cognition import (
    CNY_PER_USD_BUDGET_FLOOR,
    FX_SOURCE_URL,
    OFFICIAL_FX_SNAPSHOT_CNY_PER_USD,
    PRICING_SNAPSHOT_VERSION,
    CognitionService,
    CredentialNotConfiguredError,
    EvalSample,
    ExternalEvidenceSource,
    FailureCode,
    ModelGatewayError,
)
from backend.app.cognition.catalog import (
    DEFAULT_PROVIDER,
    listProviders,
)
from backend.app.cognition.catalog import (
    listModels as listCognitionModels,
)
from backend.app.cognition.gateway import PROVIDER_ADVANCED_PARAMETER_CAPABILITIES
from backend.app.cognition.golden_suite import (
    builtInEvalCases,
    codeGraderSelfTestSamples,
)
from backend.app.cognition.pricing import getTokenPrice
from backend.app.cognition.streaming import ModelStreamObserver, ModelStreamProgress
from backend.app.config import loadSettings
from backend.app.database import (
    Database,
    ResultInterpretationConversationDeletedError,
    ResultInterpretationRequestConflictError,
)
from backend.app.errors import ApiError
from backend.app.event_pack_factory import (
    SEARCH_ENGINE_CATALOG,
    EventPackFactoryError,
    EventPackFactoryRepository,
    EventPackFactoryService,
    FactoryRevisionConflictError,
    SourceInputKind,
    SourceReviewInput,
    ZhipuWebSearchClient,
)
from backend.app.event_pack_factory.api_models import (
    FactoryBuildCreateRequest,
    FactoryDeleteBuildRequest,
    FactoryMaterializeRequest,
    FactoryPasteMutationRequest,
    FactoryReaderMutationRequest,
    FactoryReviewMutationRequest,
    FactorySearchMutationRequest,
    FactorySourceRawTextUpdateRequest,
)
from backend.app.event_pack_factory.reader import (
    READER_CAPABILITY,
    ZhipuReaderClient,
)
from backend.app.governance.redteam import RED_TEAM_CASES, scoreRedTeamSuite
from backend.app.governance.registry import inventoryHash, inventorySnapshot
from backend.app.governance.release_gate import P0_GATES, ReleaseContext, evaluateP0Release
from backend.app.guided_workflow import (
    GuidedAdvanceRequest,
    GuidedCreateRequest,
    GuidedLinkRequest,
    GuidedProposalActionRequest,
    GuidedTurnRequest,
    GuidedWorkflowConflictError,
    GuidedWorkflowRepository,
    GuidedWorkflowService,
)
from backend.app.guided_workflow.artifacts import GuidedArtifactValidator
from backend.app.legal import publicLegalPayload
from backend.app.observability import RuntimeMetrics
from backend.app.rate_limit import RateLimitExceeded, RateLimitRule, SlidingWindowRateLimiter
from backend.app.scenario_service import ScenarioService
from backend.app.schemas import (
    BulkClaimApprovalRequest,
    ClaimReviewRequest,
    EvalRunRequest,
    EventPackCreateRequest,
    EventPackExtractRequest,
    EventSourceInput,
    ExperimentInvalidateRequest,
    ExperimentRequest,
    LlmConfigRequest,
    ResultInterpretationChatRequest,
    ScenarioDiffRequest,
    ScenarioSaveRequest,
    ScenarioUpdateRequest,
    ScenarioValidateRequest,
)
from backend.app.security import (
    ContentPolicyDecision,
    redactReviewableText,
    scanEventPackContent,
    scanTextContent,
)
from backend.app.service import EventPackService, ExperimentService
from backend.app.single_flight import (
    ResultInterpretationSingleFlight,
    SingleFlightCapacityError,
    SingleFlightRequestConflictError,
    canonicalRequestHash,
)
from backend.app.study.api_models import StudyDesignPreviewRequest, StudyRunApiRequest
from backend.app.study.api_service import StudyApiService

LOGGER = logging.getLogger(__name__)

SESSION_PATTERN = re.compile(r"^[A-Za-z0-9._-]{12,128}$")
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
AUTH_COOKIE_NAME = "eventshock_auth"
SAFE_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PUBLIC_AUTH_PATHS = frozenset(
    {
        "/api/v1/auth/session",
        "/api/v1/auth/login",
        "/api/v1/auth/verification-code",
        "/api/v1/auth/register",
        "/api/v1/auth/password-reset",
        "/api/v1/legal/terms",
    }
)
LEGAL_GATE_EXEMPT_PATHS = frozenset(
    {
        "/api/v1/auth/legal-acceptance",
        "/api/v1/auth/logout",
    }
)

MODEL_ERROR_PUBLIC_MESSAGES: dict[FailureCode, str] = {
    FailureCode.MODEL_TIMEOUT: "The model provider did not finish within the bounded time.",
    FailureCode.MODEL_TRANSPORT_ERROR: "The model provider connection failed temporarily.",
    FailureCode.MODEL_AUTHENTICATION_ERROR: "The model provider rejected the temporary API key.",
    FailureCode.MODEL_PERMISSION_ERROR: "The selected model is not available to this API key.",
    FailureCode.MODEL_RATE_LIMITED: "The model provider rate limit was reached.",
    FailureCode.MODEL_OVERLOADED: "The model provider is temporarily overloaded.",
    FailureCode.MODEL_QUOTA_EXHAUSTED: "The model provider quota is exhausted.",
    FailureCode.MODEL_REQUEST_INVALID: "The model provider rejected this structured request.",
    FailureCode.MODEL_RESPONSE_INVALID: "The model provider returned an unusable response.",
    FailureCode.MODEL_USAGE_MISSING: "The provider response omitted required usage metadata.",
    FailureCode.SCHEMA_INVALID: "The model response did not pass the required result schema.",
    FailureCode.REFUSAL: "The model declined to produce a result explanation.",
    FailureCode.CONTENT_FILTERED: "The model provider filtered the result explanation.",
    FailureCode.EVIDENCE_ID_UNKNOWN: "The model cited evidence outside the approved result slices.",
    FailureCode.ACTION_NOT_ALLOWED: "The model response crossed an allowed-action boundary.",
    FailureCode.PROMPT_DISCLOSURE_BLOCKED: (
        "The model response was blocked because it resembled protected instructions or "
        "contained unsafe disclosure content."
    ),
}

RESULT_INTERPRETATION_PRIVATE_INPUT_CODES = frozenset(
    {
        "PRIVATE_KEY_MATERIAL",
        "API_KEY_OR_TOKEN",
        "PASSWORD_VALUE",
        "URL_EMBEDDED_CREDENTIAL",
        "EMAIL_ADDRESS",
        "US_SOCIAL_SECURITY_NUMBER",
        "PHONE_NUMBER",
        "PAYMENT_CARD_NUMBER",
    }
)


def _modelGatewayStatusCode(error: ModelGatewayError) -> int:
    if error.code == FailureCode.MODEL_TIMEOUT:
        return 504
    if error.code in {FailureCode.MODEL_TRANSPORT_ERROR, FailureCode.MODEL_OVERLOADED}:
        return 503
    if error.code == FailureCode.MODEL_RATE_LIMITED:
        return 429
    if error.code in {
        FailureCode.MODEL_AUTHENTICATION_ERROR,
        FailureCode.MODEL_PERMISSION_ERROR,
        FailureCode.MODEL_QUOTA_EXHAUSTED,
        FailureCode.MODEL_REQUEST_INVALID,
    }:
        return 422
    return 502


def _modelGatewayApiError(error: ModelGatewayError) -> ApiError:
    return ApiError(
        error.code.value,
        _modelGatewayStatusCode(error),
        MODEL_ERROR_PUBLIC_MESSAGES.get(
            error.code,
            "The model response could not be used safely.",
        ),
        details={
            "retryable": error.retryable,
            "providerAttempts": max(0, error.attempts),
            "uncertainBillableAttempts": max(0, error.uncertainBillableAttempts),
            "repairUsed": error.repairUsed,
        },
    )


def _sseFrame(event: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"event: {event}\ndata: {serialized}\n\n"


def _appendResultInterpretationAuditSafely(
    database: Database,
    *,
    ownerUserId: str,
    experimentId: str,
    action: str,
    metadata: dict[str, Any],
    traceId: str | None,
) -> bool:
    """尽力写入解释审计，但绝不因审计存储故障丢弃已计费的模型终态。"""

    try:
        database.appendAuditEvent(
            ownerUserId,
            "RESULT_INTERPRETATION",
            experimentId,
            action,
            metadata,
        )
    except Exception as error:
        # 不能记录异常正文：数据库驱动或意外上游异常可能包含路径、SQL 或凭据。
        LOGGER.error(
            "Result interpretation audit write failed: traceId=%s action=%s errorType=%s",
            traceId or "unavailable",
            action,
            type(error).__name__,
        )
        return False
    return True


def _safeResultInterpretationErrorDetails(error: ApiError) -> dict[str, object]:
    """仅公开结果解释协议定义过的标量错误字段。"""

    details: dict[str, object] = {}
    for fieldName in ("retryable", "repairUsed"):
        value = error.details.get(fieldName)
        if isinstance(value, bool):
            details[fieldName] = value
    for fieldName in ("providerAttempts", "uncertainBillableAttempts"):
        value = error.details.get(fieldName)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            details[fieldName] = value
    return details


def _validateResultInterpretationPrivateInput(
    interpretationRequest: ResultInterpretationChatRequest,
) -> None:
    """在任何外部模型调用前阻断凭据和个人身份信息。"""

    for message in interpretationRequest.messages:
        findingCodes = {
            finding.code
            for finding in scanTextContent(
                message.content,
                field="resultInterpretationMessage",
            ).findings
        }
        if findingCodes & RESULT_INTERPRETATION_PRIVATE_INPUT_CODES:
            raise ApiError(
                "RESULT_INTERPRETATION_PRIVATE_INPUT",
                422,
                (
                    "Remove API keys, credentials, and personally identifying information "
                    "before asking the model."
                ),
                details={"retryable": False},
            )


def createApp(dataDir: Path | None = None, frontendDist: Path | None = None) -> FastAPI:
    settings = loadSettings(dataDir)
    rateLimiter = SlidingWindowRateLimiter()
    runtimeMetrics = RuntimeMetrics()
    resultInterpretationSingleFlight = ResultInterpretationSingleFlight()

    @asynccontextmanager
    async def lifespan(appInstance: FastAPI):
        database = Database(settings.databasePath)
        database.initialize()
        guidedWorkflowRepository = GuidedWorkflowRepository(database)
        guidedWorkflowRepository.initialize()
        factoryRepository = EventPackFactoryRepository(settings.databasePath)
        factoryRepository.initialize()
        factorySearchClient = ZhipuWebSearchClient()
        factoryReaderClient = ZhipuReaderClient()
        factoryService = EventPackFactoryService(
            factoryRepository,
            factorySearchClient,
            factoryReaderClient,
        )
        authRepository: AuthRepository | None = None
        authService: AuthService | None = None
        if settings.authenticationRequired:
            missingSettings = [
                name
                for name, value in (
                    ("EVENTSHOCK_AUTH_SECRET(_FILE)", settings.authSecret),
                    ("EVENTSHOCK_ADMIN_EMAIL", settings.adminEmail),
                    ("EVENTSHOCK_SMTP_HOST", settings.smtpHost),
                    ("EVENTSHOCK_SMTP_USERNAME", settings.smtpUsername),
                    ("EVENTSHOCK_SMTP_PASSWORD(_FILE)", settings.smtpPassword),
                    ("EVENTSHOCK_SMTP_SENDER", settings.smtpSender),
                )
                if not value
            ]
            if missingSettings:
                raise RuntimeError(
                    "authentication is enabled but required settings are missing: "
                    + ", ".join(missingSettings)
                )
            authRepository = AuthRepository(database)
            authRepository.initialize()
            try:
                configuredAdminEmail = normalizeEmail(settings.adminEmail or "")
            except ValueError as error:
                raise RuntimeError("EVENTSHOCK_ADMIN_EMAIL is invalid") from error
            mailer = SmtpVerificationMailer(
                host=settings.smtpHost or "",
                port=settings.smtpPort,
                username=settings.smtpUsername or "",
                password=settings.smtpPassword or "",
                sender=settings.smtpSender or "",
            )
            authService = AuthService(
                repository=authRepository,
                mailer=mailer,
                authSecret=settings.authSecret or "",
            )
        # 部署时必须先由一次性管理员引导认领旧数据；认领前绝不执行保留期清理。
        if not any(database.countUnownedRecords().values()):
            database.enforceRetention()
        cognitionService = CognitionService()
        eventPackService = EventPackService(
            database,
            settings.projectRoot,
            cognitionService,
        )
        scenarioService = ScenarioService(database, eventPackService)
        guidedWorkflowService = GuidedWorkflowService(
            guidedWorkflowRepository,
            GuidedArtifactValidator(
                database=database,
                factory=factoryService,
                eventPacks=eventPackService,
                scenarios=scenarioService,
            ),
        )
        experimentService = ExperimentService(database, eventPackService, cognitionService)
        studyService = StudyApiService(database)
        appInstance.state.database = database
        appInstance.state.authRepository = authRepository
        appInstance.state.authService = authService
        appInstance.state.configuredAdminEmail = (
            configuredAdminEmail if settings.authenticationRequired else None
        )
        appInstance.state.eventPackService = eventPackService
        appInstance.state.cognitionService = cognitionService
        appInstance.state.scenarioService = scenarioService
        appInstance.state.experimentService = experimentService
        appInstance.state.studyService = studyService
        appInstance.state.guidedWorkflowService = guidedWorkflowService
        appInstance.state.eventPackFactoryService = factoryService
        appInstance.state.resultInterpretationSingleFlight = resultInterpretationSingleFlight

        async def purgeExpiredCredentials() -> None:
            while True:
                await asyncio.sleep(60)
                cognitionService.purgeExpiredCredentials()
                await resultInterpretationSingleFlight.purgeExpired()

        credentialPurgeTask = asyncio.create_task(
            purgeExpiredCredentials(),
            name="purge-expired-llm-credentials",
        )
        try:
            yield
        finally:
            credentialPurgeTask.cancel()
            with suppress(asyncio.CancelledError):
                await credentialPurgeTask
            cognitionService.purgeExpiredCredentials()
            await resultInterpretationSingleFlight.purgeExpired()
            await factorySearchClient.aclose()
            await factoryReaderClient.aclose()
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
        request.state.authContext = None
        if settings.authenticationRequired and _authenticationProtected(request):
            authService: AuthService = request.app.state.authService
            rawToken = request.cookies.get(AUTH_COOKIE_NAME, "")
            requireCsrf = request.method.upper() not in SAFE_HTTP_METHODS
            try:
                if requireCsrf:
                    _validateSameOrigin(request)
                request.state.authContext = authService.authenticate(
                    token=rawToken,
                    csrfToken=request.headers.get("X-CSRF-Token"),
                    requireCsrf=requireCsrf,
                )
            except CsrfValidationError as error:
                response = _authenticationErrorResponse(
                    request,
                    code="CSRF_VALIDATION_FAILED",
                    message=str(error),
                    statusCode=403,
                )
                runtimeMetrics.record(
                    durationMs=(time.perf_counter() - requestStartedAt) * 1_000,
                    statusCode=response.status_code,
                )
                return response
            except AuthenticationError as error:
                response = _authenticationErrorResponse(
                    request,
                    code="AUTHENTICATION_REQUIRED",
                    message=str(error),
                    statusCode=401,
                )
                response.delete_cookie(
                    AUTH_COOKIE_NAME,
                    path="/",
                    secure=settings.authCookieSecure,
                    httponly=True,
                    samesite="lax",
                )
                runtimeMetrics.record(
                    durationMs=(time.perf_counter() - requestStartedAt) * 1_000,
                    statusCode=response.status_code,
                )
                return response
            except AuthorizationError as error:
                response = _authenticationErrorResponse(
                    request,
                    code="ORIGIN_VALIDATION_FAILED",
                    message=str(error),
                    statusCode=403,
                )
                runtimeMetrics.record(
                    durationMs=(time.perf_counter() - requestStartedAt) * 1_000,
                    statusCode=response.status_code,
                )
                return response
            if _legalAcceptanceProtected(request):
                legalStatus = authService.legalAcceptanceStatus(request.state.authContext.userId)
                if legalStatus.required:
                    response = _authenticationErrorResponse(
                        request,
                        code="LEGAL_ACCEPTANCE_REQUIRED",
                        message=(
                            "The current Terms of Use and Privacy Notice must be accepted "
                            "before the authenticated workspace can be used."
                        ),
                        statusCode=428,
                    )
                    runtimeMetrics.record(
                        durationMs=(time.perf_counter() - requestStartedAt) * 1_000,
                        statusCode=response.status_code,
                    )
                    return response

        # 生产保护路由必须先完成认证和 CSRF 校验。否则匿名请求可以提前消耗
        # 付费写接口的共享额度，并让同一校园 NAT 下的真实用户被拒绝。
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

    def requireOwner(
        request: Request,
        legacySessionId: Annotated[str | None, Header(alias="X-Session-ID")] = None,
    ) -> str:
        if settings.authenticationRequired:
            return _authContext(request).userId
        if legacySessionId is None:
            raise ApiError("SESSION_ID_REQUIRED", 422, "X-Session-ID is required.")
        return _sessionId(legacySessionId)

    def optionalOwner(
        request: Request,
        legacySessionId: Annotated[str | None, Header(alias="X-Session-ID")] = None,
    ) -> str | None:
        if settings.authenticationRequired:
            return _authContext(request).userId
        return _optionalSessionId(legacySessionId)

    def credentialSessionId(request: Request, ownerUserId: str) -> str:
        context = getattr(request.state, "authContext", None)
        return context.authSessionId if isinstance(context, AuthContext) else ownerUserId

    @appInstance.exception_handler(ApiError)
    async def apiErrorHandler(request: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.statusCode,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "traceId": getattr(request.state, "traceId", None),
                    **error.details,
                }
            },
        )

    @appInstance.exception_handler(EventPackFactoryError)
    async def eventPackFactoryErrorHandler(
        request: Request,
        error: EventPackFactoryError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.statusCode,
            content={
                "error": {
                    "code": error.code.value,
                    "message": error.message,
                    "traceId": getattr(request.state, "traceId", None),
                    **error.details,
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

    @appInstance.exception_handler(AuthenticationError)
    async def authenticationErrorHandler(
        request: Request, error: AuthenticationError
    ) -> JSONResponse:
        return _authenticationErrorResponse(
            request,
            code="AUTHENTICATION_FAILED",
            message=str(error),
            statusCode=401,
        )

    @appInstance.exception_handler(CsrfValidationError)
    async def csrfValidationErrorHandler(
        request: Request, error: CsrfValidationError
    ) -> JSONResponse:
        return _authenticationErrorResponse(
            request,
            code="CSRF_VALIDATION_FAILED",
            message=str(error),
            statusCode=403,
        )

    @appInstance.exception_handler(AuthorizationError)
    async def authorizationErrorHandler(
        request: Request, error: AuthorizationError
    ) -> JSONResponse:
        return _authenticationErrorResponse(
            request,
            code="ADMIN_ACCESS_REQUIRED",
            message=str(error),
            statusCode=403,
        )

    @appInstance.exception_handler(ChallengeCooldownError)
    async def challengeCooldownHandler(
        request: Request, error: ChallengeCooldownError
    ) -> JSONResponse:
        response = _authenticationErrorResponse(
            request,
            code="VERIFICATION_CODE_COOLDOWN",
            message="Wait before requesting another verification code.",
            statusCode=429,
        )
        response.headers["Retry-After"] = str(error.retryAfterSeconds)
        return response

    @appInstance.exception_handler(ChallengeVerificationError)
    async def challengeVerificationHandler(
        request: Request, error: ChallengeVerificationError
    ) -> JSONResponse:
        return _authenticationErrorResponse(
            request,
            code="VERIFICATION_CODE_INVALID",
            message=str(error),
            statusCode=400,
        )

    @appInstance.exception_handler(DuplicateUserError)
    async def duplicateUserHandler(request: Request, error: DuplicateUserError) -> JSONResponse:
        return _authenticationErrorResponse(
            request,
            code="ACCOUNT_ALREADY_EXISTS",
            message=str(error),
            statusCode=409,
        )

    @appInstance.exception_handler(PasswordPolicyError)
    async def passwordPolicyHandler(request: Request, error: PasswordPolicyError) -> JSONResponse:
        return _authenticationErrorResponse(
            request,
            code="PASSWORD_POLICY_FAILED",
            message=str(error),
            statusCode=422,
        )

    @appInstance.exception_handler(MailDeliveryError)
    async def mailDeliveryHandler(request: Request, _error: MailDeliveryError) -> JSONResponse:
        return _authenticationErrorResponse(
            request,
            code="VERIFICATION_EMAIL_UNAVAILABLE",
            message="The verification email could not be delivered. Try again later.",
            statusCode=503,
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

    @appInstance.get("/api/v1/legal/terms")
    async def getCurrentLegalTerms(
        language: Annotated[Literal["en", "zh-CN"], Query()] = "en",
    ) -> dict[str, Any]:
        return publicLegalPayload(language)

    @appInstance.get("/api/v1/auth/session")
    async def getAuthSession(request: Request) -> Response:
        if not settings.authenticationRequired:
            return JSONResponse(
                {
                    "authenticationRequired": False,
                    "authenticated": True,
                    "user": {
                        "id": "development-user",
                        "email": "development@local.invalid",
                        "role": "ADMIN",
                        "emailVerified": True,
                        "createdAt": "",
                        "lastLoginAt": None,
                    },
                }
            )
        rawToken = request.cookies.get(AUTH_COOKIE_NAME, "")
        authService: AuthService = request.app.state.authService
        authRepository: AuthRepository = request.app.state.authRepository
        try:
            context = authService.authenticate(token=rawToken)
        except AuthenticationError:
            response = JSONResponse({"authenticationRequired": True, "authenticated": False})
            if rawToken:
                response.delete_cookie(
                    AUTH_COOKIE_NAME,
                    path="/",
                    secure=settings.authCookieSecure,
                    httponly=True,
                    samesite="lax",
                )
            return response
        user = authRepository.getUserById(context.userId)
        if user is None:
            raise AuthenticationError("authenticated account no longer exists")
        return JSONResponse(
            _authSessionPayload(
                user,
                csrfToken=authService.csrfToken(rawToken),
                authService=authService,
            )
        )

    @appInstance.post("/api/v1/auth/login")
    async def loginAccount(login: AuthLoginRequest, request: Request) -> Response:
        authService = _requiredAuthService(request)
        try:
            issued = authService.login(email=login.email, password=login.password)
        except ValueError as error:
            raise ApiError("INVALID_EMAIL", 422, str(error)) from error
        response = JSONResponse(
            _authSessionPayload(
                issued.user,
                csrfToken=issued.csrfToken,
                authService=authService,
            )
        )
        _setAuthCookie(response, issued.token, settings.authCookieSecure)
        return response

    @appInstance.post("/api/v1/auth/verification-code", status_code=202)
    async def requestVerificationCode(
        payload: VerificationCodeRequest,
        request: Request,
    ) -> dict[str, Any]:
        authService = _requiredAuthService(request)
        try:
            if payload.purpose is ChallengePurpose.REGISTER:
                dispatch = await authService.requestRegistrationCode(
                    email=payload.email,
                    locale=payload.language,
                )
            else:
                dispatch = await authService.requestPasswordResetCode(
                    email=payload.email,
                    locale=payload.language,
                )
        except ValueError as error:
            raise ApiError("INVALID_EMAIL", 422, str(error)) from error
        now = datetime.now(UTC)
        return {
            "accepted": True,
            "retryAfterSeconds": max(1, int((dispatch.resendAfter - now).total_seconds())),
            "expiresInSeconds": max(1, int((dispatch.expiresAt - now).total_seconds())),
        }

    @appInstance.post("/api/v1/auth/register", status_code=201)
    async def registerAccount(payload: AuthRegistrationRequest, request: Request) -> Response:
        authService = _requiredAuthService(request)
        try:
            await authService.registerWithLatestChallenge(
                email=payload.email,
                code=payload.verificationCode,
                password=payload.password,
                legalVersion=payload.version,
                legalDocumentHash=payload.documentHash,
                legalLocale=payload.language,
                acceptedTerms=payload.acceptedTerms,
                acknowledgedPrivacy=payload.acknowledgedPrivacy,
                confirmedMinimumAge=payload.confirmedMinimumAge,
                acknowledgedAiBoundary=payload.acknowledgedAiBoundary,
            )
            issued = authService.login(email=payload.email, password=payload.password)
        except ValueError as error:
            code = (
                "LEGAL_DOCUMENT_VERSION_STALE"
                if "version changed" in str(error)
                else "INVALID_ACCOUNT_INPUT"
            )
            raise ApiError(
                code,
                409 if code == "LEGAL_DOCUMENT_VERSION_STALE" else 422,
                str(error),
            ) from error
        response = JSONResponse(
            _authSessionPayload(
                issued.user,
                csrfToken=issued.csrfToken,
                authService=authService,
            ),
            status_code=201,
        )
        _setAuthCookie(response, issued.token, settings.authCookieSecure)
        return response

    @appInstance.post("/api/v1/auth/password-reset")
    async def resetAccountPassword(
        payload: AuthPasswordResetRequest,
        request: Request,
    ) -> dict[str, bool]:
        authService = _requiredAuthService(request)
        try:
            await authService.resetPasswordWithLatestChallenge(
                email=payload.email,
                code=payload.verificationCode,
                newPassword=payload.password,
            )
        except ValueError as error:
            raise ApiError("INVALID_ACCOUNT_INPUT", 422, str(error)) from error
        return {"ok": True}

    @appInstance.post("/api/v1/auth/legal-acceptance")
    async def acceptCurrentLegalTerms(
        payload: LegalConsentRequest,
        request: Request,
    ) -> dict[str, Any]:
        authService = _requiredAuthService(request)
        context = _authContext(request)
        try:
            status = authService.acceptCurrentLegalDocuments(
                context,
                version=payload.version,
                documentHash=payload.documentHash,
                locale=payload.language,
                acceptedTerms=payload.acceptedTerms,
                acknowledgedPrivacy=payload.acknowledgedPrivacy,
                confirmedMinimumAge=payload.confirmedMinimumAge,
                acknowledgedAiBoundary=payload.acknowledgedAiBoundary,
            )
        except ValueError as error:
            code = (
                "LEGAL_DOCUMENT_VERSION_STALE"
                if "version changed" in str(error)
                else "INVALID_LEGAL_ACCEPTANCE"
            )
            raise ApiError(
                code,
                409 if code == "LEGAL_DOCUMENT_VERSION_STALE" else 422,
                str(error),
            ) from error
        return status.model_dump(mode="json")

    @appInstance.get("/api/v1/auth/preferences")
    async def getCurrentUserPreferences(request: Request) -> dict[str, Any]:
        authService = _requiredAuthService(request)
        preferences = authService.getUserPreferences(_authContext(request))
        return preferences.model_dump(mode="json")

    @appInstance.put("/api/v1/auth/preferences")
    async def saveCurrentUserPreferences(
        payload: UserPreferencesRequest,
        request: Request,
    ) -> dict[str, Any]:
        authService = _requiredAuthService(request)
        preferences = authService.saveUserPreferences(
            _authContext(request),
            experienceLevel=payload.experienceLevel,
            workspaceMode=payload.workspaceMode,
            assistancePreference=payload.assistancePreference,
            firstGoal=payload.firstGoal,
        )
        return preferences.model_dump(mode="json")

    @appInstance.get("/api/v1/guided-workflows")
    async def listGuidedWorkflows(
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: GuidedWorkflowService = request.app.state.guidedWorkflowService
        ownerUserId = _sessionId(sessionId)
        return {
            "items": [workflow.model_dump(mode="json") for workflow in service.list(ownerUserId)]
        }

    @appInstance.post("/api/v1/guided-workflows", status_code=201)
    async def createGuidedWorkflow(
        payload: GuidedCreateRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: GuidedWorkflowService = request.app.state.guidedWorkflowService
        ownerUserId = _sessionId(sessionId)
        workflow = service.create(ownerUserId, payload.language)
        database: Database = request.app.state.database
        database.appendAuditEvent(
            ownerUserId,
            "GUIDED_WORKFLOW",
            workflow.id,
            "CREATED",
            {"language": payload.language, "stage": workflow.stage.value},
        )
        return workflow.model_dump(mode="json")

    @appInstance.get("/api/v1/guided-workflows/{workflowId}")
    async def getGuidedWorkflow(
        workflowId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: GuidedWorkflowService = request.app.state.guidedWorkflowService
        try:
            workflow = service.get(workflowId, _sessionId(sessionId))
        except LookupError as error:
            raise ApiError(
                "GUIDED_WORKFLOW_NOT_FOUND",
                404,
                "The guided workflow does not exist.",
            ) from error
        return workflow.model_dump(mode="json")

    @appInstance.post("/api/v1/guided-workflows/{workflowId}/turn")
    async def createGuidedWorkflowTurn(
        workflowId: str,
        payload: GuidedTurnRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        credentialId = credentialSessionId(request, ownerUserId)
        service: GuidedWorkflowService = request.app.state.guidedWorkflowService
        cognition: CognitionService = request.app.state.cognitionService
        try:
            # 必须先于任何凭据查找或供应商调用执行，避免恶意文本进入模型边界。
            earlyScan = scanTextContent(payload.message, field="guidedWorkflowMessage")
            if earlyScan.decision is not ContentPolicyDecision.ALLOW:
                raise ValueError(
                    "guided workflow messages must not contain secrets, personal data, "
                    "executable content, or prompt-injection instructions"
                )
            claim = service.claimTurn(
                workflowId=workflowId,
                ownerUserId=ownerUserId,
                request=payload,
            )
            if claim.replayed:
                return claim.workflow.model_dump(mode="json")
            try:
                if cognition.getConfig(credentialId).configured:
                    proposal = await cognition.proposeGuidedWorkflow(
                        sessionId=credentialId,
                        workflow=claim.workflow,
                        latestUserMessage=payload.message,
                        language=payload.language,
                    )
                else:
                    proposal = service.deterministicProposal(
                        workflow=claim.workflow,
                        language=payload.language,
                    )
                updated = service.completeTurn(
                    workflowId=workflowId,
                    ownerUserId=ownerUserId,
                    request=payload,
                    claim=claim,
                    proposal=proposal,
                    recordAudit=True,
                )
            except Exception as error:
                # 模型是否已计费可能无法确定，因此保留 UNKNOWN operation，
                # 后续相同或替换 clientRequestId 都不得自动再次调用供应商。
                service.markTurnUnknown(
                    workflowId=workflowId,
                    ownerUserId=ownerUserId,
                    request=payload,
                    claim=claim,
                    errorCode=type(error).__name__,
                )
                raise
        except LookupError as error:
            raise ApiError(
                "GUIDED_WORKFLOW_NOT_FOUND",
                404,
                "The guided workflow does not exist.",
            ) from error
        except GuidedWorkflowConflictError as error:
            raise ApiError("GUIDED_WORKFLOW_CONFLICT", 409, str(error)) from error
        except CredentialNotConfiguredError as error:
            raise ApiError(
                "LLM_CREDENTIAL_NOT_CONFIGURED",
                409,
                "The temporary model credential expired; configure it again.",
            ) from error
        except ModelGatewayError as error:
            raise _modelGatewayApiError(error) from error
        except ValueError as error:
            raise ApiError("INVALID_GUIDED_WORKFLOW_TURN", 422, str(error)) from error
        return updated.model_dump(mode="json")

    @appInstance.post("/api/v1/guided-workflows/{workflowId}/apply")
    async def applyGuidedWorkflowProposal(
        workflowId: str,
        payload: GuidedProposalActionRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        service: GuidedWorkflowService = request.app.state.guidedWorkflowService
        try:
            workflow = service.applyProposal(workflowId, ownerUserId, payload)
        except LookupError as error:
            raise ApiError(
                "GUIDED_WORKFLOW_NOT_FOUND",
                404,
                "The guided workflow does not exist.",
            ) from error
        except GuidedWorkflowConflictError as error:
            raise ApiError("GUIDED_WORKFLOW_CONFLICT", 409, str(error)) from error
        request.app.state.database.appendAuditEvent(
            ownerUserId,
            "GUIDED_WORKFLOW",
            workflowId,
            "PROPOSAL_APPLIED_BY_HUMAN",
            {"stage": workflow.stage.value, "proposalId": payload.proposalId},
        )
        return workflow.model_dump(mode="json")

    @appInstance.post("/api/v1/guided-workflows/{workflowId}/advance")
    async def advanceGuidedWorkflow(
        workflowId: str,
        payload: GuidedAdvanceRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        service: GuidedWorkflowService = request.app.state.guidedWorkflowService
        try:
            workflow = service.advance(
                workflowId,
                ownerUserId,
                payload,
                credentialSessionId=credentialSessionId(request, ownerUserId),
            )
        except LookupError as error:
            raise ApiError(
                "GUIDED_WORKFLOW_NOT_FOUND",
                404,
                "The guided workflow does not exist.",
            ) from error
        except GuidedWorkflowConflictError as error:
            raise ApiError("GUIDED_WORKFLOW_CONFLICT", 409, str(error)) from error
        except ValueError as error:
            raise ApiError("GUIDED_WORKFLOW_STAGE_INCOMPLETE", 422, str(error)) from error
        request.app.state.database.appendAuditEvent(
            ownerUserId,
            "GUIDED_WORKFLOW",
            workflowId,
            "ADVANCED_BY_HUMAN",
            {"stage": workflow.stage.value},
        )
        return workflow.model_dump(mode="json")

    @appInstance.patch("/api/v1/guided-workflows/{workflowId}/links")
    async def linkGuidedWorkflowArtifacts(
        workflowId: str,
        payload: GuidedLinkRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        service: GuidedWorkflowService = request.app.state.guidedWorkflowService
        try:
            workflow = service.linkArtifacts(workflowId, ownerUserId, payload)
        except LookupError as error:
            raise ApiError(
                "GUIDED_WORKFLOW_NOT_FOUND",
                404,
                "The guided workflow does not exist.",
            ) from error
        except GuidedWorkflowConflictError as error:
            raise ApiError("GUIDED_WORKFLOW_CONFLICT", 409, str(error)) from error
        except ValueError as error:
            raise ApiError("GUIDED_ARTIFACT_INVALID", 422, str(error)) from error
        request.app.state.database.appendAuditEvent(
            ownerUserId,
            "GUIDED_WORKFLOW",
            workflowId,
            "ARTIFACT_LINKED_BY_HUMAN",
            {
                "eventPackBuildId": payload.eventPackBuildId,
                "eventPackId": payload.eventPackId,
                "scenarioId": payload.scenarioId,
            },
        )
        return workflow.model_dump(mode="json")

    @appInstance.post("/api/v1/auth/logout")
    async def logoutAccount(request: Request) -> Response:
        authService = _requiredAuthService(request)
        context = _authContext(request)
        cognition: CognitionService = request.app.state.cognitionService
        cognition.clearConfig(context.authSessionId)
        singleFlight: ResultInterpretationSingleFlight = (
            request.app.state.resultInterpretationSingleFlight
        )
        await singleFlight.clearPrincipal(context.authSessionId)
        await singleFlight.clearPrincipal(context.userId)
        authService.logout(token=request.cookies.get(AUTH_COOKIE_NAME, ""))
        response = Response(status_code=204)
        response.delete_cookie(
            AUTH_COOKIE_NAME,
            path="/",
            secure=settings.authCookieSecure,
            httponly=True,
            samesite="lax",
        )
        return response

    @appInstance.get("/api/v1/admin/users")
    async def listAdminUsers(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        authService = _requiredAuthService(request)
        context = _authContext(request)
        items = authService.listUsers(context, limit=limit, offset=offset)
        summary = authService.userStatistics(context)
        return {
            "items": [_adminUserPayload(item) for item in items],
            "total": summary["totalUsers"],
            "summary": summary,
        }

    @appInstance.get("/api/v1/admin/activity")
    async def listAdminActivity(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        userId: Annotated[str | None, Query(min_length=6, max_length=128)] = None,
    ) -> dict[str, Any]:
        authService = _requiredAuthService(request)
        context = _authContext(request)
        items = authService.listActivity(
            context,
            userId=userId,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [
                {
                    "id": item.id,
                    "userId": item.userId or "system",
                    "userEmail": item.userEmail,
                    "action": item.action,
                    "entityType": item.entityType,
                    "entityId": item.entityId,
                    "outcome": "FAILED" if item.status == "FAILED" else "SUCCEEDED",
                    "createdAt": item.createdAt.isoformat(),
                }
                for item in items
            ],
            "total": authService.countActivity(context, userId=userId),
        }

    @appInstance.patch("/api/v1/admin/users/{userId}")
    async def updateAdminUserStatus(
        userId: str,
        payload: UserStatusRequest,
        request: Request,
    ) -> dict[str, Any]:
        authService = _requiredAuthService(request)
        context = _authContext(request)
        try:
            user = authService.setUserStatus(context, userId=userId, status=payload.status)
        except LookupError as error:
            raise ApiError("ACCOUNT_NOT_FOUND", 404, str(error)) from error
        return _publicUserPayload(user)

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
        sessionId: str | None = Depends(optionalOwner),
    ) -> dict[str, Any]:
        service: EventPackService = request.app.state.eventPackService
        return {"items": service.listCases(_optionalSessionId(sessionId))}

    @appInstance.get("/api/v1/event-pack-factory/search-engines")
    async def getEventPackFactorySearchEngines() -> dict[str, Any]:
        return {
            "items": [
                descriptor.model_dump(mode="json") for descriptor in SEARCH_ENGINE_CATALOG.values()
            ],
            "reader": READER_CAPABILITY.model_dump(mode="json"),
        }

    @appInstance.get("/api/v1/event-pack-factory/builds")
    async def listEventPackFactoryBuilds(
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        return {
            "items": [
                item.model_dump(mode="json")
                for item in factory.listBuilds(ownerUserId=_sessionId(sessionId))
            ]
        }

    @appInstance.post("/api/v1/event-pack-factory/builds", status_code=201)
    async def createEventPackFactoryBuild(
        payload: FactoryBuildCreateRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        build = factory.createBuild(ownerUserId=ownerUserId, title=payload.title)
        database: Database = request.app.state.database
        database.appendAuditEvent(
            ownerUserId,
            "EVENT_PACK_FACTORY",
            build.id,
            "BUILD_CREATED",
            {"revision": build.revision},
        )
        return build.model_dump(mode="json")

    @appInstance.get("/api/v1/event-pack-factory/builds/{buildId}")
    async def getEventPackFactoryBuild(
        buildId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        snapshot = factory.getBuild(
            ownerUserId=_sessionId(sessionId),
            buildId=buildId,
        )
        return snapshot.model_dump(mode="json")

    @appInstance.delete("/api/v1/event-pack-factory/builds/{buildId}", status_code=204)
    async def deleteEventPackFactoryBuild(
        buildId: str,
        payload: FactoryDeleteBuildRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> Response:
        ownerUserId = _sessionId(sessionId)
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        checkpointSucceeded = factory.deleteBuild(
            ownerUserId=ownerUserId,
            buildId=buildId,
            expectedRevision=payload.expectedRevision,
        )
        database: Database = request.app.state.database
        database.appendAuditEvent(
            ownerUserId,
            "EVENT_PACK_FACTORY",
            buildId,
            "BUILD_DELETED",
            {
                "deletedRawSourcePayloads": True,
                "walCheckpointAttempted": True,
                "walCheckpointSucceeded": checkpointSucceeded,
            },
        )
        return Response(status_code=204)

    @appInstance.post(
        "/api/v1/event-pack-factory/builds/{buildId}/paste",
        status_code=201,
    )
    async def addEventPackFactoryPasteSource(
        buildId: str,
        payload: FactoryPasteMutationRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        result = factory.addPasteSource(
            ownerUserId=ownerUserId,
            buildId=buildId,
            expectedRevision=payload.expectedRevision,
            sourceInput=payload.source.toDomainInput(),
        )
        request.app.state.database.appendAuditEvent(
            ownerUserId,
            "EVENT_PACK_FACTORY",
            buildId,
            "PASTE_SOURCE_ADDED",
            {
                "revision": result.build.revision,
                "sourceIds": [source.id for source in result.sources],
                "contentLengths": [source.contentLength for source in result.sources],
            },
        )
        return result.model_dump(mode="json")

    @appInstance.get("/api/v1/event-pack-factory/builds/{buildId}/sources/{sourceId}/raw-text")
    async def getEventPackFactorySourceRawText(
        buildId: str,
        sourceId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> JSONResponse:
        ownerUserId = _sessionId(sessionId)
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        result = factory.getSourceRawText(
            ownerUserId=ownerUserId,
            buildId=buildId,
            sourceId=sourceId,
        )
        request.app.state.database.appendAuditEvent(
            ownerUserId,
            "EVENT_PACK_FACTORY",
            buildId,
            "SOURCE_RAW_TEXT_VIEWED",
            {
                "revision": result.revision,
                "sourceId": sourceId,
                "contentHash": result.contentHash,
                "contentLength": result.contentLength,
            },
        )
        return JSONResponse(
            content=result.model_dump(mode="json"),
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )

    @appInstance.put("/api/v1/event-pack-factory/builds/{buildId}/sources/{sourceId}/raw-text")
    async def updateEventPackFactorySourceRawText(
        buildId: str,
        sourceId: str,
        payload: FactorySourceRawTextUpdateRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> JSONResponse:
        ownerUserId = _sessionId(sessionId)
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        previous = factory.getSourceRawText(
            ownerUserId=ownerUserId,
            buildId=buildId,
            sourceId=sourceId,
        )
        result = factory.updateSourceRawText(
            ownerUserId=ownerUserId,
            buildId=buildId,
            sourceId=sourceId,
            expectedRevision=payload.expectedRevision,
            rawText=payload.revealedRawText(),
            reviewSummary=payload.reviewSummary,
            verifiedEvidenceQuotes=payload.verifiedEvidenceQuotes,
        )
        revised = result.sources[0]
        request.app.state.database.appendAuditEvent(
            ownerUserId,
            "EVENT_PACK_FACTORY",
            buildId,
            "SOURCE_RAW_TEXT_EDITED",
            {
                "previousRevision": previous.revision,
                "revision": result.build.revision,
                "sourceId": sourceId,
                "previousContentHash": previous.contentHash,
                "contentHash": revised.contentHash,
                "previousContentLength": previous.contentLength,
                "contentLength": revised.contentLength,
                "securityDecision": revised.securityDecision.value,
                "reviewReset": True,
            },
        )
        return JSONResponse(
            content=result.model_dump(mode="json"),
            headers={
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )

    @appInstance.post("/api/v1/event-pack-factory/builds/{buildId}/search")
    async def searchEventPackFactorySources(
        buildId: str,
        payload: FactorySearchMutationRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        credentialId = credentialSessionId(request, ownerUserId)
        cognition: CognitionService = request.app.state.cognitionService
        try:
            apiKey = cognition.requireTemporaryApiKey(credentialId, provider="zhipu")
        except CredentialNotConfiguredError as error:
            raise ApiError(
                "ZHIPU_TEMPORARY_CREDENTIAL_REQUIRED",
                409,
                "Configure a temporary Zhipu API key before using Web Search.",
            ) from error
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        result = await factory.searchSources(
            ownerUserId=ownerUserId,
            buildId=buildId,
            expectedRevision=payload.expectedRevision,
            request=payload.request,
            apiKey=apiKey,
            clientRequestId=payload.clientRequestId,
        )
        if not result.idempotencyReplayed:
            request.app.state.database.appendAuditEvent(
                ownerUserId,
                "EVENT_PACK_FACTORY",
                buildId,
                "WEB_SEARCH_COMPLETED",
                {
                    "revision": result.build.revision,
                    "engine": payload.request.engine.value,
                    "queryHash": hashlib.sha256(payload.request.query.encode()).hexdigest(),
                    "resultCount": len(result.sources),
                    "estimatedCostCny": (
                        result.searchRun.estimatedCostCny if result.searchRun else None
                    ),
                },
            )
        return result.model_dump(mode="json")

    @appInstance.post(
        "/api/v1/event-pack-factory/builds/{buildId}/reader",
        status_code=201,
    )
    async def readEventPackFactorySource(
        buildId: str,
        payload: FactoryReaderMutationRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        credentialId = credentialSessionId(request, ownerUserId)
        cognition: CognitionService = request.app.state.cognitionService
        try:
            apiKey = cognition.requireTemporaryApiKey(credentialId, provider="zhipu")
        except CredentialNotConfiguredError as error:
            raise ApiError(
                "ZHIPU_TEMPORARY_CREDENTIAL_REQUIRED",
                409,
                "Configure a temporary Zhipu API key before using Reader.",
            ) from error
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        result = await factory.fetchReaderSource(
            ownerUserId=ownerUserId,
            buildId=buildId,
            expectedRevision=payload.expectedRevision,
            searchResultSourceId=payload.searchResultSourceId,
            knownAt=payload.knownAt,
            apiKey=apiKey,
            clientRequestId=payload.clientRequestId,
        )
        if not result.idempotencyReplayed:
            request.app.state.database.appendAuditEvent(
                ownerUserId,
                "EVENT_PACK_FACTORY",
                buildId,
                "READER_SOURCE_ADDED",
                {
                    "revision": result.build.revision,
                    "parentSourceId": payload.searchResultSourceId,
                    "sourceIds": [source.id for source in result.sources],
                    "readerBillingStatus": READER_CAPABILITY.billingStatus.value,
                },
            )
        return result.model_dump(mode="json")

    @appInstance.post("/api/v1/event-pack-factory/builds/{buildId}/sources/{sourceId}/review")
    async def reviewEventPackFactorySource(
        buildId: str,
        sourceId: str,
        payload: FactoryReviewMutationRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        result = factory.reviewSource(
            ownerUserId=ownerUserId,
            buildId=buildId,
            sourceId=sourceId,
            expectedRevision=payload.expectedRevision,
            reviewInput=SourceReviewInput(status=payload.status),
        )
        request.app.state.database.appendAuditEvent(
            ownerUserId,
            "EVENT_PACK_FACTORY",
            buildId,
            "SOURCE_REVIEWED",
            {
                "revision": result.build.revision,
                "sourceId": sourceId,
                "status": payload.status.value,
            },
        )
        return result.model_dump(mode="json")

    @appInstance.post(
        "/api/v1/event-pack-factory/builds/{buildId}/materialize",
        status_code=201,
    )
    async def materializeEventPackFactoryBuild(
        buildId: str,
        payload: FactoryMaterializeRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        factory: EventPackFactoryService = request.app.state.eventPackFactoryService
        payloadHash = factory.canonicalPayloadHash(
            "MATERIALIZE",
            buildId,
            payload.model_dump(mode="json", exclude={"clientRequestId"}),
        )
        eventPackService: EventPackService = request.app.state.eventPackService
        database: Database = request.app.state.database
        materializationDigest = hashlib.blake2s(
            (f"{ownerUserId}:{buildId}:{payload.clientRequestId}:{payloadHash}").encode(),
            digest_size=12,
        ).hexdigest()
        eventPackSlug = re.sub(r"[^a-z0-9]+", "-", payload.title.lower()).strip("-")[:44]
        deterministicEventPackId = f"custom-{eventPackSlug or 'event'}-{materializationDigest}"

        def ensureMaterializationAudit(
            result: dict[str, Any],
            *,
            extractionMode: str,
            sourceCount: int,
            publicationTimeAssumedSourceIds: list[str],
        ) -> None:
            if database.eventPackWasMaterializedFromFactoryBuild(
                ownerUserId=ownerUserId,
                buildId=buildId,
                eventPackId=str(result["id"]),
            ):
                return
            database.appendAuditEvent(
                ownerUserId,
                "EVENT_PACK_FACTORY",
                buildId,
                "EVENT_PACK_MATERIALIZED",
                {
                    "factoryRevision": payload.expectedRevision,
                    "eventPackId": result["id"],
                    "sourceCount": sourceCount,
                    "publicationTimeAssumedSourceIds": publicationTimeAssumedSourceIds,
                    "extractionMode": extractionMode,
                    "humanClaimReviewRequired": True,
                    "allEvidenceSourcesReviewed": True,
                    "materializationRequestHash": payloadHash,
                    "frozen": False,
                },
            )

        async def materializeOnce() -> dict[str, object]:
            snapshot = factory.getBuild(ownerUserId=ownerUserId, buildId=buildId)
            if snapshot.build.revision != payload.expectedRevision:
                raise FactoryRevisionConflictError(
                    expectedRevision=payload.expectedRevision,
                    actualRevision=snapshot.build.revision,
                )
            approvedInputs = factory.approvedEvidenceInputsForMaterialization(
                ownerUserId=ownerUserId,
                buildId=buildId,
            )
            sources = [
                EventSourceInput(
                    sourceId=item.source.id,
                    title=item.source.title,
                    publisher=item.source.publisher,
                    url=item.source.url,
                    sourceType=(
                        "USER_PROVIDED"
                        if item.source.kind is SourceInputKind.PASTE
                        else "REPORTING"
                    ),
                    publishedAt=item.source.publishedAt or item.source.knownAt,
                    knownAt=item.source.knownAt,
                    rawText=item.rawText,
                    publicationTimeAssumed=item.source.publishedAt is None,
                )
                for item in approvedInputs
            ]
            eventPack = EventPackCreateRequest(
                title=payload.title,
                titleZh=payload.titleZh,
                summary=payload.summary,
                summaryZh=payload.summaryZh,
                asOf=payload.asOf,
                instrument=payload.instrument,
                sources=sources,
                acknowledgedContentReview=payload.acknowledgedContentReview,
            )
            contentSecurity = _scanEventPackSources(
                eventPack.sources,
                acknowledged=eventPack.acknowledgedContentReview,
                eventPackMetadata={
                    "title": eventPack.title,
                    "titleZh": eventPack.titleZh or "",
                    "summary": eventPack.summary,
                    "summaryZh": eventPack.summaryZh or "",
                    "value": eventPack.instrument,
                    "factoryBuildId": buildId,
                },
            )
            eventPack = _sanitizeAcknowledgedEventPack(eventPack, contentSecurity)
            cognition: CognitionService = request.app.state.cognitionService
            claims, extractionMode = await _extractEventClaimsInBatches(
                cognition,
                credentialId=credentialSessionId(request, ownerUserId),
                sources=eventPack.sources,
                maximumClaims=payload.maximumClaims,
                requestedImpactChannels=payload.requestedImpactChannels,
            )
            result = eventPackService.createEventPack(
                eventPack,
                ownerUserId,
                claims=claims,
                extractionMode=extractionMode,
                contentSecurity=contentSecurity,
                eventPackId=deterministicEventPackId,
            )
            ensureMaterializationAudit(
                result,
                extractionMode=extractionMode,
                sourceCount=len(sources),
                publicationTimeAssumedSourceIds=[
                    source.sourceId for source in sources if source.publicationTimeAssumed
                ],
            )
            return result

        async def recoverMaterializedEventPack() -> dict[str, object] | None:
            try:
                recovered = eventPackService.getEventPack(
                    deterministicEventPackId,
                    ownerUserId,
                )
            except ApiError as error:
                if error.code == "EVENT_PACK_NOT_FOUND":
                    return None
                raise
            recoveredSources = recovered.get("sources")
            sourceRecords = recoveredSources if isinstance(recoveredSources, list) else []
            extraction = recovered.get("extraction")
            extractionMode = (
                str(extraction.get("mode", "UNKNOWN"))
                if isinstance(extraction, dict)
                else "UNKNOWN"
            )
            ensureMaterializationAudit(
                recovered,
                extractionMode=extractionMode,
                sourceCount=len(sourceRecords),
                publicationTimeAssumedSourceIds=[
                    str(source.get("sourceId"))
                    for source in sourceRecords
                    if isinstance(source, dict) and source.get("publicationTimeAssumed") is True
                ],
            )
            return recovered

        idempotentResult = await factory.executeIdempotentJson(
            ownerUserId=ownerUserId,
            buildId=buildId,
            operation="MATERIALIZE",
            clientRequestId=payload.clientRequestId,
            payloadHash=payloadHash,
            callback=materializeOnce,
            recovery=recoverMaterializedEventPack,
        )
        return idempotentResult.payload

    @appInstance.post("/api/v1/event-packs", status_code=201)
    async def createEventPack(
        eventPack: EventPackCreateRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        validatedSessionId = _sessionId(sessionId)
        credentialId = credentialSessionId(request, validatedSessionId)
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
        claims, extractionMode = await _extractEventClaimsInBatches(
            cognition,
            credentialId=credentialId,
            sources=eventPack.sources,
            maximumClaims=16,
        )
        return service.createEventPack(
            eventPack,
            validatedSessionId,
            claims=claims,
            extractionMode=extractionMode,
            contentSecurity=contentSecurity,
        )

    @appInstance.get("/api/v1/models")
    async def listModels(request: Request) -> dict[str, Any]:
        del request

        def modelPayload(model: Any) -> dict[str, Any]:
            price = getTokenPrice(model.provider, model.model_id)
            return {
                "provider": model.provider,
                "id": model.model_id,
                "name": model.display_name,
                "contextTokens": model.context_tokens,
                "maxOutputTokens": model.max_output_tokens,
                "officialMaxOutputTokens": model.official_max_output_tokens,
                "applicationMaxOutputTokens": model.max_output_tokens,
                "supportsJsonObject": model.supports_json_object,
                "supportsJsonSchema": model.supports_json_schema,
                "supportsFunctionCalling": model.supports_function_calling,
                "supportsThinking": model.supports_thinking,
                "thinkingAlwaysOn": model.thinking_behavior == "always",
                "structuredOutputMode": model.structured_output_mode,
                "qualityTier": model.quality_tier,
                "recommended": model.recommended,
                "freeTier": model.free_tier,
                "legacy": model.legacy,
                "deprecationNote": model.deprecation_note,
                "capabilityNote": model.capability_note,
                "region": model.region,
                "officialModelUrl": model.official_model_url,
                "catalogVerifiedAt": model.verified_at,
                "pricingStatus": (
                    "VERIFIED_UPPER_BOUND" if price is not None else "UNAVAILABLE_FAIL_CLOSED"
                ),
                "billingCurrency": price.currency if price is not None else None,
                "inputRateUpperPerMillion": (
                    float(price.listInputPerMillion) if price is not None else None
                ),
                "cachedInputRatePerMillion": (
                    float(price.listCachedInputPerMillion)
                    if price is not None and price.listCachedInputPerMillion is not None
                    else None
                ),
                "outputRateUpperPerMillion": (
                    float(price.listOutputPerMillion) if price is not None else None
                ),
                "budgetInputRateUpperPerMillion": (
                    float(price.budgetInputUpperBoundPerMillion) if price is not None else None
                ),
                "budgetOutputRateUpperPerMillion": (
                    float(price.budgetOutputUpperBoundPerMillion) if price is not None else None
                ),
                "pricingVerifiedAt": price.verifiedAt if price is not None else None,
                "pricingNote": price.pricingNote if price is not None else None,
            }

        providerPayloads: list[dict[str, Any]] = []
        for provider in listProviders():
            providerModels = [
                modelPayload(model) for model in listCognitionModels(provider.provider)
            ]
            structuredModes = sorted({item["structuredOutputMode"] for item in providerModels})
            providerPayloads.append(
                {
                    "id": provider.provider,
                    "name": provider.display_name,
                    "baseUrl": provider.api_endpoint,
                    "apiStyle": provider.api_style,
                    "authMode": provider.auth_mode,
                    "documentationUrl": provider.official_docs_url,
                    "pricingUrl": provider.official_pricing_url,
                    "region": provider.region,
                    "defaultModel": provider.default_model_id,
                    "catalogVerifiedAt": provider.verified_at,
                    "integrationValidationStatus": (provider.integration_validation_status),
                    "supportedAdvancedParameters": sorted(
                        PROVIDER_ADVANCED_PARAMETER_CAPABILITIES.get(
                            provider.provider,
                            frozenset(),
                        )
                    ),
                    "feedbackIssueUrl": provider.feedback_issue_url,
                    "structuredOutputMode": "/".join(structuredModes),
                    "structuredOutputNote": (
                        "Native JSON Schema is requested and every response is still "
                        "validated locally against the application schema."
                        if structuredModes == ["json_schema"]
                        else "JSON-object mode is requested and every response is then "
                        "validated locally against the application schema."
                    ),
                    "models": providerModels,
                }
            )

        defaultProvider = next(item for item in providerPayloads if item["id"] == DEFAULT_PROVIDER)
        return {
            "defaultProvider": DEFAULT_PROVIDER,
            "providers": providerPayloads,
            # 保留旧的单供应商字段，便于已部署前端平滑升级。
            "provider": defaultProvider["id"],
            "providerName": defaultProvider["name"],
            "baseUrl": defaultProvider["baseUrl"],
            "documentationUrl": defaultProvider["documentationUrl"],
            "pricingUrl": defaultProvider["pricingUrl"],
            "pricingSnapshotVersion": PRICING_SNAPSHOT_VERSION,
            "fxSourceUrl": FX_SOURCE_URL,
            "officialFxSnapshotCnyPerUsd": float(OFFICIAL_FX_SNAPSHOT_CNY_PER_USD),
            "cnyPerUsdBudgetFloor": float(CNY_PER_USD_BUDGET_FLOOR),
            "costCapSemantics": (
                "Verified public list-price upper bounds retain their source currency; CNY "
                "rates use a conservative frozen FX floor for the USD hard cap, while USD "
                "rates need no conversion. Unknown prices fail closed before dispatch."
            ),
            "models": defaultProvider["models"],
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
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        cognition: CognitionService = request.app.state.cognitionService
        ownerUserId = _sessionId(sessionId)
        return cognition.getConfig(credentialSessionId(request, ownerUserId)).model_dump(
            mode="json"
        )

    @appInstance.put("/api/v1/llm/config")
    async def saveLlmConfig(
        config: LlmConfigRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        credentialId = credentialSessionId(request, ownerUserId)
        cognition: CognitionService = request.app.state.cognitionService
        database: Database = request.app.state.database
        try:
            view = cognition.setConfig(
                sessionId=credentialId,
                apiKey=config.apiKey,
                model=config.model,
                provider=config.provider,
                thinkingEnabled=config.thinkingEnabled,
                maxTokens=config.maxTokens,
                advancedParameters=config.advancedParameters,
            )
        except ValueError as error:
            raise ApiError("INVALID_LLM_CONFIG", 422, str(error)) from error
        database.appendAuditEvent(
            ownerUserId,
            "MODEL_CONFIG",
            f"{config.provider}-session-config",
            "CONFIGURED",
            {
                "provider": config.provider,
                "model": config.model,
                "thinkingEnabled": config.thinkingEnabled,
                "maxTokens": config.maxTokens,
                "advancedParameters": config.advancedParameters.model_dump(
                    mode="json",
                    exclude_none=True,
                ),
            },
        )
        return view.model_dump(mode="json")

    @appInstance.delete("/api/v1/llm/config")
    async def clearLlmConfig(
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        credentialId = credentialSessionId(request, ownerUserId)
        cognition: CognitionService = request.app.state.cognitionService
        database: Database = request.app.state.database
        cleared = cognition.clearConfig(credentialId)
        database.appendAuditEvent(
            ownerUserId,
            "MODEL_CONFIG",
            "provider-session-config",
            "CLEARED",
            {"credentialWasPresent": cleared},
        )
        return cognition.getConfig(credentialId).model_dump(mode="json")

    @appInstance.post("/api/v1/llm/test")
    async def testLlmConfig(
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        credentialId = credentialSessionId(request, ownerUserId)
        cognition: CognitionService = request.app.state.cognitionService
        try:
            result = await cognition.testConnection(credentialId)
        except CredentialNotConfiguredError as error:
            raise ApiError(
                "LLM_CREDENTIAL_NOT_CONFIGURED",
                409,
                "Configure a session API key before testing the model connection.",
            ) from error
        except ModelGatewayError as error:
            raise _modelGatewayApiError(error) from error
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
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        ownerUserId = _sessionId(sessionId)
        credentialId = credentialSessionId(request, ownerUserId)
        cognition: CognitionService = request.app.state.cognitionService
        cases = builtInEvalCases()[: evaluation.maximumCases]
        modelRuns: list[dict[str, Any]] = []
        if evaluation.mode == "CODE_GRADER_SELF_TEST":
            samples = codeGraderSelfTestSamples(cases)
            evaluatedSystem = "DETERMINISTIC_CODE_GRADER"
        else:
            liveConfig = cognition.getConfig(credentialId)
            if not liveConfig.configured:
                raise ApiError(
                    "LLM_CREDENTIAL_NOT_CONFIGURED",
                    409,
                    "Configure a session-scoped provider API key before running the live suite.",
                )
            liveSamples: list[EvalSample] = []
            for case in cases:
                try:
                    modelRun = await cognition.generateBeliefDecision(
                        sessionId=credentialId,
                        observation=case.observation,
                    )
                except CredentialNotConfiguredError as error:
                    raise ApiError(
                        "LLM_CREDENTIAL_NOT_CONFIGURED",
                        409,
                        "The session credential expired before the evaluation completed.",
                    ) from error
                except ModelGatewayError as error:
                    raise _modelGatewayApiError(error) from error
                liveSamples.append(EvalSample(case=case, rawDecision=modelRun.decision))
                modelRuns.append(
                    {
                        "caseId": case.case_id,
                        "provider": modelRun.provider,
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
            configuredProvider = liveConfig.provider or DEFAULT_PROVIDER
            evaluatedSystem = f"LIVE_CONFIGURED_{configuredProvider.upper()}_MODEL"
        result = cognition.runEvaluation(samples)
        database: Database = request.app.state.database
        database.appendAuditEvent(
            ownerUserId,
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
        sessionId: str = Depends(requireOwner),
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
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: StudyApiService = request.app.state.studyService
        return {"items": service.listRuns(_sessionId(sessionId))}

    @appInstance.get("/api/v1/studies/{runId}")
    async def getStudyRun(
        runId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: StudyApiService = request.app.state.studyService
        return service.getRun(runId, _sessionId(sessionId))

    @appInstance.get("/api/v1/event-packs/{eventPackId}")
    async def getEventPack(
        eventPackId: str,
        request: Request,
        sessionId: str | None = Depends(optionalOwner),
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
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: EventPackService = request.app.state.eventPackService
        return service.reviewClaim(eventPackId, claimId, _sessionId(sessionId), review)

    @appInstance.post("/api/v1/event-packs/{eventPackId}/claims/approve-all")
    async def approveAllClaims(
        eventPackId: str,
        approval: BulkClaimApprovalRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: EventPackService = request.app.state.eventPackService
        return service.approveAllProposedClaims(
            eventPackId,
            _sessionId(sessionId),
            approval,
        )

    @appInstance.post("/api/v1/event-packs/{eventPackId}/freeze")
    async def freezeEventPack(
        eventPackId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: EventPackService = request.app.state.eventPackService
        return service.freezeEventPack(eventPackId, _sessionId(sessionId))

    @appInstance.post("/api/v1/event-packs/{eventPackId}/extract")
    async def extractEventPackClaims(
        eventPackId: str,
        extraction: EventPackExtractRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        validatedSessionId = _sessionId(sessionId)
        credentialId = credentialSessionId(request, validatedSessionId)
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
        if extraction.useLlm and cognition.getConfig(credentialId).configured:
            try:
                llmExtraction = await cognition.extractEventClaims(
                    sessionId=credentialId,
                    sources=_cognitionSources(extraction.sources),
                    maximumClaims=extraction.maximumClaims,
                    requestedImpactChannels=tuple(extraction.requestedImpactChannels),
                )
                if llmExtraction.event_pack_claims:
                    claims = list(llmExtraction.event_pack_claims)
                    providerLabel = llmExtraction.provider.upper()
                    extractionMode = (
                        f"{providerLabel}_{llmExtraction.model}_FALLBACK"
                        if llmExtraction.fallback_used
                        else f"{providerLabel}_{llmExtraction.model}"
                    )
                else:
                    extractionMode = (
                        f"{llmExtraction.provider.upper()}_{llmExtraction.model}_"
                        "ABSTAINED_RULE_FALLBACK"
                    )
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
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        return {"items": service.listScenarios(_sessionId(sessionId))}

    @appInstance.post("/api/v1/scenarios", status_code=201)
    async def createScenario(
        scenario: ScenarioSaveRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        ownerUserId = _sessionId(sessionId)
        return service.createScenario(
            scenario,
            ownerUserId,
            credentialSessionId=credentialSessionId(request, ownerUserId),
        )

    @appInstance.get("/api/v1/scenarios/{scenarioId}")
    async def getScenario(
        scenarioId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        return service.getScenario(scenarioId, _sessionId(sessionId))

    @appInstance.put("/api/v1/scenarios/{scenarioId}")
    async def updateScenario(
        scenarioId: str,
        scenario: ScenarioUpdateRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        return service.updateScenario(scenarioId, scenario, _sessionId(sessionId))

    @appInstance.delete("/api/v1/scenarios/{scenarioId}", status_code=204)
    async def deleteScenario(
        scenarioId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> Response:
        service: ScenarioService = request.app.state.scenarioService
        service.deleteScenario(scenarioId, _sessionId(sessionId))
        return Response(status_code=204)

    @appInstance.post("/api/v1/scenarios/{scenarioId}/clone", status_code=201)
    async def cloneScenario(
        scenarioId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        return service.cloneScenario(scenarioId, _sessionId(sessionId))

    @appInstance.post("/api/v1/scenarios/{scenarioId}/freeze")
    async def freezeScenario(
        scenarioId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ScenarioService = request.app.state.scenarioService
        ownerUserId = _sessionId(sessionId)
        return service.freezeScenario(
            scenarioId,
            ownerUserId,
            credentialSessionId=credentialSessionId(request, ownerUserId),
        )

    @appInstance.post("/api/v1/scenarios/diff")
    async def diffScenarios(scenarios: ScenarioDiffRequest) -> dict[str, Any]:
        return ScenarioService.diffConfigs(scenarios.baseline, scenarios.intervention)

    @appInstance.post("/api/v1/scenarios/validate")
    async def validateScenario(
        scenario: ScenarioValidateRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: EventPackService = request.app.state.eventPackService
        ownerUserId = _sessionId(sessionId)
        return service.validateExperiment(
            scenario,
            ownerUserId,
            credentialSessionId=credentialSessionId(request, ownerUserId),
        )

    @appInstance.get("/api/v1/experiments")
    async def listExperiments(
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return {"items": service.listExperiments(_sessionId(sessionId))}

    @appInstance.get("/api/v1/audit-events")
    async def listAuditEvents(
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        database: Database = request.app.state.database
        return {"items": database.listAuditEvents(_sessionId(sessionId))}

    @appInstance.get("/api/v1/audit-events/verify")
    async def verifyAuditEvents(
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        database: Database = request.app.state.database
        return database.verifyAuditChain(_sessionId(sessionId))

    @appInstance.post("/api/v1/experiments")
    async def createExperiment(
        experiment: ExperimentRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
        idempotencyKey: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> Response:
        service: ExperimentService = request.app.state.experimentService
        ownerUserId = _sessionId(sessionId)
        createdExperiment, created = service.createExperiment(
            experiment,
            ownerUserId,
            _idempotencyKey(idempotencyKey),
            credentialSessionId=credentialSessionId(request, ownerUserId),
        )
        return JSONResponse(status_code=201 if created else 200, content=createdExperiment)

    @appInstance.get("/api/v1/experiments/{experimentId}")
    async def getExperiment(
        experimentId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.publicExperiment(service.getExperiment(experimentId, _sessionId(sessionId)))

    @appInstance.get("/api/v1/experiments/{experimentId}/events")
    async def streamExperimentEvents(
        experimentId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
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
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        ownerUserId = _sessionId(sessionId)
        return service.startExperiment(
            experimentId,
            ownerUserId,
            credentialSessionId=credentialSessionId(request, ownerUserId),
        )

    @appInstance.post("/api/v1/experiments/{experimentId}/cancel")
    async def cancelExperiment(
        experimentId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.cancelExperiment(experimentId, _sessionId(sessionId))

    @appInstance.post("/api/v1/experiments/{experimentId}/invalidate")
    async def invalidateExperiment(
        experimentId: str,
        invalidation: ExperimentInvalidateRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
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
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.getResults(experimentId, _sessionId(sessionId))

    def validatePersistedInterpretationConversation(
        *,
        database: Database,
        ownerUserId: str,
        experimentId: str,
        interpretationRequest: ResultInterpretationChatRequest,
    ) -> None:
        """把客户端追问历史绑定到服务器终态，拒绝伪造或分叉上下文。"""

        conversation = database.getResultInterpretationConversation(
            ownerUserId=ownerUserId,
            experimentId=experimentId,
            conversationId=interpretationRequest.conversationId,
        )
        if interpretationRequest.mode == "INITIAL":
            if conversation is not None:
                raise ApiError(
                    "RESULT_INTERPRETATION_CONVERSATION_CONFLICT",
                    409,
                    "This conversation already contains a completed exchange.",
                    details={"retryable": False},
                )
            return
        if conversation is None:
            raise ApiError(
                "RESULT_INTERPRETATION_CONVERSATION_NOT_FOUND",
                409,
                "Start a new result interpretation before sending a follow-up.",
                details={"retryable": False},
            )

        persistedTurns: list[dict[str, str]] = []
        for exchange in conversation["exchanges"]:
            persistedTurns.extend(
                (
                    {"role": "user", "content": exchange["userMessage"]},
                    {
                        "role": "assistant",
                        "content": exchange["assistantMessage"]["answer"],
                    },
                )
            )
        submittedPriorTurns = [
            message.model_dump(mode="json") for message in interpretationRequest.messages[:-1]
        ]
        if (
            len(submittedPriorTurns) > len(persistedTurns)
            or persistedTurns[-len(submittedPriorTurns) :] != submittedPriorTurns
        ):
            raise ApiError(
                "RESULT_INTERPRETATION_CONVERSATION_MISMATCH",
                409,
                "The submitted conversation does not match the saved server history.",
                details={"retryable": False},
            )

    def ensureInterpretationConversationNotDeleted(
        *,
        database: Database,
        ownerUserId: str,
        experimentId: str,
        conversationId: str,
    ) -> None:
        """在缓存命中和供应商调用前阻断已删除会话的任何旧请求。"""

        if database.isResultInterpretationConversationDeleted(
            ownerUserId=ownerUserId,
            experimentId=experimentId,
            conversationId=conversationId,
        ):
            raise ApiError(
                "RESULT_INTERPRETATION_CONVERSATION_DELETED",
                410,
                "This result interpretation conversation was deleted and cannot be reused.",
                details={"retryable": False},
            )

    async def generateResultInterpretation(
        *,
        experimentId: str,
        interpretationRequest: ResultInterpretationChatRequest,
        request: Request,
        ownerUserId: str,
        credentialId: str,
        authoritativeResult: dict[str, Any],
        requestHash: str,
        progressObserver: ModelStreamObserver | None = None,
    ) -> dict[str, Any]:
        """执行一次可单飞复用的解释，并只持久化严格验证后的完整问答。"""

        cognition: CognitionService = request.app.state.cognitionService
        database: Database = request.app.state.database
        resultHash = canonicalRequestHash(authoritativeResult)
        conversationHash = hashlib.sha256(
            interpretationRequest.conversationId.encode("utf-8")
        ).hexdigest()
        clientRequestHash = hashlib.sha256(
            interpretationRequest.clientRequestId.encode("utf-8")
        ).hexdigest()

        # 该检查必须在单飞 operation 内再执行一次：请求可能在排队期间被另一个
        # 浏览器删除。数据库保存层还有第三道事务内检查，覆盖多进程竞争。
        ensureInterpretationConversationNotDeleted(
            database=database,
            ownerUserId=ownerUserId,
            experimentId=experimentId,
            conversationId=interpretationRequest.conversationId,
        )

        # 持久化终态是跨进程、跨重启的第二层幂等保护。它必须先于读取临时
        # API Key，使用户即使没有重新填写 Key，也能恢复已经完成的回答。
        try:
            persistedExchange = database.getResultInterpretationExchangeByRequest(
                ownerUserId=ownerUserId,
                experimentId=experimentId,
                clientRequestId=interpretationRequest.clientRequestId,
                requestHash=requestHash,
            )
        except ResultInterpretationRequestConflictError as error:
            raise ApiError(
                "CLIENT_REQUEST_ID_REUSED",
                409,
                "clientRequestId is already bound to a different persisted request.",
                details={"retryable": False},
            ) from error
        if persistedExchange is not None:
            _appendResultInterpretationAuditSafely(
                database,
                ownerUserId=ownerUserId,
                experimentId=experimentId,
                action="INTERPRETATION_REPLAYED",
                metadata={
                    "resultHash": resultHash,
                    "conversationHash": conversationHash,
                    "clientRequestHash": clientRequestHash,
                    "historyPersisted": True,
                    "providerCallMade": False,
                },
                traceId=getattr(request.state, "traceId", None),
            )
            return {
                "schemaVersion": "1.0.0",
                "conversationId": persistedExchange["conversationId"],
                "clientRequestId": persistedExchange["clientRequestId"],
                "experimentId": experimentId,
                "resultHash": resultHash,
                "historyPersisted": True,
                "message": persistedExchange["assistantMessage"],
            }

        validatePersistedInterpretationConversation(
            database=database,
            ownerUserId=ownerUserId,
            experimentId=experimentId,
            interpretationRequest=interpretationRequest,
        )
        config = cognition.getConfig(credentialId)
        try:
            run = await cognition.interpretExperimentResult(
                sessionId=credentialId,
                result=authoritativeResult,
                messages=tuple(
                    message.model_dump(mode="json") for message in interpretationRequest.messages
                ),
                language=interpretationRequest.language,
                initial=interpretationRequest.mode == "INITIAL",
                includeAnalysisSummary=interpretationRequest.reasoningSummaryRequested,
                progressObserver=progressObserver,
            )
        except CredentialNotConfiguredError as error:
            raise ApiError(
                "LLM_CREDENTIAL_NOT_CONFIGURED",
                409,
                "Configure a temporary session API key before asking the result interpreter.",
                details={"retryable": False},
            ) from error
        except ModelGatewayError as error:
            _appendResultInterpretationAuditSafely(
                database,
                ownerUserId=ownerUserId,
                experimentId=experimentId,
                action="INTERPRETATION_FAILED",
                metadata={
                    "resultHash": resultHash,
                    "conversationHash": conversationHash,
                    "clientRequestHash": clientRequestHash,
                    "language": interpretationRequest.language,
                    "mode": interpretationRequest.mode,
                    "reasoningSummaryRequested": (interpretationRequest.reasoningSummaryRequested),
                    "provider": config.provider,
                    "model": config.model,
                    "thinkingEnabled": config.thinking_enabled,
                    "failureCode": error.code.value,
                    "retryable": error.retryable,
                    "providerAttempts": max(0, error.attempts),
                    "uncertainBillableAttempts": max(
                        0,
                        error.uncertainBillableAttempts,
                    ),
                    "repairUsed": error.repairUsed,
                },
                traceId=getattr(request.state, "traceId", None),
            )
            raise _modelGatewayApiError(error) from error
        except ValueError as error:
            raise ApiError(
                "RESULT_INTERPRETATION_CONTEXT_INVALID",
                422,
                "The result interpretation context was invalid.",
                details={"retryable": False},
            ) from error
        except Exception as error:
            # 上游未知异常只按类型记录；正文可能包含供应商响应或请求对象。
            LOGGER.error(
                "Unexpected result interpretation failure: traceId=%s errorType=%s",
                getattr(request.state, "traceId", "unavailable"),
                type(error).__name__,
            )
            raise ApiError(
                "RESULT_INTERPRETATION_INTERNAL_ERROR",
                500,
                "The result interpretation could not be completed safely.",
                details={
                    "retryable": True,
                    # 未知异常可能发生在供应商已接收请求之后，保守提示计费不确定性。
                    "uncertainBillableAttempts": 1,
                },
            ) from error

        answer = run.interpretation
        createdAt = datetime.now(UTC).isoformat()
        messageId = f"interpretation-{uuid.uuid4().hex[:24]}"
        response: dict[str, Any] = {
            "schemaVersion": "1.0.0",
            "conversationId": interpretationRequest.conversationId,
            "clientRequestId": interpretationRequest.clientRequestId,
            "experimentId": experimentId,
            "resultHash": run.result_hash,
            "historyPersisted": False,
            "message": {
                "id": messageId,
                "role": "assistant",
                "language": interpretationRequest.language,
                "answer": answer.answer,
                "analysisSummary": answer.analysis_summary,
                "groundingReferences": list(answer.grounding_references),
                "followUpSuggestions": list(answer.follow_up_suggestions),
                "toolActivity": [
                    {
                        "tool": activity.tool.value,
                        "label": activity.label,
                        "itemCount": activity.item_count,
                        "truncated": activity.truncated,
                        "evidenceId": activity.evidence_id,
                    }
                    for activity in run.tool_activity
                ],
                "provider": run.provider,
                "model": run.model,
                "thinkingEnabled": run.thinking_enabled,
                "streamed": run.streamed,
                "promptTokens": run.usage.promptTokens,
                "completionTokens": run.usage.completionTokens,
                "cachedTokens": run.usage.cachedTokens,
                "totalTokens": run.usage.totalTokens,
                "modelCalls": run.model_calls,
                "transportAttempts": run.transport_attempts,
                "uncertainBillableAttempts": run.uncertain_billable_attempts,
                "cacheHit": run.cache_hit,
                "repairUsed": run.repair_used,
                "plannerUsed": run.planner_used,
                "plannerFallbackUsed": run.planner_fallback_used,
                "failureCodes": list(run.failure_codes),
                "promptVersion": run.prompt_version,
                "latencyMs": run.latency_ms,
                "createdAt": createdAt,
            },
        }

        historyPersisted = False
        try:
            persistedExchange, historyCreated = database.saveResultInterpretationExchange(
                ownerUserId=ownerUserId,
                experimentId=experimentId,
                conversationId=interpretationRequest.conversationId,
                clientRequestId=interpretationRequest.clientRequestId,
                requestHash=requestHash,
                language=interpretationRequest.language,
                userMessage=interpretationRequest.messages[-1].content,
                assistantMessage=response["message"],
            )
            historyPersisted = True
            # 极少数多进程竞争中，另一个进程可能已经先写入同一幂等结果。
            # 这时必须返回数据库中的首次终态，不能让同一请求 ID 看到两份回答。
            if not historyCreated:
                response["message"] = persistedExchange["assistantMessage"]
        except ResultInterpretationRequestConflictError as error:
            raise ApiError(
                "CLIENT_REQUEST_ID_REUSED",
                409,
                "clientRequestId is already bound to a different persisted request.",
                details={
                    "retryable": False,
                    "providerAttempts": max(0, run.transport_attempts),
                },
            ) from error
        except ResultInterpretationConversationDeletedError:
            # 另一个进程可能在模型运行期间完成删除。此时回答仍可交付给当前
            # 等待者，但绝不重新写入服务器历史。
            historyPersisted = False
        except Exception as error:
            # 用户可能误把凭据粘贴进问题，或数据库暂时不可写。无论哪种情况，
            # 都不能因为持久化失败而丢弃已经验证且可能已经计费的模型终态。
            LOGGER.error(
                "Result interpretation history write failed: traceId=%s errorType=%s",
                getattr(request.state, "traceId", "unavailable"),
                type(error).__name__,
            )
        response["historyPersisted"] = historyPersisted

        _appendResultInterpretationAuditSafely(
            database,
            ownerUserId=ownerUserId,
            experimentId=experimentId,
            action="INTERPRETATION_GENERATED",
            metadata={
                "resultHash": run.result_hash,
                "conversationHash": conversationHash,
                "clientRequestHash": clientRequestHash,
                "language": interpretationRequest.language,
                "mode": interpretationRequest.mode,
                "reasoningSummaryRequested": interpretationRequest.reasoningSummaryRequested,
                "provider": run.provider,
                "model": run.model,
                "thinkingEnabled": run.thinking_enabled,
                "streamed": run.streamed,
                "modelCalls": run.model_calls,
                "transportAttempts": run.transport_attempts,
                "uncertainBillableAttempts": run.uncertain_billable_attempts,
                "repairUsed": run.repair_used,
                "plannerFallbackUsed": run.planner_fallback_used,
                "failureCodes": list(run.failure_codes),
                "promptTokens": run.usage.promptTokens,
                "completionTokens": run.usage.completionTokens,
                "cachedTokens": run.usage.cachedTokens,
                "tools": [activity.tool.value for activity in run.tool_activity],
                "truncatedTools": [
                    activity.tool.value for activity in run.tool_activity if activity.truncated
                ],
                "historyPersisted": historyPersisted,
            },
            traceId=getattr(request.state, "traceId", None),
        )
        return response

    def resultInterpretationContext(
        *,
        experimentId: str,
        interpretationRequest: ResultInterpretationChatRequest,
        request: Request,
        sessionId: str,
    ) -> tuple[str, str, dict[str, Any], str]:
        _validateResultInterpretationPrivateInput(interpretationRequest)
        ownerUserId = _sessionId(sessionId)
        credentialId = credentialSessionId(request, ownerUserId)
        database: Database = request.app.state.database
        # 放在单飞缓存查找之前，避免删除后的一分钟完成态缓存谎报仍已持久化。
        ensureInterpretationConversationNotDeleted(
            database=database,
            ownerUserId=ownerUserId,
            experimentId=experimentId,
            conversationId=interpretationRequest.conversationId,
        )
        experimentService: ExperimentService = request.app.state.experimentService
        # 先按 owner 读取，防止客户端通过提交结果正文或猜测 ID 跨用户取数。
        authoritativeResult = experimentService.getResults(experimentId, ownerUserId)
        requestHash = canonicalRequestHash(
            {
                "ownerUserId": ownerUserId,
                "experimentId": experimentId,
                "resultHash": canonicalRequestHash(authoritativeResult),
                "request": interpretationRequest.model_dump(mode="json"),
            }
        )
        return ownerUserId, credentialId, authoritativeResult, requestHash

    @appInstance.post("/api/v1/experiments/{experimentId}/interpretation-chat")
    async def interpretExperimentResults(
        experimentId: str,
        interpretationRequest: ResultInterpretationChatRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        """兼容端点：上游仍流式接收，浏览器在最终严格校验后一次取得 JSON。"""

        ownerUserId, credentialId, authoritativeResult, requestHash = resultInterpretationContext(
            experimentId=experimentId,
            interpretationRequest=interpretationRequest,
            request=request,
            sessionId=sessionId,
        )
        singleFlight: ResultInterpretationSingleFlight = (
            request.app.state.resultInterpretationSingleFlight
        )

        async def generateInterpretation() -> dict[str, Any]:
            return await generateResultInterpretation(
                experimentId=experimentId,
                interpretationRequest=interpretationRequest,
                request=request,
                ownerUserId=ownerUserId,
                credentialId=credentialId,
                authoritativeResult=authoritativeResult,
                requestHash=requestHash,
            )

        try:
            return await singleFlight.execute(
                principalKey=ownerUserId,
                clientRequestId=interpretationRequest.clientRequestId,
                requestHash=requestHash,
                operation=generateInterpretation,
            )
        except SingleFlightRequestConflictError as error:
            raise ApiError(
                "CLIENT_REQUEST_ID_REUSED",
                409,
                "clientRequestId is already bound to a different recent request.",
            ) from error
        except SingleFlightCapacityError as error:
            raise ApiError(
                "RESULT_INTERPRETATION_BUSY",
                503,
                "Too many result interpretation requests are active. Retry shortly.",
            ) from error

    @appInstance.post("/api/v1/experiments/{experimentId}/interpretation-chat/stream")
    async def streamExperimentResultInterpretation(
        experimentId: str,
        interpretationRequest: ResultInterpretationChatRequest,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> StreamingResponse:
        """以 SSE 推送安全阶段、片段计数和最终已验证结构化回答。"""

        ownerUserId, credentialId, authoritativeResult, requestHash = resultInterpretationContext(
            experimentId=experimentId,
            interpretationRequest=interpretationRequest,
            request=request,
            sessionId=sessionId,
        )
        singleFlight: ResultInterpretationSingleFlight = (
            request.app.state.resultInterpretationSingleFlight
        )
        progressQueue: asyncio.Queue[ModelStreamProgress] = asyncio.Queue(maxsize=64)

        async def observeProgress(progress: ModelStreamProgress) -> None:
            if progressQueue.full():
                with suppress(asyncio.QueueEmpty):
                    progressQueue.get_nowait()
            progressQueue.put_nowait(progress)

        async def generateInterpretation() -> dict[str, Any]:
            return await generateResultInterpretation(
                experimentId=experimentId,
                interpretationRequest=interpretationRequest,
                request=request,
                ownerUserId=ownerUserId,
                credentialId=credentialId,
                authoritativeResult=authoritativeResult,
                requestHash=requestHash,
                progressObserver=observeProgress,
            )

        async def eventStream():
            startedAt = time.perf_counter()
            currentStage = "PREPARING"
            executionTask: asyncio.Task[dict[str, Any]] | None = None
            progressTask: asyncio.Task[ModelStreamProgress] | None = None
            terminalRecorded = False

            def recordTerminal(outcome: Literal["success", "error", "cancelled"]) -> None:
                nonlocal terminalRecorded
                if terminalRecorded:
                    return
                runtimeMetrics.recordSseTerminal(
                    durationMs=(time.perf_counter() - startedAt) * 1_000,
                    outcome=outcome,
                )
                terminalRecorded = True

            try:
                yield _sseFrame(
                    "status",
                    {
                        "schemaVersion": "1.0.0",
                        "stage": currentStage,
                        "elapsedMs": 0,
                    },
                )
                executionTask = asyncio.create_task(
                    singleFlight.execute(
                        principalKey=ownerUserId,
                        clientRequestId=interpretationRequest.clientRequestId,
                        requestHash=requestHash,
                        operation=generateInterpretation,
                    ),
                    name=(
                        f"result-interpretation-stream:{interpretationRequest.clientRequestId[:32]}"
                    ),
                )
                while not executionTask.done():
                    progressTask = asyncio.create_task(progressQueue.get())
                    done, _pending = await asyncio.wait(
                        {executionTask, progressTask},
                        timeout=2.0,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if progressTask in done:
                        progress = progressTask.result()
                        currentStage = progress.stage.value
                        yield _sseFrame(
                            "progress",
                            {
                                "schemaVersion": "1.0.0",
                                "stage": currentStage,
                                "elapsedMs": round(
                                    (time.perf_counter() - startedAt) * 1_000,
                                    3,
                                ),
                                "chunkCount": progress.chunkCount,
                                "answerChunkCount": progress.answerChunkCount,
                                "reasoningChunkCount": progress.reasoningChunkCount,
                                "attempt": progress.attempt,
                                "repair": progress.repair,
                            },
                        )
                    else:
                        progressTask.cancel()
                        with suppress(asyncio.CancelledError):
                            await progressTask
                    if executionTask not in done and progressTask not in done:
                        yield _sseFrame(
                            "status",
                            {
                                "schemaVersion": "1.0.0",
                                "stage": currentStage,
                                "elapsedMs": round(
                                    (time.perf_counter() - startedAt) * 1_000,
                                    3,
                                ),
                            },
                        )
                response = await executionTask
                recordTerminal("success")
                yield _sseFrame("final", response)
            except (SingleFlightRequestConflictError, SingleFlightCapacityError) as error:
                code = (
                    "CLIENT_REQUEST_ID_REUSED"
                    if isinstance(error, SingleFlightRequestConflictError)
                    else "RESULT_INTERPRETATION_BUSY"
                )
                statusCode = 409 if isinstance(error, SingleFlightRequestConflictError) else 503
                recordTerminal("error")
                yield _sseFrame(
                    "error",
                    {
                        "schemaVersion": "1.0.0",
                        "code": code,
                        "message": "The result interpretation request could not be started.",
                        "retryable": statusCode == 503,
                        "httpStatus": statusCode,
                        "traceId": getattr(request.state, "traceId", None),
                    },
                )
            except ApiError as error:
                recordTerminal("error")
                yield _sseFrame(
                    "error",
                    {
                        "schemaVersion": "1.0.0",
                        **_safeResultInterpretationErrorDetails(error),
                        "code": error.code,
                        "message": error.message,
                        "httpStatus": error.statusCode,
                        "traceId": getattr(request.state, "traceId", None),
                    },
                )
            except Exception as error:
                # 响应头已经发出后只能用 SSE 报告失败；禁止回显异常正文或堆栈。
                LOGGER.error(
                    "Unexpected result interpretation stream failure: traceId=%s errorType=%s",
                    getattr(request.state, "traceId", "unavailable"),
                    type(error).__name__,
                )
                recordTerminal("error")
                yield _sseFrame(
                    "error",
                    {
                        "schemaVersion": "1.0.0",
                        "code": "RESULT_INTERPRETATION_INTERNAL_ERROR",
                        "message": "The result interpretation stream ended unexpectedly.",
                        "retryable": True,
                        "httpStatus": 500,
                        # 未知错误可能发生在供应商已接收请求之后，不能宣称未计费。
                        "uncertainBillableAttempts": 1,
                        "traceId": getattr(request.state, "traceId", None),
                    },
                )
            finally:
                if not terminalRecorded:
                    recordTerminal("cancelled")
                if progressTask is not None and not progressTask.done():
                    progressTask.cancel()
                if executionTask is not None and not executionTask.done():
                    # 只取消本次 SSE 等待；单飞协调器会保护已经可能计费的底层调用。
                    executionTask.cancel()

        return StreamingResponse(
            eventStream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-store, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @appInstance.get("/api/v1/experiments/{experimentId}/interpretation-conversations")
    async def listResultInterpretationConversations(
        experimentId: str,
        request: Request,
        limit: Annotated[int, Query(ge=1, le=300)] = 300,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        """列出当前用户在指定实验中已经完整验证并持久化的 AI 对话。"""

        ownerUserId = _sessionId(sessionId)
        experimentService: ExperimentService = request.app.state.experimentService
        # 所有历史端点都先经过实验所有权检查，避免借会话 ID 枚举其他用户数据。
        # 只检查所有权而不要求结果仍有效；即使实验后来被作废，用户也必须
        # 能查看或删除自己此前保存的对话。
        experimentService.getExperiment(experimentId, ownerUserId)
        database: Database = request.app.state.database
        return {
            "schemaVersion": "1.0.0",
            "items": database.listResultInterpretationConversations(
                ownerUserId,
                experimentId=experimentId,
                limit=limit,
            ),
        }

    @appInstance.get(
        "/api/v1/experiments/{experimentId}/interpretation-conversations/{conversationId}"
    )
    async def getResultInterpretationConversation(
        experimentId: str,
        conversationId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        """恢复当前用户的一段完整问答；API Key 与供应商私有推理从未入库。"""

        ownerUserId = _sessionId(sessionId)
        experimentService: ExperimentService = request.app.state.experimentService
        experimentService.getExperiment(experimentId, ownerUserId)
        database: Database = request.app.state.database
        conversation = database.getResultInterpretationConversation(
            ownerUserId=ownerUserId,
            experimentId=experimentId,
            conversationId=conversationId,
        )
        if conversation is None:
            raise ApiError(
                "RESULT_INTERPRETATION_CONVERSATION_NOT_FOUND",
                404,
                "The saved result interpretation conversation was not found.",
            )

        messages: list[dict[str, Any]] = []
        for exchange in conversation["exchanges"]:
            userMessageId = hashlib.sha256(
                f"user:{exchange['clientRequestId']}".encode()
            ).hexdigest()[:24]
            messages.append(
                {
                    "id": f"persisted-user-{userMessageId}",
                    "role": "user",
                    "language": exchange["language"],
                    "content": exchange["userMessage"],
                    "createdAt": exchange["createdAt"],
                }
            )
            messages.append(exchange["assistantMessage"])
        return {
            "schemaVersion": "1.0.0",
            "conversationId": conversation["conversationId"],
            "experimentId": conversation["experimentId"],
            "language": conversation["language"],
            "createdAt": conversation["createdAt"],
            "updatedAt": conversation["updatedAt"],
            "messages": messages,
        }

    @appInstance.delete(
        "/api/v1/experiments/{experimentId}/interpretation-conversations/{conversationId}"
    )
    async def deleteResultInterpretationConversation(
        experimentId: str,
        conversationId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        """删除当前用户的一段解释历史，不删除实验、结果或其他会话。"""

        ownerUserId = _sessionId(sessionId)
        experimentService: ExperimentService = request.app.state.experimentService
        experimentService.getExperiment(experimentId, ownerUserId)
        database: Database = request.app.state.database
        conversationHash = hashlib.sha256(conversationId.encode()).hexdigest()

        async def performDelete() -> dict[str, Any]:
            database.deleteResultInterpretationConversation(
                ownerUserId=ownerUserId,
                experimentId=experimentId,
                conversationId=conversationId,
                auditPayload={"conversationHash": conversationHash},
            )
            return {
                "schemaVersion": "1.0.0",
                "deleted": True,
                "conversationId": conversationId,
            }

        singleFlight: ResultInterpretationSingleFlight = (
            request.app.state.resultInterpretationSingleFlight
        )
        try:
            # 与该账号的模型生成共享排他锁，保证“删除成功”之后不会被一个
            # 先前已排队的回答重新插入；稳定请求键也覆盖删除响应丢失后的重试。
            return await singleFlight.execute(
                principalKey=ownerUserId,
                clientRequestId=f"delete-{conversationHash}",
                requestHash=canonicalRequestHash(
                    {
                        "ownerUserId": ownerUserId,
                        "experimentId": experimentId,
                        "conversationHash": conversationHash,
                        "operation": "DELETE_INTERPRETATION_CONVERSATION",
                    }
                ),
                operation=performDelete,
            )
        except SingleFlightRequestConflictError as error:
            raise ApiError(
                "RESULT_INTERPRETATION_DELETE_CONFLICT",
                409,
                "The conversation deletion conflicted with a recent operation.",
            ) from error
        except SingleFlightCapacityError as error:
            raise ApiError(
                "RESULT_INTERPRETATION_BUSY",
                503,
                "Too many result interpretation operations are active. Retry shortly.",
            ) from error

    @appInstance.get("/api/v1/experiments/{experimentId}/runs")
    async def getExperimentRuns(
        experimentId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.getRuns(experimentId, _sessionId(sessionId))

    @appInstance.get("/api/v1/experiments/{experimentId}/metrics")
    async def getExperimentMetrics(
        experimentId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
    ) -> dict[str, Any]:
        service: ExperimentService = request.app.state.experimentService
        return service.getMetrics(experimentId, _sessionId(sessionId))

    @appInstance.get("/api/v1/experiments/{experimentId}/traces")
    async def getExperimentTraces(
        experimentId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
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
        sessionId: str = Depends(requireOwner),
    ) -> Response:
        return await exportResponse(experimentId, request, sessionId)

    @appInstance.post("/api/v1/experiments/{experimentId}/export")
    async def exportExperimentPost(
        experimentId: str,
        request: Request,
        sessionId: str = Depends(requireOwner),
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


def _authenticationProtected(request: Request) -> bool:
    path = request.url.path.rstrip("/") or "/"
    return path.startswith("/api/v1/") and path not in PUBLIC_AUTH_PATHS


def _legalAcceptanceProtected(request: Request) -> bool:
    path = request.url.path.rstrip("/") or "/"
    return path.startswith("/api/v1/") and path not in LEGAL_GATE_EXEMPT_PATHS


def _validateSameOrigin(request: Request) -> None:
    """CSRF token 是主防线；若浏览器提供 Origin，再严格校验同源。"""

    origin = request.headers.get("Origin")
    if not origin:
        return
    parsed = urlsplit(origin)
    expectedHost = request.headers.get("Host", "").lower()
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != expectedHost:
        raise AuthorizationError("cross-origin write requests are not allowed")


def _authContext(request: Request) -> AuthContext:
    context = getattr(request.state, "authContext", None)
    if not isinstance(context, AuthContext):
        raise AuthenticationError("authentication is required")
    return context


def _requiredAuthService(request: Request) -> AuthService:
    service = getattr(request.app.state, "authService", None)
    if not isinstance(service, AuthService):
        raise ApiError(
            "AUTHENTICATION_DISABLED",
            409,
            "Account authentication is disabled in this development environment.",
        )
    repository = getattr(request.app.state, "authRepository", None)
    adminEmail = getattr(request.app.state, "configuredAdminEmail", None)
    adminRow = (
        repository.getUserByEmail(adminEmail)
        if isinstance(repository, AuthRepository) and isinstance(adminEmail, str)
        else None
    )
    if adminRow is None or adminRow.get("role") != UserRole.ADMIN.value:
        # 首次部署会先让容器通过内部健康检查，再经受限 stdin 创建管理员。
        # 在这几秒内拒绝注册/登录等写入，避免匿名用户抢在遗留数据认领前建号。
        raise ApiError(
            "AUTHENTICATION_INITIALIZING",
            503,
            "Account authentication is being initialized. Retry shortly.",
        )
    return service


def _publicUserPayload(user: PublicUser) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role.value,
        "status": user.status.value,
        "emailVerified": True,
        "emailVerifiedAt": user.emailVerifiedAt.isoformat(),
        "createdAt": user.createdAt.isoformat(),
        "lastLoginAt": user.lastLoginAt.isoformat() if user.lastLoginAt else None,
    }


def _adminUserPayload(user: Any) -> dict[str, Any]:
    payload = _publicUserPayload(user)
    payload.update(
        {
            "experimentCount": user.experimentCount,
            "activityCount": user.activityCount,
            "lastActivityAt": (user.lastActivityAt.isoformat() if user.lastActivityAt else None),
        }
    )
    return payload


def _authSessionPayload(
    user: PublicUser,
    *,
    csrfToken: str,
    authService: AuthService,
) -> dict[str, Any]:
    return {
        "authenticationRequired": True,
        "authenticated": True,
        "user": _publicUserPayload(user),
        "csrfToken": csrfToken,
        "legalAcceptance": authService.legalAcceptanceStatus(user.id).model_dump(mode="json"),
        "preferences": authService.repository.getUserPreferences(user.id).model_dump(mode="json"),
    }


def _setAuthCookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=7 * 24 * 60 * 60,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )


def _authenticationErrorResponse(
    request: Request,
    *,
    code: str,
    message: str,
    statusCode: int,
) -> JSONResponse:
    response = JSONResponse(
        status_code=statusCode,
        content={
            "error": {
                "code": code,
                "message": message,
                "traceId": getattr(request.state, "traceId", None),
            }
        },
        headers={"Cache-Control": "no-store"},
    )
    _addSecurityHeaders(response, getattr(request.state, "traceId", "unknown"))
    return response


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
            title=source.title,
            publisher=source.publisher,
            url=source.url,
            publishedAt=source.publishedAt,
        )
        for source in sources
    )


def _cognitionSourceBatches(
    sources: list[EventSourceInput],
    *,
    maximumSourcesPerBatch: int = 8,
    maximumCharactersPerBatch: int = 160_000,
) -> tuple[tuple[ExternalEvidenceSource, ...], ...]:
    """按模型契约和保守字符预算切分来源，避免大量上传挤爆单次上下文。"""

    batches: list[tuple[ExternalEvidenceSource, ...]] = []
    current: list[EventSourceInput] = []
    currentCharacters = 0
    for source in sources:
        sourceCharacters = len(source.rawText)
        if current and (
            len(current) >= maximumSourcesPerBatch
            or currentCharacters + sourceCharacters > maximumCharactersPerBatch
        ):
            batches.append(_cognitionSources(current))
            current = []
            currentCharacters = 0
        current.append(source)
        currentCharacters += sourceCharacters
    if current:
        batches.append(_cognitionSources(current))
    return tuple(batches)


async def _extractEventClaimsInBatches(
    cognition: CognitionService,
    *,
    credentialId: str,
    sources: list[EventSourceInput],
    maximumClaims: int,
    requestedImpactChannels: tuple[str, ...] = (
        "belief",
        "liquidity",
        "passiveFlow",
        "stopLoss",
    ),
) -> tuple[list[dict[str, Any]] | None, str]:
    """批量抽取仍保持一次 Event Pack 最多 ``maximumClaims`` 条候选主张。"""

    if not cognition.getConfig(credentialId).configured:
        return None, "RULE_FALLBACK_NO_LLM_CONFIG"

    batches = _cognitionSourceBatches(sources)
    claims: list[dict[str, Any]] = []
    seenClaims: set[tuple[str, tuple[str, ...]]] = set()
    providerLabel = ""
    modelLabel = ""
    fallbackUsed = False
    try:
        for batchIndex, batch in enumerate(batches):
            remainingClaims = maximumClaims - len(claims)
            if remainingClaims <= 0:
                break
            remainingBatches = len(batches) - batchIndex
            batchMaximum = max(1, (remainingClaims + remainingBatches - 1) // remainingBatches)
            extraction = await cognition.extractEventClaims(
                sessionId=credentialId,
                sources=batch,
                maximumClaims=batchMaximum,
                requestedImpactChannels=requestedImpactChannels,
            )
            providerLabel = extraction.provider.upper()
            modelLabel = extraction.model
            fallbackUsed = fallbackUsed or extraction.fallback_used
            for claim in extraction.event_pack_claims:
                claimKey = (
                    " ".join(str(claim.get("text", "")).split()),
                    tuple(sorted(str(item) for item in claim.get("sourceIds", []))),
                )
                if not claimKey[0] or claimKey in seenClaims:
                    continue
                seenClaims.add(claimKey)
                claims.append(claim)
                if len(claims) >= maximumClaims:
                    break
    except CredentialNotConfiguredError:
        return None, "RULE_FALLBACK_LLM_CONFIG_EXPIRED"
    except ModelGatewayError as error:
        # 不能把部分成功的批次伪装成完整抽取；失败时统一回退到确定性规则。
        return None, f"RULE_FALLBACK_{error.code.value}"

    if not claims:
        label = f"{providerLabel}_{modelLabel}" if providerLabel and modelLabel else "MODEL"
        return None, f"{label}_ABSTAINED_RULE_FALLBACK"
    mode = f"{providerLabel}_{modelLabel}"
    if len(batches) > 1:
        mode += "_BATCHED"
    if fallbackUsed:
        mode += "_FALLBACK"
    return claims, mode


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
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return []
    path = request.url.path.rstrip("/")
    clientIp = _clientIp(request)
    if path.startswith("/api/v1/auth/"):
        # 课堂演示时多个学生通常共用学校出口 IP，因此 IP 配额只承担异常流量
        # 兜底；单邮箱仍受 60 秒发送冷却，单验证码仍只有 5 次尝试机会。
        rules = [RateLimitRule(key=f"auth-write:ip:{clientIp}", limit=120, windowSeconds=300)]
        if path == "/api/v1/auth/login":
            rules.append(
                RateLimitRule(key=f"auth-login:ip:{clientIp}", limit=30, windowSeconds=300)
            )
        if path == "/api/v1/auth/verification-code":
            rules.append(
                RateLimitRule(key=f"auth-code:ip:{clientIp}", limit=60, windowSeconds=3600)
            )
        return rules
    isExperimentCreate = path == "/api/v1/experiments"
    isStudyRun = path == "/api/v1/studies/run"
    isResultInterpretation = bool(
        re.fullmatch(
            r"/api/v1/experiments/[^/]+/interpretation-chat(?:/stream)?",
            path,
        )
    )
    isFactoryProviderCall = bool(
        re.fullmatch(
            r"/api/v1/event-pack-factory/builds/[^/]+/(?:search|reader|materialize)",
            path,
        )
    )
    isLimitedWrite = (
        isExperimentCreate
        or isStudyRun
        or isResultInterpretation
        or any(
            re.fullmatch(pattern, path)
            for pattern in (
                r"/api/v1/event-packs",
                r"/api/v1/event-packs/[^/]+/extract",
                r"/api/v1/event-packs/[^/]+/claims/[^/]+/review",
                r"/api/v1/event-packs/[^/]+/claims/approve-all",
                r"/api/v1/event-packs/[^/]+/freeze",
                r"/api/v1/event-pack-factory/builds",
                r"/api/v1/event-pack-factory/builds/[^/]+",
                r"/api/v1/event-pack-factory/builds/[^/]+/(?:paste|search|reader|materialize)",
                r"/api/v1/event-pack-factory/builds/[^/]+/sources/[^/]+/(?:review|raw-text)",
                r"/api/v1/guided-workflows",
                r"/api/v1/guided-workflows/[^/]+/(?:turn|apply|advance|links)",
                r"/api/v1/scenarios(?:/[^/]+(?:/(?:clone|freeze))?)?",
                r"/api/v1/llm/(?:config|test)",
                r"/api/v1/evals/run",
                r"/api/v1/experiments/[^/]+/(start|cancel|invalidate|export)",
                r"/api/v1/experiments/[^/]+/interpretation-conversations/[^/]+",
            )
        )
    )
    if not isLimitedWrite:
        return []

    authContext = getattr(request.state, "authContext", None)
    isAuthenticatedRequest = isinstance(authContext, AuthContext)
    rawSessionId = (
        authContext.authSessionId
        if isAuthenticatedRequest
        else (
            request.cookies.get(AUTH_COOKIE_NAME)
            or request.headers.get("X-Session-ID", "missing-session")
        )[:128]
    )
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
    if isResultInterpretation:
        # 解释端点会调用外部付费模型。生产环境以已验证的 authSessionId 严格
        # 限制每个会话；共享校园 NAT 的 IP 桶只承担异常流量兜底。
        interpretationIpLimit = 120 if isAuthenticatedRequest else 8
        rules.extend(
            (
                RateLimitRule(
                    key=f"result-interpretation:ip:{clientIp}",
                    limit=interpretationIpLimit,
                ),
                RateLimitRule(
                    key=f"result-interpretation:session:{sessionDigest}",
                    limit=8,
                ),
            )
        )
    if isFactoryProviderCall:
        # 搜索、Reader 与模型物化都可能计费；校园共享 NAT 采用宽 IP 桶，
        # 真实防滥用边界落在已认证会话。
        rules.extend(
            (
                RateLimitRule(
                    key=f"factory-provider:ip:{clientIp}",
                    limit=120 if isAuthenticatedRequest else 10,
                    windowSeconds=300,
                ),
                RateLimitRule(
                    key=f"factory-provider:session:{sessionDigest}",
                    limit=12,
                    windowSeconds=300,
                ),
            )
        )
    return rules


def _clientIp(request: Request) -> str:
    directPeer = (request.client.host if request.client else "unknown-client")[:64]
    try:
        peerAddress = ipaddress.ip_address(directPeer)
    except ValueError:
        return directPeer

    # 公网客户端可以自行构造 X-Forwarded-For；只有回环或私有容器网络中的
    # 受控反向代理才有权覆盖客户端地址。生产链路由宝塔 Nginx 明确写入
    # X-Real-IP；Caddy 直连回退则读取代理追加在最右侧的 X-Forwarded-For。
    if not (peerAddress.is_loopback or peerAddress.is_private):
        return peerAddress.compressed
    candidates = [request.headers.get("X-Real-IP", "")]
    forwardedFor = request.headers.get("X-Forwarded-For", "")
    if forwardedFor:
        candidates.append(forwardedFor.rsplit(",", maxsplit=1)[-1])
    for candidate in candidates:
        try:
            return ipaddress.ip_address(candidate.strip()).compressed
        except ValueError:
            continue
    return peerAddress.compressed


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
    faviconPath = frontendDist / "favicon.svg"
    if not indexPath.is_file():
        return
    resolvedRoot = frontendDist.resolve()

    @appInstance.api_route("/{frontendPath:path}", methods=["GET", "HEAD"], include_in_schema=False)
    async def frontendFallback(frontendPath: str) -> Response:
        requestedPath = (resolvedRoot / frontendPath).resolve()
        if requestedPath.is_relative_to(resolvedRoot) and requestedPath.is_file():
            return FileResponse(requestedPath)
        if frontendPath == "favicon.ico" and faviconPath.is_file():
            return FileResponse(faviconPath, media_type="image/svg+xml")
        if frontendPath == "":
            return FileResponse(indexPath)
        return Response(status_code=404)


app = createApp()
