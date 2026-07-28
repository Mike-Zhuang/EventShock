import type { Language } from './i18n';

export type PageGuideId =
  | 'cases'
  | 'pack'
  | 'ai'
  | 'scenario'
  | 'preflight'
  | 'runs'
  | 'results'
  | 'study'
  | 'trace'
  | 'governance'
  | 'export'
  | 'admin';

export interface PageGuideContent {
  label: string;
  optional: boolean;
  steps: readonly [string, string, string];
}

interface BilingualPageGuide {
  optional?: boolean;
  en: readonly [string, string, string];
  zh: readonly [string, string, string];
}

const PAGE_GUIDES: Record<PageGuideId, BilingualPageGuide> = {
  cases: {
    en: ['Choose a case.', 'Open its Event Pack and check sources and claims.', 'Freeze reviewed evidence, then build a scenario.'],
    zh: ['选择一个案例。', '打开事件包，核对来源与候选主张。', '冻结已审核证据，再构建情景。'],
  },
  pack: {
    en: ['Check every claim against its sources.', 'Approve, edit, or reject every pending claim.', 'Freeze the reviewed evidence and continue to Scenario Builder.'],
    zh: ['对照来源检查每条主张。', '批准、修改或拒绝所有待审核项。', '冻结已审核证据，再进入情景构建器。'],
  },
  ai: {
    optional: true,
    en: ['Enter a key for this sign-in and choose a model.', 'Save it temporarily and test structured output.', 'Return to Scenario Builder and select Hybrid LLM.'],
    zh: ['填写本次登录使用的 Key，并选择模型。', '临时保存并测试结构化输出。', '回到情景构建器，选择混合 LLM。'],
  },
  scenario: {
    en: ['Review the event, market, agents, and network in steps 01–05.', 'Change exactly one intervention in step 06.', 'Choose matched seeds in step 07, then select Validate Scenario.'],
    zh: ['按 01–05 检查事件、市场、Agent 与网络。', '在 06 中只设置一个干预变量。', '在 07 中选择配对随机种子，再点击“验证情景”。'],
  },
  preflight: {
    en: ['Resolve every failed check.', 'Review the plan, cost cap, and limitations.', 'Complete all three confirmations and start the experiment.'],
    zh: ['处理所有未通过的检查。', '核对实验计划、费用上限与局限。', '勾选三项确认，再创建并启动实验。'],
  },
  runs: {
    en: ['Select a run on the left.', 'Wait for valid seeds to finish; playback controls affect only the displayed log.', 'Open Results when the run completes.'],
    zh: ['在左侧选择一个实验。', '等待有效随机种子完成；播放控件只影响日志显示。', '实验完成后打开“实验结果”。'],
  },
  results: {
    en: ['Read the primary metric, interval, and paired difference first.', 'Then inspect distributions and median paths.', 'Use Trace Explorer for mechanisms or Export & History to preserve evidence.'],
    zh: ['先读主要指标、区间与配对差异。', '再查看分布和中位路径。', '到链路追踪解释机制，或到导出与历史保存证据。'],
  },
  study: {
    en: ['Choose a preset and frozen evidence.', 'Preregister outcomes and design factors.', 'Preview resources, confirm boundaries, and run the study.'],
    zh: ['选择预设和已冻结证据。', '预注册结果指标与设计因素。', '预览资源、确认边界并运行研究。'],
  },
  trace: {
    en: ['Load traces from a completed result.', 'Filter and select a trace node.', 'Follow evidence to belief, order, and fill while retaining the method warning.'],
    zh: ['从已完成结果加载追踪。', '筛选并选择一个链路节点。', '沿证据、信念、订单和成交解释机制，并保留方法警告。'],
  },
  governance: {
    en: ['Read the release gate and highest permitted claim.', 'Inspect validation evidence and versions.', 'Retain pending states and limitations when reporting.'],
    zh: ['先看发布门禁与最高允许主张。', '核对验证证据与版本。', '报告时保留未执行状态与局限。'],
  },
  export: {
    optional: true,
    en: ['Select a completed experiment.', 'Open it for review or download its ZIP.', 'Follow replay instructions and retain license and privacy boundaries.'],
    zh: ['选择一个已完成实验。', '打开复核或下载 ZIP。', '按重放说明验证，并遵守许可与隐私边界。'],
  },
  admin: {
    en: ['Review account totals.', 'Select an email to filter activity.', 'Inspect minimized activity and experiment counts; credentials and source text are excluded.'],
    zh: ['查看账户总览。', '点击邮箱筛选用户活动。', '查看最小化活动与实验数量；本页不显示凭据或来源正文。'],
  },
};

export function getPageGuide(id: PageGuideId, language: Language): PageGuideContent {
  const guide = PAGE_GUIDES[id];
  return {
    label: language === 'zh-CN' ? '本页怎么做' : 'How to use this page',
    optional: Boolean(guide.optional),
    steps: language === 'zh-CN' ? guide.zh : guide.en,
  };
}
