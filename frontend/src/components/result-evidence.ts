import type { RouteTargetId, ViewId } from '../app';
import type {
  ResultInterpretationLanguage,
  ResultInterpretationToolActivity,
} from '../api/types';
import type { Root, RootContent } from 'mdast';
import remarkGfm from 'remark-gfm';
import remarkParse from 'remark-parse';
import { unified } from 'unified';

/**
 * 后端允许的引用语法。导出 source 而不是带 g 标志的 RegExp，避免多个渲染器共享
 * lastIndex 后产生偶发漏匹配。调用方如需遍历，应通过工厂创建自己的 RegExp。
 */
export const RESULT_EVIDENCE_REFERENCE_SOURCE =
  String.raw`\[(result:[A-Za-z0-9][A-Za-z0-9._:-]{0,72})\]`;

export const RESULT_EVIDENCE_REFERENCE_PATTERN = new RegExp(
  `^${RESULT_EVIDENCE_REFERENCE_SOURCE}$`,
);

export const RESULT_EVIDENCE_IDS = [
  'result:overview',
  'result:metric-summary',
  'result:paired-deltas',
  'result:path-series',
  'result:trace',
  'result:agent-outcomes',
  'result:cognition-summary',
  'result:cognition-decisions',
  'result:analysis-diagnostics',
  'result:limitations',
  'result:manifest',
] as const;

export type ResultEvidenceId = typeof RESULT_EVIDENCE_IDS[number];

export type ResultEvidenceTool =
  | 'OVERVIEW'
  | 'METRIC_SUMMARY'
  | 'PAIRED_DELTAS'
  | 'PATH_SERIES'
  | 'TRACE'
  | 'AGENT_OUTCOMES'
  | 'COGNITION_SUMMARY'
  | 'COGNITION_DECISIONS'
  | 'ANALYSIS_DIAGNOSTICS'
  | 'LIMITATIONS'
  | 'MANIFEST';

type ResultEvidenceView = Extract<ViewId, 'results' | 'trace'>;

interface ResultEvidenceLocalizedText {
  en: string;
  'zh-CN': string;
}

export interface ResultEvidenceDefinition {
  evidenceId: ResultEvidenceId;
  tool: ResultEvidenceTool;
  label: ResultEvidenceLocalizedText;
  description: ResultEvidenceLocalizedText;
  view: ResultEvidenceView;
  target: RouteTargetId;
}

