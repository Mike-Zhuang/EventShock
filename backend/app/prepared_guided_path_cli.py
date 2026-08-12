"""准备或重置可重复使用、经过人工复核的引导研究路径。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from backend.app.account_capabilities import AccountCapabilityRepository
from backend.app.auth import AuthRepository, normalizeEmail
from backend.app.cognition import (
    AdminPersistentCredentialVault,
    CognitionService,
    SessionConfigStore,
    adminCredentialReference,
)
from backend.app.config import Settings, loadSettings
from backend.app.database import Database
from backend.app.guided_workflow.models import GuidedStage
from backend.app.guided_workflow.repository import GuidedWorkflowRepository
from backend.app.prepared_guided_path import (
    PREPARED_GUIDED_PATH_CAPABILITY,
    PreparedGuidedPathConfiguration,
)
from backend.app.schemas import EventPackCreateRequest, EventSourceInput, ExperimentRequest
from backend.app.service import EventPackService, ExperimentService

EVENT_PACK_ID = "custom-gold-liquidity-reviewed-v3"
SCENARIO_ID = "scn-gold-liquidity-reviewed-v3"
COGNITION_SESSION_ID = "guided-research-seeding-v3"
EXPERIMENT_IDEMPOTENCY_KEYS = (
    "guided-gold-liquidity-hybrid-v3-a1",
    "guided-gold-liquidity-hybrid-v3-a2",
    "guided-gold-liquidity-hybrid-v3-a3",
    "guided-gold-liquidity-hybrid-v3-a4",
)
INTERPRETATION_CONVERSATION_ID = "gold-research-summary-en-v1"
INTERPRETATION_CLIENT_REQUEST_ID = "gold-research-summary-request-en-v1"
INTERPRETATION_QUESTION = (
    "War usually supports gold, so why could gold fall from its January 29 record high near "
    "USD 5,600 to about USD 4,675 by March 20? Using this experiment, explain in plain English "
    "how safe-haven demand, liquidity stress, an oil shock, and forced selling can compete; "
    "what lower market-making capacity changed; how the validated hybrid-LLM cognition layer "
    "participated; and what the biggest limitation is. Use the strongest server-verified "
    "numbers and cite result claims with the supplied [result:*] evidence markers. End with one "
    "practical takeaway for Xiaoming while making clear that this scenario neither proves the "
    "historical price move nor provides a forecast or investment advice."
)
INTERPRETATION_REQUIRED_TERMS = (
    "5,600",
    "4,675",
    "xiaoming",
    "safe-haven",
    "liquidity",
    "oil",
    "forced selling",
    "market-making",
)


def _eventMetadata() -> dict[str, object]:
    return {
        "title": "Gold after a Record High: Safe-Haven Demand versus Liquidity Stress",
        "titleZh": "黄金创新高后的反转：避险需求与流动性压力",
        "summary": (
            "A bounded synthetic scenario based on a human-reviewed classroom narrative: gold "
            "reached a record high near USD 5,600 on January 29, 2026, then fell to USD 4,675 "
            "by March 20 as war-related safe-haven demand competed with liquidity stress, an "
            "oil shock, and forced selling."
        ),
        "summaryZh": (
            "一个基于人工审核课堂叙事的有边界合成情景：黄金在 2026 年 1 月 29 日于 5,600 美元附近"
            "创下高点，战争爆发后并未单向上涨，而是在避险需求、流动性压力、油价冲击与被迫卖出共同作用下，"
            "于 3 月 20 日回落至 4,675 美元。"
        ),
        "instrument": "XAUUSD_SYNTH",
        "asOf": "2026-03-20T23:59:59Z",
        "asOfPrecision": "SECOND",
        "researchQuestion": (
            "Holding the reviewed evidence and all other assumptions fixed, does lower "
            "synthetic market-making capacity amplify gold liquidity stress and downside risk?"
        ),
    }


def _experimentRequest(*, provider: str, model: str) -> ExperimentRequest:
    return ExperimentRequest(
        eventPackId=EVENT_PACK_ID,
        question=str(_eventMetadata()["researchQuestion"]),
        questionZh=(
            "在已审核证据和其他假设不变时，降低合成做市能力是否会放大黄金市场的流动性压力与下行风险？"
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
            "mode": "HYBRID_LLM",
            "provider": provider,
            "modelId": model,
            "representativeAgentCount": 2,
            "decisionIntervalSteps": 60,
            "callBudget": 4,
            "maxCostUsd": 40,
            "fallbackToRules": False,
        },
        primaryOutcome="maxSpreadBps",
        secondaryOutcomes=["maxDrawdownPct", "minDepth", "liquidityStressIndex"],
        acknowledgedScenarioNotForecast=True,
        acknowledgedSyntheticAssumptions=True,
    )


def _reviewItem(
    itemId: str,
    category: str,
    title: str,
    detail: str,
) -> dict[str, object]:
    return {
        "id": itemId,
        "category": category,
        "title": title,
        "detail": detail,
        "requiresExplicitReview": True,
    }


def _stageCopy(*, provider: str, model: str) -> dict[str, dict[str, dict[str, Any]]]:
    zh: dict[str, dict[str, Any]] = {
        GuidedStage.EVENT_GOAL.value: {
            "assistantMessage": (
                "我已把研究目标拆成五个可审核字段。请逐项确认事件标题、摘要、合成研究对象、"
                "时点边界和研究问题；只有全部勾选并应用后，这些内容才进入 Event Pack 草稿。"
            ),
            "preparationSteps": [
                "识别研究对象与非预测边界",
                "把问题改写为可配对比较的单一研究问题",
                "校验时点边界和合成代码",
            ],
            "reviewItems": [
                _reviewItem(
                    "goal-title", "METADATA", "事件标题", "黄金流动性压力：避险需求与被迫卖出。"
                ),
                _reviewItem(
                    "goal-summary",
                    "METADATA",
                    "研究摘要",
                    "只研究机制传播，不把合成路径写成真实价格预测。",
                ),
                _reviewItem(
                    "goal-instrument",
                    "METADATA",
                    "研究对象",
                    "XAUUSD_SYNTH 是合成市场代理，不是真实可交易报价。",
                ),
                _reviewItem(
                    "goal-asof", "METADATA", "时点边界", "证据冻结在 2026-03-20 23:59:59 UTC。"
                ),
                _reviewItem(
                    "goal-question",
                    "METADATA",
                    "研究问题",
                    "只检验降低做市能力是否放大流动性压力与下行风险。",
                ),
            ],
            "nextQuestionOptions": ("全部核对无误，生成研究目标草稿", "修改其中一个字段"),
        },
        GuidedStage.SOURCE_METHOD.value: {
            "assistantMessage": (
                "下一步构建 Event Pack 的来源账本。本流程使用五份已整理的课程研究材料：演讲时间线、"
                "冲突与避险需求、油价与融资压力、流动性机制、研究边界与实验控制。"
                "请确认采用人工审核来源；系统不会把课堂叙事冒充独立核验的实时行情。"
            ),
            "preparationSteps": [
                "解析五份来源材料",
                "统一发布时间与可见时间",
                "生成来源 ID、内容哈希和来源类型",
            ],
            "reviewItems": [
                _reviewItem(
                    "method-corpus",
                    "SOURCE",
                    "来源范围",
                    "仅使用五份有边界、经过人工复核的课程研究材料。",
                ),
                _reviewItem(
                    "method-ledger", "SOURCE", "来源账本", "每份材料保留来源 ID、时间和内容哈希。"
                ),
                _reviewItem(
                    "method-human", "SOURCE", "人工责任", "所有来源和抽取主张仍需逐项人工决定。"
                ),
            ],
            "nextQuestionOptions": ("采用人工审核来源并构建 Event Pack", "调整来源方法"),
        },
        GuidedStage.SOURCE_REVIEW.value: {
            "assistantMessage": (
                "Event Pack 来源账本已经建立，共 5 个来源。请逐份核对它们的用途和边界；"
                "此步骤只确认来源可以进入研究，不等于批准由来源抽取出的全部主张。"
            ),
            "preparationSteps": [
                "写入 5 条来源账本记录",
                "计算并保存来源内容哈希",
                "检查所有来源均不晚于时点边界",
            ],
            "reviewItems": [
                _reviewItem(
                    "source-timeline",
                    "SOURCE",
                    "演讲时间线",
                    (
                        "记录 1 月 29 日高点与 3 月 20 日回落；它是人工审核的课堂叙事，"
                        "不是独立行情核验。"
                    ),
                ),
                _reviewItem(
                    "source-conflict",
                    "SOURCE",
                    "冲突与避险材料",
                    "说明战争可提高避险需求，但不能单独决定价格方向。",
                ),
                _reviewItem(
                    "source-oil",
                    "SOURCE",
                    "油价与融资材料",
                    "说明油价冲击可经通胀、利率预期和融资压力影响信念与流动性。",
                ),
                _reviewItem(
                    "source-liquidity",
                    "SOURCE",
                    "流动性机制材料",
                    "描述做市能力、保证金压力和被迫卖出通道。",
                ),
                _reviewItem(
                    "source-boundary",
                    "SOURCE",
                    "研究边界与控制",
                    "定义合成研究对象、单变量配对设计和非预测边界。",
                ),
            ],
            "nextQuestionOptions": ("五份来源均已核对", "打开事件包查看完整来源账本"),
        },
        GuidedStage.CLAIM_REVIEW.value: {
            "assistantMessage": (
                "系统从来源材料整理出 9 条候选主张。请逐条阅读：时间线只复述人工审核的课堂材料；"
                "冲突、避险、油价、流动性和被迫卖出属于待检验机制；最后两条约束实验设计与解释边界。"
                "未核对的主张不能进入冻结证据集。"
            ),
            "preparationSteps": [
                "将跨句材料合并为完整主张",
                "把每条主张绑定到来源 ID",
                "为主张标注影响通道和合成属性",
            ],
            "reviewItems": [
                _reviewItem(
                    "claim-timeline",
                    "CLAIM",
                    "课堂时间线",
                    "课堂叙事记录了创新高、战争与随后回落，但未把它标成独立行情核验。",
                ),
                _reviewItem(
                    "claim-competing", "CLAIM", "竞争机制", "避险买入与流动性压力可能同时存在。"
                ),
                _reviewItem(
                    "claim-demand", "CLAIM", "避险需求", "避险需求可改变参与者信念和买入偏好。"
                ),
                _reviewItem(
                    "claim-oil",
                    "CLAIM",
                    "油价冲击",
                    "油价冲击可能经通胀、利率预期与融资条件改变市场行为。",
                ),
                _reviewItem(
                    "claim-interaction",
                    "CLAIM",
                    "机制交互",
                    "战争并非单一方向信号；避险买入、油价冲击、融资压力和被迫卖出会共同作用。",
                ),
                _reviewItem(
                    "claim-capacity", "CLAIM", "做市能力", "较低做市能力可能降低深度并扩大价差。"
                ),
                _reviewItem(
                    "claim-forced-sale", "CLAIM", "被迫卖出", "保证金与去杠杆可能形成额外卖压。"
                ),
                _reviewItem(
                    "claim-design", "CLAIM", "实验设计", "只改变做市能力，并使用相同随机种子配对。"
                ),
                _reviewItem(
                    "claim-synthetic",
                    "CLAIM",
                    "解释边界",
                    "价格、订单流和 Agent 行为均为模拟数据。",
                ),
            ],
            "nextQuestionOptions": ("九条主张均已逐项核对", "打开事件包逐条查看"),
        },
        GuidedStage.PACK_METADATA_REVIEW.value: {
            "assistantMessage": (
                "来源和主张已经关联，现在请复核 Event Pack 的整体元数据。标题、摘要、研究对象、"
                "时点边界和研究问题必须与刚才批准的内容一致，避免证据和实验问题错配。"
            ),
            "preparationSteps": [
                "关联 5 个来源与 9 条主张",
                "核对中英文元数据",
                "验证研究对象与时点一致",
            ],
            "reviewItems": [
                _reviewItem(
                    "pack-identity",
                    "METADATA",
                    "事件包身份",
                    "标题、摘要与黄金流动性压力研究一致。",
                ),
                _reviewItem(
                    "pack-time", "METADATA", "时点一致性", "所有来源可见时间均不晚于冻结边界。"
                ),
                _reviewItem(
                    "pack-question", "METADATA", "问题一致性", "研究问题只对应做市能力这一项干预。"
                ),
            ],
            "nextQuestionOptions": ("事件包元数据一致", "返回修改研究目标"),
        },
        GuidedStage.PACK_FREEZE_REVIEW.value: {
            "assistantMessage": (
                "Event Pack 已达到可冻结状态。冻结会锁定 5 个来源、"
                "9 条人工审核主张、时点边界和哈希；"
                "之后实验只能读取这个版本，不能悄悄覆盖证据。请确认冻结含义。"
            ),
            "preparationSteps": [
                "检查所有主张均有人工作出决定",
                "生成冻结内容哈希",
                "绑定不可变事件包版本",
            ],
            "reviewItems": [
                _reviewItem(
                    "freeze-sources", "FREEZE", "锁定来源", "5 个来源及其内容哈希进入冻结版本。"
                ),
                _reviewItem("freeze-claims", "FREEZE", "锁定主张", "9 条已审核主张进入冻结版本。"),
                _reviewItem("freeze-boundary", "FREEZE", "锁定边界", "后续信息不会进入本次实验。"),
            ],
            "nextQuestionOptions": ("理解并确认冻结证据", "打开事件包复核"),
        },
        GuidedStage.SCENARIO_INTERVENTION.value: {
            "assistantMessage": (
                "证据已经冻结。建议只改变一个变量：把合成做市能力从 1.00 降到 0.65；"
                "其他市场参数、Agent 人口和随机种子保持一致，从而保留清晰的配对解释。"
            ),
            "preparationSteps": ["读取冻结 Event Pack", "生成基准情景", "克隆情景并只修改做市能力"],
            "reviewItems": [
                _reviewItem(
                    "scenario-variable", "SCENARIO", "唯一变量", "只改变 marketMakerCapacity。"
                ),
                _reviewItem(
                    "scenario-values", "SCENARIO", "基准与干预", "基准为 1.00，干预为 0.65。"
                ),
                _reviewItem(
                    "scenario-boundary", "SCENARIO", "解释范围", "结果用于机制比较，不是投资建议。"
                ),
            ],
            "nextQuestionOptions": ("应用单一干预", "调整干预强度"),
        },
        GuidedStage.SCENARIO_REVIEW.value: {
            "assistantMessage": (
                "完整情景已保存：10 对随机种子、56 个 Agent、120 步，"
                f"并启用 {provider}/{model} 的混合 LLM 认知。"
                "代表性 Agent 只形成有界信念和行动偏好；订单与价格仍由确定性市场机制处理。"
            ),
            "preparationSteps": [
                "生成 10 组配对随机种子",
                "配置 56 个 Agent 与 120 个仿真步",
                "绑定严格混合 LLM 认知路由",
            ],
            "reviewItems": [
                _reviewItem(
                    "scenario-seeds", "SCENARIO", "配对设计", "基准和干预复用同一组 10 个随机种子。"
                ),
                _reviewItem(
                    "scenario-agents", "SCENARIO", "Agent 规模", "56 个 Agent，120 个仿真步。"
                ),
                _reviewItem(
                    "scenario-llm",
                    "SCENARIO",
                    "AI 介入",
                    f"{provider}/{model} 负责代表性 Agent 的结构化认知决策。",
                ),
                _reviewItem(
                    "scenario-authority",
                    "SCENARIO",
                    "权限边界",
                    "LLM 不能定价、提交订单或访问网络工具。",
                ),
            ],
            "nextQuestionOptions": ("情景配置无误", "打开情景构建器查看参数"),
        },
        GuidedStage.PREFLIGHT.value: {
            "assistantMessage": (
                "运行前检查已经完成。请核对证据冻结、单变量差异、"
                "LLM 费用上限、结构化输出和工具权限。"
                "本研究资产只在外部 LLM 决策全部通过校验且零规则回退时才会被标记为可用。"
            ),
            "preparationSteps": [
                "验证冻结证据与情景绑定",
                "验证单变量差异",
                "验证外部 LLM 决策与零规则回退",
            ],
            "reviewItems": [
                _reviewItem(
                    "preflight-pack",
                    "PREFLIGHT",
                    "证据检查",
                    "Event Pack 已冻结，来源与主张审核完整。",
                ),
                _reviewItem(
                    "preflight-diff", "PREFLIGHT", "差异检查", "基准与干预只有一个注册变量不同。"
                ),
                _reviewItem(
                    "preflight-ai",
                    "PREFLIGHT",
                    "AI 检查",
                    "外部结构化认知决策已验证，规则回退为 0。",
                ),
                _reviewItem(
                    "preflight-cost", "PREFLIGHT", "费用边界", "调用数量和最大费用责任均已设上限。"
                ),
                _reviewItem(
                    "preflight-tools",
                    "PREFLIGHT",
                    "工具权限",
                    "LLM 无定价、交易、网络或文件系统权限。",
                ),
            ],
            "nextQuestionOptions": ("运行前检查全部通过", "打开运行前检查查看详情"),
        },
        GuidedStage.READY_TO_SUBMIT.value: {
            "assistantMessage": (
                "研究配置与已验证实验记录已经绑定。进入运行中心后，界面会依次展示证据约束观察、"
                "外部 LLM 结构化决策、模式校验、10 组配对路径和结果聚合；"
                "这些阶段都对应同一份服务器实验记录。"
            ),
            "preparationSteps": [
                "加载冻结认知决策",
                "核对 10 组有效配对",
                "准备分阶段运行记录与结果入口",
            ],
            "reviewItems": [
                _reviewItem(
                    "submit-continuity",
                    "PREFLIGHT",
                    "研究连续性",
                    "事件包、情景、认知决策和实验结果属于同一研究链路。",
                ),
                _reviewItem(
                    "submit-result",
                    "PREFLIGHT",
                    "结果可用性",
                    "实验包含 10 组有效配对和完整可复现元数据。",
                ),
                _reviewItem(
                    "submit-boundary",
                    "PREFLIGHT",
                    "最终边界",
                    "输出是合成情景结果，不是现实价格预测。",
                ),
            ],
            "nextQuestionOptions": ("进入运行中心", "再次检查配置"),
        },
    }

    en: dict[str, dict[str, Any]] = {}
    englishMessages = {
        GuidedStage.EVENT_GOAL.value: (
            "Review the five event-goal fields before they enter the Event Pack draft."
        ),
        GuidedStage.SOURCE_METHOD.value: (
            "Build the Event Pack from five bounded, human-reviewed course materials. The supplied "
            "price timeline remains a reviewed classroom narrative rather than an independently "
            "verified market quote."
        ),
        GuidedStage.SOURCE_REVIEW.value: (
            "Review all five source-ledger entries and their evidence boundaries before "
            "claim review."
        ),
        GuidedStage.CLAIM_REVIEW.value: (
            "Review all nine source-linked candidate claims before freezing evidence."
        ),
        GuidedStage.PACK_METADATA_REVIEW.value: (
            "Confirm that Event Pack metadata matches the reviewed evidence and research question."
        ),
        GuidedStage.PACK_FREEZE_REVIEW.value: (
            "Confirm the immutable evidence boundary before freezing this Event Pack version."
        ),
        GuidedStage.SCENARIO_INTERVENTION.value: (
            "Review the single market-making-capacity intervention before applying it."
        ),
        GuidedStage.SCENARIO_REVIEW.value: (
            f"Review paired seeds, agent settings, and strict {provider}/{model} hybrid cognition."
        ),
        GuidedStage.PREFLIGHT.value: (
            "Review evidence, single-variable, cost, structured-output, and tool-authority checks."
        ),
        GuidedStage.READY_TO_SUBMIT.value: (
            "The verified research chain is ready for staged playback in Run Center."
        ),
    }
    englishPreparationSteps = {
        GuidedStage.EVENT_GOAL.value: (
            "Identify the research object and non-forecast boundary",
            "Rewrite the request as one paired research question",
            "Validate the point-in-time boundary and synthetic instrument",
        ),
        GuidedStage.SOURCE_METHOD.value: (
            "Parse five bounded, human-reviewed research sources",
            "Normalize published-at and known-at timestamps",
            "Prepare source identifiers and content hashes",
        ),
        GuidedStage.SOURCE_REVIEW.value: (
            "Write five entries to the source ledger",
            "Calculate and retain content hashes",
            "Check that every source precedes the point-in-time boundary",
        ),
        GuidedStage.CLAIM_REVIEW.value: (
            "Merge source fragments into complete candidate claims",
            "Bind every claim to a source identifier",
            "Label impact channels and synthetic assumptions",
        ),
        GuidedStage.PACK_METADATA_REVIEW.value: (
            "Link five sources and nine reviewed claims",
            "Check English and Chinese Event Pack metadata",
            "Confirm the instrument and point-in-time boundary",
        ),
        GuidedStage.PACK_FREEZE_REVIEW.value: (
            "Check that every claim has a human decision",
            "Generate the immutable content hash",
            "Bind the frozen Event Pack version",
        ),
        GuidedStage.SCENARIO_INTERVENTION.value: (
            "Load the frozen Event Pack",
            "Generate the baseline scenario",
            "Clone it and change only market-making capacity",
        ),
        GuidedStage.SCENARIO_REVIEW.value: (
            "Generate ten paired random seeds",
            "Configure 56 agents and 120 simulation steps",
            "Bind the strict hybrid-LLM cognition route",
        ),
        GuidedStage.PREFLIGHT.value: (
            "Validate the Event Pack and scenario binding",
            "Validate the single-variable difference",
            "Verify external LLM decisions and zero rule fallback",
        ),
        GuidedStage.READY_TO_SUBMIT.value: (
            "Load frozen cognition decisions",
            "Verify ten valid paired runs",
            "Prepare staged run activity and the results link",
        ),
    }
    englishReviewItems = {
        GuidedStage.EVENT_GOAL.value: (
            (
                "Event title",
                "Gold after a Record High: Safe-Haven Demand versus Liquidity Stress.",
            ),
            ("Research summary", "Study mechanism propagation, not a real-world price forecast."),
            ("Research instrument", "XAUUSD_SYNTH is a synthetic proxy, not a tradable quote."),
            ("Point-in-time boundary", "Evidence is frozen at 2026-03-20 23:59:59 UTC."),
            (
                "Research question",
                "Test only whether lower market-making capacity amplifies stress.",
            ),
        ),
        GuidedStage.SOURCE_METHOD.value: (
            ("Source scope", "Use only the five bounded, human-reviewed course materials."),
            ("Source ledger", "Keep a source ID, timestamp, and content hash for every source."),
            ("Human responsibility", "A person must decide on every source and candidate claim."),
        ),
        GuidedStage.SOURCE_REVIEW.value: (
            (
                "Presentation timeline",
                "Records the January 29 high and March 20 decline as a reviewed classroom "
                "narrative, not independent quote verification.",
            ),
            (
                "Conflict and safe-haven source",
                "Explains why war can increase safe-haven demand without determining one "
                "price direction.",
            ),
            (
                "Oil and funding source",
                "Connects an oil shock to inflation expectations, funding pressure, beliefs, "
                "and liquidity.",
            ),
            (
                "Liquidity mechanism source",
                "Describes market-making capacity, margin pressure, and forced selling.",
            ),
            (
                "Research boundary and controls",
                "Defines the synthetic proxy, paired single-variable design, and non-forecast "
                "boundary.",
            ),
        ),
        GuidedStage.CLAIM_REVIEW.value: (
            (
                "Classroom timeline",
                "The reviewed presentation records a high near USD 5,600, the start of war, "
                "and a later decline to USD 4,675; it is not independent quote verification.",
            ),
            (
                "Conflict is not one lever",
                "War may raise safe-haven demand but does not imply a one-direction price outcome.",
            ),
            ("Competing mechanisms", "Safe-haven buying and liquidity pressure can coexist."),
            ("Safe-haven demand", "Demand can change beliefs and buying preferences."),
            (
                "Oil shock",
                "Oil can alter inflation and rate expectations, funding conditions, and market "
                "behavior.",
            ),
            ("Market-making capacity", "Lower capacity may reduce depth and widen spreads."),
            ("Forced selling", "Margin pressure and deleveraging may create selling pressure."),
            ("Paired design", "Only capacity changes and the same seeds are reused."),
            ("Interpretation boundary", "Prices, order flow, and agent behavior are simulated."),
        ),
        GuidedStage.PACK_METADATA_REVIEW.value: (
            ("Event Pack identity", "Title and summary match the gold-liquidity study."),
            ("Time consistency", "Every source is known before the frozen boundary."),
            ("Question consistency", "The question maps to one market-making intervention."),
        ),
        GuidedStage.PACK_FREEZE_REVIEW.value: (
            ("Lock sources", "Freeze five sources and their content hashes."),
            ("Lock claims", "Freeze the nine human-reviewed claims."),
            ("Lock the boundary", "Later information cannot enter this experiment."),
        ),
        GuidedStage.SCENARIO_INTERVENTION.value: (
            ("Single variable", "Change marketMakerCapacity only."),
            ("Baseline and intervention", "Compare 1.00 with 0.65."),
            ("Interpretation scope", "Use results for mechanism comparison, not advice."),
        ),
        GuidedStage.SCENARIO_REVIEW.value: (
            ("Paired design", "Baseline and intervention reuse ten identical random seeds."),
            ("Agent scale", "Use 56 agents and 120 simulation steps."),
            ("AI involvement", f"{provider}/{model} produces structured cognition decisions."),
            (
                "Authority boundary",
                "The LLM cannot price assets, place orders, or use network tools.",
            ),
        ),
        GuidedStage.PREFLIGHT.value: (
            ("Evidence check", "The Event Pack is frozen and every claim has a decision."),
            ("Difference check", "Exactly one registered variable differs."),
            ("AI check", "External structured decisions passed with zero rule fallback."),
            ("Cost boundary", "The call count and maximum cost responsibility are capped."),
            ("Tool authority", "The LLM has no pricing, trading, network, or file access."),
        ),
        GuidedStage.READY_TO_SUBMIT.value: (
            ("Research continuity", "Evidence, scenario, cognition, and results form one chain."),
            ("Result availability", "The experiment has ten valid pairs and replay metadata."),
            ("Final boundary", "Outputs are synthetic scenario results, not price forecasts."),
        ),
    }
    englishNextQuestionOptions = {
        GuidedStage.EVENT_GOAL.value: (
            "I reviewed the title, summary, synthetic instrument, time boundary, and research "
            "question. Prepare this event-goal candidate for my approval.",
            "I need to revise one event-goal field before approval.",
        ),
        GuidedStage.SOURCE_METHOD.value: (
            "Use the five bounded, human-reviewed course materials and preserve the distinction "
            "between the classroom timeline and independently verified market data.",
            "I need to revise the source method before approval.",
        ),
        GuidedStage.SOURCE_REVIEW.value: (
            "I reviewed all five source-ledger entries, their timestamps, hashes, and stated "
            "evidence boundaries. Prepare the source-review candidate.",
            "Open the Event Pack so I can inspect the complete bilingual source ledger.",
        ),
        GuidedStage.CLAIM_REVIEW.value: (
            "I reviewed all nine claims and their source links. Keep facts, supplied narrative, "
            "and mechanism hypotheses visibly distinct.",
            "Open the Event Pack so I can inspect every claim before approval.",
        ),
        GuidedStage.PACK_METADATA_REVIEW.value: (
            "The bilingual Event Pack metadata matches the reviewed evidence, synthetic "
            "instrument, time boundary, and research question.",
            "I need to revise the Event Pack metadata.",
        ),
        GuidedStage.PACK_FREEZE_REVIEW.value: (
            "I understand that freezing locks the five sources, nine reviewed claims, timestamps, "
            "and hashes for reproducible experiments.",
            "Open the Event Pack for one final review before freezing.",
        ),
        GuidedStage.SCENARIO_INTERVENTION.value: (
            "Apply one intervention only: reduce synthetic market-making capacity from 1.00 to "
            "0.65 while holding all other settings fixed.",
            "I need to revise the intervention strength.",
        ),
        GuidedStage.SCENARIO_REVIEW.value: (
            f"I reviewed the ten paired seeds, 56 agents, 120 steps, and the bounded "
            f"{provider}/{model} hybrid-cognition role. Prepare the scenario-review candidate.",
            "Open Scenario Builder so I can inspect the complete configuration.",
        ),
        GuidedStage.PREFLIGHT.value: (
            "I reviewed the frozen evidence, one-variable difference, structured cognition, "
            "zero rule fallback, cost cap, and tool-authority boundary.",
            "Open Preflight so I can inspect every system check.",
        ),
        GuidedStage.READY_TO_SUBMIT.value: (
            "I verified that the Event Pack, scenario, frozen cognition decisions, ten paired "
            "runs, and reproducibility metadata belong to one research chain. Prepare the final "
            "handoff.",
            "Open Preflight for one final check before the run playback.",
        ),
    }
    for stage, copy in zh.items():
        en[stage] = {
            "assistantMessage": englishMessages[stage],
            "preparationSteps": englishPreparationSteps[stage],
            "reviewItems": [
                _reviewItem(
                    f"en-{stage.lower()}-{index}",
                    str(item["category"]),
                    englishReviewItems[stage][index - 1][0],
                    englishReviewItems[stage][index - 1][1],
                )
                for index, item in enumerate(copy["reviewItems"], start=1)
            ],
            "nextQuestionOptions": englishNextQuestionOptions[stage],
        }
    return {"zh-CN": zh, "en": en}


def _configuration(
    experimentId: str,
    *,
    provider: str,
    model: str,
) -> PreparedGuidedPathConfiguration:
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
            "stageCopy": _stageCopy(provider=provider, model=model),
        }
    )


def _userId(authRepository: AuthRepository, email: str) -> str:
    user = authRepository.getUserByEmail(normalizeEmail(email))
    if user is None:
        raise LookupError("the requested account does not exist")
    if user["status"] != "ACTIVE":
        raise ValueError("the requested account is not active")
    return str(user["id"])


def _claim(
    *,
    claimId: str,
    text: str,
    textZh: str,
    claimType: str,
    sourceId: str,
    sourceText: str,
    impactChannels: list[str],
    ownerUserId: str,
    asOf: datetime,
) -> dict[str, object]:
    return {
        "claimId": claimId,
        "text": text,
        "textZh": textZh,
        "claimType": claimType,
        "sourceIds": [sourceId],
        "sourceTier": "USER_PROVIDED",
        "publishedAt": asOf.isoformat(),
        "knownAt": asOf.isoformat(),
        "confidence": 1.0,
        "impactChannels": impactChannels,
        "reviewStatus": "HUMAN_APPROVED",
        "reviewedBy": ownerUserId,
        "reviewedAt": datetime.now(UTC).isoformat(),
        "reviewRationale": "Reviewed for the bounded course research scenario.",
        "isRequired": True,
        "evidenceQuote": sourceText,
        "synthetic": True,
    }


def _prepareEventPack(eventPacks: EventPackService, ownerUserId: str) -> None:
    try:
        existing = eventPacks.getEventPack(EVENT_PACK_ID, ownerUserId)
    except Exception as error:
        if getattr(error, "code", None) != "EVENT_PACK_NOT_FOUND":
            raise
        existing = None
    if existing is not None:
        if not existing.get("frozen"):
            eventPacks.freezeEventPack(EVENT_PACK_ID, ownerUserId)
        return

    asOf = datetime(2026, 3, 20, 23, 59, 59, tzinfo=UTC)
    sourceTexts = {
        "course-gold-presentation-timeline": (
            "The human-reviewed classroom presentation states that gold reached a record high "
            "near USD 5,600 on January 29, 2026 and later stood at USD 4,675 by March 20, 2026 "
            "after war began. This records the supplied narrative as a scenario input; it is not "
            "independent market-price verification."
        ),
        "course-gold-conflict-safe-haven": (
            "The reviewed mechanism brief states that war can increase safe-haven demand and "
            "change participant beliefs and buying preferences. It does not imply a one-direction "
            "price outcome because other channels may dominate."
        ),
        "course-gold-oil-funding": (
            "The reviewed mechanism brief treats an oil shock as a possible channel through "
            "inflation expectations, rate expectations, collateral and funding pressure. These "
            "changes may alter beliefs and market liquidity; they remain hypotheses for testing."
        ),
        "course-gold-liquidity-mechanisms": (
            "Lower synthetic market-making capacity can reduce order-book depth and widen spreads "
            "during stress. Margin pressure and deleveraging can create a forced-selling channel. "
            "Safe-haven buying, oil-related funding pressure, and forced selling may coexist."
        ),
        "course-gold-research-boundary": (
            "This reviewed design brief defines XAUUSD_SYNTH as a synthetic gold-linked market "
            "proxy. The paired experiment changes only marketMakerCapacity from 1.00 to 0.65 and "
            "reuses identical random seeds. Prices, order flow, and agent behavior are simulated; "
            "outputs are mechanism scenarios, not forecasts or investment advice."
        ),
    }
    sources = [
        EventSourceInput(
            sourceId=sourceId,
            title=title,
            titleZh=titleZh,
            publisher="EventShock Lab course research",
            sourceType="USER_PROVIDED",
            publishedAt=asOf,
            knownAt=asOf,
            rawText=sourceTexts[sourceId],
        )
        for sourceId, title, titleZh in (
            (
                "course-gold-presentation-timeline",
                "Human-reviewed classroom gold timeline",
                "人工审核的课堂黄金时间线",
            ),
            (
                "course-gold-conflict-safe-haven",
                "Conflict and safe-haven mechanism notes",
                "冲突与避险需求机制材料",
            ),
            (
                "course-gold-oil-funding",
                "Oil shock and funding-pressure notes",
                "油价冲击与融资压力材料",
            ),
            (
                "course-gold-liquidity-mechanisms",
                "Liquidity capacity and forced-selling notes",
                "流动性能力与被迫卖出材料",
            ),
            (
                "course-gold-research-boundary",
                "Synthetic proxy, paired design, and research boundary",
                "合成代理、配对设计与研究边界",
            ),
        )
    ]
    claims = [
        _claim(
            claimId="claim-gold-classroom-timeline",
            text=(
                "The human-reviewed classroom presentation records a gold high near USD 5,600 "
                "on January 29, the start of war, and a later level of USD 4,675 on March 20."
            ),
            textZh=(
                "经人工审核的课堂演讲材料记录了 1 月 29 日黄金在 5,600 美元附近创下高点、战争爆发，"
                "以及 3 月 20 日回落至 4,675 美元的叙事。"
            ),
            claimType="FACT",
            sourceId="course-gold-presentation-timeline",
            sourceText=sourceTexts["course-gold-presentation-timeline"],
            impactChannels=["belief", "liquidity"],
            ownerUserId=ownerUserId,
            asOf=asOf,
        ),
        _claim(
            claimId="claim-gold-conflict-not-single-direction",
            text=(
                "War can increase safe-haven demand but does not imply a one-direction gold price "
                "outcome when liquidity and funding channels compete."
            ),
            textZh="战争可以提高避险需求，但在流动性与融资通道竞争时并不意味着黄金价格只向一个方向变化。",
            claimType="MECHANISM_HYPOTHESIS",
            sourceId="course-gold-conflict-safe-haven",
            sourceText=sourceTexts["course-gold-conflict-safe-haven"],
            impactChannels=["belief", "liquidity"],
            ownerUserId=ownerUserId,
            asOf=asOf,
        ),
        _claim(
            claimId="claim-gold-competing-mechanisms",
            text=(
                "Safe-haven buying, oil-related funding pressure, and forced selling are competing "
                "mechanisms in this synthetic scenario."
            ),
            textZh="避险买入、油价相关融资压力与被迫卖出是本合成情景中的竞争机制。",
            claimType="MECHANISM_HYPOTHESIS",
            sourceId="course-gold-liquidity-mechanisms",
            sourceText=sourceTexts["course-gold-liquidity-mechanisms"],
            impactChannels=["belief", "liquidity"],
            ownerUserId=ownerUserId,
            asOf=asOf,
        ),
        _claim(
            claimId="claim-gold-safe-haven-demand",
            text="Safe-haven demand can shift participant beliefs and buying preferences.",
            textZh="避险需求可以改变参与者信念和买入偏好。",
            claimType="MECHANISM_HYPOTHESIS",
            sourceId="course-gold-conflict-safe-haven",
            sourceText=sourceTexts["course-gold-conflict-safe-haven"],
            impactChannels=["belief"],
            ownerUserId=ownerUserId,
            asOf=asOf,
        ),
        _claim(
            claimId="claim-gold-oil-funding-pressure",
            text=(
                "An oil shock can alter inflation and rate expectations, collateral and funding "
                "conditions, participant beliefs, and market liquidity."
            ),
            textZh="油价冲击可能改变通胀与利率预期、抵押品与融资条件、参与者信念和市场流动性。",
            claimType="MECHANISM_HYPOTHESIS",
            sourceId="course-gold-oil-funding",
            sourceText=sourceTexts["course-gold-oil-funding"],
            impactChannels=["belief", "liquidity"],
            ownerUserId=ownerUserId,
            asOf=asOf,
        ),
        _claim(
            claimId="claim-gold-market-making-capacity",
            text=(
                "Lower synthetic market-making capacity can reduce depth and widen "
                "spreads during stress."
            ),
            textZh="较低的合成做市能力可能在压力期降低深度并扩大价差。",
            claimType="MECHANISM_HYPOTHESIS",
            sourceId="course-gold-liquidity-mechanisms",
            sourceText=sourceTexts["course-gold-liquidity-mechanisms"],
            impactChannels=["liquidity"],
            ownerUserId=ownerUserId,
            asOf=asOf,
        ),
        _claim(
            claimId="claim-gold-forced-selling",
            text="Margin pressure and deleveraging can create a forced-selling channel.",
            textZh="保证金压力和去杠杆可以形成被迫卖出通道。",
            claimType="MECHANISM_HYPOTHESIS",
            sourceId="course-gold-liquidity-mechanisms",
            sourceText=sourceTexts["course-gold-liquidity-mechanisms"],
            impactChannels=["stopLoss", "liquidity"],
            ownerUserId=ownerUserId,
            asOf=asOf,
        ),
        _claim(
            claimId="claim-gold-paired-design",
            text=(
                "The paired design changes only marketMakerCapacity from 1.00 to 0.65 "
                "and reuses identical seeds."
            ),
            textZh="配对设计只把做市能力从 1.00 改为 0.65，并复用相同随机种子。",
            claimType="FACT",
            sourceId="course-gold-research-boundary",
            sourceText=sourceTexts["course-gold-research-boundary"],
            impactChannels=["liquidity"],
            ownerUserId=ownerUserId,
            asOf=asOf,
        ),
        _claim(
            claimId="claim-gold-synthetic-boundary",
            text=(
                "All price paths, order flow, and agent behavior are simulated and "
                "are not forecasts."
            ),
            textZh="所有价格路径、订单流和 Agent 行为均为模拟结果，不是预测。",
            claimType="FACT",
            sourceId="course-gold-research-boundary",
            sourceText=sourceTexts["course-gold-research-boundary"],
            impactChannels=["belief"],
            ownerUserId=ownerUserId,
            asOf=asOf,
        ),
    ]
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
            sources=sources,
        ),
        ownerUserId,
        eventPackId=EVENT_PACK_ID,
        extractionMode="HUMAN_REVIEWED",
        claims=claims,
    )
    eventPacks.freezeEventPack(EVENT_PACK_ID, ownerUserId)


def _persistentRuntime(
    *,
    settings: Settings,
    database: Database,
    authRepository: AuthRepository,
) -> tuple[SessionConfigStore, str, str]:
    if not settings.adminApiKeyEncryptionKey or not settings.adminEmail:
        raise ValueError("administrator persistent LLM credentials are not configured")
    adminUserId = _userId(authRepository, settings.adminEmail)
    vault = AdminPersistentCredentialVault(
        database=database,
        encryptionKey=settings.adminApiKeyEncryptionKey,
        configuredAdminEmail=settings.adminEmail,
    )
    vault.initialize()
    reference = adminCredentialReference(
        userId=adminUserId,
        authSessionId=COGNITION_SESSION_ID,
    )
    runtime = vault.resolveRuntimeReference(reference)
    if runtime is None:
        raise ValueError("administrator persistent LLM credential is unavailable")
    configStore = SessionConfigStore()
    configStore.setConfig(
        sessionId=COGNITION_SESSION_ID,
        apiKey=runtime.apiKey,
        provider=runtime.provider,
        model=runtime.model,
        thinkingEnabled=False,
        maxTokens=min(runtime.maxTokens, 4_096),
        advancedParameters=runtime.advancedParameters,
    )
    return configStore, runtime.provider, runtime.model


def _verifiedHybridResult(experiment: dict[str, Any]) -> bool:
    result = experiment.get("result") or {}
    manifest = result.get("manifest") or {}
    cognition = result.get("cognition") or {}
    return bool(
        experiment.get("status") == "COMPLETED"
        and manifest.get("agentMode") == "HYBRID_LLM"
        and manifest.get("llmExternalModelUsed") is True
        and int(manifest.get("llmFallbackCount") or 0) == 0
        and int(cognition.get("attemptedCalls") or 0) > 0
        and int(cognition.get("structuredValidCalls") or 0) > 0
        and int(cognition.get("calls") or 0) > 0
        and int(cognition.get("fallbackCount") or 0) == 0
        and cognition.get("resolvedMode") == "HYBRID_LLM"
    )


def _prepareExperiment(
    *,
    experiments: ExperimentService,
    eventPacks: EventPackService,
    database: Database,
    ownerUserId: str,
    provider: str,
    model: str,
) -> dict[str, Any]:
    requestData = _experimentRequest(provider=provider, model=model)
    validation = eventPacks.validateExperiment(
        requestData,
        ownerUserId,
        COGNITION_SESSION_ID,
    )
    if not validation["valid"]:
        raise ValueError(f"guided scenario failed validation: {validation['errors']}")
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
        "REVIEWED_AND_FROZEN",
        {"contentHash": scenario["contentHash"]},
    )

    failures: list[str] = []
    for idempotencyKey in EXPERIMENT_IDEMPOTENCY_KEYS:
        public, _ = experiments.createExperiment(
            requestData,
            ownerUserId,
            idempotencyKey,
            COGNITION_SESSION_ID,
        )
        stored = experiments.getExperiment(public["id"], ownerUserId)
        if _verifiedHybridResult(stored):
            return stored
        if stored["status"] in {"READY", "FAILED_RETRYABLE"}:
            experiments.startExperiment(
                stored["id"],
                ownerUserId,
                COGNITION_SESSION_ID,
            )
        deadline = time.monotonic() + 600
        while True:
            stored = experiments.getExperiment(stored["id"], ownerUserId)
            if stored["status"] in {"COMPLETED", "FAILED_FINAL", "CANCELLED"}:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("guided experiment did not finish within 600 seconds")
            time.sleep(0.5)
        if _verifiedHybridResult(stored):
            return stored
        failures.append(f"{stored['id']}:{stored['status']}:{stored.get('errorCode')}")
    raise RuntimeError(
        "no verified zero-fallback hybrid experiment was produced: " + ", ".join(failures)
    )


def _validatePreparedInterpretation(
    run: Any,
    *,
    provider: str,
    model: str,
) -> None:
    """只接受真实模型生成且已通过证据约束的演示解释。"""

    if run.provider != provider or run.model != model:
        raise ValueError("prepared interpretation used an unexpected provider or model")
    if run.deterministic_fallback_used:
        raise ValueError("prepared interpretation used deterministic fallback text")
    if run.semantic_validation_status not in {"PASSED", "COMPLETED_WITH_WARNINGS"}:
        raise ValueError(
            "prepared interpretation did not reach an accepted semantic terminal state"
        )
    if not run.interpretation.grounding_references:
        raise ValueError("prepared interpretation did not include result evidence references")
    _validatePreparedInterpretationContent(
        answer=run.interpretation.answer,
        groundingReferences=run.interpretation.grounding_references,
    )


def _validatePreparedInterpretationContent(
    *,
    answer: str,
    groundingReferences: tuple[str, ...] | list[str],
) -> None:
    """确保课堂解释既有可核对证据，也完整回应黄金故事。"""

    if not groundingReferences:
        raise ValueError("prepared interpretation did not include result evidence references")
    normalizedAnswer = answer.lower().replace("-", " ")
    missingTerms = [
        term
        for term in INTERPRETATION_REQUIRED_TERMS
        if term.replace("-", " ") not in normalizedAnswer
    ]
    if missingTerms:
        raise ValueError(
            "prepared interpretation omitted presentation anchors: " + ", ".join(missingTerms)
        )
    if "[result:" not in normalizedAnswer:
        raise ValueError("prepared interpretation did not cite evidence markers inline")


def _existingPreparedInterpretation(
    *,
    database: Database,
    ownerUserId: str,
    experimentId: str,
    provider: str,
    model: str,
) -> dict[str, Any] | None:
    """复用已通过校验的预置解释，避免重复准备时再次产生模型费用。"""

    conversation = database.getResultInterpretationConversation(
        ownerUserId=ownerUserId,
        experimentId=experimentId,
        conversationId=INTERPRETATION_CONVERSATION_ID,
    )
    if conversation is None:
        return None
    exchanges = conversation.get("exchanges")
    if not isinstance(exchanges, list) or len(exchanges) != 1:
        raise ValueError("prepared interpretation conversation has an unexpected shape")
    exchange = exchanges[0]
    assistant = exchange.get("assistantMessage")
    if not isinstance(assistant, dict):
        raise ValueError("prepared interpretation history has no assistant message")
    if assistant.get("provider") != provider or assistant.get("model") != model:
        raise ValueError("prepared interpretation history used an unexpected model route")
    if assistant.get("deterministicFallbackUsed") is True:
        raise ValueError("prepared interpretation history used deterministic fallback text")
    if assistant.get("semanticValidationStatus") not in {
        "PASSED",
        "COMPLETED_WITH_WARNINGS",
    }:
        raise ValueError("prepared interpretation history failed semantic validation")
    answer = assistant.get("answer")
    groundingReferences = assistant.get("groundingReferences")
    if not isinstance(answer, str) or not isinstance(groundingReferences, list):
        raise ValueError("prepared interpretation history is missing grounded answer fields")
    _validatePreparedInterpretationContent(
        answer=answer,
        groundingReferences=groundingReferences,
    )
    return exchange


def _preparedInterpretationMessage(run: Any) -> dict[str, Any]:
    """复用正式接口的持久化白名单结构，避免演示历史产生第二套格式。"""

    answer = run.interpretation
    return {
        "id": f"interpretation-{uuid.uuid4().hex[:24]}",
        "role": "assistant",
        "language": "en",
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
        "thinkingPreferenceEnabled": run.thinking_preference_enabled,
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
        "semanticValidationStatus": run.semantic_validation_status,
        "deterministicFallbackUsed": run.deterministic_fallback_used,
        "semanticViolationCodes": list(run.semantic_violation_codes),
        "failureCodes": list(run.failure_codes),
        "promptVersion": run.prompt_version,
        "latencyMs": run.latency_ms,
        "createdAt": datetime.now(UTC).isoformat(),
    }


def _prepareInterpretation(
    *,
    cognition: CognitionService,
    database: Database,
    ownerUserId: str,
    experiment: dict[str, Any],
    provider: str,
    model: str,
) -> dict[str, Any]:
    """用真实完成结果生成一次英文解释，并保存为课堂期间可直接加载的历史。"""

    authoritativeResult = experiment.get("result")
    if not isinstance(authoritativeResult, dict):
        raise ValueError("completed experiment does not contain an authoritative result")
    existing = _existingPreparedInterpretation(
        database=database,
        ownerUserId=ownerUserId,
        experimentId=experiment["id"],
        provider=provider,
        model=model,
    )
    if existing is not None:
        return existing
    run = asyncio.run(
        cognition.interpretExperimentResult(
            sessionId=COGNITION_SESSION_ID,
            result=authoritativeResult,
            messages=({"role": "user", "content": INTERPRETATION_QUESTION},),
            language="en",
            initial=True,
            includeAnalysisSummary=False,
        )
    )
    _validatePreparedInterpretation(run, provider=provider, model=model)
    requestHash = hashlib.sha256(
        json.dumps(
            {
                "conversationId": INTERPRETATION_CONVERSATION_ID,
                "experimentId": experiment["id"],
                "language": "en",
                "question": INTERPRETATION_QUESTION,
                "resultHash": run.result_hash,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    persisted, _created = database.saveResultInterpretationExchange(
        ownerUserId=ownerUserId,
        experimentId=experiment["id"],
        conversationId=INTERPRETATION_CONVERSATION_ID,
        clientRequestId=INTERPRETATION_CLIENT_REQUEST_ID,
        requestHash=requestHash,
        language="en",
        userMessage=INTERPRETATION_QUESTION,
        assistantMessage=_preparedInterpretationMessage(run),
    )
    return persisted


def prepare(email: str) -> dict[str, str]:
    settings = loadSettings()
    database = Database(settings.databasePath)
    database.initialize()
    authRepository = AuthRepository(database)
    authRepository.initialize()
    capabilities = AccountCapabilityRepository(database)
    capabilities.initialize()
    ownerUserId = _userId(authRepository, email)
    configStore, provider, model = _persistentRuntime(
        settings=settings,
        database=database,
        authRepository=authRepository,
    )
    cognition = CognitionService(configStore=configStore)
    eventPacks = EventPackService(database, settings.projectRoot, cognition)
    experiments = ExperimentService(database, eventPacks, cognition)
    try:
        _prepareEventPack(eventPacks, ownerUserId)
        experiment = _prepareExperiment(
            experiments=experiments,
            eventPacks=eventPacks,
            database=database,
            ownerUserId=ownerUserId,
            provider=provider,
            model=model,
        )
        interpretation = _prepareInterpretation(
            cognition=cognition,
            database=database,
            ownerUserId=ownerUserId,
            experiment=experiment,
            provider=provider,
            model=model,
        )
        capabilities.grant(
            userId=ownerUserId,
            capability=PREPARED_GUIDED_PATH_CAPABILITY,
            configuration=_configuration(
                experiment["id"],
                provider=provider,
                model=model,
            ).model_dump(mode="json"),
        )
        return {
            "userId": ownerUserId,
            "eventPackId": EVENT_PACK_ID,
            "scenarioId": SCENARIO_ID,
            "experimentId": experiment["id"],
            "interpretationConversationId": interpretation["conversationId"],
            "provider": provider,
            "model": model,
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
        raise ValueError("the account does not have a guided research path")
    with database.writeLock, database.connection() as connection:
        cursor = connection.execute(
            "DELETE FROM guided_workflows WHERE owner_user_id=?",
            (ownerUserId,),
        )
    database.appendAuditEvent(
        ownerUserId,
        "GUIDED_WORKFLOW",
        ownerUserId,
        "WORKFLOW_RESET",
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
