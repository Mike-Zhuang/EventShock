"""Event Pack Factory 的独立 SQLite 仓库。

该仓库自行建表，便于在现有 ``Database.initialize`` 之外增量接入。所有读取都把
``owner_user_id`` 作为查询条件；不存在与越权访问返回同一种 Not Found 错误。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.event_pack_factory.errors import (
    FactoryErrorCode,
    FactoryIdempotencyError,
    FactoryNotFoundError,
    FactoryRevisionConflictError,
    FactoryValidationError,
)
from backend.app.event_pack_factory.models import (
    BuildSnapshot,
    BuildStatus,
    EventPackFactoryBuild,
    EventPackFactorySource,
    EvidenceRole,
    FactorySourceRawText,
    SearchEngine,
    SearchRunRecord,
    SourceInputKind,
    SourceReviewStatus,
    SourceSecurityDecision,
)

MAX_ACTIVE_EVIDENCE_SOURCES_PER_BUILD = 24
MAX_RETAINED_RAW_TEXT_CHARACTERS_PER_BUILD = 400_000
FACTORY_BUILD_RETENTION_DAYS = 7


def utcNowDateTime() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _ApprovedEvidencePayload:
    """内部物化载荷；不能导出为公开 API 模型。"""

    source: EventPackFactorySource
    rawText: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    state: str
    responseJson: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class FactoryCleanupResult:
    deletedBuildCount: int
    walCheckpointSucceeded: bool | None


class EventPackFactoryRepository:
    def __init__(self, databasePath: Path) -> None:
        self.databasePath = databasePath
        self._writeLock = threading.RLock()

    def initialize(self) -> None:
        self.databasePath.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                PRAGMA secure_delete=ON;
                CREATE TABLE IF NOT EXISTS event_pack_factory_builds (
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL CHECK(length(owner_user_id) BETWEEN 1 AND 128),
                    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
                    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'REVIEW_READY')),
                    revision INTEGER NOT NULL DEFAULT 0 CHECK(revision >= 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    retention_expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_event_pack_factory_builds_owner_updated
                ON event_pack_factory_builds(owner_user_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS event_pack_factory_search_runs (
                    id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    engine TEXT NOT NULL CHECK(engine IN (
                        'search_std', 'search_pro', 'search_pro_sogou', 'search_pro_quark'
                    )),
                    query TEXT NOT NULL CHECK(length(query) BETWEEN 1 AND 70),
                    query_hash TEXT NOT NULL CHECK(length(query_hash) = 64),
                    request_parameters_json TEXT NOT NULL,
                    provider_request_id TEXT NOT NULL,
                    estimated_cost_cny REAL NOT NULL CHECK(estimated_cost_cny >= 0),
                    result_count INTEGER NOT NULL CHECK(result_count >= 0),
                    dropped_result_count INTEGER NOT NULL CHECK(dropped_result_count >= 0),
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (build_id) REFERENCES event_pack_factory_builds(id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_event_pack_factory_search_runs_build
                ON event_pack_factory_search_runs(build_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS event_pack_factory_sources (
                    id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK(kind IN ('PASTE', 'SEARCH_RESULT', 'READER')),
                    evidence_role TEXT NOT NULL CHECK(
                        evidence_role IN ('EVIDENCE', 'DISCOVERY_ONLY')
                    ),
                    review_status TEXT NOT NULL CHECK(
                        review_status IN ('PENDING', 'APPROVED', 'REJECTED')
                    ),
                    security_decision TEXT NOT NULL CHECK(
                        security_decision IN ('ALLOW', 'REVIEW')
                    ),
                    title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 300),
                    publisher TEXT NOT NULL CHECK(length(publisher) BETWEEN 1 AND 200),
                    url TEXT,
                    published_at TEXT,
                    known_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
                    content_length INTEGER NOT NULL CHECK(content_length >= 0),
                    review_summary TEXT NOT NULL CHECK(length(review_summary) <= 2000),
                    verified_evidence_quotes_json TEXT NOT NULL,
                    search_run_id TEXT,
                    parent_source_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (build_id) REFERENCES event_pack_factory_builds(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (search_run_id) REFERENCES event_pack_factory_search_runs(id)
                        ON DELETE SET NULL,
                    FOREIGN KEY (parent_source_id) REFERENCES event_pack_factory_sources(id)
                        ON DELETE RESTRICT
                );
                CREATE INDEX IF NOT EXISTS idx_event_pack_factory_sources_build
                ON event_pack_factory_sources(build_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_event_pack_factory_sources_parent
                ON event_pack_factory_sources(parent_source_id);

                CREATE TABLE IF NOT EXISTS event_pack_factory_source_payloads (
                    source_id TEXT PRIMARY KEY,
                    build_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL CHECK(
                        length(owner_user_id) BETWEEN 1 AND 128
                    ),
                    raw_text TEXT NOT NULL CHECK(
                        length(raw_text) BETWEEN 1 AND 100000
                    ),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (source_id) REFERENCES event_pack_factory_sources(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (build_id) REFERENCES event_pack_factory_builds(id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_event_pack_factory_payloads_owner_build
                ON event_pack_factory_source_payloads(owner_user_id, build_id);

                CREATE TABLE IF NOT EXISTS event_pack_factory_idempotency (
                    owner_user_id TEXT NOT NULL,
                    operation TEXT NOT NULL CHECK(operation IN ('SEARCH', 'READER', 'MATERIALIZE')),
                    client_request_id TEXT NOT NULL,
                    build_id TEXT NOT NULL,
                    payload_hash TEXT NOT NULL CHECK(length(payload_hash) = 64),
                    status TEXT NOT NULL CHECK(status IN ('PENDING', 'SUCCEEDED', 'FAILED')),
                    response_json TEXT,
                    failure_code TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (owner_user_id, operation, client_request_id),
                    FOREIGN KEY (build_id) REFERENCES event_pack_factory_builds(id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_event_pack_factory_idempotency_build
                ON event_pack_factory_idempotency(build_id);
                """
            )
            self._migrateBuildRetention(connection)
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_event_pack_factory_builds_retention
                ON event_pack_factory_builds(retention_expires_at)
                """
            )

    @staticmethod
    def _migrateBuildRetention(connection: sqlite3.Connection) -> None:
        """为早期数据库增加明确到期时间，不读取或重写原文。"""

        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(event_pack_factory_builds)").fetchall()
        }
        if "retention_expires_at" not in columns:
            connection.execute(
                "ALTER TABLE event_pack_factory_builds ADD COLUMN retention_expires_at TEXT"
            )
        rows = connection.execute(
            """
            SELECT id, updated_at FROM event_pack_factory_builds
            WHERE retention_expires_at IS NULL OR retention_expires_at = ''
            """
        ).fetchall()
        for row in rows:
            updatedAt = datetime.fromisoformat(row["updated_at"])
            expiresAt = updatedAt + timedelta(days=FACTORY_BUILD_RETENTION_DAYS)
            connection.execute(
                """
                UPDATE event_pack_factory_builds
                SET retention_expires_at = ?
                WHERE id = ?
                """,
                (expiresAt.isoformat(), row["id"]),
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.databasePath, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA secure_delete=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def createBuild(
        self,
        *,
        buildId: str,
        ownerUserId: str,
        title: str,
        now: datetime | None = None,
    ) -> EventPackFactoryBuild:
        timestamp = now or utcNowDateTime()
        expiresAt = timestamp + timedelta(days=FACTORY_BUILD_RETENTION_DAYS)
        with self._writeLock, self.connection() as connection:
            connection.execute(
                """
                INSERT INTO event_pack_factory_builds (
                    id, owner_user_id, title, status, revision, created_at, updated_at,
                    retention_expires_at
                ) VALUES (?, ?, ?, 'DRAFT', 0, ?, ?, ?)
                """,
                (
                    buildId,
                    ownerUserId,
                    title,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                    expiresAt.isoformat(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM event_pack_factory_builds WHERE id = ?",
                (buildId,),
            ).fetchone()
        if row is None:
            raise RuntimeError("created build could not be loaded")
        return self._buildFromRow(row)

    def getSnapshot(self, *, ownerUserId: str, buildId: str) -> BuildSnapshot:
        with self.connection() as connection:
            buildRow = self._ownedBuildRow(connection, ownerUserId, buildId)
            sourceRows = connection.execute(
                """
                SELECT * FROM event_pack_factory_sources
                WHERE build_id = ?
                ORDER BY created_at, id
                """,
                (buildId,),
            ).fetchall()
            searchRows = connection.execute(
                """
                SELECT * FROM event_pack_factory_search_runs
                WHERE build_id = ?
                ORDER BY created_at, id
                """,
                (buildId,),
            ).fetchall()
        return BuildSnapshot(
            build=self._buildFromRow(buildRow),
            sources=tuple(self._sourceFromRow(row) for row in sourceRows),
            searchRuns=tuple(self._searchRunFromRow(row) for row in searchRows),
        )

    def listBuilds(self, *, ownerUserId: str, limit: int = 50) -> tuple[EventPackFactoryBuild, ...]:
        boundedLimit = min(max(limit, 1), 100)
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM event_pack_factory_builds
                WHERE owner_user_id = ?
                ORDER BY updated_at DESC, id
                LIMIT ?
                """,
                (ownerUserId, boundedLimit),
            ).fetchall()
        return tuple(self._buildFromRow(row) for row in rows)

    def addSource(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        expectedRevision: int,
        source: EventPackFactorySource,
        rawText: str | None = None,
    ) -> EventPackFactoryBuild:
        with self._writeLock, self.connection() as connection:
            self._requireRevision(connection, ownerUserId, buildId, expectedRevision)
            self._insertSource(connection, source)
            if source.evidenceRole is EvidenceRole.EVIDENCE:
                if rawText is None:
                    raise RuntimeError("evidence sources require an internal raw text payload")
                self._insertSourcePayload(
                    connection,
                    ownerUserId=ownerUserId,
                    source=source,
                    rawText=rawText,
                )
            elif rawText is not None:
                raise RuntimeError("discovery-only sources must not retain raw text payloads")
            return self._advanceBuild(connection, buildId, expectedRevision)

    def recordSearch(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        expectedRevision: int,
        searchRun: SearchRunRecord,
        sources: Sequence[EventPackFactorySource],
    ) -> EventPackFactoryBuild:
        with self._writeLock, self.connection() as connection:
            self._requireRevision(connection, ownerUserId, buildId, expectedRevision)
            connection.execute(
                """
                INSERT INTO event_pack_factory_search_runs (
                    id, build_id, engine, query, query_hash, request_parameters_json,
                    provider_request_id, estimated_cost_cny, result_count,
                    dropped_result_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    searchRun.id,
                    buildId,
                    searchRun.engine.value,
                    searchRun.query,
                    searchRun.queryHash,
                    json.dumps(
                        searchRun.requestParameters,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    searchRun.providerRequestId,
                    searchRun.estimatedCostCny,
                    searchRun.resultCount,
                    searchRun.droppedResultCount,
                    searchRun.createdAt.isoformat(),
                ),
            )
            for source in sources:
                self._insertSource(connection, source)
            return self._advanceBuild(connection, buildId, expectedRevision)

    def reviewSource(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        sourceId: str,
        expectedRevision: int,
        reviewStatus: SourceReviewStatus,
        now: datetime | None = None,
    ) -> tuple[EventPackFactoryBuild, EventPackFactorySource]:
        timestamp = now or utcNowDateTime()
        with self._writeLock, self.connection() as connection:
            self._requireRevision(connection, ownerUserId, buildId, expectedRevision)
            sourceRow = connection.execute(
                """
                SELECT source.* FROM event_pack_factory_sources AS source
                JOIN event_pack_factory_builds AS build ON build.id = source.build_id
                WHERE source.id = ? AND source.build_id = ? AND build.owner_user_id = ?
                """,
                (sourceId, buildId, ownerUserId),
            ).fetchone()
            if sourceRow is None:
                raise FactoryNotFoundError(source=True)
            currentStatus = SourceReviewStatus(sourceRow["review_status"])
            evidenceRole = EvidenceRole(sourceRow["evidence_role"])
            if (
                currentStatus is SourceReviewStatus.REJECTED
                and reviewStatus is SourceReviewStatus.APPROVED
            ):
                raise FactoryValidationError(
                    FactoryErrorCode.SOURCE_REVIEW_REQUIRED,
                    "Rejected source text has been deleted; add the source again before approval.",
                )
            if (
                evidenceRole is EvidenceRole.EVIDENCE
                and reviewStatus is SourceReviewStatus.APPROVED
            ):
                payloadRow = connection.execute(
                    """
                    SELECT 1 FROM event_pack_factory_source_payloads
                    WHERE source_id = ? AND build_id = ? AND owner_user_id = ?
                    """,
                    (sourceId, buildId, ownerUserId),
                ).fetchone()
                if payloadRow is None:
                    raise FactoryValidationError(
                        FactoryErrorCode.SOURCE_REVIEW_REQUIRED,
                        "The source text is unavailable; add the source again before approval.",
                    )
            if reviewStatus is SourceReviewStatus.REJECTED:
                # 拒绝意味着撤销后续使用授权，原文必须在同一事务中物理清除。
                connection.execute(
                    """
                    UPDATE event_pack_factory_sources
                    SET review_status = 'REJECTED',
                        review_summary = '[SOURCE_REJECTED_AND_TEXT_DELETED]',
                        verified_evidence_quotes_json = '[]',
                        updated_at = ?
                    WHERE id = ? AND build_id = ?
                    """,
                    (timestamp.isoformat(), sourceId, buildId),
                )
                connection.execute(
                    """
                    DELETE FROM event_pack_factory_source_payloads
                    WHERE source_id = ? AND build_id = ? AND owner_user_id = ?
                    """,
                    (sourceId, buildId, ownerUserId),
                )
            else:
                connection.execute(
                    """
                    UPDATE event_pack_factory_sources
                    SET review_status = ?, updated_at = ?
                    WHERE id = ? AND build_id = ?
                    """,
                    (reviewStatus.value, timestamp.isoformat(), sourceId, buildId),
                )
            build = self._advanceBuild(connection, buildId, expectedRevision)
            updatedRow = connection.execute(
                "SELECT * FROM event_pack_factory_sources WHERE id = ?",
                (sourceId,),
            ).fetchone()
        if updatedRow is None:
            raise RuntimeError("reviewed source could not be loaded")
        if reviewStatus is SourceReviewStatus.REJECTED:
            self._checkpointSensitiveDeletion()
        return build, self._sourceFromRow(updatedRow)

    def getSource(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        sourceId: str,
    ) -> EventPackFactorySource:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT source.* FROM event_pack_factory_sources AS source
                JOIN event_pack_factory_builds AS build ON build.id = source.build_id
                WHERE source.id = ? AND source.build_id = ? AND build.owner_user_id = ?
                """,
                (sourceId, buildId, ownerUserId),
            ).fetchone()
        if row is None:
            raise FactoryNotFoundError(source=True)
        return self._sourceFromRow(row)

    def getSourceRawText(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        sourceId: str,
    ) -> FactorySourceRawText:
        """按 owner 边界读取完整原文；调用方必须显式设置 no-store。"""

        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT source.content_hash, source.content_length, payload.raw_text,
                       build.revision, build.retention_expires_at
                FROM event_pack_factory_sources AS source
                JOIN event_pack_factory_builds AS build ON build.id = source.build_id
                JOIN event_pack_factory_source_payloads AS payload
                  ON payload.source_id = source.id
                 AND payload.build_id = source.build_id
                 AND payload.owner_user_id = build.owner_user_id
                WHERE source.id = ? AND source.build_id = ? AND build.owner_user_id = ?
                  AND source.evidence_role = 'EVIDENCE'
                  AND source.review_status != 'REJECTED'
                """,
                (sourceId, buildId, ownerUserId),
            ).fetchone()
        if row is None:
            raise FactoryNotFoundError(source=True)
        rawText = str(row["raw_text"])
        if (
            len(rawText) != int(row["content_length"])
            or hashlib.sha256(rawText.encode("utf-8")).hexdigest() != row["content_hash"]
        ):
            raise RuntimeError("stored Event Pack Factory source payload is inconsistent")
        return FactorySourceRawText(
            buildId=buildId,
            sourceId=sourceId,
            revision=int(row["revision"]),
            rawText=rawText,
            contentHash=str(row["content_hash"]),
            contentLength=int(row["content_length"]),
            retentionExpiresAt=datetime.fromisoformat(row["retention_expires_at"]),
        )

    def updateSourceRawText(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        sourceId: str,
        expectedRevision: int,
        source: EventPackFactorySource,
        rawText: str,
        now: datetime | None = None,
    ) -> tuple[EventPackFactoryBuild, EventPackFactorySource]:
        """替换原文并强制重置人工审核，任何旧批准不得跨 revision 继承。"""

        timestamp = now or utcNowDateTime()
        with self._writeLock, self.connection() as connection:
            self._requireRevision(connection, ownerUserId, buildId, expectedRevision)
            existing = connection.execute(
                """
                SELECT source.* FROM event_pack_factory_sources AS source
                JOIN event_pack_factory_builds AS build ON build.id = source.build_id
                JOIN event_pack_factory_source_payloads AS payload
                  ON payload.source_id = source.id
                 AND payload.build_id = source.build_id
                 AND payload.owner_user_id = build.owner_user_id
                WHERE source.id = ? AND source.build_id = ? AND build.owner_user_id = ?
                  AND source.evidence_role = 'EVIDENCE'
                  AND source.review_status != 'REJECTED'
                """,
                (sourceId, buildId, ownerUserId),
            ).fetchone()
            if existing is None:
                raise FactoryNotFoundError(source=True)
            if source.kind is not SourceInputKind(existing["kind"]):
                raise RuntimeError("source kind cannot change during raw-text revision")
            if (
                len(rawText) != source.contentLength
                or hashlib.sha256(rawText.encode("utf-8")).hexdigest() != source.contentHash
            ):
                raise RuntimeError("source metadata does not match the revised raw text")

            retainedCharacters = int(
                connection.execute(
                    """
                    SELECT COALESCE(SUM(source.content_length), 0)
                    FROM event_pack_factory_source_payloads AS payload
                    JOIN event_pack_factory_sources AS source
                      ON source.id = payload.source_id
                     AND source.build_id = payload.build_id
                    WHERE payload.build_id = ? AND source.id != ?
                    """,
                    (buildId, sourceId),
                ).fetchone()[0]
            )
            if retainedCharacters + len(rawText) > MAX_RETAINED_RAW_TEXT_CHARACTERS_PER_BUILD:
                raise FactoryValidationError(
                    FactoryErrorCode.RETAINED_TEXT_LIMIT_EXCEEDED,
                    "The build exceeds the retained source-text limit.",
                    details={
                        "maximumCharacters": MAX_RETAINED_RAW_TEXT_CHARACTERS_PER_BUILD,
                        "retainedCharacters": retainedCharacters,
                        "candidateCharacters": len(rawText),
                    },
                )
            connection.execute(
                """
                UPDATE event_pack_factory_sources
                SET review_status = 'PENDING', security_decision = ?,
                    content_hash = ?, content_length = ?, review_summary = ?,
                    verified_evidence_quotes_json = ?, updated_at = ?
                WHERE id = ? AND build_id = ?
                """,
                (
                    source.securityDecision.value,
                    source.contentHash,
                    source.contentLength,
                    source.reviewSummary,
                    json.dumps(
                        source.verifiedEvidenceQuotes,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    timestamp.isoformat(),
                    sourceId,
                    buildId,
                ),
            )
            connection.execute(
                """
                UPDATE event_pack_factory_source_payloads
                SET raw_text = ?, updated_at = ?
                WHERE source_id = ? AND build_id = ? AND owner_user_id = ?
                """,
                (rawText, timestamp.isoformat(), sourceId, buildId, ownerUserId),
            )
            build = self._advanceBuild(connection, buildId, expectedRevision)
            row = connection.execute(
                "SELECT * FROM event_pack_factory_sources WHERE id = ?",
                (sourceId,),
            ).fetchone()
        if row is None:
            raise RuntimeError("revised source could not be loaded")
        return build, self._sourceFromRow(row)

    def listEligibleEvidenceSources(
        self,
        *,
        ownerUserId: str,
        buildId: str,
    ) -> tuple[EventPackFactorySource, ...]:
        with self.connection() as connection:
            self._ownedBuildRow(connection, ownerUserId, buildId)
            rows = connection.execute(
                """
                SELECT source.* FROM event_pack_factory_sources AS source
                JOIN event_pack_factory_source_payloads AS payload
                  ON payload.source_id = source.id
                 AND payload.build_id = source.build_id
                 AND payload.owner_user_id = ?
                WHERE source.build_id = ?
                  AND source.evidence_role = 'EVIDENCE'
                  AND source.review_status = 'APPROVED'
                ORDER BY source.created_at, source.id
                """,
                (ownerUserId, buildId),
            ).fetchall()
        return tuple(self._sourceFromRow(row) for row in rows)

    def _listApprovedEvidencePayloads(
        self,
        *,
        ownerUserId: str,
        buildId: str,
    ) -> tuple[_ApprovedEvidencePayload, ...]:
        """只供服务层物化使用；公开查询永远不读取 ``raw_text``。"""

        with self.connection() as connection:
            self._ownedBuildRow(connection, ownerUserId, buildId)
            rows = connection.execute(
                """
                SELECT source.*, payload.raw_text AS internal_raw_text
                FROM event_pack_factory_sources AS source
                JOIN event_pack_factory_source_payloads AS payload
                  ON payload.source_id = source.id
                 AND payload.build_id = source.build_id
                 AND payload.owner_user_id = ?
                WHERE source.build_id = ?
                  AND source.evidence_role = 'EVIDENCE'
                  AND source.review_status = 'APPROVED'
                ORDER BY source.created_at, source.id
                """,
                (ownerUserId, buildId),
            ).fetchall()
        payloads: list[_ApprovedEvidencePayload] = []
        for row in rows:
            rawText = str(row["internal_raw_text"])
            source = self._sourceFromRow(row)
            if (
                len(rawText) != source.contentLength
                or hashlib.sha256(rawText.encode("utf-8")).hexdigest() != source.contentHash
            ):
                raise RuntimeError("stored Event Pack Factory source payload is inconsistent")
            payloads.append(_ApprovedEvidencePayload(source=source, rawText=rawText))
        return tuple(payloads)

    def deleteBuild(
        self,
        *,
        ownerUserId: str,
        buildId: str,
        expectedRevision: int,
    ) -> bool:
        """删除 owner 自己的构建及全部原始资料；越权与不存在等价。"""

        with self._writeLock, self.connection() as connection:
            self._requireRevision(connection, ownerUserId, buildId, expectedRevision)
            self._deleteBuildRows(connection, buildId=buildId, ownerUserId=ownerUserId)
            result = connection.execute(
                """
                DELETE FROM event_pack_factory_builds
                WHERE id = ? AND owner_user_id = ? AND revision = ?
                """,
                (buildId, ownerUserId, expectedRevision),
            )
            if result.rowcount != 1:
                raise FactoryRevisionConflictError(
                    expectedRevision=expectedRevision,
                    actualRevision=-1,
                )
        return self._checkpointSensitiveDeletion()

    def claimIdempotency(
        self,
        *,
        ownerUserId: str,
        operation: str,
        clientRequestId: str,
        buildId: str,
        payloadHash: str,
        now: datetime | None = None,
    ) -> IdempotencyClaim:
        """原子占用请求键；已完成结果可恢复，未知计费结果绝不自动重放。"""

        timestamp = (now or utcNowDateTime()).isoformat()
        with self._writeLock, self.connection() as connection:
            self._ownedBuildRow(connection, ownerUserId, buildId)
            result = connection.execute(
                """
                INSERT OR IGNORE INTO event_pack_factory_idempotency (
                    owner_user_id, operation, client_request_id, build_id, payload_hash,
                    status, response_json, failure_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'PENDING', NULL, NULL, ?, ?)
                """,
                (
                    ownerUserId,
                    operation,
                    clientRequestId,
                    buildId,
                    payloadHash,
                    timestamp,
                    timestamp,
                ),
            )
            if result.rowcount == 1:
                return IdempotencyClaim(state="CLAIMED")
            row = connection.execute(
                """
                SELECT build_id, payload_hash, status, response_json
                FROM event_pack_factory_idempotency
                WHERE owner_user_id = ? AND operation = ? AND client_request_id = ?
                """,
                (ownerUserId, operation, clientRequestId),
            ).fetchone()
        if row is None:
            raise RuntimeError("idempotency record could not be loaded")
        if row["build_id"] != buildId or row["payload_hash"] != payloadHash:
            raise FactoryIdempotencyError(
                FactoryErrorCode.IDEMPOTENCY_CONFLICT,
                "clientRequestId was already used with a different request payload.",
                statusCode=409,
            )
        if row["status"] == "SUCCEEDED" and row["response_json"]:
            return IdempotencyClaim(state="SUCCEEDED", responseJson=row["response_json"])
        if row["status"] == "PENDING":
            return IdempotencyClaim(state="PENDING")
        return IdempotencyClaim(state="FAILED")

    def completeIdempotency(
        self,
        *,
        ownerUserId: str,
        operation: str,
        clientRequestId: str,
        payloadHash: str,
        responseJson: str,
    ) -> None:
        with self._writeLock, self.connection() as connection:
            result = connection.execute(
                """
                UPDATE event_pack_factory_idempotency
                SET status = 'SUCCEEDED', response_json = ?, failure_code = NULL,
                    updated_at = ?
                WHERE owner_user_id = ? AND operation = ? AND client_request_id = ?
                  AND payload_hash = ? AND status = 'PENDING'
                """,
                (
                    responseJson,
                    utcNowDateTime().isoformat(),
                    ownerUserId,
                    operation,
                    clientRequestId,
                    payloadHash,
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("idempotency completion state changed unexpectedly")

    def recoverIdempotency(
        self,
        *,
        ownerUserId: str,
        operation: str,
        clientRequestId: str,
        payloadHash: str,
        responseJson: str,
    ) -> None:
        """只在确定性业务对象已落库时，把未知结果恢复为可重放成功。"""

        with self._writeLock, self.connection() as connection:
            result = connection.execute(
                """
                UPDATE event_pack_factory_idempotency
                SET status = 'SUCCEEDED', response_json = ?, failure_code = NULL,
                    updated_at = ?
                WHERE owner_user_id = ? AND operation = ? AND client_request_id = ?
                  AND payload_hash = ? AND status IN ('PENDING', 'FAILED')
                """,
                (
                    responseJson,
                    utcNowDateTime().isoformat(),
                    ownerUserId,
                    operation,
                    clientRequestId,
                    payloadHash,
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("idempotency recovery state changed unexpectedly")

    def failIdempotency(
        self,
        *,
        ownerUserId: str,
        operation: str,
        clientRequestId: str,
        payloadHash: str,
        failureCode: str,
    ) -> None:
        with self._writeLock, self.connection() as connection:
            connection.execute(
                """
                UPDATE event_pack_factory_idempotency
                SET status = 'FAILED', failure_code = ?, updated_at = ?
                WHERE owner_user_id = ? AND operation = ? AND client_request_id = ?
                  AND payload_hash = ? AND status = 'PENDING'
                """,
                (
                    failureCode[:120],
                    utcNowDateTime().isoformat(),
                    ownerUserId,
                    operation,
                    clientRequestId,
                    payloadHash,
                ),
            )

    def cleanupExpiredBuilds(
        self,
        *,
        now: datetime | None = None,
    ) -> FactoryCleanupResult:
        """在 Factory 请求入口调用；到期后清除原文和全部未物化工作状态。"""

        threshold = (now or utcNowDateTime()).isoformat()
        deleted = 0
        with self._writeLock, self.connection() as connection:
            rows = connection.execute(
                """
                SELECT id, owner_user_id FROM event_pack_factory_builds
                WHERE retention_expires_at <= ?
                """,
                (threshold,),
            ).fetchall()
            for row in rows:
                self._deleteBuildRows(
                    connection,
                    buildId=str(row["id"]),
                    ownerUserId=str(row["owner_user_id"]),
                )
                result = connection.execute(
                    """
                    DELETE FROM event_pack_factory_builds
                    WHERE id = ? AND owner_user_id = ?
                    """,
                    (row["id"], row["owner_user_id"]),
                )
                deleted += max(result.rowcount, 0)
        checkpoint = self._checkpointSensitiveDeletion() if deleted else None
        return FactoryCleanupResult(
            deletedBuildCount=deleted,
            walCheckpointSucceeded=checkpoint,
        )

    def _requireRevision(
        self,
        connection: sqlite3.Connection,
        ownerUserId: str,
        buildId: str,
        expectedRevision: int,
    ) -> sqlite3.Row:
        row = self._ownedBuildRow(connection, ownerUserId, buildId)
        actualRevision = int(row["revision"])
        if actualRevision != expectedRevision:
            raise FactoryRevisionConflictError(
                expectedRevision=expectedRevision,
                actualRevision=actualRevision,
            )
        return row

    def _checkpointSensitiveDeletion(self) -> bool:
        """尽力截断 WAL；删除事务已经提交，checkpoint 失败不得恢复敏感数据。"""

        try:
            with sqlite3.connect(self.databasePath, timeout=30) as connection:
                row = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                return row is not None and int(row[0]) == 0
        except sqlite3.Error:
            return False

    @staticmethod
    def _deleteBuildRows(
        connection: sqlite3.Connection,
        *,
        buildId: str,
        ownerUserId: str,
    ) -> None:
        connection.execute(
            """
            DELETE FROM event_pack_factory_source_payloads
            WHERE build_id = ? AND owner_user_id = ?
            """,
            (buildId, ownerUserId),
        )
        # 先删 Reader 子来源，兼容 parent_source_id RESTRICT。
        connection.execute(
            """
            DELETE FROM event_pack_factory_sources
            WHERE build_id = ? AND parent_source_id IS NOT NULL
            """,
            (buildId,),
        )
        connection.execute(
            "DELETE FROM event_pack_factory_sources WHERE build_id = ?",
            (buildId,),
        )
        connection.execute(
            "DELETE FROM event_pack_factory_search_runs WHERE build_id = ?",
            (buildId,),
        )
        connection.execute(
            "DELETE FROM event_pack_factory_idempotency WHERE build_id = ?",
            (buildId,),
        )

    @staticmethod
    def _ownedBuildRow(
        connection: sqlite3.Connection,
        ownerUserId: str,
        buildId: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM event_pack_factory_builds
            WHERE id = ? AND owner_user_id = ?
            """,
            (buildId, ownerUserId),
        ).fetchone()
        if row is None:
            raise FactoryNotFoundError()
        return row

    def _advanceBuild(
        self,
        connection: sqlite3.Connection,
        buildId: str,
        previousRevision: int,
    ) -> EventPackFactoryBuild:
        now = utcNowDateTime()
        timestamp = now.isoformat()
        retentionExpiresAt = (now + timedelta(days=FACTORY_BUILD_RETENTION_DAYS)).isoformat()
        readyRow = connection.execute(
            """
            SELECT 1 FROM event_pack_factory_sources AS source
            JOIN event_pack_factory_source_payloads AS payload
              ON payload.source_id = source.id
             AND payload.build_id = source.build_id
            WHERE source.build_id = ?
              AND source.evidence_role = 'EVIDENCE'
              AND source.review_status = 'APPROVED'
            LIMIT 1
            """,
            (buildId,),
        ).fetchone()
        status = BuildStatus.REVIEW_READY if readyRow is not None else BuildStatus.DRAFT
        result = connection.execute(
            """
            UPDATE event_pack_factory_builds
            SET revision = revision + 1, status = ?, updated_at = ?,
                retention_expires_at = ?
            WHERE id = ? AND revision = ?
            """,
            (status.value, timestamp, retentionExpiresAt, buildId, previousRevision),
        )
        if result.rowcount != 1:
            row = connection.execute(
                "SELECT revision FROM event_pack_factory_builds WHERE id = ?",
                (buildId,),
            ).fetchone()
            actualRevision = int(row["revision"]) if row is not None else -1
            raise FactoryRevisionConflictError(
                expectedRevision=previousRevision,
                actualRevision=actualRevision,
            )
        row = connection.execute(
            "SELECT * FROM event_pack_factory_builds WHERE id = ?",
            (buildId,),
        ).fetchone()
        if row is None:
            raise RuntimeError("updated build could not be loaded")
        return self._buildFromRow(row)

    @staticmethod
    def _insertSource(
        connection: sqlite3.Connection,
        source: EventPackFactorySource,
    ) -> None:
        connection.execute(
            """
            INSERT INTO event_pack_factory_sources (
                id, build_id, kind, evidence_role, review_status, security_decision,
                title, publisher, url, published_at, known_at, content_hash,
                content_length, review_summary, verified_evidence_quotes_json,
                search_run_id, parent_source_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source.id,
                source.buildId,
                source.kind.value,
                source.evidenceRole.value,
                source.reviewStatus.value,
                source.securityDecision.value,
                source.title,
                source.publisher,
                source.url,
                source.publishedAt.isoformat() if source.publishedAt else None,
                source.knownAt.isoformat(),
                source.contentHash,
                source.contentLength,
                source.reviewSummary,
                json.dumps(
                    source.verifiedEvidenceQuotes,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                source.searchRunId,
                source.parentSourceId,
                source.createdAt.isoformat(),
                source.updatedAt.isoformat(),
            ),
        )

    @staticmethod
    def _insertSourcePayload(
        connection: sqlite3.Connection,
        *,
        ownerUserId: str,
        source: EventPackFactorySource,
        rawText: str,
    ) -> None:
        if (
            len(rawText) != source.contentLength
            or hashlib.sha256(rawText.encode("utf-8")).hexdigest() != source.contentHash
        ):
            raise RuntimeError("source metadata does not match the internal raw text payload")

        activeEvidenceCount = int(
            connection.execute(
                """
                SELECT COUNT(*) FROM event_pack_factory_sources
                WHERE build_id = ?
                  AND evidence_role = 'EVIDENCE'
                  AND review_status != 'REJECTED'
                """,
                (source.buildId,),
            ).fetchone()[0]
        )
        if activeEvidenceCount > MAX_ACTIVE_EVIDENCE_SOURCES_PER_BUILD:
            raise FactoryValidationError(
                FactoryErrorCode.EVIDENCE_SOURCE_LIMIT_EXCEEDED,
                "A build may retain at most 24 active evidence sources.",
                details={
                    "maximumSources": MAX_ACTIVE_EVIDENCE_SOURCES_PER_BUILD,
                    "activeSources": activeEvidenceCount - 1,
                },
            )

        retainedCharacters = int(
            connection.execute(
                """
                SELECT COALESCE(SUM(source.content_length), 0)
                FROM event_pack_factory_source_payloads AS payload
                JOIN event_pack_factory_sources AS source
                  ON source.id = payload.source_id
                 AND source.build_id = payload.build_id
                WHERE payload.build_id = ?
                """,
                (source.buildId,),
            ).fetchone()[0]
        )
        if retainedCharacters + len(rawText) > MAX_RETAINED_RAW_TEXT_CHARACTERS_PER_BUILD:
            raise FactoryValidationError(
                FactoryErrorCode.RETAINED_TEXT_LIMIT_EXCEEDED,
                "The build exceeds the retained source-text limit.",
                details={
                    "maximumCharacters": MAX_RETAINED_RAW_TEXT_CHARACTERS_PER_BUILD,
                    "retainedCharacters": retainedCharacters,
                    "candidateCharacters": len(rawText),
                },
            )

        connection.execute(
            """
            INSERT INTO event_pack_factory_source_payloads (
                source_id, build_id, owner_user_id, raw_text, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source.id,
                source.buildId,
                ownerUserId,
                rawText,
                source.createdAt.isoformat(),
                source.updatedAt.isoformat(),
            ),
        )

    @staticmethod
    def _buildFromRow(row: sqlite3.Row) -> EventPackFactoryBuild:
        return EventPackFactoryBuild(
            id=row["id"],
            ownerUserId=row["owner_user_id"],
            title=row["title"],
            status=BuildStatus(row["status"]),
            revision=row["revision"],
            createdAt=datetime.fromisoformat(row["created_at"]),
            updatedAt=datetime.fromisoformat(row["updated_at"]),
            retentionExpiresAt=datetime.fromisoformat(row["retention_expires_at"]),
        )

    @staticmethod
    def _sourceFromRow(row: sqlite3.Row) -> EventPackFactorySource:
        quotes = json.loads(row["verified_evidence_quotes_json"])
        if not isinstance(quotes, list) or not all(isinstance(item, str) for item in quotes):
            raise RuntimeError("stored Event Pack Factory quote data is invalid")
        return EventPackFactorySource(
            id=row["id"],
            buildId=row["build_id"],
            kind=SourceInputKind(row["kind"]),
            evidenceRole=EvidenceRole(row["evidence_role"]),
            reviewStatus=SourceReviewStatus(row["review_status"]),
            securityDecision=SourceSecurityDecision(row["security_decision"]),
            title=row["title"],
            publisher=row["publisher"],
            url=row["url"],
            publishedAt=(
                datetime.fromisoformat(row["published_at"]) if row["published_at"] else None
            ),
            knownAt=datetime.fromisoformat(row["known_at"]),
            contentHash=row["content_hash"],
            contentLength=row["content_length"],
            reviewSummary=row["review_summary"],
            verifiedEvidenceQuotes=tuple(quotes),
            searchRunId=row["search_run_id"],
            parentSourceId=row["parent_source_id"],
            createdAt=datetime.fromisoformat(row["created_at"]),
            updatedAt=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _searchRunFromRow(row: sqlite3.Row) -> SearchRunRecord:
        parameters = json.loads(row["request_parameters_json"])
        if not isinstance(parameters, dict):
            raise RuntimeError("stored Event Pack Factory search parameters are invalid")
        return SearchRunRecord(
            id=row["id"],
            buildId=row["build_id"],
            engine=SearchEngine(row["engine"]),
            query=row["query"],
            queryHash=row["query_hash"],
            requestParameters=parameters,
            providerRequestId=row["provider_request_id"],
            estimatedCostCny=row["estimated_cost_cny"],
            resultCount=row["result_count"],
            droppedResultCount=row["dropped_result_count"],
            createdAt=datetime.fromisoformat(row["created_at"]),
        )