export const RESULT_EVIDENCE_DEFINITIONS = [
  {
    evidenceId: 'result:overview',
    tool: 'OVERVIEW',
    label: { en: 'Experiment overview', 'zh-CN': '实验概览' },
    description: {
      en: 'Research question, intervention, valid paired seeds, and stopping rule for this experiment.',
      'zh-CN': '本次实验的研究问题、单一干预、有效配对随机种子和停止规则。',
    },
    view: 'results',
    target: 'result-overview-heading',
  },
  {
    evidenceId: 'result:metric-summary',
    tool: 'METRIC_SUMMARY',
    label: { en: 'Primary metrics', 'zh-CN': '主要指标' },
    description: {
      en: 'Registered metrics, effect estimates, intervals, and sample counts calculated by the backend.',
      'zh-CN': '后端计算的预注册指标、效应估计、区间和样本数量。',
    },
    view: 'results',
    target: 'metrics-heading',
  },
  {
    evidenceId: 'result:paired-deltas',
    tool: 'PAIRED_DELTAS',
    label: { en: 'Paired-seed differences', 'zh-CN': '配对随机种子差异' },
    description: {
      en: 'Baseline-versus-intervention differences computed from matched random seeds.',
      'zh-CN': '使用相同随机种子计算的基准情景与干预情景差异。',
    },
    view: 'results',
    target: 'paired-heading',
  },
  {
    evidenceId: 'result:path-series',
    tool: 'PATH_SERIES',
    label: { en: 'Market paths', 'zh-CN': '市场路径' },
    description: {
      en: 'Sampled price, liquidity, volume, and sentiment paths used for mechanism inspection.',
      'zh-CN': '用于检查机制的价格、流动性、成交量和情绪抽样路径。',
    },
    view: 'results',
    target: 'paths-heading',
  },
  {
    evidenceId: 'result:trace',
    tool: 'TRACE',
    label: { en: 'Mechanism trace', 'zh-CN': '机制链路' },
    description: {
      en: 'Event-to-belief-to-order-to-trade trace for diagnosing a sampled path.',
      'zh-CN': '用于诊断抽样路径的事件—信念—订单—成交链路。',
    },
    view: 'trace',
    target: 'trace-timeline-heading',
  },
  {
    evidenceId: 'result:agent-outcomes',
    tool: 'AGENT_OUTCOMES',
    label: { en: 'Agent outcomes', 'zh-CN': 'Agent 结果' },
    description: {
      en: 'Aggregated agent flows, positions, and economic outcomes from the simulation.',
      'zh-CN': '仿真产生的智能体资金流、持仓和经济结果汇总。',
    },
    view: 'results',
    target: 'agent-flow-heading',
  },
  {
    evidenceId: 'result:cognition-summary',
    tool: 'COGNITION_SUMMARY',
    label: { en: 'Cognition summary', 'zh-CN': '认知层汇总' },
    description: {
      en: 'Bounded cognition mode, usage, repair, and deterministic fallback summary.',
      'zh-CN': '受限认知模式、调用量、修复和确定性回退情况汇总。',
    },
    view: 'results',
    target: 'cognition-heading',
  },
  {
    evidenceId: 'result:cognition-decisions',
    tool: 'COGNITION_DECISIONS',
    label: { en: 'Cognition decisions', 'zh-CN': '认知决策' },
    description: {
      en: 'Evidence-bound belief and action-preference decisions used by simulated agents.',
      'zh-CN': '模拟智能体采用的证据约束信念和行动偏好决策。',
    },
    view: 'results',
    target: 'cognition-decisions-heading',
  },
  {
    evidenceId: 'result:analysis-diagnostics',
    tool: 'ANALYSIS_DIAGNOSTICS',
    label: { en: 'Analysis diagnostics', 'zh-CN': '分析诊断' },
    description: {
      en: 'Preregistered controls, sensitivity checks, and multiple-comparison diagnostics.',
      'zh-CN': '预注册对照、敏感性检查和多重比较诊断。',
    },
    view: 'results',
    target: 'analysis-diagnostics-heading',
  },
  {
    evidenceId: 'result:limitations',
    tool: 'LIMITATIONS',
    label: { en: 'Limitations', 'zh-CN': '局限性' },
    description: {
      en: 'Model, data, and interpretation boundaries that constrain the result.',
      'zh-CN': '限制结果适用范围的模型、数据和解释边界。',
    },
    view: 'results',
    target: 'result-limitations-heading',
  },
  {
    evidenceId: 'result:manifest',
    tool: 'MANIFEST',
    label: { en: 'Versions and provenance', 'zh-CN': '版本与来源' },
    description: {
      en: 'Experiment identifiers, generation time, model versions, and data versions.',
      'zh-CN': '实验标识、生成时间、模型版本和数据版本。',
    },
    view: 'results',
    target: 'result-manifest-heading',
  },
] as const satisfies readonly ResultEvidenceDefinition[];

const RESULT_EVIDENCE_DEFINITION_BY_ID = new Map<string, ResultEvidenceDefinition>(
  RESULT_EVIDENCE_DEFINITIONS.map((definition) => [definition.evidenceId, definition]),
);

export interface LocalizedResultEvidence {
  evidenceId: string;
  known: boolean;
  label: string;
  description: string;
  tool?: ResultEvidenceTool;
  view?: ResultEvidenceView;
  target?: RouteTargetId;
}

export interface ResultEvidenceNumbering {
  evidenceIds: readonly string[];
  numberByEvidenceId: ReadonlyMap<string, number>;
}

export interface ResultEvidenceTextSegment {
  kind: 'text' | 'citation';
  value: string;
  evidenceId?: string;
  number?: number;
}

export type ResultEvidenceIntegrityIssue = 'missing' | 'unknown' | 'mismatch';

export interface ResultEvidenceCitationAudit {
  evidenceId: string;
  number?: number;
  known: boolean;
  inline: boolean;
  groundingListed: boolean;
  toolActivityPresent: boolean;
  toolMatchesDefinition: boolean;
  itemCount: number;
  truncated: boolean;
  issues: readonly ResultEvidenceIntegrityIssue[];
}

export interface ResultEvidenceAudit {
  numbering: ResultEvidenceNumbering;
  citations: readonly ResultEvidenceCitationAudit[];
  issues: readonly ResultEvidenceIntegrityIssue[];
  missingFromGrounding: readonly string[];
  missingFromText: readonly string[];
  missingToolActivity: readonly string[];
  unreferencedToolActivity: readonly string[];
  unknownEvidenceIds: readonly string[];
  mismatchedToolEvidenceIds: readonly string[];
}

function uniqueInOrder<T extends string>(values: Iterable<T>): T[] {
  return [...new Set(values)];
}

