"""引导工作流各阶段的确定性双语开场消息。"""

from __future__ import annotations

from typing import Literal

from backend.app.guided_workflow.models import GuidedStage

GuidedLanguage = Literal["en", "zh-CN"]

_STAGE_OPENINGS: dict[GuidedStage, dict[GuidedLanguage, str]] = {
    GuidedStage.EVENT_GOAL: {
        "en": (
            "Define the event, instrument, time boundary, and research question for this "
            "study. Tell me the bounded event and question you want to examine; AI may "
            "propose editable metadata, but you must review and explicitly apply it."
        ),
        "zh-CN": (
            "本阶段用于界定研究事件、对象、时间边界和研究问题。请说明要研究的有界事件与"
            "问题；AI 可以提出可编辑的元数据，但必须由你逐项审核并明确应用。"
        ),
    },
    GuidedStage.SOURCE_METHOD: {
        "en": (
            "Choose how evidence will be collected: pasted text, bounded web discovery, "
            "both, or manual entry. Tell me your preferred method; AI may propose a method "
            "and search queries, but you must apply the choice and review every source."
        ),
        "zh-CN": (
            "本阶段用于选择证据收集方式：粘贴原文、受限联网发现、两者结合或手动录入。"
            "请说明偏好的方式；AI 可以提议方式和检索问题，但必须由你应用选择并逐条审核来源。"
        ),
    },
    GuidedStage.SOURCE_REVIEW: {
        "en": (
            "Review the collected source candidates and their time boundaries. Add or open "
            "the linked source workspace; AI may help organize candidates, but search "
            "snippets are not evidence and you must approve or reject each retained source."
        ),
        "zh-CN": (
            "本阶段用于审核候选来源及其时间边界。请新增或打开已链接的来源工作区；AI 可以"
            "协助整理候选，但搜索摘要不是证据，每条保留来源都必须由你批准或拒绝。"
        ),
    },
    GuidedStage.CLAIM_REVIEW: {
        "en": (
            "Review every candidate claim against its approved source. Open the linked Event "
            "Pack and inspect wording and citations; AI may explain or propose edits, but "
            "only your explicit approval, edit, or rejection can decide a claim."
        ),
        "zh-CN": (
            "本阶段用于逐条核对候选主张与已批准来源。请打开已链接的事件包检查措辞和引文；"
            "AI 可以解释或提议修改，但只有你的明确批准、编辑或拒绝才能决定主张状态。"
        ),
    },
    GuidedStage.PACK_METADATA_REVIEW: {
        "en": (
            "Confirm the Event Pack title, summary, instrument, and point-in-time boundary. "
            "Provide any corrections; AI may propose metadata, but you must compare it with "
            "the evidence and explicitly apply or edit the final fields."
        ),
        "zh-CN": (
            "本阶段用于确认事件包标题、摘要、研究对象和时点边界。请指出需要修正的字段；"
            "AI 可以提议元数据，但必须由你对照证据并明确应用或编辑最终字段。"
        ),
    },
    GuidedStage.PACK_FREEZE_REVIEW: {
        "en": (
            "Perform the final evidence-set review before freezing the Event Pack. Inspect "
            "sources, claims, limitations, and timestamps; AI may identify possible gaps, "
            "but only you can confirm the review and freeze the pack."
        ),
        "zh-CN": (
            "本阶段用于在冻结事件包前完成最终证据集审核。请检查来源、主张、局限和时间戳；"
            "AI 可以提示可能的缺口，但只有你能确认审核并冻结事件包。"
        ),
    },
    GuidedStage.SCENARIO_INTERVENTION: {
        "en": (
            "Define exactly one counterfactual intervention while holding other settings "
            "fixed. Tell me which allowed condition should change; AI may propose bounded "
            "values and an explanation, but you must review and explicitly apply them."
        ),
        "zh-CN": (
            "本阶段用于在其他设置不变时定义唯一一个反事实干预。请说明要改变的白名单条件；"
            "AI 可以提议有界数值和解释，但必须由你审核并明确应用。"
        ),
    },
    GuidedStage.SCENARIO_REVIEW: {
        "en": (
            "Review the complete scenario and verify that only the declared intervention "
            "differs. Open or link the scenario; AI may explain fields and assumptions, but "
            "you must save, inspect, and freeze the reviewed configuration."
        ),
        "zh-CN": (
            "本阶段用于审核完整情景，并确认只有声明的干预发生变化。请打开或链接情景；"
            "AI 可以解释字段和假设，但必须由你保存、检查并冻结已审核配置。"
        ),
    },
    GuidedStage.PREFLIGHT: {
        "en": (
            "Run the preflight checks for evidence, configuration, cognition mode, and cost "
            "boundaries. Provide any issue you want explained; AI may clarify warnings, but "
            "you must resolve blockers and explicitly confirm any permitted fallback."
        ),
        "zh-CN": (
            "本阶段用于检查证据、配置、认知模式和费用边界。请指出需要解释的问题；AI 可以"
            "说明警告，但必须由你解决阻塞项并明确确认任何允许的回退。"
        ),
    },
    GuidedStage.READY_TO_SUBMIT: {
        "en": (
            "Review the final frozen configuration before submission. AI may summarize the "
            "saved artifacts and remaining limitations, but it cannot start a run; only your "
            "explicit submission can create and start the experiment."
        ),
        "zh-CN": (
            "本阶段用于提交前复核最终冻结配置。AI 可以总结已保存工件和剩余局限，但不能"
            "启动运行；只有你的明确提交才能创建并启动实验。"
        ),
    },
    GuidedStage.COMPLETED: {
        "en": (
            "The guided setup is complete. This message does not claim that an experiment "
            "has run or been validated; AI may help explain saved artifacts, while you "
            "remain responsible for starting, monitoring, and interpreting any run."
        ),
        "zh-CN": (
            "引导配置已经完成。本消息不表示实验已经运行或通过验证；AI 可以协助解释已保存"
            "工件，但任何运行仍须由你启动、监控并负责解读。"
        ),
    },
}


def guidedStageOpening(stage: GuidedStage, language: GuidedLanguage) -> str:
    """返回固定文案，不触发模型调用。"""

    return _STAGE_OPENINGS[stage][language]


def guidedStageOpeningMessageId(workflowId: str, stage: GuidedStage) -> str:
    """同一工作流的同一阶段只允许一个确定性开场消息。"""

    normalizedStage = stage.value.lower().replace("_", "-")
    return f"msg-{workflowId}-stage-{normalizedStage}-opening"
