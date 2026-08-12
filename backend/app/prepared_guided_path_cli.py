"""准备或重置可重复使用的引导研究路径。"""

from __future__ import annotations

import argparse
import time
from datetime import UTC, datetime

from backend.app.account_capabilities import AccountCapabilityRepository
from backend.app.auth import AuthRepository, normalizeEmail
from backend.app.cognition import CognitionService, SessionConfigStore
from backend.app.config import loadSettings
from backend.app.database import Database
from backend.app.guided_workflow.models import GuidedStage
from backend.app.guided_workflow.repository import GuidedWorkflowRepository
from backend.app.prepared_guided_path import (
    PREPARED_GUIDED_PATH_CAPABILITY,
    PreparedGuidedPathConfiguration,
)
from backend.app.schemas import EventPackCreateRequest, EventSourceInput, ExperimentRequest
from backend.app.service import EventPackService, ExperimentService

EVENT_PACK_ID = "custom-gold-liquidity-prepared-v1"
SCENARIO_ID = "scn-prepared-gold-liquidity-v1"
EXPERIMENT_IDEMPOTENCY_KEY = "prepared-guided-gold-liquidity-v1"


def _eventMetadata() -> dict[str, object]:
    return {
        "title": "Gold Liquidity Stress: Safe-Haven Demand versus Forced Selling",
        "titleZh": "黄金流动性压力：避险需求与被迫卖出",
        "summary": (
            "A bounded synthetic scenario examining how safe-haven demand and liquidity "
            "pressure can interact in a gold-linked market proxy."
        ),
        "summaryZh": (
            "一个有边界的合成情景，用于研究避险需求与流动性压力如何在黄金关联市场代理中相互作用。"
        ),
        "instrument": "XAUUSD_SYNTH",
        "asOf": "2026-03-20T23:59:59Z",
        "asOfPrecision": "SECOND",
        "researchQuestion": (
            "Holding the prepared evidence and all other assumptions fixed, does lower "
            "synthetic market-making capacity amplify gold liquidity stress and downside risk?"
        ),
    }


def _experimentRequest() -> ExperimentRequest:
    return ExperimentRequest(
        eventPackId=EVENT_PACK_ID,
        question=str(_eventMetadata()["researchQuestion"]),
        questionZh=(
            "在既有证据和其他假设不变时，降低合成做市能力是否会放大黄金市场的流动性压力与下行风险？"
        ),
        questionInterventionParameter="marketMakerCapacity",
        questionReviewMethod="GENERATED_ALIGNED",
        intervention={
            "parameter": "marketMakerCapacity",
            "baselineValue": 1.0,
            "interventionValue": 0.65,
        },
        seedCount=10,
        populationSize=56,
        steps=120,
        market={
            "instrumentId": "XAUUSD_SYNTH",
            "benchmarkId": "GOLD_SYNTHETIC",
            "tickSize": 0.1,
            "initialPrice": 3_250.0,
            "feeBps": 0.3,
            "latencyMs": 25,
            "openingAuction": True,
            "volatilityHalt": True,
            "priceCollarBps": 180.0,
        },
        llmPolicy={
            "mode": "RULE_ONLY",
            "representativeAgentCount": 0,
            "callBudget": 0,
            "maxCostUsd": 0,
            "fallbackToRules": False,
        },
        primaryOutcome="maxSpreadBps",
        secondaryOutcomes=["maxDrawdownPct", "minDepth", "liquidityStressIndex"],
        acknowledgedScenarioNotForecast=True,
        acknowledgedSyntheticAssumptions=True,
    )


