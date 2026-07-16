"""信息对象、四个时间语义和点时可见性。

``knownAt`` 是仿真中是否可见的唯一入口。``eventTime`` 可以晚于公告时间，
例如提前宣布的指数调整，因此不能强制四个时间完全递增；来源链路仅要求
``publishedAt <= knownAt <= ingestedAt``。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class InformationType(StrEnum):
    """蓝图规定的信息语义；前五类是外部证据的核心类型。"""

    FACT = "FACT"
    CLAIM = "CLAIM"
    RUMOR = "RUMOR"
    CORRECTION = "CORRECTION"
    ANALYSIS = "ANALYSIS"
    MARKET_SIGNAL = "MARKET_SIGNAL"
    SOCIAL_POST = "SOCIAL_POST"
    PRIVATE_SIGNAL = "PRIVATE_SIGNAL"


class SourceTier(StrEnum):
    """来源等级，不把模型判断直接等同于事实等级。"""

    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"
    T5 = "T5"


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
    )


class InformationTimes(StrictModel):
    """一条信息的现实、发布、场景可见和抓取时间。"""

    eventTime: datetime
    publishedAt: datetime
    knownAt: datetime
    ingestedAt: datetime

    @field_validator("eventTime", "publishedAt", "knownAt", "ingestedAt")
    @classmethod
    def requireTimezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("information times must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validateSourceTimeline(self) -> InformationTimes:
        if self.publishedAt > self.knownAt:
            raise ValueError("publishedAt must not be after knownAt")
        if self.knownAt > self.ingestedAt:
            raise ValueError("knownAt must not be after ingestedAt")
        return self


class InformationItem(StrictModel):
    """可追溯且可做未来信息泄漏检查的信息节点。"""

    infoId: str = Field(min_length=1)
    type: InformationType
    claim: str = Field(min_length=1)
    entityIds: tuple[str, ...] = ()
    times: InformationTimes
    sourceId: str = Field(min_length=1)
    sourceTier: SourceTier
    credibilityPrior: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)
    severity: float = Field(ge=0.0, le=1.0)
    validUntil: datetime | None = None
    supersedes: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()
    correctsInfoIds: tuple[str, ...] = ()
    contentHash: str = ""

    @field_validator("entityIds", "supersedes", "contradicts", "correctsInfoIds")
    @classmethod
    def rejectEmptyIdentifiers(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value for value in values):
            raise ValueError("identifier collections must not contain empty values")
        if len(set(values)) != len(values):
            raise ValueError("identifier collections must not contain duplicates")
        return values

    @field_validator("validUntil")
    @classmethod
    def requireValidUntilTimezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("validUntil must be timezone-aware")
        return value

    @model_validator(mode="before")
    @classmethod
    def populateContentHash(cls, data: object) -> object:
        if isinstance(data, dict) and not data.get("contentHash"):
            claim = data.get("claim")
            if isinstance(claim, str):
                copied = dict(data)
                copied["contentHash"] = cls.computeContentHash(claim)
                return copied
        return data

    @model_validator(mode="after")
    def validateSemantics(self) -> InformationItem:
        if not SHA256_PATTERN.fullmatch(self.contentHash):
            raise ValueError("contentHash must be a lowercase sha256 digest")
        if self.validUntil is not None and self.validUntil < self.times.knownAt:
            raise ValueError("validUntil must not be before knownAt")
        if self.type is InformationType.CORRECTION and not self.correctsInfoIds:
            raise ValueError("CORRECTION must identify at least one corrected item")
        if self.type is not InformationType.CORRECTION and self.correctsInfoIds:
            raise ValueError("only CORRECTION may set correctsInfoIds")
        if self.sourceTier is SourceTier.T4 and self.type is InformationType.FACT:
            raise ValueError("T4 social content cannot directly become a FACT")
        if self.sourceTier is SourceTier.T5 and self.type is InformationType.FACT:
            raise ValueError("T5 synthetic content cannot directly become a FACT")
        return self

    @staticmethod
    def computeContentHash(claim: str) -> str:
        return f"sha256:{hashlib.sha256(claim.encode('utf-8')).hexdigest()}"

    def isVisibleAt(self, asOf: datetime) -> bool:
        _requireAware(asOf, "asOf")
        if asOf < self.times.knownAt:
            return False
        return self.validUntil is None or asOf <= self.validUntil


class InformationReceipt(StrictModel):
    """某节点收到信息的传播证据链。"""

    receiptId: str = Field(min_length=1)
    infoId: str = Field(min_length=1)
    nodeId: str = Field(min_length=1)
    receivedAt: datetime
    senderNodeId: str | None = None
    parentReceiptId: str | None = None
    hopCount: int = Field(ge=0)
    distorted: bool = False
    evidencePath: tuple[str, ...] = ()

    @field_validator("receivedAt")
    @classmethod
    def requireReceivedTimezone(cls, value: datetime) -> datetime:
        _requireAware(value, "receivedAt")
        return value

    @model_validator(mode="after")
    def validateReceiptRoot(self) -> InformationReceipt:
        if self.hopCount == 0 and (
            self.senderNodeId is not None or self.parentReceiptId is not None
        ):
            raise ValueError("a root receipt cannot have a sender or parent")
        if self.hopCount > 0 and (self.senderNodeId is None or self.parentReceiptId is None):
            raise ValueError("a propagated receipt must have a sender and parent")
        if self.evidencePath and self.evidencePath[-1] != self.nodeId:
            raise ValueError("evidencePath must end at nodeId")
        return self


class PointInTimeInformationStore:
    """只按场景 ``knownAt`` 提供历史时点视图的不可重复信息库。"""

    def __init__(self, items: tuple[InformationItem, ...] = ()) -> None:
        self._items: dict[str, InformationItem] = {}
        for item in items:
            self.add(item)

    def __len__(self) -> int:
        return len(self._items)

    def add(self, item: InformationItem) -> None:
        if not isinstance(item, InformationItem):
            raise TypeError("item must be an InformationItem")
        if item.infoId in self._items:
            raise ValueError(f"duplicate infoId: {item.infoId}")
        self._items[item.infoId] = item

    def get(self, infoId: str) -> InformationItem:
        try:
            return self._items[infoId]
        except KeyError as error:
            raise KeyError(f"unknown infoId: {infoId}") from error

    def visibleAt(
        self,
        asOf: datetime,
        *,
        allowedTypes: frozenset[InformationType] | None = None,
        minimumTier: SourceTier | None = None,
    ) -> tuple[InformationItem, ...]:
        """返回稳定排序的点时快照，不参考抓取时间或当前系统时间。"""

        _requireAware(asOf, "asOf")
        tierRank = {tier: index for index, tier in enumerate(SourceTier, start=1)}
        visible = (
            item
            for item in self._items.values()
            if item.isVisibleAt(asOf)
            and (allowedTypes is None or item.type in allowedTypes)
            and (minimumTier is None or tierRank[item.sourceTier] <= tierRank[minimumTier])
        )
        return tuple(sorted(visible, key=lambda item: (item.times.knownAt, item.infoId)))

    def assertNoFutureLeak(
        self,
        infoIds: tuple[str, ...],
        asOf: datetime,
    ) -> None:
        leaked = [infoId for infoId in infoIds if not self.get(infoId).isVisibleAt(asOf)]
        if leaked:
            raise ValueError(f"future or expired information is not visible: {sorted(leaked)}")


def _requireAware(value: datetime, fieldName: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{fieldName} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{fieldName} must be timezone-aware")
