"""L0–L8 验证阶梯及证据门禁。"""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ValidationLevel(IntEnum):
    L0 = 0
    L1 = 1
    L2 = 2
    L3 = 3
    L4 = 4
    L5 = 5
    L6 = 6
    L7 = 7
    L8 = 8

    @property
    def label(self) -> str:
        return f"L{int(self)}"


LEVEL_TITLES: dict[ValidationLevel, str] = {
    ValidationLevel.L0: "代码与账本不变量",
    ValidationLevel.L1: "微观结构单模块验证",
    ValidationLevel.L2: "规则智能体总体行为",
    ValidationLevel.L3: "LLM 认知与工具行为",
    ValidationLevel.L4: "市场统计与 stylized facts",
    ValidationLevel.L5: "历史事件响应与事件研究",
    ValidationLevel.L6: "反事实稳健性、消融与负对照",
    ValidationLevel.L7: "用户理解与可用性",
    ValidationLevel.L8: "运行、成本、安全与治理",
}


class LevelStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


class EvidenceStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    INVALIDATED = "INVALIDATED"


class EvidenceType(StrEnum):
    TEST_REPORT = "TEST_REPORT"
    CALIBRATION = "CALIBRATION"
    MODEL_EVAL = "MODEL_EVAL"
    HISTORICAL_STUDY = "HISTORICAL_STUDY"
    ROBUSTNESS_STUDY = "ROBUSTNESS_STUDY"
    USER_TEST = "USER_TEST"
    OPERATIONS = "OPERATIONS"
    GOVERNANCE = "GOVERNANCE"
    OTHER = "OTHER"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ValidationEvidence(StrictModel):
    evidenceId: str = Field(min_length=1)
    evidenceType: EvidenceType
    title: str = Field(min_length=1, max_length=200)
    artifactUri: str = Field(min_length=1)
    artifactHash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    recordedAt: datetime
    reviewer: str = Field(min_length=1)
    status: EvidenceStatus = EvidenceStatus.UNVERIFIED
    summary: str = Field(min_length=1, max_length=1_000)

    @field_validator("recordedAt")
    @classmethod
    def requireRecordedTimezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("recordedAt must be timezone-aware")
        return value


class ValidationLevelRecord(StrictModel):
    level: ValidationLevel
    title: str
    status: LevelStatus = LevelStatus.NOT_STARTED
    evidence: tuple[ValidationEvidence, ...] = ()
    statusSummary: str = "尚未开始"
    blockers: tuple[str, ...] = ()
    updatedAt: datetime | None = None

    @model_validator(mode="after")
    def validateLevelRecord(self) -> ValidationLevelRecord:
        if self.title != LEVEL_TITLES[self.level]:
            raise ValueError("level title does not match the canonical validation ladder")
        if self.updatedAt is not None and (
            self.updatedAt.tzinfo is None or self.updatedAt.utcoffset() is None
        ):
            raise ValueError("updatedAt must be timezone-aware")
        if self.status is LevelStatus.BLOCKED and not self.blockers:
            raise ValueError("BLOCKED requires at least one blocker")
        if self.status is not LevelStatus.BLOCKED and self.blockers:
            raise ValueError("blockers are only valid for BLOCKED")
        return self


class ValidationLadderSnapshot(StrictModel):
    records: tuple[ValidationLevelRecord, ...]

    @model_validator(mode="after")
    def validateCompleteLadder(self) -> ValidationLadderSnapshot:
        levels = tuple(record.level for record in self.records)
        if levels != tuple(ValidationLevel):
            raise ValueError("snapshot must contain L0 through L8 exactly once in order")
        return self