function createGlobalReferencePattern(): RegExp {
  return new RegExp(RESULT_EVIDENCE_REFERENCE_SOURCE, 'g');
}

const RESULT_EVIDENCE_MARKDOWN_PARSER = unified()
  .use(remarkParse)
  .use(remarkGfm);

function collectMarkdownEvidenceReferences(markdown: string): string[] {
  const references: string[] = [];
  const tree = RESULT_EVIDENCE_MARKDOWN_PARSER.parse(markdown) as Root;

  const visit = (node: Root | RootContent, insideLink = false): void => {
    if (node.type === 'text') {
      if (!insideLink) references.push(...extractResultEvidenceReferences(node.value));
      return;
    }
    if (!('children' in node) || !Array.isArray(node.children)) return;
    const childInsideLink = insideLink || node.type === 'link' || node.type === 'linkReference';
    for (const child of node.children) visit(child, childInsideLink);
  };

  visit(tree);
  return references;
}

export function isResultEvidenceId(value: string): value is ResultEvidenceId {
  return RESULT_EVIDENCE_DEFINITION_BY_ID.has(value);
}

export function getResultEvidenceDefinition(
  evidenceId: string,
): ResultEvidenceDefinition | undefined {
  return RESULT_EVIDENCE_DEFINITION_BY_ID.get(evidenceId);
}

export function getLocalizedResultEvidence(
  evidenceId: string,
  language: ResultInterpretationLanguage,
): LocalizedResultEvidence {
  const definition = getResultEvidenceDefinition(evidenceId);
  if (!definition) {
    return {
      evidenceId,
      known: false,
      label: language === 'zh-CN' ? '旧版证据引用' : 'Legacy evidence reference',
      description: language === 'zh-CN'
        ? '此历史引用不在当前证据白名单中，已保留以供审计，但无法定位到结果区段。'
        : 'This historical reference is not in the current evidence allowlist. It is retained for audit but cannot be located in the results.',
    };
  }
  return {
    evidenceId,
    known: true,
    label: definition.label[language],
    description: definition.description[language],
    tool: definition.tool,
    view: definition.view,
    target: definition.target,
  };
}

export function extractResultEvidenceReferences(text: string): string[] {
  const references: string[] = [];
  for (const match of text.matchAll(createGlobalReferencePattern())) {
    references.push(match[1]);
  }
  return references;
}

export function buildResultEvidenceNumbering(
  answer: string,
  analysisSummary?: string,
): ResultEvidenceNumbering {
  const evidenceIds = uniqueInOrder([
    ...collectMarkdownEvidenceReferences(answer),
    ...collectMarkdownEvidenceReferences(analysisSummary ?? ''),
  ]);
  return {
    evidenceIds,
    numberByEvidenceId: new Map(
      evidenceIds.map((evidenceId, index) => [evidenceId, index + 1]),
    ),
  };
}

/**
 * 将任意 Markdown 文本节点拆成安全片段。SafeMarkdown 应把 citation 片段渲染为按钮；
 * code/inlineCode 等不可交互节点也可复用本函数的 value（例如“[2]”），确保内部 ID
 * 不会泄漏到普通界面。
 */
export function splitResultEvidenceText(
  text: string,
  numbering: ResultEvidenceNumbering,
): ResultEvidenceTextSegment[] {
  const segments: ResultEvidenceTextSegment[] = [];
  let cursor = 0;
  for (const match of text.matchAll(createGlobalReferencePattern())) {
    const start = match.index;
    if (start > cursor) {
      segments.push({ kind: 'text', value: text.slice(cursor, start) });
    }
    const evidenceId = match[1];
    const number = numbering.numberByEvidenceId.get(evidenceId);
    segments.push({
      kind: 'citation',
      value: `[${number ?? '?'}]`,
      evidenceId,
      number,
    });
    cursor = start + match[0].length;
  }
  if (cursor < text.length) {
    segments.push({ kind: 'text', value: text.slice(cursor) });
  }
  return segments.length > 0 ? segments : [{ kind: 'text', value: text }];
}

export function replaceResultEvidenceReferencesWithMarkers(
  text: string,
  numbering: ResultEvidenceNumbering,
): string {
  return splitResultEvidenceText(text, numbering).map((segment) => segment.value).join('');
}

/**
 * 历史模型回答可能在普通文本建议中留下内部证据 ID。建议按钮不是证据引用入口，
 * 因此这里将标识替换成当前界面的可读名称，既保留语义，也不把内部协议暴露给用户。
 */