def _configuration(experimentId: str) -> PreparedGuidedPathConfiguration:
    return PreparedGuidedPathConfiguration.model_validate(
        {
            "eventPackId": EVENT_PACK_ID,
            "scenarioId": SCENARIO_ID,
            "experimentId": experimentId,
            "eventMetadata": _eventMetadata(),
            "sourceMethod": "MANUAL",
            "intervention": {
                "parameter": "marketMakerCapacity",
                "baselineValue": 1.0,
                "interventionValue": 0.65,
                "explanation": (
                    "Change only synthetic market-making capacity so the paired comparison "
                    "keeps a clear single-intervention interpretation."
                ),
            },
            "stageCopy": {
                "zh-CN": {
                    GuidedStage.EVENT_GOAL.value: {
                        "assistantMessage": (
                            "我已把你的研究意图整理为一份可编辑候选：比较避险需求与流动性压力共同出现时，"
                            "做市能力下降是否放大黄金关联市场代理的压力。请核对标题、摘要、研究对象、截止时间和研究问题；"
                            "只有你点击应用后才会进入草稿。"
                        ),
                        "nextQuestionOptions": ("应用候选并继续", "要求修改研究问题"),
                    },
                    GuidedStage.SOURCE_METHOD.value: {
                        "assistantMessage": (
                            "我已把证据收集方式整理为人工审核来源。请确认采用这套来源方案；"
                            "来源、主张和冻结状态仍可在事件包页面逐项核对。"
                        ),
                        "nextQuestionOptions": ("采用人工整理来源", "查看事件包"),
                    },
                    GuidedStage.SCENARIO_INTERVENTION.value: {
                        "assistantMessage": (
                            "建议只改变一个变量：将合成做市能力从 1.00 降至 0.65，"
                            "其他条件与配对随机种子保持一致。"
                            "请核对后应用；结果是机制情景分析，不是价格预测或投资建议。"
                        ),
                        "nextQuestionOptions": ("应用单一干预并完成", "要求修改干预"),
                    },
                },
                "en": {
                    GuidedStage.EVENT_GOAL.value: {
                        "assistantMessage": (
                            "I organized your research intent into an editable candidate: test "
                            "whether lower market-making capacity amplifies stress in a "
                            "gold-linked "
                            "market proxy when safe-haven demand and liquidity pressure interact. "
                            "Review every field; it enters the draft only after you apply it."
                        ),
                        "nextQuestionOptions": ("Apply and continue", "Revise the question"),
                    },
                    GuidedStage.SOURCE_METHOD.value: {
                        "assistantMessage": (
                            "I organized the evidence collection method as human-reviewed manual "
                            "sources. Confirm this source plan, and inspect the evidence, claims, "
                            "and frozen boundary on the evidence page if needed."
                        ),
                        "nextQuestionOptions": ("Use reviewed manual sources", "Inspect evidence"),
                    },
                    GuidedStage.SCENARIO_INTERVENTION.value: {
                        "assistantMessage": (
                            "Change one variable only: reduce synthetic market-making capacity "
                            "from 1.00 to 0.65 while holding other settings and paired seeds "
                            "fixed. Review "
                            "before applying; this is scenario analysis, not a forecast or advice."
                        ),
                        "nextQuestionOptions": ("Apply and complete", "Revise intervention"),
                    },
                },
            },
        }
    )


def _userId(authRepository: AuthRepository, email: str) -> str:
    user = authRepository.getUserByEmail(normalizeEmail(email))
    if user is None:
        raise LookupError("the requested account does not exist")
    if user["status"] != "ACTIVE":
        raise ValueError("the requested account is not active")
    return str(user["id"])


def _prepareEventPack(eventPacks: EventPackService, ownerUserId: str) -> None:
    try:
        existing = eventPacks.getEventPack(EVENT_PACK_ID, ownerUserId)
    except Exception as error:
        if getattr(error, "code", None) != "EVENT_PACK_NOT_FOUND":
            raise
        existing = None
    if existing is None:
        asOf = datetime(2026, 3, 20, 23, 59, 59, tzinfo=UTC)
        sourceText = (
            "This course research brief defines a synthetic gold-liquidity stress scenario. "
            "It examines safe-haven demand and liquidity pressure as competing mechanisms. "
            "All price paths, order flow, and agent behavior are simulated and are not forecasts."
        )
        eventPacks.createEventPack(
            EventPackCreateRequest(
                title=str(_eventMetadata()["title"]),
                titleZh=str(_eventMetadata()["titleZh"]),
                summary=str(_eventMetadata()["summary"]),
                summaryZh=str(_eventMetadata()["summaryZh"]),
                asOf=asOf,
                instrument="XAUUSD_SYNTH",
                acknowledgedContentReview=True,
                useLlm=False,
                sources=[
                    EventSourceInput(
                        sourceId="prepared-course-research-brief",
                        title="Prepared gold-liquidity course research brief",
                        publisher="EventShock Lab course team",
                        sourceType="USER_PROVIDED",
                        publishedAt=asOf,
                        knownAt=asOf,
                        rawText=sourceText,
                    )
                ],
            ),
            ownerUserId,
            eventPackId=EVENT_PACK_ID,
            extractionMode="HUMAN_PREPARED",
            claims=[
                {
                    "claimId": "claim-prepared-mechanism-boundary",
                    "text": (
                        "The reviewed brief defines safe-haven demand and liquidity pressure "
                        "as competing mechanisms in a synthetic gold-linked scenario."
                    ),
                    "textZh": (
                        "已审核资料将避险需求与流动性压力定义为黄金关联合成情景中的竞争机制。"
                    ),
                    "claimType": "MECHANISM_HYPOTHESIS",
                    "sourceIds": ["prepared-course-research-brief"],
                    "sourceTier": "USER_PROVIDED",
                    "publishedAt": asOf.isoformat(),
                    "knownAt": asOf.isoformat(),
                    "confidence": 1.0,
                    "impactChannels": ["belief", "liquidity"],
                    "reviewStatus": "HUMAN_APPROVED",
                    "reviewedBy": ownerUserId,
                    "reviewedAt": datetime.now(UTC).isoformat(),
                    "reviewRationale": "Prepared and reviewed for the bounded course scenario.",
                    "isRequired": True,
                    "evidenceQuote": sourceText,
                    "synthetic": True,
                },
                {
                    "claimId": "claim-prepared-synthetic-boundary",
                    "text": (
                        "All prices, order flow, and agent behavior in this scenario are simulated."
                    ),
                    "textZh": "本情景中的价格、订单流与智能体行为全部为模拟数据。",
                    "claimType": "FACT",
                    "sourceIds": ["prepared-course-research-brief"],
                    "sourceTier": "USER_PROVIDED",
                    "publishedAt": asOf.isoformat(),
                    "knownAt": asOf.isoformat(),
                    "confidence": 1.0,
                    "impactChannels": ["liquidity"],
                    "reviewStatus": "HUMAN_APPROVED",
                    "reviewedBy": ownerUserId,
                    "reviewedAt": datetime.now(UTC).isoformat(),
                    "reviewRationale": "The scenario boundary is explicit in the reviewed brief.",
                    "isRequired": True,
                    "evidenceQuote": sourceText,
                    "synthetic": True,
                },
            ],
        )
    eventPacks.freezeEventPack(EVENT_PACK_ID, ownerUserId)


