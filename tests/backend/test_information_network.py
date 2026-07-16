from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

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
    SocialGraph,
    buildSocialGraph,
)

BASE_TIME = datetime(2026, 6, 26, 20, 0, tzinfo=UTC)


def makeItem(
    *,
    infoId: str = "info-announcement",
    infoType: InformationType = InformationType.FACT,
    knownOffsetMinutes: int = 5,
    correctsInfoIds: tuple[str, ...] = (),
    sourceTier: SourceTier = SourceTier.T1,
) -> InformationItem:
    return InformationItem(
        infoId=infoId,
        type=infoType,
        claim="SpaceX-related test evidence",
        entityIds=("SPACEX",),
        times=InformationTimes(
            eventTime=BASE_TIME + timedelta(days=10),
            publishedAt=BASE_TIME,
            knownAt=BASE_TIME + timedelta(minutes=knownOffsetMinutes),
            ingestedAt=BASE_TIME + timedelta(minutes=30),
        ),
        sourceId="source-official",
        sourceTier=sourceTier,
        credibilityPrior=0.99,
        novelty=1.0,
        severity=1.0,
        correctsInfoIds=correctsInfoIds,
    )


def test_four_times_and_point_in_time_visibility_prevent_future_leaks() -> None:
    item = makeItem()
    store = PointInTimeInformationStore((item,))

    assert store.visibleAt(BASE_TIME + timedelta(minutes=4)) == ()
    assert store.visibleAt(BASE_TIME + timedelta(minutes=5)) == (item,)
    with pytest.raises(ValueError, match="future or expired"):
        store.assertNoFutureLeak(
            (item.infoId,),
            BASE_TIME + timedelta(minutes=4),
        )
    store.assertNoFutureLeak((item.infoId,), BASE_TIME + timedelta(minutes=5))
    assert item.contentHash.startswith("sha256:")


def test_information_semantics_validate_source_tiers_and_corrections() -> None:
    for infoType in (
        InformationType.FACT,
        InformationType.CLAIM,
        InformationType.RUMOR,
        InformationType.ANALYSIS,
    ):
        assert makeItem(infoType=infoType).type is infoType

    correction = makeItem(
        infoId="correction",
        infoType=InformationType.CORRECTION,
        correctsInfoIds=("rumor",),
    )
    assert correction.correctsInfoIds == ("rumor",)
    with pytest.raises(ValidationError, match="CORRECTION"):
        makeItem(infoType=InformationType.CORRECTION)
    with pytest.raises(ValidationError, match="T4"):
        makeItem(sourceTier=SourceTier.T4)
    with pytest.raises(ValidationError, match="publishedAt"):
        InformationTimes(
            eventTime=BASE_TIME,
            publishedAt=BASE_TIME + timedelta(minutes=2),
            knownAt=BASE_TIME + timedelta(minutes=1),
            ingestedAt=BASE_TIME + timedelta(minutes=3),
        )


@pytest.mark.parametrize(
    ("graphType", "overrides"),
    (
        (GraphType.ER, {"edgeProbability": 0.3}),
        (GraphType.WS, {"neighborCount": 4, "rewiringProbability": 0.25}),
        (GraphType.BA, {"attachmentEdges": 2}),
        (GraphType.SBM, {"communitySizes": (6, 6)}),
        (GraphType.ECHO_CHAMBER, {"communitySizes": (6, 6)}),
        (GraphType.CORE_PERIPHERY, {"coreFraction": 0.25}),
    ),
)
def test_all_graph_families_are_deterministic(
    graphType: GraphType,
    overrides: dict[str, object],
) -> None:
    spec = GraphSpec(graphType=graphType, nodeCount=12, seed=739, **overrides)
    first = buildSocialGraph(spec)
    second = buildSocialGraph(spec)

    assert first.nodeIds == second.nodeIds
    assert first.edgeSnapshot() == second.edgeSnapshot()
    assert first.metrics() == second.metrics()
    assert first.metrics().nodeCount == 12
    if graphType is GraphType.BA:
        assert first.edgeCount == 21


