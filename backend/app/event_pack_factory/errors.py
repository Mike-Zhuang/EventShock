"""Event Pack Factory 的稳定、可分类错误。

错误对象只携带安全的结构化详情。供应商响应正文、API Key 和原始来源正文不得进入
``message`` 或 ``details``，这样上层即使直接记录异常也不会泄露凭据或未审阅内容。
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class FactoryErrorCode(StrEnum):
    BUILD_NOT_FOUND = "EVENT_PACK_FACTORY_BUILD_NOT_FOUND"
    SOURCE_NOT_FOUND = "EVENT_PACK_FACTORY_SOURCE_NOT_FOUND"
    REVISION_CONFLICT = "EVENT_PACK_FACTORY_REVISION_CONFLICT"
    BUILD_NOT_READY = "EVENT_PACK_FACTORY_BUILD_NOT_READY"
    INVALID_SOURCE = "EVENT_PACK_FACTORY_INVALID_SOURCE"
    CONTENT_BLOCKED = "EVENT_PACK_FACTORY_CONTENT_BLOCKED"
    SOURCE_REVIEW_REQUIRED = "EVENT_PACK_FACTORY_SOURCE_REVIEW_REQUIRED"
    DISCOVERY_SOURCE_NOT_EVIDENCE = "EVENT_PACK_FACTORY_DISCOVERY_SOURCE_NOT_EVIDENCE"
    UNSAFE_SOURCE_URL = "EVENT_PACK_FACTORY_UNSAFE_SOURCE_URL"
    READER_SOURCE_IDENTITY_INVALID = "EVENT_PACK_FACTORY_READER_SOURCE_IDENTITY_INVALID"
    READER_SOURCE_NOT_ALLOWED = "EVENT_PACK_FACTORY_READER_SOURCE_NOT_ALLOWED"
    INVALID_SEARCH_REQUEST = "EVENT_PACK_FACTORY_INVALID_SEARCH_REQUEST"
    SEARCH_AUTHENTICATION_FAILED = "EVENT_PACK_FACTORY_SEARCH_AUTHENTICATION_FAILED"
    SEARCH_RATE_LIMITED = "EVENT_PACK_FACTORY_SEARCH_RATE_LIMITED"
    SEARCH_PROVIDER_UNAVAILABLE = "EVENT_PACK_FACTORY_SEARCH_PROVIDER_UNAVAILABLE"
    SEARCH_REQUEST_FAILED = "EVENT_PACK_FACTORY_SEARCH_REQUEST_FAILED"
    SEARCH_RESPONSE_INVALID = "EVENT_PACK_FACTORY_SEARCH_RESPONSE_INVALID"
    READER_AUTHENTICATION_FAILED = "EVENT_PACK_FACTORY_READER_AUTHENTICATION_FAILED"
    READER_RATE_LIMITED = "EVENT_PACK_FACTORY_READER_RATE_LIMITED"
    READER_PROVIDER_UNAVAILABLE = "EVENT_PACK_FACTORY_READER_PROVIDER_UNAVAILABLE"
    READER_REQUEST_FAILED = "EVENT_PACK_FACTORY_READER_REQUEST_FAILED"
    READER_RESPONSE_INVALID = "EVENT_PACK_FACTORY_READER_RESPONSE_INVALID"
    EVIDENCE_SOURCE_LIMIT_EXCEEDED = "EVENT_PACK_FACTORY_EVIDENCE_SOURCE_LIMIT_EXCEEDED"
    RETAINED_TEXT_LIMIT_EXCEEDED = "EVENT_PACK_FACTORY_RETAINED_TEXT_LIMIT_EXCEEDED"
    IDEMPOTENCY_CONFLICT = "EVENT_PACK_FACTORY_IDEMPOTENCY_CONFLICT"
    IDEMPOTENCY_IN_PROGRESS = "EVENT_PACK_FACTORY_IDEMPOTENCY_IN_PROGRESS"
    IDEMPOTENCY_OUTCOME_UNKNOWN = "EVENT_PACK_FACTORY_IDEMPOTENCY_OUTCOME_UNKNOWN"


class EventPackFactoryError(Exception):
    """所有 Factory 业务错误的基类。"""

    def __init__(
        self,
        code: FactoryErrorCode,
        message: str,
        *,
        statusCode: int = 400,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.statusCode = statusCode
        self.details = dict(details or {})


class FactoryNotFoundError(EventPackFactoryError):
    """资源不存在或不属于当前 owner；两种情况故意使用相同响应。"""

    def __init__(self, *, source: bool = False) -> None:
        super().__init__(
            (FactoryErrorCode.SOURCE_NOT_FOUND if source else FactoryErrorCode.BUILD_NOT_FOUND),
            "The requested Event Pack Factory resource was not found.",
            statusCode=404,
        )


class FactoryRevisionConflictError(EventPackFactoryError):
    def __init__(self, *, expectedRevision: int, actualRevision: int) -> None:
        super().__init__(
            FactoryErrorCode.REVISION_CONFLICT,
            "The Event Pack Factory build changed; reload it before retrying.",
            statusCode=409,
            details={
                "expectedRevision": expectedRevision,
                "actualRevision": actualRevision,
            },
        )


class FactoryValidationError(EventPackFactoryError):
    def __init__(
        self,
        code: FactoryErrorCode,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(code, message, statusCode=422, details=details)


class FactorySearchError(EventPackFactoryError):
    """固定搜索端点的安全供应商错误。"""


class FactoryReaderError(EventPackFactoryError):
    """固定 Reader 端点的安全供应商错误。"""


class FactoryIdempotencyError(EventPackFactoryError):
    """收费或创建型操作的稳定幂等错误，不包含供应商正文。"""
