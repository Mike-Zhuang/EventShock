"""确定性社交图、传播规则和节点级点时信息视图。"""

from __future__ import annotations

import hashlib
import heapq
import random
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.information.models import (
    InformationItem,
    InformationReceipt,
    InformationType,
    PointInTimeInformationStore,
    SourceTier,
)


class GraphType(StrEnum):
    ER = "ER"
    WS = "WS"
    BA = "BA"
    SBM = "SBM"
    ECHO_CHAMBER = "ECHO_CHAMBER"
    CORE_PERIPHERY = "CORE_PERIPHERY"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class GraphSpec(StrictModel):
    """六类预置图的统一、可序列化参数。"""

    graphType: GraphType
    nodeCount: int = Field(ge=1, le=10_000)
    seed: int = 0
    edgeProbability: float = Field(default=0.08, ge=0.0, le=1.0)
    neighborCount: int = Field(default=4, ge=2)
    rewiringProbability: float = Field(default=0.1, ge=0.0, le=1.0)
    attachmentEdges: int = Field(default=2, ge=1)
    communitySizes: tuple[int, ...] = ()
    communityCount: int = Field(default=2, ge=1)
    withinCommunityProbability: float = Field(default=0.5, ge=0.0, le=1.0)
    betweenCommunityProbability: float = Field(default=0.05, ge=0.0, le=1.0)
    coreFraction: float = Field(default=0.2, gt=0.0, le=1.0)
    coreProbability: float = Field(default=0.8, ge=0.0, le=1.0)
    corePeripheryProbability: float = Field(default=0.3, ge=0.0, le=1.0)
    peripheryProbability: float = Field(default=0.03, ge=0.0, le=1.0)

    @field_validator("communitySizes")
    @classmethod
    def requirePositiveCommunitySizes(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(value <= 0 for value in values):
            raise ValueError("communitySizes must contain positive integers")
        return values

    @model_validator(mode="after")
    def validateTopologyParameters(self) -> GraphSpec:
        if self.graphType is GraphType.WS:
            if self.nodeCount < 3:
                raise ValueError("WS requires at least three nodes")
            if self.neighborCount >= self.nodeCount or self.neighborCount % 2:
                raise ValueError("WS neighborCount must be even and smaller than nodeCount")
        if self.graphType is GraphType.BA and self.attachmentEdges >= self.nodeCount:
            raise ValueError("BA attachmentEdges must be smaller than nodeCount")
        if self.graphType in {GraphType.SBM, GraphType.ECHO_CHAMBER}:
            if self.communitySizes and sum(self.communitySizes) != self.nodeCount:
                raise ValueError("communitySizes must sum to nodeCount")
            if not self.communitySizes and self.communityCount > self.nodeCount:
                raise ValueError("communityCount must not exceed nodeCount")
        return self


class NetworkNodeProfile(StrictModel):
    """传播 hazard 中可校准的节点参数。"""

    nodeId: str = Field(min_length=1)
    communityId: str = Field(default="all", min_length=1)
    attention: float = Field(default=1.0, ge=0.0, le=1.0)
    forwardingBias: float = Field(default=1.0, ge=0.0, le=2.0)
    distortionBias: float = Field(default=1.0, ge=0.0, le=2.0)
    sourceTrust: dict[SourceTier, float] = Field(
        default_factory=lambda: {tier: 1.0 for tier in SourceTier}
    )

    @field_validator("sourceTrust")
    @classmethod
    def validateTrust(cls, values: dict[SourceTier, float]) -> dict[SourceTier, float]:
        if any(not 0.0 <= value <= 1.0 for value in values.values()):
            raise ValueError("source trust values must be between 0 and 1")
        return dict(values)


@dataclass(frozen=True, slots=True)
class GraphMetrics:
    nodeCount: int
    edgeCount: int
    averageDegree: float
    clusteringCoefficient: float
    averagePathLength: float | None
    connected: bool
    modularity: float
    homophily: float
    maxInfluenceConcentration: float


class SocialGraph:
    """经过对称性校验的无向简单图。"""

    def __init__(
        self,
        adjacency: Mapping[str, Iterable[str]],
        *,
        profiles: Mapping[str, NetworkNodeProfile] | None = None,
    ) -> None:
        self._adjacency = {nodeId: set(neighbors) for nodeId, neighbors in adjacency.items()}
        if not self._adjacency:
            raise ValueError("a social graph must contain at least one node")
        nodeIds = set(self._adjacency)
        for nodeId, neighbors in self._adjacency.items():
            if nodeId in neighbors:
                raise ValueError(f"self-loop is not allowed: {nodeId}")
            unknown = neighbors - nodeIds
            if unknown:
                raise ValueError(f"unknown neighbors for {nodeId}: {sorted(unknown)}")
            for neighborId in neighbors:
                if nodeId not in self._adjacency[neighborId]:
                    raise ValueError(f"edge {nodeId}-{neighborId} is not symmetric")

        resolvedProfiles = profiles or {
            nodeId: NetworkNodeProfile(nodeId=nodeId) for nodeId in nodeIds
        }
        if set(resolvedProfiles) != nodeIds:
            raise ValueError("profile node IDs must exactly match graph node IDs")
        for nodeId, profile in resolvedProfiles.items():
            if profile.nodeId != nodeId:
                raise ValueError("profile key must match profile.nodeId")
        self._profiles = dict(resolvedProfiles)

    @classmethod
    def fromEdges(
        cls,
        nodeIds: Iterable[str],
        edges: Iterable[tuple[str, str]],
        *,
        communityByNode: Mapping[str, str] | None = None,
    ) -> SocialGraph:
        orderedNodeIds = tuple(nodeIds)
        if len(set(orderedNodeIds)) != len(orderedNodeIds):
            raise ValueError("node IDs must be unique")
        adjacency = {nodeId: set() for nodeId in orderedNodeIds}
        for left, right in edges:
            if left not in adjacency or right not in adjacency:
                raise ValueError("an edge references an unknown node")
            if left == right:
                raise ValueError("self-loops are not allowed")
            adjacency[left].add(right)
            adjacency[right].add(left)
        communities = communityByNode or {}
        profiles = {
            nodeId: NetworkNodeProfile(
                nodeId=nodeId,
                communityId=communities.get(nodeId, "all"),
            )
            for nodeId in orderedNodeIds
        }
        return cls(adjacency, profiles=profiles)

    @property
    def nodeIds(self) -> tuple[str, ...]:
        return tuple(sorted(self._adjacency))

    @property
    def edgeCount(self) -> int:
        return sum(len(neighbors) for neighbors in self._adjacency.values()) // 2

    def hasNode(self, nodeId: str) -> bool:
        return nodeId in self._adjacency

    def neighbors(self, nodeId: str) -> tuple[str, ...]:
        return tuple(sorted(self._adjacency[nodeId]))

    def profile(self, nodeId: str) -> NetworkNodeProfile:
        # 返回深拷贝，避免调用方修改 sourceTrust 后悄然改变同一 seed 的传播结果。
        return self._profiles[nodeId].model_copy(deep=True)

    def edgeSnapshot(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (left, right) for left in self.nodeIds for right in self.neighbors(left) if left < right
        )

    def metrics(self) -> GraphMetrics:
        degrees = {nodeId: len(self._adjacency[nodeId]) for nodeId in self.nodeIds}
        edgeCount = self.edgeCount
        averageDegree = sum(degrees.values()) / len(degrees)
        clusteringValues: list[float] = []
        for nodeId, degree in degrees.items():
            if degree < 2:
                clusteringValues.append(0.0)
                continue
            neighbors = self._adjacency[nodeId]
            neighborEdges = sum(
                1
                for left in neighbors
                for right in self._adjacency[left]
                if right in neighbors and left < right
            )
            clusteringValues.append(neighborEdges / (degree * (degree - 1) / 2))

        pathLengths: list[int] = []
        connected = True
        for index, source in enumerate(self.nodeIds):
            distances = self._shortestDistances(source)
            for target in self.nodeIds[index + 1 :]:
                if target not in distances:
                    connected = False
                else:
                    pathLengths.append(distances[target])

        homophilousEdges = sum(
            1
            for left, right in self.edgeSnapshot()
            if self.profile(left).communityId == self.profile(right).communityId
        )
        modularity = self._modularity(degrees, edgeCount)
        return GraphMetrics(
            nodeCount=len(self.nodeIds),
            edgeCount=edgeCount,
            averageDegree=averageDegree,
            clusteringCoefficient=sum(clusteringValues) / len(clusteringValues),
            averagePathLength=(sum(pathLengths) / len(pathLengths) if pathLengths else None),
            connected=connected,
            modularity=modularity,
            homophily=homophilousEdges / edgeCount if edgeCount else 0.0,
            maxInfluenceConcentration=(
                max(degrees.values()) / (2 * edgeCount) if edgeCount else 0.0
            ),
        )

    def _shortestDistances(self, source: str) -> dict[str, int]:
        distances = {source: 0}
        queue = deque([source])
        while queue:
            nodeId = queue.popleft()
            for neighborId in self.neighbors(nodeId):
                if neighborId not in distances:
                    distances[neighborId] = distances[nodeId] + 1
                    queue.append(neighborId)
        return distances

    def _modularity(self, degrees: Mapping[str, int], edgeCount: int) -> float:
        if edgeCount == 0:
            return 0.0
        communityNodes: dict[str, set[str]] = {}
        for nodeId in self.nodeIds:
            communityNodes.setdefault(self.profile(nodeId).communityId, set()).add(nodeId)
        modularity = 0.0
        for nodes in communityNodes.values():
            internalEdges = sum(
                1 for left, right in self.edgeSnapshot() if left in nodes and right in nodes
            )
            degreeSum = sum(degrees[nodeId] for nodeId in nodes)
            modularity += internalEdges / edgeCount - (degreeSum / (2 * edgeCount)) ** 2
        return modularity


def buildSocialGraph(spec: GraphSpec) -> SocialGraph:
    """仅依赖给定参数和 seed 构造图；不读取全局随机状态。"""

    randomStream = random.Random(spec.seed)
    nodeIds = tuple(f"node-{index:04d}" for index in range(spec.nodeCount))
    adjacency = {nodeId: set() for nodeId in nodeIds}
    communityByNode = {nodeId: "all" for nodeId in nodeIds}

    if spec.graphType is GraphType.ER:
        _connectByProbability(adjacency, nodeIds, spec.edgeProbability, randomStream)
    elif spec.graphType is GraphType.WS:
        _buildWattsStrogatz(adjacency, nodeIds, spec, randomStream)
    elif spec.graphType is GraphType.BA:
        _buildBarabasiAlbert(adjacency, nodeIds, spec.attachmentEdges, randomStream)
    elif spec.graphType in {GraphType.SBM, GraphType.ECHO_CHAMBER}:
        communityByNode = _assignCommunities(nodeIds, spec)
        _buildBlockModel(adjacency, nodeIds, communityByNode, spec, randomStream)
    else:
        communityByNode = _buildCorePeriphery(
            adjacency,
            nodeIds,
            spec,
            randomStream,
        )

    profiles = {
        nodeId: NetworkNodeProfile(
            nodeId=nodeId,
            communityId=communityByNode[nodeId],
        )
        for nodeId in nodeIds
    }
    return SocialGraph(adjacency, profiles=profiles)


def _connect(adjacency: dict[str, set[str]], left: str, right: str) -> None:
    adjacency[left].add(right)
    adjacency[right].add(left)


def _disconnect(adjacency: dict[str, set[str]], left: str, right: str) -> None:
    adjacency[left].remove(right)
    adjacency[right].remove(left)


def _connectByProbability(
    adjacency: dict[str, set[str]],
    nodeIds: tuple[str, ...],
    probability: float,
    randomStream: random.Random,
) -> None:
    for leftIndex, left in enumerate(nodeIds):
        for right in nodeIds[leftIndex + 1 :]:
            if randomStream.random() < probability:
                _connect(adjacency, left, right)


def _buildWattsStrogatz(
    adjacency: dict[str, set[str]],
    nodeIds: tuple[str, ...],
    spec: GraphSpec,
    randomStream: random.Random,
) -> None:
    halfNeighbors = spec.neighborCount // 2
    originalEdges: list[tuple[str, str]] = []
    for index, left in enumerate(nodeIds):
        for offset in range(1, halfNeighbors + 1):
            right = nodeIds[(index + offset) % len(nodeIds)]
            if right not in adjacency[left]:
                _connect(adjacency, left, right)
                originalEdges.append((left, right))

    for left, right in originalEdges:
        if randomStream.random() >= spec.rewiringProbability:
            continue
        candidates = [
            nodeId for nodeId in nodeIds if nodeId != left and nodeId not in adjacency[left]
        ]
        if candidates:
            _disconnect(adjacency, left, right)
            _connect(adjacency, left, randomStream.choice(candidates))


def _buildBarabasiAlbert(
    adjacency: dict[str, set[str]],
    nodeIds: tuple[str, ...],
    attachmentEdges: int,
    randomStream: random.Random,
) -> None:
    initialNodeCount = attachmentEdges + 1
    for leftIndex, left in enumerate(nodeIds[:initialNodeCount]):
        for right in nodeIds[leftIndex + 1 : initialNodeCount]:
            _connect(adjacency, left, right)

    for newNodeIndex in range(initialNodeCount, len(nodeIds)):
        newNode = nodeIds[newNodeIndex]
        candidates = list(nodeIds[:newNodeIndex])
        selected: list[str] = []
        for _ in range(attachmentEdges):
            weights = [len(adjacency[nodeId]) for nodeId in candidates]
            chosen = _weightedChoice(candidates, weights, randomStream)
            selected.append(chosen)
            candidates.remove(chosen)
        for target in selected:
            _connect(adjacency, newNode, target)


def _weightedChoice(
    candidates: list[str],
    weights: list[int],
    randomStream: random.Random,
) -> str:
    totalWeight = sum(weights)
    if totalWeight <= 0:
        return randomStream.choice(candidates)
    threshold = randomStream.random() * totalWeight
    cumulative = 0
    for candidate, weight in zip(candidates, weights, strict=True):
        cumulative += weight
        if threshold < cumulative:
            return candidate
    return candidates[-1]


def _assignCommunities(
    nodeIds: tuple[str, ...],
    spec: GraphSpec,
) -> dict[str, str]:
    if spec.communitySizes:
        sizes = spec.communitySizes
    else:
        baseSize, remainder = divmod(len(nodeIds), spec.communityCount)
        sizes = tuple(
            baseSize + (1 if index < remainder else 0) for index in range(spec.communityCount)
        )
    communityByNode: dict[str, str] = {}
    cursor = 0
    for communityIndex, size in enumerate(sizes):
        for nodeId in nodeIds[cursor : cursor + size]:
            communityByNode[nodeId] = f"community-{communityIndex:02d}"
        cursor += size
    return communityByNode


def _buildBlockModel(
    adjacency: dict[str, set[str]],
    nodeIds: tuple[str, ...],
    communityByNode: Mapping[str, str],
    spec: GraphSpec,
    randomStream: random.Random,
) -> None:
    withinProbability = spec.withinCommunityProbability
    betweenProbability = spec.betweenCommunityProbability
    if spec.graphType is GraphType.ECHO_CHAMBER:
        withinProbability = max(withinProbability, 0.75)
        betweenProbability = min(betweenProbability, 0.02)
    for leftIndex, left in enumerate(nodeIds):
        for right in nodeIds[leftIndex + 1 :]:
            probability = (
                withinProbability
                if communityByNode[left] == communityByNode[right]
                else betweenProbability
            )
            if randomStream.random() < probability:
                _connect(adjacency, left, right)


def _buildCorePeriphery(
    adjacency: dict[str, set[str]],
    nodeIds: tuple[str, ...],
    spec: GraphSpec,
    randomStream: random.Random,
) -> dict[str, str]:
    coreNodeCount = max(1, min(len(nodeIds), round(len(nodeIds) * spec.coreFraction)))
    coreNodes = set(nodeIds[:coreNodeCount])
    communityByNode = {nodeId: "core" if nodeId in coreNodes else "periphery" for nodeId in nodeIds}
    for leftIndex, left in enumerate(nodeIds):
        for right in nodeIds[leftIndex + 1 :]:
            if left in coreNodes and right in coreNodes:
                probability = spec.coreProbability
            elif left in coreNodes or right in coreNodes:
                probability = spec.corePeripheryProbability
            else:
                probability = spec.peripheryProbability
            if randomStream.random() < probability:
                _connect(adjacency, left, right)
    return communityByNode


class PropagationConfig(StrictModel):
    """传播、延迟、失真和澄清覆盖率的可校准规则。"""

    baseForwardProbability: float = Field(default=0.4, ge=0.0, le=1.0)
    minimumDelaySeconds: int = Field(default=1, ge=0)
    maximumDelaySeconds: int = Field(default=60, ge=0)
    maximumHops: int = Field(default=5, ge=0)
    distortionProbability: float = Field(default=0.0, ge=0.0, le=1.0)
    correctionCoverage: float = Field(default=1.0, ge=0.0, le=1.0)
    rumorMultiplier: float = Field(default=1.0, ge=0.0, le=3.0)

    @model_validator(mode="after")
    def validateDelayRange(self) -> PropagationConfig:
        if self.maximumDelaySeconds < self.minimumDelaySeconds:
            raise ValueError("maximumDelaySeconds must not be below minimumDelaySeconds")
        return self


class NodeInformationView(StrictModel):
    item: InformationItem
    receipt: InformationReceipt


@dataclass(frozen=True, slots=True)
class PropagationResult:
    infoId: str
    receipts: tuple[InformationReceipt, ...]
    reachedNodeCount: int
    forwardedNodeCount: int
    maximumHopCount: int


class InformationNetwork:
    """用稳定哈希代替全局随机流的点时传播引擎。"""

    def __init__(
        self,
        graph: SocialGraph,
        informationStore: PointInTimeInformationStore,
        *,
        seed: int,
    ) -> None:
        self.graph = graph
        self.informationStore = informationStore
        self.seed = seed
        self._receipts: dict[tuple[str, str], InformationReceipt] = {}

    def propagate(
        self,
        *,
        infoId: str,
        seedNodeIds: tuple[str, ...],
        startAt: datetime,
        config: PropagationConfig,
    ) -> PropagationResult:
        """传播一条信息；最早接收时间不会早于该信息的 ``knownAt``。"""

        _requireAware(startAt, "startAt")
        if not seedNodeIds:
            raise ValueError("at least one seed node is required")
        if len(set(seedNodeIds)) != len(seedNodeIds):
            raise ValueError("seed node IDs must be unique")
        unknownSeeds = [nodeId for nodeId in seedNodeIds if not self.graph.hasNode(nodeId)]
        if unknownSeeds:
            raise ValueError(f"unknown seed nodes: {sorted(unknownSeeds)}")
        item = self.informationStore.get(infoId)
        effectiveStart = max(startAt, item.times.knownAt)

        pending: list[
            tuple[
                datetime,
                int,
                int,
                str,
                str | None,
                str | None,
                tuple[str, ...],
            ]
        ] = []
        sequence = 0
        for nodeId in sorted(seedNodeIds):
            sequence += 1
            heapq.heappush(
                pending,
                (effectiveStart, 0, sequence, nodeId, None, None, (nodeId,)),
            )

        localReceipts: dict[str, InformationReceipt] = {}
        while pending:
            (
                receivedAt,
                hopCount,
                _,
                nodeId,
                senderNodeId,
                parentReceiptId,
                evidencePath,
            ) = heapq.heappop(pending)
            if nodeId in localReceipts:
                continue
            receiptId = self._receiptId(infoId, nodeId, receivedAt, parentReceiptId)
            distorted = hopCount > 0 and self._draw(
                "distortion", infoId, senderNodeId, nodeId, hopCount
            ) < min(
                1.0,
                config.distortionProbability * self.graph.profile(nodeId).distortionBias,
            )
            receipt = InformationReceipt(
                receiptId=receiptId,
                infoId=infoId,
                nodeId=nodeId,
                receivedAt=receivedAt,
                senderNodeId=senderNodeId,
                parentReceiptId=parentReceiptId,
                hopCount=hopCount,
                distorted=distorted,
                evidencePath=evidencePath,
            )
            localReceipts[nodeId] = receipt
            if hopCount >= config.maximumHops:
                continue

            for neighborId in self.graph.neighbors(nodeId):
                if neighborId in localReceipts:
                    continue
                nextHopCount = hopCount + 1
                if (
                    item.type is InformationType.CORRECTION
                    and self._draw("coverage", infoId, nodeId, neighborId, nextHopCount)
                    >= config.correctionCoverage
                ):
                    continue
                if self._draw(
                    "forward", infoId, nodeId, neighborId, nextHopCount
                ) >= self._forwardProbability(item, nodeId, neighborId, config):
                    continue
                delaySeconds = self._delaySeconds(
                    infoId,
                    nodeId,
                    neighborId,
                    nextHopCount,
                    config,
                )
                sequence += 1
                heapq.heappush(
                    pending,
                    (
                        receivedAt + timedelta(seconds=delaySeconds),
                        nextHopCount,
                        sequence,
                        neighborId,
                        nodeId,
                        receiptId,
                        (*evidencePath, neighborId),
                    ),
                )

        receipts = tuple(
            sorted(
                localReceipts.values(),
                key=lambda receipt: (
                    receipt.receivedAt,
                    receipt.hopCount,
                    receipt.nodeId,
                ),
            )
        )
        for receipt in receipts:
            key = (receipt.infoId, receipt.nodeId)
            existing = self._receipts.get(key)
            if existing is None or (
                receipt.receivedAt,
                receipt.receiptId,
            ) < (existing.receivedAt, existing.receiptId):
                self._receipts[key] = receipt
        self.assertNoFutureLeaks()
        return PropagationResult(
            infoId=infoId,
            receipts=receipts,
            reachedNodeCount=len(receipts),
            forwardedNodeCount=sum(receipt.hopCount > 0 for receipt in receipts),
            maximumHopCount=max((receipt.hopCount for receipt in receipts), default=0),
        )

    def visibleForNode(
        self,
        nodeId: str,
        asOf: datetime,
    ) -> tuple[NodeInformationView, ...]:
        _requireAware(asOf, "asOf")
        if not self.graph.hasNode(nodeId):
            raise KeyError(f"unknown graph node: {nodeId}")
        views = []
        for (infoId, receiptNodeId), receipt in self._receipts.items():
            if receiptNodeId != nodeId or receipt.receivedAt > asOf:
                continue
            item = self.informationStore.get(infoId)
            if item.isVisibleAt(asOf):
                views.append(NodeInformationView(item=item, receipt=receipt))
        return tuple(
            sorted(
                views,
                key=lambda view: (
                    view.receipt.receivedAt,
                    view.item.infoId,
                ),
            )
        )

    def receiptsForInfo(self, infoId: str) -> tuple[InformationReceipt, ...]:
        return tuple(
            sorted(
                (
                    receipt
                    for (receiptInfoId, _), receipt in self._receipts.items()
                    if receiptInfoId == infoId
                ),
                key=lambda receipt: (receipt.receivedAt, receipt.nodeId),
            )
        )

    def assertNoFutureLeaks(self) -> None:
        violations = []
        for (infoId, nodeId), receipt in self._receipts.items():
            knownAt = self.informationStore.get(infoId).times.knownAt
            if receipt.receivedAt < knownAt:
                violations.append(f"{infoId}@{nodeId}")
        if violations:
            raise AssertionError(f"information arrived before knownAt: {sorted(violations)}")

    def _forwardProbability(
        self,
        item: InformationItem,
        senderNodeId: str,
        receiverNodeId: str,
        config: PropagationConfig,
    ) -> float:
        sender = self.graph.profile(senderNodeId)
        receiver = self.graph.profile(receiverNodeId)
        salience = (item.novelty + item.severity) / 2
        trust = receiver.sourceTrust.get(item.sourceTier, 0.0)
        probability = (
            config.baseForwardProbability
            * receiver.attention
            * salience
            * trust
            * sender.forwardingBias
        )
        if item.type is InformationType.RUMOR:
            probability *= config.rumorMultiplier
        return min(1.0, max(0.0, probability))

    def _delaySeconds(
        self,
        infoId: str,
        senderNodeId: str,
        receiverNodeId: str,
        hopCount: int,
        config: PropagationConfig,
    ) -> int:
        delayRange = config.maximumDelaySeconds - config.minimumDelaySeconds + 1
        if delayRange == 1:
            return config.minimumDelaySeconds
        value = self._stableInteger("delay", infoId, senderNodeId, receiverNodeId, hopCount)
        return config.minimumDelaySeconds + value % delayRange

    def _draw(self, purpose: str, *parts: object) -> float:
        return self._stableInteger(purpose, *parts) / 2**64

    def _stableInteger(self, purpose: str, *parts: object) -> int:
        message = "|".join(str(part) for part in (self.seed, purpose, *parts))
        digest = hashlib.blake2b(message.encode("utf-8"), digest_size=8).digest()
        return int.from_bytes(digest, "big")

    @staticmethod
    def _receiptId(
        infoId: str,
        nodeId: str,
        receivedAt: datetime,
        parentReceiptId: str | None,
    ) -> str:
        value = f"{infoId}|{nodeId}|{receivedAt.isoformat()}|{parentReceiptId or 'ROOT'}"
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
        return f"receipt-{digest}"


def _requireAware(value: datetime, fieldName: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{fieldName} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{fieldName} must be timezone-aware")