def test_echo_chamber_and_core_periphery_expose_structural_metrics() -> None:
    echoGraph = buildSocialGraph(
        GraphSpec(
            graphType=GraphType.ECHO_CHAMBER,
            nodeCount=10,
            seed=4,
            communitySizes=(5, 5),
            withinCommunityProbability=1.0,
            betweenCommunityProbability=0.0,
        )
    )
    coreGraph = buildSocialGraph(
        GraphSpec(
            graphType=GraphType.CORE_PERIPHERY,
            nodeCount=10,
            seed=4,
            coreFraction=0.3,
            coreProbability=1.0,
            corePeripheryProbability=1.0,
            peripheryProbability=0.0,
        )
    )

    assert echoGraph.metrics().homophily == 1.0
    assert echoGraph.metrics().modularity > 0
    assert coreGraph.profile("node-0000").communityId == "core"
    assert coreGraph.profile("node-0009").communityId == "periphery"
    assert len(coreGraph.neighbors("node-0000")) > len(coreGraph.neighbors("node-0009"))


def test_propagation_is_replayable_and_never_precedes_known_at() -> None:
    graph = SocialGraph.fromEdges(
        ("a", "b", "c", "d"),
        (("a", "b"), ("b", "c"), ("c", "d")),
    )
    item = makeItem()
    store = PointInTimeInformationStore((item,))
    config = PropagationConfig(
        baseForwardProbability=1.0,
        minimumDelaySeconds=2,
        maximumDelaySeconds=2,
        maximumHops=4,
    )
    firstNetwork = InformationNetwork(graph, store, seed=91)
    secondNetwork = InformationNetwork(graph, store, seed=91)

    first = firstNetwork.propagate(
        infoId=item.infoId,
        seedNodeIds=("a",),
        startAt=BASE_TIME,
        config=config,
    )
    second = secondNetwork.propagate(
        infoId=item.infoId,
        seedNodeIds=("a",),
        startAt=BASE_TIME,
        config=config,
    )

    assert first == second
    assert first.reachedNodeCount == 4
    assert first.forwardedNodeCount == 3
    assert first.maximumHopCount == 3
    assert first.receipts[0].receivedAt == item.times.knownAt
    assert firstNetwork.visibleForNode("a", item.times.knownAt - timedelta(microseconds=1)) == ()
    assert firstNetwork.visibleForNode("d", item.times.knownAt + timedelta(seconds=6))


def test_correction_coverage_and_disconnected_graph_have_bounded_effects() -> None:
    graph = SocialGraph.fromEdges(("a", "b", "isolated"), (("a", "b"),))
    rumor = makeItem(infoId="rumor", infoType=InformationType.RUMOR)
    correction = makeItem(
        infoId="correction",
        infoType=InformationType.CORRECTION,
        knownOffsetMinutes=20,
        correctsInfoIds=(rumor.infoId,),
    )
    store = PointInTimeInformationStore((rumor, correction))
    network = InformationNetwork(graph, store, seed=10)
    noCoverage = PropagationConfig(
        baseForwardProbability=1.0,
        correctionCoverage=0.0,
        minimumDelaySeconds=0,
        maximumDelaySeconds=0,
    )

    result = network.propagate(
        infoId=correction.infoId,
        seedNodeIds=("a",),
        startAt=BASE_TIME,
        config=noCoverage,
    )
    assert result.reachedNodeCount == 1
    assert result.receipts[0].receivedAt == correction.times.knownAt
    assert network.visibleForNode("a", correction.times.knownAt - timedelta(microseconds=1)) == ()
    assert network.visibleForNode("isolated", correction.times.knownAt) == ()


def test_graph_and_propagation_reject_invalid_boundaries() -> None:
    with pytest.raises(ValidationError, match="even"):
        GraphSpec(
            graphType=GraphType.WS,
            nodeCount=8,
            neighborCount=3,
        )
    graph = SocialGraph.fromEdges(("a",), ())
    item = makeItem()
    network = InformationNetwork(
        graph,
        PointInTimeInformationStore((item,)),
        seed=1,
    )
    with pytest.raises(ValueError, match="unknown seed"):
        network.propagate(
            infoId=item.infoId,
            seedNodeIds=("missing",),
            startAt=BASE_TIME,
            config=PropagationConfig(),
        )