export function sanitizeResultEvidencePlainText(
  text: string,
  language: ResultInterpretationLanguage,
): string {
  return text.replace(createGlobalReferencePattern(), (_match, evidenceId: string) => (
    getLocalizedResultEvidence(evidenceId, language).label
  ));
}

export function auditResultEvidence(
  answer: string,
  analysisSummary: string | undefined,
  groundingReferences: readonly string[],
  toolActivity: readonly ResultInterpretationToolActivity[],
): ResultEvidenceAudit {
  const numbering = buildResultEvidenceNumbering(answer, analysisSummary);
  const inlineEvidenceIds = numbering.evidenceIds;
  const groundingEvidenceIds = uniqueInOrder(groundingReferences);
  const activityEvidenceIds = uniqueInOrder(toolActivity.map((activity) => activity.evidenceId));
  const inlineSet = new Set(inlineEvidenceIds);
  const groundingSet = new Set(groundingEvidenceIds);
  const activitySet = new Set(activityEvidenceIds);

  const missingFromGrounding = inlineEvidenceIds.filter((evidenceId) => !groundingSet.has(evidenceId));
  const missingFromText = groundingEvidenceIds.filter((evidenceId) => !inlineSet.has(evidenceId));
  const referencedEvidenceIds = uniqueInOrder([...inlineEvidenceIds, ...groundingEvidenceIds]);
  const missingToolActivity = referencedEvidenceIds.filter((evidenceId) => !activitySet.has(evidenceId));
  const unreferencedToolActivity = activityEvidenceIds.filter(
    (evidenceId) => !inlineSet.has(evidenceId) && !groundingSet.has(evidenceId),
  );
  const allEvidenceIds = uniqueInOrder([...referencedEvidenceIds, ...activityEvidenceIds]);
  // 额外工具读取属于正常的上下文准备，只在技术详情中披露。只有回答或
  // grounding 真正引用的证据才参与面向用户的完整性告警。
  const unknownEvidenceIds = referencedEvidenceIds.filter(
    (evidenceId) => !isResultEvidenceId(evidenceId),
  );
  const mismatchedToolEvidenceIds = uniqueInOrder(
    toolActivity.flatMap((activity) => {
      if (!inlineSet.has(activity.evidenceId) && !groundingSet.has(activity.evidenceId)) {
        return [];
      }
      const definition = getResultEvidenceDefinition(activity.evidenceId);
      return definition && definition.tool !== activity.tool ? [activity.evidenceId] : [];
    }),
  );

  const citations = allEvidenceIds.map<ResultEvidenceCitationAudit>((evidenceId) => {
    const activities = toolActivity.filter((activity) => activity.evidenceId === evidenceId);
    const known = isResultEvidenceId(evidenceId);
    const inline = inlineSet.has(evidenceId);
    const groundingListed = groundingSet.has(evidenceId);
    const referenced = inline || groundingListed;
    const toolActivityPresent = activities.length > 0;
    // 旧版未知引用没有可比较的当前工具定义；它属于 unknown，而不是工具错配。
    const toolMatchesDefinition = !known
      || activities.every((activity) => activity.tool === getResultEvidenceDefinition(evidenceId)?.tool);
    const issues: ResultEvidenceIntegrityIssue[] = [];
    if (referenced && !known) issues.push('unknown');
    if (referenced && (!inline || !groundingListed || !toolActivityPresent)) issues.push('missing');
    if (referenced && (inline !== groundingListed || !toolMatchesDefinition)) {
      issues.push('mismatch');
    }
    return {
      evidenceId,
      number: numbering.numberByEvidenceId.get(evidenceId),
      known,
      inline,
      groundingListed,
      toolActivityPresent,
      toolMatchesDefinition,
      itemCount: activities.reduce((total, activity) => total + Math.max(0, activity.itemCount), 0),
      truncated: activities.some((activity) => activity.truncated),
      issues: uniqueInOrder(issues),
    };
  });

  const issues: ResultEvidenceIntegrityIssue[] = [];
  if (missingFromGrounding.length > 0 || missingFromText.length > 0 || missingToolActivity.length > 0) {
    issues.push('missing');
  }
  if (unknownEvidenceIds.length > 0) issues.push('unknown');
  if (
    missingFromGrounding.length > 0
    || missingFromText.length > 0
    || mismatchedToolEvidenceIds.length > 0
  ) {
    issues.push('mismatch');
  }

  return {
    numbering,
    citations,
    issues,
    missingFromGrounding,
    missingFromText,
    missingToolActivity,
    unreferencedToolActivity,
    unknownEvidenceIds,
    mismatchedToolEvidenceIds,
  };
}