def prepare(email: str) -> dict[str, str]:
    settings = loadSettings()
    database = Database(settings.databasePath)
    database.initialize()
    authRepository = AuthRepository(database)
    authRepository.initialize()
    capabilities = AccountCapabilityRepository(database)
    capabilities.initialize()
    ownerUserId = _userId(authRepository, email)
    cognition = CognitionService(configStore=SessionConfigStore())
    eventPacks = EventPackService(database, settings.projectRoot, cognition)
    experiments = ExperimentService(database, eventPacks, cognition)
    try:
        _prepareEventPack(eventPacks, ownerUserId)
        requestData = _experimentRequest()
        validation = eventPacks.validateExperiment(requestData, ownerUserId, None)
        if not validation["valid"]:
            raise ValueError(f"prepared scenario failed validation: {validation['errors']}")
        scenario = database.saveScenario(
            SCENARIO_ID,
            ownerUserId,
            "Gold liquidity stress — one-variable paired comparison",
            requestData.model_dump(mode="json"),
            True,
        )
        database.appendAuditEvent(
            ownerUserId,
            "SCENARIO",
            SCENARIO_ID,
            "PREPARED_AND_FROZEN",
            {"contentHash": scenario["contentHash"]},
        )
        experiment, _ = experiments.createExperiment(
            requestData,
            ownerUserId,
            EXPERIMENT_IDEMPOTENCY_KEY,
        )
        experiment = experiments.startExperiment(experiment["id"], ownerUserId)
        deadline = time.monotonic() + 180
        while experiment["status"] not in {"COMPLETED", "FAILED_FINAL"}:
            if time.monotonic() >= deadline:
                raise TimeoutError("prepared experiment did not finish within 180 seconds")
            time.sleep(0.5)
            experiment = experiments.publicExperiment(
                experiments.getExperiment(experiment["id"], ownerUserId)
            )
        if experiment["status"] != "COMPLETED":
            raise RuntimeError(f"prepared experiment failed: {experiment.get('errorCode')}")
        capabilities.grant(
            userId=ownerUserId,
            capability=PREPARED_GUIDED_PATH_CAPABILITY,
            configuration=_configuration(experiment["id"]).model_dump(mode="json"),
        )
        return {
            "userId": ownerUserId,
            "eventPackId": EVENT_PACK_ID,
            "scenarioId": SCENARIO_ID,
            "experimentId": experiment["id"],
        }
    finally:
        experiments.shutdown()


def reset(email: str) -> dict[str, str | int]:
    settings = loadSettings()
    database = Database(settings.databasePath)
    database.initialize()
    authRepository = AuthRepository(database)
    authRepository.initialize()
    GuidedWorkflowRepository(database).initialize()
    capabilities = AccountCapabilityRepository(database)
    capabilities.initialize()
    ownerUserId = _userId(authRepository, email)
    if (
        capabilities.getConfiguration(
            userId=ownerUserId,
            capability=PREPARED_GUIDED_PATH_CAPABILITY,
        )
        is None
    ):
        raise ValueError("the account does not have a prepared guided path")
    with database.writeLock, database.connection() as connection:
        cursor = connection.execute(
            "DELETE FROM guided_workflows WHERE owner_user_id=?",
            (ownerUserId,),
        )
    database.appendAuditEvent(
        ownerUserId,
        "GUIDED_WORKFLOW",
        ownerUserId,
        "PREPARED_WORKFLOW_RESET",
        {"deletedWorkflowCount": cursor.rowcount},
    )
    return {"userId": ownerUserId, "deletedWorkflowCount": cursor.rowcount}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "reset"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--email", required=True)
    arguments = parser.parse_args()
    result = prepare(arguments.email) if arguments.command == "prepare" else reset(arguments.email)
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