class ValidationLadder:
    """强制下层先通过，并保留每次结论的可核验证据。"""

    def __init__(self) -> None:
        self._records = {
            level: ValidationLevelRecord(level=level, title=LEVEL_TITLES[level])
            for level in ValidationLevel
        }

    def get(self, level: ValidationLevel) -> ValidationLevelRecord:
        return self._records[level]

    def addEvidence(
        self,
        level: ValidationLevel,
        evidence: ValidationEvidence,
    ) -> ValidationLevelRecord:
        if any(
            evidence.evidenceId == existing.evidenceId
            for record in self._records.values()
            for existing in record.evidence
        ):
            raise ValueError(f"duplicate evidenceId: {evidence.evidenceId}")
        record = self._records[level]
        self._records[level] = self._replaceRecord(
            record,
            evidence=(*record.evidence, evidence),
        )
        return self._records[level]

    def updateStatus(
        self,
        level: ValidationLevel,
        status: LevelStatus,
        *,
        statusSummary: str,
        updatedAt: datetime,
        blockers: tuple[str, ...] = (),
    ) -> ValidationLevelRecord:
        if not statusSummary:
            raise ValueError("statusSummary must not be empty")
        if not isinstance(updatedAt, datetime):
            raise TypeError("updatedAt must be a datetime")
        if updatedAt.tzinfo is None or updatedAt.utcoffset() is None:
            raise ValueError("updatedAt must be timezone-aware")
        record = self._records[level]
        if status in {LevelStatus.PASS, LevelStatus.WARN}:
            verifiedEvidence = [
                evidence
                for evidence in record.evidence
                if evidence.status is EvidenceStatus.VERIFIED
            ]
            if not verifiedEvidence:
                raise ValueError(
                    f"{level.label} cannot be {status.value} without verified evidence"
                )
        if status is LevelStatus.PASS:
            incompleteLowerLevels = [
                lowerLevel.label
                for lowerLevel in ValidationLevel
                if lowerLevel < level and self._records[lowerLevel].status is not LevelStatus.PASS
            ]
            if incompleteLowerLevels:
                raise ValueError(f"{level.label} is gated by lower levels: {incompleteLowerLevels}")
        self._records[level] = self._replaceRecord(
            record,
            status=status,
            statusSummary=statusSummary,
            updatedAt=updatedAt,
            blockers=blockers,
        )
        return self._records[level]

    def invalidateEvidence(
        self,
        evidenceId: str,
        *,
        invalidatedAt: datetime,
        reason: str,
    ) -> None:
        if not isinstance(invalidatedAt, datetime):
            raise TypeError("invalidatedAt must be a datetime")
        if invalidatedAt.tzinfo is None or invalidatedAt.utcoffset() is None:
            raise ValueError("invalidatedAt must be timezone-aware")
        if not reason:
            raise ValueError("reason must not be empty")
        locatedLevel: ValidationLevel | None = None
        for level, record in self._records.items():
            updatedEvidence = []
            for evidence in record.evidence:
                if evidence.evidenceId == evidenceId:
                    locatedLevel = level
                    updatedEvidence.append(
                        evidence.model_copy(update={"status": EvidenceStatus.INVALIDATED})
                    )
                else:
                    updatedEvidence.append(evidence)
            if locatedLevel is level:
                stillVerified = any(
                    evidence.status is EvidenceStatus.VERIFIED for evidence in updatedEvidence
                )
                replacementStatus = record.status
                replacementSummary = record.statusSummary
                if record.status in {LevelStatus.PASS, LevelStatus.WARN} and not stillVerified:
                    replacementStatus = LevelStatus.FAIL
                    replacementSummary = f"证据失效：{reason}"
                self._records[level] = self._replaceRecord(
                    record,
                    evidence=tuple(updatedEvidence),
                    status=replacementStatus,
                    statusSummary=replacementSummary,
                    updatedAt=invalidatedAt,
                )
                break
        if locatedLevel is None:
            raise KeyError(f"unknown evidenceId: {evidenceId}")

        for level in ValidationLevel:
            if level <= locatedLevel:
                continue
            record = self._records[level]
            if record.status is LevelStatus.PASS:
                self._records[level] = self._replaceRecord(
                    record,
                    status=LevelStatus.BLOCKED,
                    statusSummary=f"下层 {locatedLevel.label} 的证据已失效",
                    blockers=(f"{locatedLevel.label}: {reason}",),
                    updatedAt=invalidatedAt,
                )

    def canInterpret(self, level: ValidationLevel) -> bool:
        return all(
            self._records[currentLevel].status is LevelStatus.PASS
            for currentLevel in ValidationLevel
            if currentLevel <= level
        )

    def highestPassedLevel(self) -> ValidationLevel | None:
        highest: ValidationLevel | None = None
        for level in ValidationLevel:
            if self._records[level].status is LevelStatus.PASS:
                highest = level
            else:
                break
        return highest

    def snapshot(self) -> ValidationLadderSnapshot:
        return ValidationLadderSnapshot(
            records=tuple(self._records[level] for level in ValidationLevel)
        )

    @staticmethod
    def _replaceRecord(
        record: ValidationLevelRecord,
        **updates: object,
    ) -> ValidationLevelRecord:
        data = record.model_dump()
        data.update(updates)
        return ValidationLevelRecord.model_validate(data)
