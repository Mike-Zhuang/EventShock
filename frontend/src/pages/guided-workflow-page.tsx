import {
  Button,
  InlineNotification,
  Tag,
  TextArea,
} from '@carbon/react';
import {
  ArrowClockwise,
  ArrowRight,
  Archive,
  CheckCircle,
  ClipboardText,
  Factory,
  PaperPlaneTilt,
  Plus,
  Robot,
  Warning,
  User,
} from '@phosphor-icons/react';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import type { Navigate } from '../app';
import { api, ApiError } from '../api/client';
import type {
  GuidedStage,
  GuidedTurnOperation,
  GuidedTurnRecoveryAction,
  GuidedWorkflow,
  GuidedWorkflowProposal,
} from '../api/types';
import { EmptyState, ErrorPanel, LoadingPanel, PageHeader, StatusBadge } from '../components/common';
import { SafeMarkdown } from '../components/safe-markdown';
import {
  readGuidedReturnContext,
  writeFactoryGuidedHandoff,
  writeGuidedReturnContext,
  writeScenarioGuidedHandoff,
} from '../guided-handoff';
import { useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { safeDate } from '../utils/format';
import { SyntheticInstrumentLabel } from '../components/synthetic-instrument-label';
import { TechnicalCodeDisplay, technicalCodeLabel } from '../components/technical-code';

const STAGES: GuidedStage[] = [
  'EVENT_GOAL',
  'SOURCE_METHOD',
  'SOURCE_REVIEW',
  'CLAIM_REVIEW',
  'PACK_METADATA_REVIEW',
  'PACK_FREEZE_REVIEW',
  'SCENARIO_INTERVENTION',
  'SCENARIO_REVIEW',
  'PREFLIGHT',
  'READY_TO_SUBMIT',
  'COMPLETED',
];

const STAGE_LABELS: Record<GuidedStage, { en: string; zh: string }> = {
  EVENT_GOAL: { en: 'Event goal', zh: '事件目标' },
  SOURCE_METHOD: { en: 'Source method', zh: '来源方式' },
  SOURCE_REVIEW: { en: 'Source review', zh: '来源审核' },
  CLAIM_REVIEW: { en: 'Claim review', zh: '主张审核' },
  PACK_METADATA_REVIEW: { en: 'Pack metadata', zh: '事件包元数据' },
  PACK_FREEZE_REVIEW: { en: 'Freeze review', zh: '冻结前审核' },
  SCENARIO_INTERVENTION: { en: 'One intervention', zh: '单一干预' },
  SCENARIO_REVIEW: { en: 'Scenario review', zh: '情景审核' },
  PREFLIGHT: { en: 'Preflight', zh: '运行前检查' },
  READY_TO_SUBMIT: { en: 'Ready to submit', zh: '准备提交' },
  COMPLETED: { en: 'Completed', zh: '已完成' },
};

const EVENT_GOAL_FIELD_LABELS = {
  title: { en: 'Event title', zh: '事件标题' },
  summary: { en: 'Short summary', zh: '事件摘要' },
  instrument: { en: 'Instrument', zh: '证券代码' },
  asOf: { en: 'As-of date', zh: '时点日期' },
  researchQuestion: { en: 'Research question', zh: '研究问题' },
} as const;

type EventGoalField = keyof typeof EVENT_GOAL_FIELD_LABELS;
type EventGoalBatchDraft = Record<EventGoalField, string>;

const EMPTY_EVENT_GOAL_BATCH: EventGoalBatchDraft = {
  title: '',
  summary: '',
  instrument: '',
  asOf: '',
  researchQuestion: '',
};

const RESPONSIBILITY_FLOW = [
  {
    key: 'goal',
    owner: 'AI',
    title: { en: 'Frame the event and one intervention', zh: '梳理事件目标与单一干预' },
    detail: {
      en: 'AI proposes bounded metadata, source methods, search queries, and intervention fields. You review before applying.',
      zh: 'AI 提出受限的事件元数据、来源方式、检索词和干预字段；你核对后才应用。',
    },
  },
  {
    key: 'source',
    owner: 'HUMAN',
    title: { en: 'Authorize and review source evidence', zh: '授权并审核来源证据' },
    detail: {
      en: 'This opens the dedicated workspace because lawful use, full-text fidelity, and source authorization require a human decision.',
      zh: '这里必须跳到专业页，因为合法使用、全文忠实度和证据授权必须由人判断。',
    },
  },
  {
    key: 'claim',
    owner: 'HUMAN',
    title: { en: 'Decide every retained claim', zh: '逐项决定保留的主张' },
    detail: {
      en: 'Approve, edit, or reject each claim. AI cannot replace the accountable evidence judgment.',
      zh: '逐项批准、编辑或拒绝主张；AI 不能替代需要承担责任的证据判断。',
    },
  },
  {
    key: 'freeze',
    owner: 'HUMAN',
    title: { en: 'Freeze reproducible inputs', zh: '冻结可复现输入' },
    detail: {
      en: 'Freezing the Event Pack and scenario locks the exact inputs used for reproducibility, so it remains an explicit human action.',
      zh: '冻结 Event Pack 和情景会锁定复现实验所需的精确输入，因此始终是明确的人类操作。',
    },
  },
  {
    key: 'preflight',
    owner: 'HUMAN',
    title: { en: 'Review preflight and start', zh: '核对运行前检查并启动' },
    detail: {
      en: 'Starting may create provider fees and carries interpretation responsibility. Review the cost boundary and limitations before submission.',
      zh: '启动可能产生供应商费用，也伴随解释责任；提交前必须核对费用边界和局限。',
    },
  },
  {
    key: 'continue',
    owner: 'SYSTEM',
    title: { en: 'Return and continue from verified state', zh: '返回并从已核验状态继续' },
    detail: {
      en: 'On return, the guide reloads the linked server artifacts and resumes the next stage without asking you to describe completed work again.',
      zh: '返回后，引导会重读服务器上的真实关联对象并继续下一阶段，不要求你重复描述已完成工作。',
    },
  },
] as const;

function stageLabel(stage: GuidedStage, isZh: boolean): string {
  return isZh ? STAGE_LABELS[stage].zh : STAGE_LABELS[stage].en;
}

interface GuidedAdvanceBlocker {
  message: string;
  targetId: string;
}

interface LocalGuidedTurn {
  id: string;
  content: string;
  createdAt: string;
  startedAtMs: number;
  stage: GuidedStage;
  status: 'sending' | 'failed' | 'delivered';
}

interface GuidedRecoveryIntent {
  operation: GuidedTurnOperation;
  action: GuidedTurnRecoveryAction;
}

function guidedOperationStatus(
  status: GuidedTurnOperation['status'],
  isZh: boolean,
): string {
  const labels: Record<GuidedTurnOperation['status'], { en: string; zh: string }> = {
    PENDING: { en: 'Request in progress', zh: '请求处理中' },
    RESULT_READY: { en: 'Validated result cached', zh: '已缓存校验结果' },
    SUCCEEDED: { en: 'Committed', zh: '已完成提交' },
    UNKNOWN: { en: 'Outcome requires a decision', zh: '结果未知，需人工决定' },
    ABANDONED_BY_USER: { en: 'Abandoned by user', zh: '已由用户放弃' },
  };
  return isZh ? labels[status].zh : labels[status].en;
}

function localTurnProgress(
  elapsedSeconds: number,
  isZh: boolean,
  operation?: GuidedTurnOperation,
): string {
  const stage = operation?.failureStage;
  if (stage === 'BEFORE_PROVIDER_DISPATCH') {
    return isZh
      ? '正在执行安全检查并准备受约束上下文'
      : 'Running safety checks and preparing bounded context';
  }
  if (stage === 'PROVIDER_DISPATCHED') {
    return isZh ? '模型请求已发出，正在等待供应商响应' : 'Model request sent; waiting for the provider';
  }
  if (stage === 'PROVIDER_RESPONSE_VALIDATED') {
    return isZh ? '模型已返回，正在校验并保存候选' : 'Model returned; validating and saving the candidate';
  }
  if (stage === 'DETERMINISTIC_PROPOSAL_READY') {
    return isZh ? '规则候选已生成，正在保存' : 'Rule-based candidate generated; saving it';
  }
  if (stage === 'DATABASE_COMMIT_PENDING') {
    return isZh ? '候选已通过校验，正在提交数据库' : 'Candidate validated; committing it to the database';
  }
  if (stage === 'PROVIDER_RESPONSE_FAILED') {
    return isZh
      ? '供应商响应未能通过，正在记录可恢复状态'
      : 'Provider response failed; recording a recoverable state';
  }
  if (elapsedSeconds < 2) {
    return isZh ? '请求已安全发送' : 'Request sent safely';
  }
  if (elapsedSeconds < 8) {
    return isZh ? '正在理解当前阶段与修改要求' : 'Reading the current stage and requested changes';
  }
  if (elapsedSeconds < 20) {
    return isZh ? '正在等待服务器校验结构化候选' : 'Waiting for the server to validate a structured candidate';
  }
  return isZh
    ? '服务器仍在处理；请保留本页，系统不会重复发送'
    : 'The server is still processing. Keep this page open; the request will not be resent';
}

function focusGuidedTarget(targetId: string): void {
  window.requestAnimationFrame(() => {
    const target = document.getElementById(targetId);
    if (!(target instanceof HTMLElement)) return;
    const reduceMotion = typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (typeof target.scrollIntoView === 'function') {
      target.scrollIntoView({
        behavior: reduceMotion ? 'auto' : 'smooth',
        block: 'center',
      });
    }
    target.focus({ preventScroll: true });
  });
}

function guidedAdvanceBlocker(
  workflow: GuidedWorkflow,
  isZh: boolean,
): GuidedAdvanceBlocker | undefined {
  if (workflow.pendingProposal) {
    return {
      targetId: 'guided-proposal-heading',
      message: isZh
        ? '请先核对并应用当前候选；如果候选不正确，请在对话框中要求修改。'
        : 'Review and apply the current candidate first, or ask for a correction in the conversation.',
    };
  }
  const draft = workflow.draft;
  if (workflow.stage === 'EVENT_GOAL' && !draft.eventMetadata) {
    return {
      targetId: 'guided-message',
      message: isZh
        ? '请先描述事件并应用一份完整的事件元数据候选。'
        : 'Describe the event and apply a complete event-metadata candidate first.',
    };
  }
  if (workflow.stage === 'SOURCE_METHOD' && !draft.sourceMethod) {
    return {
      targetId: 'guided-message',
      message: isZh
        ? '请先选择并应用来源方式。'
        : 'Choose and apply a source method first.',
    };
  }
  if (
    ['SOURCE_REVIEW', 'CLAIM_REVIEW', 'PACK_METADATA_REVIEW', 'PACK_FREEZE_REVIEW']
      .includes(workflow.stage)
    && !draft.eventPackId
  ) {
    return {
      targetId: 'guided-review-link-heading',
      message: isZh
        ? '请先在专业页面完成全文证据审核并生成真实 Event Pack；仅关联构建任务还不能进入下一阶段。'
        : 'Complete full-text evidence review and generate a real Event Pack in the dedicated workspace. Linking only a build is not enough.',
    };
  }
  if (workflow.stage === 'SCENARIO_INTERVENTION' && !draft.intervention) {
    return {
      targetId: 'guided-message',
      message: isZh
        ? '请先核对并应用一个单一干预候选。'
        : 'Review and apply one intervention candidate first.',
    };
  }
  if (
    ['SCENARIO_INTERVENTION', 'SCENARIO_REVIEW', 'PREFLIGHT', 'READY_TO_SUBMIT']
      .includes(workflow.stage)
    && !draft.scenarioId
  ) {
    return {
      targetId: 'guided-stage-workspace-action',
      message: isZh
        ? '请先在情景构建器中保存并关联当前工作流的情景。'
        : 'Save and link this workflow scenario in Scenario Builder first.',
    };
  }
  return undefined;
}

function guidedAdvanceErrorMessage(error: unknown, isZh: boolean): string {
  const message = error instanceof Error ? error.message : String(error);
  if (!isZh || !(error instanceof ApiError)) return message;
  if (message.includes('link the reviewed Event Pack')) {
    return '请先完成全文证据审核、生成 Event Pack，并将服务器返回的真实 Event Pack 关联到本引导。';
  }
  if (message.includes('explicit human review decision')) {
    return '仍有候选主张没有得到明确的人工批准、编辑或拒绝，请返回事件包审核。';
  }
  if (message.includes('must be frozen')) {
    return '关联对象尚未冻结，请在对应专业页面完成冻结后再继续。';
  }
  if (message.includes('scenario')) {
    return '情景尚未保存、关联或冻结，请返回情景构建器完成标红步骤。';
  }
  if (error.code === 'GUIDED_WORKFLOW_CONFLICT') {
    return '该引导已在其他操作中更新。请刷新服务器状态后重新核对当前阶段。';
  }
  return message;
}

function guidedAdvanceErrorTarget(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  if (
    message.includes('link the reviewed Event Pack')
    || message.includes('explicit human review decision')
    || message.includes('must be frozen')
  ) {
    return 'guided-review-link-heading';
  }
  if (message.toLowerCase().includes('scenario')) {
    return 'guided-stage-workspace-action';
  }
  return 'guided-advance-heading';
}

function guidedTurnErrorMessage(error: unknown, isZh: boolean): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : String(error);
  }
  if (error.code === 'LLM_CREDENTIAL_EXPIRED') {
    return isZh
      ? '临时 API Key 已过期。你的消息已恢复到输入框；请重新配置并测试 Key 后再次发送。'
      : 'The temporary API key expired. Your message was restored to the composer; configure and test the key, then send it again.';
  }
  if (error.code === 'LLM_CREDENTIAL_NOT_CONFIGURED') {
    return isZh
      ? '当前没有可用的 API Key。你的消息尚未被消费并已恢复；请先完成 AI 配置。'
      : 'No API key is configured. Your message was not consumed and has been restored; complete AI configuration first.';
  }
  return error.message;
}

function guidedBlockedReasonLabel(reason: string, isZh: boolean): string {
  if (reason === 'FUTURE_EVENT_REQUIRES_HUMAN_CONFIRMATION') {
    return isZh
      ? '这是计划中的未来事件情景。应用前请人工确认日期与时点边界；该提醒不会阻止继续。'
      : 'This is a planned future-event scenario. Confirm the date and point-in-time boundary before applying; this warning does not block progress.';
  }
  if (reason === 'LLM_CREDENTIAL_NOT_CONFIGURED') {
    return isZh ? '需要先配置并测试 API Key。' : 'Configure and test an API key first.';
  }
  return reason.replaceAll('_', ' ').toLocaleLowerCase();
}

function ProposalDetails({
  proposal,
  isZh,
}: {
  proposal: GuidedWorkflowProposal;
  isZh: boolean;
}) {
  const metadata = proposal.proposedEventMetadata;
  const intervention = proposal.proposedIntervention;
  const fieldLabel = (field: string) => ({
    title: isZh ? '事件标题' : 'Event title',
    summary: isZh ? '事件摘要' : 'Event summary',
    instrument: isZh ? '合成证券代码' : 'Synthetic instrument code',
    asOf: isZh ? '时点截止日期' : 'Point-in-time cutoff',
    researchQuestion: isZh ? '研究问题' : 'Research question',
  }[field] ?? (isZh ? '待补字段' : 'Unresolved field'));
  return (
    <div className="guided-proposal__details">
      {metadata ? (
        <dl>
          <div><dt>{isZh ? '标题' : 'Title'}</dt><dd>{isZh ? metadata.titleZh ?? metadata.title : metadata.title}</dd></div>
          <div><dt>{isZh ? '研究问题' : 'Research question'}</dt><dd>{metadata.researchQuestion}</dd></div>
          <div><dt>{isZh ? '证券代码' : 'Instrument'}</dt><dd><SyntheticInstrumentLabel instrument={metadata.instrument} compact /></dd></div>
          <div>
            <dt>{isZh ? '时点边界' : 'Point-in-time cutoff'}</dt>
            <dd>
              {safeDate(metadata.asOf, isZh ? 'zh-CN' : 'en')}
              {metadata.asOfPrecision === 'DAY' ? (
                <small className="guided-proposal__precision">
                  {isZh ? '仅到日期；未虚构具体时分' : 'Day precision; no time was inferred'}
                </small>
              ) : null}
            </dd>
          </div>
          <div className="guided-proposal__wide"><dt>{isZh ? '摘要' : 'Summary'}</dt><dd>{isZh ? metadata.summaryZh ?? metadata.summary : metadata.summary}</dd></div>
        </dl>
      ) : null}
      {proposal.proposedSourceMethod ? (
        <dl>
          <div><dt>{isZh ? '建议来源方式' : 'Proposed source method'}</dt><dd>{proposal.proposedSourceMethod.replaceAll('_', ' ')}</dd></div>
        </dl>
      ) : null}
      {proposal.proposedSearchQueries.length > 0 ? (
        <div>
          <strong>{isZh ? '候选检索式' : 'Candidate search queries'}</strong>
          <ul>{proposal.proposedSearchQueries.map((query) => <li key={query}>{query}</li>)}</ul>
        </div>
      ) : null}
      {intervention ? (
        <dl>
          <div><dt>{isZh ? '干预参数' : 'Intervention'}</dt><dd><code>{intervention.parameter}</code></dd></div>
          <div><dt>{isZh ? '基准值' : 'Baseline'}</dt><dd>{intervention.baselineValue}</dd></div>
          <div><dt>{isZh ? '干预值' : 'Intervention value'}</dt><dd>{intervention.interventionValue}</dd></div>
          <div className="guided-proposal__wide"><dt>{isZh ? '理由' : 'Rationale'}</dt><dd>{intervention.explanation}</dd></div>
        </dl>
      ) : null}
      {proposal.blockedReasons.length > 0 ? (
        <div className="guided-proposal__blocked">
          <strong>{isZh ? '尚未满足' : 'Still required'}</strong>
          <ul>{proposal.blockedReasons.map((reason) => <li key={reason}>{guidedBlockedReasonLabel(reason, isZh)}</li>)}</ul>
        </div>
      ) : null}
      {(proposal.unresolvedFields?.length ?? 0) > 0 ? (
        <div className="guided-proposal__unresolved" role="alert">
          <strong>{isZh ? '需要你补充的信息' : 'Information you still need to provide'}</strong>
          <p>{isZh
            ? '这些内容不会以“未知”或“TBD”等占位词写入正式事件元数据；全部解决后才能应用候选。'
            : 'Placeholder text such as “unknown” or “TBD” will not enter formal event metadata. Resolve every item before applying the proposal.'}</p>
          <ul>
            {proposal.unresolvedFields?.map((item) => (
              <li key={item.field}><strong>{fieldLabel(item.field)}</strong><span>{item.reason}</span></li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function GuidedWorkflowPage({ navigate }: { navigate: Navigate }) {
  const { language } = useI18n();
  const isZh = language === 'zh-CN';
  const { selectCase, setScenario } = useWorkflow();
  const [workflows, setWorkflows] = useState<GuidedWorkflow[]>([]);
  const [workflow, setWorkflow] = useState<GuidedWorkflow>();
  const [message, setMessage] = useState('');
  const [eventGoalBatch, setEventGoalBatch] = useState<EventGoalBatchDraft>(
    EMPTY_EVENT_GOAL_BATCH,
  );
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [busyAction, setBusyAction] = useState<string>();
  const [error, setError] = useState<string>();
  const [credentialActionRequired, setCredentialActionRequired] = useState(false);
  const [advanceError, setAdvanceError] = useState<GuidedAdvanceBlocker>();
  const [localTurn, setLocalTurn] = useState<LocalGuidedTurn>();
  const [turnElapsedSeconds, setTurnElapsedSeconds] = useState(0);
  const [turnOperations, setTurnOperations] = useState<GuidedTurnOperation[]>([]);
  const [operationError, setOperationError] = useState<string>();
  const [recoveryIntent, setRecoveryIntent] = useState<GuidedRecoveryIntent>();
  const [archiveRequested, setArchiveRequested] = useState(false);

  const fillComposerFromEventGoalBatch = () => {
    const labels = EVENT_GOAL_FIELD_LABELS;
    setMessage((isZh
      ? [
          `${labels.title.zh}：${eventGoalBatch.title}`,
          `${labels.summary.zh}：${eventGoalBatch.summary}`,
          `${labels.instrument.zh}：${eventGoalBatch.instrument.toUpperCase()}`,
          `${labels.asOf.zh}：${eventGoalBatch.asOf}`,
          `${labels.researchQuestion.zh}：${eventGoalBatch.researchQuestion}`,
        ]
      : [
          `${labels.title.en}: ${eventGoalBatch.title}`,
          `${labels.summary.en}: ${eventGoalBatch.summary}`,
          `${labels.instrument.en}: ${eventGoalBatch.instrument.toUpperCase()}`,
          `${labels.asOf.en}: ${eventGoalBatch.asOf}`,
          `${labels.researchQuestion.en}: ${eventGoalBatch.researchQuestion}`,
        ]).join('\n'));
  };

  const load = async () => {
    setState('loading');
    setError(undefined);
    try {
      const next = await api.getGuidedWorkflows();
      setWorkflows(next);
      const returnContext = readGuidedReturnContext();
      const selected = next.find((item) => item.id === returnContext?.workflowId) ?? next[0];
      if (selected) setWorkflow(await api.getGuidedWorkflow(selected.id));
      setState('ready');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
      setState('error');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!workflow) {
      setTurnOperations([]);
      return;
    }
    let active = true;
    const loadOperations = async () => {
      try {
        const next = await api.getGuidedTurnOperations(workflow.id);
        if (active) {
          setTurnOperations(next);
          setOperationError(undefined);
        }
      } catch (loadError) {
        if (active) {
          setOperationError(loadError instanceof Error ? loadError.message : String(loadError));
        }
      }
    };
    void loadOperations();
    return () => {
      active = false;
    };
  }, [workflow?.id, workflow?.updatedAt]);

  useEffect(() => {
    if (!localTurn || localTurn.status !== 'sending') {
      setTurnElapsedSeconds(0);
      return undefined;
    }
    const updateElapsed = () => {
      setTurnElapsedSeconds(Math.max(
        0,
        Math.floor((Date.now() - localTurn.startedAtMs) / 1_000),
      ));
    };
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1_000);
    return () => window.clearInterval(timer);
  }, [localTurn]);

  useEffect(() => {
    if (!workflow || !localTurn || localTurn.status !== 'sending') return undefined;
    let active = true;
    const refreshOperation = async () => {
      try {
        const next = await api.getGuidedTurnOperations(workflow.id);
        if (active) {
          setTurnOperations(next);
          setOperationError(undefined);
        }
      } catch (loadError) {
        if (active) {
          setOperationError(loadError instanceof Error ? loadError.message : String(loadError));
        }
      }
    };
    void refreshOperation();
    const timer = window.setInterval(() => void refreshOperation(), 1_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [localTurn?.id, localTurn?.status, workflow?.id]);

  useEffect(() => {
    if (!localTurn || !workflow) return;
    const persisted = workflow.messages.some(
      (item) => item.role === 'user' && item.content === localTurn.content,
    );
    if (persisted) setLocalTurn(undefined);
  }, [localTurn, workflow]);

  const setCurrent = (next: GuidedWorkflow) => {
    setWorkflow(next);
    setWorkflows((current) => [
      next,
      ...current.filter((item) => item.id !== next.id),
    ]);
  };

  const run = async (action: string, operation: () => Promise<GuidedWorkflow>) => {
    setBusyAction(action);
    setError(undefined);
    setAdvanceError(undefined);
    try {
      setCurrent(await operation());
    } catch (operationError) {
      const message = action === 'advance'
        ? guidedAdvanceErrorMessage(operationError, isZh)
        : operationError instanceof Error ? operationError.message : String(operationError);
      setError(message);
      if (action === 'advance') {
        if (
          operationError instanceof ApiError
          && operationError.code === 'GUIDED_WORKFLOW_CONFLICT'
          && workflow
        ) {
          try {
            setCurrent(await api.getGuidedWorkflow(workflow.id));
          } catch {
            // 保留原冲突作为主错误；刷新失败不能掩盖需要重新核对服务器状态这一事实。
          }
        }
        const targetId = guidedAdvanceErrorTarget(operationError);
        setAdvanceError({
          message,
          targetId,
        });
        focusGuidedTarget(targetId);
      }
    } finally {
      setBusyAction(undefined);
    }
  };

  const createWorkflow = () => run(
    'create',
    () => api.createGuidedWorkflow(language),
  );

  const sendMessage = async (event: FormEvent) => {
    event.preventDefault();
    if (!workflow || !message.trim()) return;
    const content = message.trim();
    const clientRequestId = `guided-${crypto.randomUUID()}`;
    await submitGuidedTurn(content, clientRequestId, workflow.version, true);
  };

  const submitGuidedTurn = async (
    content: string,
    clientRequestId: string,
    expectedVersion: number,
    clearComposer: boolean,
  ) => {
    if (!workflow) return;
    const startedAtMs = Date.now();
    const optimisticTurn: LocalGuidedTurn = {
      id: clientRequestId,
      content,
      createdAt: new Date(startedAtMs).toISOString(),
      startedAtMs,
      stage: workflow.stage,
      status: 'sending',
    };
    setLocalTurn(optimisticTurn);
    if (clearComposer) setMessage('');
    setBusyAction('turn');
    setError(undefined);
    setCredentialActionRequired(false);
    setAdvanceError(undefined);
    try {
      const next = await api.sendGuidedTurn(workflow.id, {
        message: content,
        language,
        expectedVersion,
        clientRequestId,
      });
      setCurrent(next);
      const persisted = next.messages.some(
        (item) => item.role === 'user' && item.content === content,
      );
      setLocalTurn(persisted ? undefined : { ...optimisticTurn, status: 'delivered' });
    } catch (operationError) {
      setMessage(content);
      setLocalTurn({ ...optimisticTurn, status: 'failed' });
      setCredentialActionRequired(
        operationError instanceof ApiError
        && (
          operationError.code === 'LLM_CREDENTIAL_EXPIRED'
          || operationError.code === 'LLM_CREDENTIAL_NOT_CONFIGURED'
        ),
      );
      setError(guidedTurnErrorMessage(operationError, isZh));
    } finally {
      setBusyAction(undefined);
    }
  };

  const decideRecovery = async () => {
    if (!workflow || !recoveryIntent) return;
    const { operation, action } = recoveryIntent;
    setBusyAction('recover');
    setError(undefined);
    try {
      const newClientRequestId = action === 'ABANDON_AND_AUTHORIZE_RETRY'
        ? `guided-${crypto.randomUUID()}`
        : undefined;
      const result = await api.recoverGuidedTurn(
        workflow.id,
        operation.clientRequestId,
        {
          recoveryRequestId: `recovery-${crypto.randomUUID()}`,
          action,
          expectedVersion: operation.expectedVersion,
          newClientRequestId,
        },
      );
      setRecoveryIntent(undefined);
      if (result.kind === 'WORKFLOW') {
        setCurrent(result.workflow);
        return;
      }
      setTurnOperations((current) => current.map((item) => (
        item.clientRequestId === result.operation.clientRequestId
          ? result.operation
          : item
      )));
      if (
        action === 'ABANDON_AND_AUTHORIZE_RETRY'
        && result.operation.authorizedRetryClientRequestId
        && result.operation.requestMessage
      ) {
        setBusyAction(undefined);
        await submitGuidedTurn(
          result.operation.requestMessage,
          result.operation.authorizedRetryClientRequestId,
          result.operation.expectedVersion,
          false,
        );
      } else if (action === 'ABANDON_AND_AUTHORIZE_RETRY') {
        setMessage(result.operation.requestMessage ?? operation.requestMessage ?? '');
        setError(isZh
          ? '原请求已安全放弃，但旧记录没有可恢复的正文。请核对输入框后手动重新发送。'
          : 'The original request was safely abandoned, but its text is unavailable. Review the composer before sending again.');
      }
    } catch (recoveryError) {
      setError(recoveryError instanceof Error ? recoveryError.message : String(recoveryError));
    } finally {
      setBusyAction(undefined);
    }
  };

  const archiveWorkflow = async () => {
    if (!workflow) return;
    setBusyAction('archive');
    setError(undefined);
    try {
      await api.archiveGuidedWorkflow(workflow.id, workflow.version);
      const remaining = await api.getGuidedWorkflows();
      setWorkflows(remaining);
      setWorkflow(remaining.length > 0
        ? await api.getGuidedWorkflow(remaining[0].id)
        : undefined);
      setArchiveRequested(false);
    } catch (archiveError) {
      setError(archiveError instanceof Error ? archiveError.message : String(archiveError));
    } finally {
      setBusyAction(undefined);
    }
  };

  const applyProposal = () => {
    if (!workflow?.pendingProposalId) return;
    void run('apply', () => api.applyGuidedProposal(
      workflow.id,
      workflow.pendingProposalId!,
      workflow.version,
    ));
  };

  const advanceWorkflow = () => {
    if (!workflow) return;
    const blocker = guidedAdvanceBlocker(workflow, isZh);
    if (blocker) {
      setError(undefined);
      setAdvanceError(blocker);
      focusGuidedTarget(blocker.targetId);
      return;
    }
    void run(
      'advance',
      () => api.advanceGuidedWorkflow(workflow.id, workflow.version),
    );
  };

  const currentStageIndex = workflow ? STAGES.indexOf(workflow.stage) : 0;
  const pendingProposal = workflow?.pendingProposal;
  const eventGoalBatchCompleted = Object.values(eventGoalBatch)
    .filter((value) => value.trim()).length;
  const eventGoalProposalCompleted = pendingProposal
    ? Math.max(0, 5 - (pendingProposal.missingFields?.length ?? 0))
    : 0;
  const eventGoalCompleted = workflow?.draft.eventMetadata
    ? 5
    : Math.max(eventGoalBatchCompleted, eventGoalProposalCompleted);
  const currentTurnOperation = localTurn
    ? turnOperations.find((operation) => operation.clientRequestId === localTurn.id)
    : undefined;
  const needsExternalReview = workflow && [
    'SOURCE_REVIEW',
    'CLAIM_REVIEW',
    'PACK_METADATA_REVIEW',
    'PACK_FREEZE_REVIEW',
    'SCENARIO_REVIEW',
    'PREFLIGHT',
  ].includes(workflow.stage);

  const stageAction = useMemo(() => {
    if (!workflow) return undefined;
    if (workflow.stage === 'SOURCE_REVIEW') {
      return {
        label: isZh ? '打开 Event Pack Factory' : 'Open Event Pack Factory',
        view: 'factory' as const,
      };
    }
    if (['CLAIM_REVIEW', 'PACK_METADATA_REVIEW', 'PACK_FREEZE_REVIEW'].includes(workflow.stage)) {
      return { label: isZh ? '打开事件包审核' : 'Open Event Pack review', view: 'pack' as const };
    }
    if (workflow.stage === 'SCENARIO_INTERVENTION' || workflow.stage === 'SCENARIO_REVIEW') {
      return { label: isZh ? '打开情景构建器' : 'Open Scenario Builder', view: 'scenario' as const };
    }
    if (workflow.stage === 'PREFLIGHT' || workflow.stage === 'READY_TO_SUBMIT') {
      return { label: isZh ? '打开运行前检查' : 'Open Preflight', view: 'preflight' as const };
    }
    return undefined;
  }, [isZh, workflow]);

  const selectLinkedEventPack = async (eventPackId: string) => {
    const pack = await api.getEventPack(eventPackId);
    await selectCase({
      id: pack.caseId ?? `case-${pack.id}`,
      eventPackId: pack.id,
      name: pack.name,
      nameZh: pack.nameZh,
      description: pack.description,
      descriptionZh: pack.descriptionZh,
      isSynthetic: Boolean(pack.isSynthetic),
    });
  };

  const openStageWorkspace = async () => {
    if (!workflow || !stageAction) return;
    setBusyAction('handoff');
    setError(undefined);
    try {
      // 专业页只持有返回指针；真实完成状态仍在返回时从服务器重新读取。
      writeGuidedReturnContext(workflow);
      if (stageAction.view === 'factory') {
        writeFactoryGuidedHandoff(workflow);
      } else if (stageAction.view === 'pack') {
        if (!workflow.draft.eventPackId) {
          throw new Error(isZh
            ? 'Factory 尚未返回并关联真实 Event Pack，请先完成来源审核和生成。'
            : 'The Factory has not returned and linked a real Event Pack yet.');
        }
        await selectLinkedEventPack(workflow.draft.eventPackId);
      } else if (stageAction.view === 'scenario') {
        writeScenarioGuidedHandoff(workflow);
        await selectLinkedEventPack(workflow.draft.eventPackId!);
      } else if (stageAction.view === 'preflight') {
        if (!workflow.draft.eventPackId || !workflow.draft.scenarioId) {
          throw new Error(isZh
            ? '请先在情景构建器保存并冻结当前工作流的情景。'
            : 'Save and freeze this workflow scenario in Scenario Builder first.');
        }
        const savedScenario = await api.getScenario(workflow.draft.scenarioId);
        await selectLinkedEventPack(workflow.draft.eventPackId);
        setScenario(savedScenario.config);
      }
      navigate(stageAction.view);
    } catch (handoffError) {
      setError(handoffError instanceof Error ? handoffError.message : String(handoffError));
    } finally {
      setBusyAction(undefined);
    }
  };

  if (state === 'loading') {
    return <div className="page"><PageHeader title={isZh ? 'AI 引导' : 'AI-guided workflow'} subtitle={isZh ? '正在恢复你的引导记录。' : 'Restoring your guided records.'} /><LoadingPanel /></div>;
  }
  if (state === 'error') {
    return <div className="page"><PageHeader title={isZh ? 'AI 引导' : 'AI-guided workflow'} subtitle={isZh ? '分阶段完成事件研究设置。' : 'Complete event research setup in bounded stages.'} /><ErrorPanel detail={error} onRetry={() => void load()} /></div>;
  }

  return (
    <div className="page page--guided">
      <PageHeader
        title={isZh ? 'AI 引导工作流' : 'AI-guided workflow'}
        subtitle={isZh
          ? '一次只完成一个确定阶段。AI 只能提出候选草稿，应用候选、人工审核、冻结和提交始终是彼此独立的操作。'
          : 'Complete one bounded stage at a time. AI may propose a draft, while applying, reviewing, freezing, and submitting remain separate human actions.'}
        actions={(
          <Button kind="tertiary" renderIcon={Plus} disabled={Boolean(busyAction)} onClick={() => void createWorkflow()}>
            {isZh ? '新建引导' : 'New guided workflow'}
          </Button>
        )}
      />

      <section
        className="guided-responsibility-map"
        aria-labelledby="guided-responsibility-map-heading"
      >
        <div className="section-heading">
          <h2 id="guided-responsibility-map-heading">
            {isZh ? 'AI 与人工职责全流程' : 'End-to-end AI and human responsibilities'}
          </h2>
          <p>{isZh
            ? '引导负责提出和衔接草稿；涉及证据授权、主张判断、冻结、费用与提交责任的步骤必须在专业页由人完成。'
            : 'Guidance proposes and connects drafts. Evidence authorization, claim judgment, freezing, cost review, and submission accountability remain human actions in dedicated workspaces.'}</p>
        </div>
        <ol>
          {RESPONSIBILITY_FLOW.map((item, index) => (
            <li key={item.key}>
              <span aria-hidden="true">{index + 1}</span>
              <div>
                <Tag
                  size="sm"
                  type={item.owner === 'AI' ? 'blue' : item.owner === 'HUMAN' ? 'purple' : 'cool-gray'}
                >
                  {item.owner === 'AI'
                    ? isZh ? 'AI 提议' : 'AI proposes'
                    : item.owner === 'HUMAN'
                      ? isZh ? '人工负责' : 'Human accountable'
                      : isZh ? '系统续接' : 'System resumes'}
                </Tag>
                <strong>{isZh ? item.title.zh : item.title.en}</strong>
                <p>{isZh ? item.detail.zh : item.detail.en}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {error && !advanceError ? (
        <div className="guided-inline-error">
          <InlineNotification
            kind="error"
            lowContrast
            hideCloseButton
            title={isZh ? '操作没有完成' : 'Action was not completed'}
            subtitle={error}
          />
          {credentialActionRequired ? (
            <Button kind="tertiary" onClick={() => navigate('ai')}>
              {isZh ? '前往 AI 配置' : 'Open AI configuration'}
            </Button>
          ) : null}
        </div>
      ) : null}

      {workflows.length === 0 || !workflow ? (
        <EmptyState
          title={isZh ? '从一个研究问题开始' : 'Start with a research question'}
          body={isZh
            ? '系统将依次处理事件目标、来源、主张、事件包、单一干预和运行前检查。没有任何 AI 操作会直接冻结或提交研究对象。'
            : 'The workflow covers the event goal, sources, claims, Event Pack, one intervention, and preflight. No AI action directly freezes or submits a research object.'}
          action={<Button renderIcon={ArrowRight} onClick={() => void createWorkflow()}>{isZh ? '开始引导' : 'Start guidance'}</Button>}
        />
      ) : (
        <div className="guided-layout">
          <aside className="guided-rail" aria-label={isZh ? '引导进度' : 'Guided progress'}>
            <div className="guided-workflow-picker">
              <label htmlFor="guided-workflow-select">{isZh ? '已有引导' : 'Saved workflows'}</label>
              <select
                id="guided-workflow-select"
                value={workflow.id}
                disabled={Boolean(busyAction)}
                onChange={(event) => {
                  const nextId = event.target.value;
                  void run('select', () => api.getGuidedWorkflow(nextId));
                }}
              >
                {workflows.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.draft.eventMetadata?.title ?? `${stageLabel(item.stage, isZh)} · ${item.id.slice(-6)}`}
                  </option>
                ))}
              </select>
              <Button
                kind="ghost"
                size="sm"
                renderIcon={Archive}
                disabled={Boolean(busyAction)}
                onClick={() => setArchiveRequested(true)}
              >
                {isZh ? '归档当前引导' : 'Archive this workflow'}
              </Button>
            </div>
            {archiveRequested ? (
              <div className="guided-inline-decision" role="alert">
                <strong>{isZh ? '归档后将从列表隐藏' : 'This workflow will leave the active list'}</strong>
                <p>{isZh
                  ? '服务器会保留审计记录，不会删除已创建的 Event Pack、情景或实验。'
                  : 'Audit records remain, and linked Event Packs, scenarios, and experiments are not deleted.'}</p>
                <div>
                  <Button
                    size="sm"
                    kind="danger"
                    disabled={Boolean(busyAction)}
                    onClick={() => void archiveWorkflow()}
                  >
                    {isZh ? '确认归档' : 'Confirm archive'}
                  </Button>
                  <Button
                    size="sm"
                    kind="ghost"
                    disabled={Boolean(busyAction)}
                    onClick={() => setArchiveRequested(false)}
                  >
                    {isZh ? '取消' : 'Cancel'}
                  </Button>
                </div>
              </div>
            ) : null}
            <ol className="guided-stages">
              {STAGES.map((stage, index) => (
                <li
                  key={stage}
                  className={index === currentStageIndex
                    ? 'is-current'
                    : index < currentStageIndex
                      ? 'is-complete'
                      : ''}
                  aria-current={index === currentStageIndex ? 'step' : undefined}
                >
                  <span>{index < currentStageIndex ? <CheckCircle size={17} weight="fill" /> : index + 1}</span>
                  <div><strong>{stageLabel(stage, isZh)}</strong></div>
                </li>
              ))}
            </ol>
          </aside>

          <section className="guided-workspace" aria-labelledby="guided-current-stage">
            <header className="guided-stage-header">
              <div>
                <span>{isZh ? `阶段 ${currentStageIndex + 1} / ${STAGES.length}` : `Stage ${currentStageIndex + 1} of ${STAGES.length}`}</span>
                <h2 id="guided-current-stage">{stageLabel(workflow.stage, isZh)}</h2>
              </div>
              <StatusBadge status={workflow.status} />
            </header>

            <InlineNotification
              kind="info"
              lowContrast
              hideCloseButton
              title={isZh ? '人工控制边界' : 'Human-control boundary'}
              subtitle={isZh
                ? '“应用候选”只把结构化建议放入引导草稿，不会创建、冻结或提交 Event Pack、情景或实验。'
                : 'Apply candidate only copies a structured proposal into this guided draft. It does not create, freeze, or submit an Event Pack, scenario, or experiment.'}
            />

            {workflow.stage === 'EVENT_GOAL' ? (
              <section className="guided-event-goal-helper" aria-labelledby="guided-event-goal-helper-heading">
                <header>
                  <div>
                    <span>{isZh ? '本阶段字段进度' : 'Field progress for this stage'}</span>
                    <h3 id="guided-event-goal-helper-heading">
                      {isZh
                        ? `已填 ${eventGoalCompleted}/5`
                        : `${eventGoalCompleted}/5 complete`}
                    </h3>
                  </div>
                  <Tag type={workflow.draft.eventMetadata ? 'green' : 'cool-gray'}>
                    {workflow.draft.eventMetadata
                      ? isZh ? '完整草稿' : 'Complete draft'
                      : isZh ? '待补全' : 'Incomplete'}
                  </Tag>
                </header>
                <p>
                  {isZh
                    ? '推荐示例：我要研究 2024-01-05 阿拉斯加航空 1282 航班门塞脱落事件，使用 BA（合成市场代理）比较做市能力下降是否放大模拟流动性压力。'
                    : 'Example: Study the 2024-01-05 Alaska Airlines Flight 1282 door-plug event using BA (a synthetic market proxy), focusing on whether reduced market-making capacity amplified simulated liquidity stress.'}
                </p>
                {!workflow.draft.eventMetadata ? (
                  <details>
                    <summary>{isZh ? '一次填写本阶段全部字段' : 'Complete every field in one batch'}</summary>
                    <div className="guided-event-goal-helper__fields">
                      {(Object.keys(EVENT_GOAL_FIELD_LABELS) as EventGoalField[]).map((field) => (
                        <label key={field}>
                          <span>{isZh ? EVENT_GOAL_FIELD_LABELS[field].zh : EVENT_GOAL_FIELD_LABELS[field].en}</span>
                          {field === 'summary' || field === 'researchQuestion' ? (
                            <textarea
                              rows={3}
                              value={eventGoalBatch[field]}
                              onChange={(event) => setEventGoalBatch((current) => ({
                                ...current,
                                [field]: event.target.value,
                              }))}
                            />
                          ) : (
                            <input
                              type={field === 'asOf' ? 'date' : 'text'}
                              value={eventGoalBatch[field]}
                              onChange={(event) => setEventGoalBatch((current) => ({
                                ...current,
                                [field]: event.target.value,
                              }))}
                            />
                          )}
                        </label>
                      ))}
                    </div>
                    <div className="guided-event-goal-helper__actions">
                      <Button
                        size="sm"
                        disabled={Object.values(eventGoalBatch).some((value) => !value.trim())}
                        onClick={fillComposerFromEventGoalBatch}
                      >
                        {isZh ? '放入对话并一次提交' : 'Put all fields in the composer'}
                      </Button>
                      <Button kind="ghost" size="sm" onClick={() => navigate('factory')}>
                        {isZh ? '切换到专家手动入口' : 'Use expert manual entry'}
                      </Button>
                    </div>
                  </details>
                ) : null}
              </section>
            ) : null}

            <div className="guided-conversation" aria-live="polite">
              {workflow.messages.map((item) => (
                <article key={item.id} className={`guided-message guided-message--${item.role}`}>
                  <header>
                    {item.role === 'assistant' ? <Robot size={18} aria-hidden="true" /> : <User size={18} aria-hidden="true" />}
                    <strong>{item.role === 'assistant' ? (isZh ? '引导助手' : 'Guided assistant') : (isZh ? '你' : 'You')}</strong>
                    <time dateTime={item.createdAt}>{safeDate(item.createdAt, language)}</time>
                    {workflow.language !== language ? (
                      <Tag type="cool-gray" size="sm">
                        {isZh
                          ? `此对话以${workflow.language === 'zh-CN' ? '中文' : '英文'}生成`
                          : `Conversation generated in ${workflow.language === 'zh-CN' ? 'Chinese' : 'English'}`}
                      </Tag>
                    ) : null}
                  </header>
                  {item.role === 'assistant'
                    ? <SafeMarkdown content={item.content} />
                    : <p>{item.content}</p>}
                </article>
              ))}
              {localTurn ? (
                <article
                  key={localTurn.id}
                  className={`guided-message guided-message--user guided-message--${localTurn.status}`}
                  data-testid="guided-local-turn"
                >
                  <header>
                    <User size={18} aria-hidden="true" />
                    <strong>{isZh ? '你' : 'You'}</strong>
                    <time dateTime={localTurn.createdAt}>
                      {safeDate(localTurn.createdAt, language)}
                    </time>
                    <Tag
                      type={localTurn.status === 'failed' ? 'red' : 'cool-gray'}
                      size="sm"
                    >
                      {localTurn.status === 'failed'
                        ? isZh ? '发送失败，输入已恢复' : 'Failed; input restored'
                        : localTurn.status === 'delivered'
                          ? isZh ? '已发送，等待同步' : 'Sent; awaiting sync'
                          : isZh ? '发送中' : 'Sending'}
                    </Tag>
                  </header>
                  <p>{localTurn.content}</p>
                </article>
              ) : null}
            </div>

            {localTurn?.status === 'sending' ? (
              <div className="guided-turn-progress" role="status" aria-live="polite">
                <ArrowClockwise size={18} aria-hidden="true" />
                <div>
                  <strong>{localTurnProgress(
                    turnElapsedSeconds,
                    isZh,
                    currentTurnOperation,
                  )}</strong>
                  <span>
                    {isZh
                      ? `服务器阶段：${currentTurnOperation?.failureStage
                        ? technicalCodeLabel(currentTurnOperation.failureStage, language)
                        : '等待操作登记'} · 已真实等待 ${turnElapsedSeconds} 秒`
                      : `Server stage: ${currentTurnOperation?.failureStage
                        ? technicalCodeLabel(currentTurnOperation.failureStage, language)
                        : 'awaiting operation record'} · Actual wait: ${turnElapsedSeconds} seconds`}
                  </span>
                </div>
              </div>
            ) : null}

            {turnOperations.some((item) => item.status === 'UNKNOWN') ? (
              <section className="guided-operation-recovery" aria-labelledby="guided-recovery-heading">
                <header>
                  <Warning size={22} weight="fill" aria-hidden="true" />
                  <div>
                    <h3 id="guided-recovery-heading">
                      {isZh ? '有一次模型调用需要你决定如何恢复' : 'A model call needs a recovery decision'}
                    </h3>
                    <p>{isZh
                      ? '系统不会自动重试未知调用，避免重复计费。先查看证据，再选择使用缓存结果或明确放弃并授权一次新调用。'
                      : 'Unknown calls are never retried automatically, preventing duplicate charges. Review the evidence, then reuse a cached result or explicitly authorize one new call.'}</p>
                  </div>
                </header>
                {turnOperations.filter((item) => item.status === 'UNKNOWN').map((operation) => (
                  <article key={operation.clientRequestId}>
                    <div className="guided-operation-recovery__summary">
                      <div>
                        <strong>{guidedOperationStatus(operation.status, isZh)}</strong>
                        <span>{safeDate(operation.updatedAt, language)}</span>
                      </div>
                      <Tag
                        type="red"
                        size="sm"
                        title={technicalCodeLabel(operation.errorCode, language)}
                      >
                        {technicalCodeLabel(operation.errorCode, language)}
                      </Tag>
                    </div>
                    {operation.requestMessage ? <p>{operation.requestMessage}</p> : null}
                    <dl>
                      <div>
                        <dt>{isZh ? '供应商请求' : 'Provider request'}</dt>
                        <dd>{operation.providerRequestId
                          ? isZh ? '已记录' : 'Recorded'
                          : isZh ? '未记录' : 'Not recorded'}</dd>
                      </div>
                      <div>
                        <dt>{isZh ? '最后确认阶段' : 'Last confirmed stage'}</dt>
                        <dd>{technicalCodeLabel(operation.failureStage, language)}</dd>
                      </div>
                      <div>
                        <dt>{isZh ? '收到 HTTP 响应' : 'HTTP response received'}</dt>
                        <dd>{operation.httpResponseReceived === undefined
                          ? isZh ? '无法确认' : 'Unconfirmed'
                          : operation.httpResponseReceived
                            ? isZh ? '是' : 'Yes'
                            : isZh ? '否' : 'No'}</dd>
                      </div>
                      <div>
                        <dt>{isZh ? '已缓存可校验候选' : 'Validated candidate cached'}</dt>
                        <dd>{operation.cachedProposalAvailable
                          ? isZh ? '是' : 'Yes'
                          : isZh ? '否' : 'No'}</dd>
                      </div>
                    </dl>
                    <details className="guided-operation-technical-details">
                      <summary>{isZh ? '技术详情' : 'Technical details'}</summary>
                      <dl>
                        <div>
                          <dt>{isZh ? '客户端请求 ID' : 'Client request ID'}</dt>
                          <dd><code>{operation.clientRequestId}</code></dd>
                        </div>
                        <div>
                          <dt>{isZh ? '供应商请求 ID' : 'Provider request ID'}</dt>
                          <dd><code>{operation.providerRequestId ?? (isZh ? '未记录' : 'Not recorded')}</code></dd>
                        </div>
                      </dl>
                      <TechnicalCodeDisplay
                        codes={[operation.errorCode, operation.failureStage]}
                        language={language}
                      />
                    </details>
                    <div className="guided-operation-recovery__actions">
                      {operation.recoveryOptions.includes('RETRY_CACHED_COMMIT') ? (
                        <Button
                          size="sm"
                          disabled={Boolean(busyAction)}
                          onClick={() => setRecoveryIntent({
                            operation,
                            action: 'RETRY_CACHED_COMMIT',
                          })}
                        >
                          {isZh ? '使用缓存结果，不调用模型' : 'Use cached result; no model call'}
                        </Button>
                      ) : null}
                      {operation.recoveryOptions.includes('ABANDON_AND_AUTHORIZE_RETRY') ? (
                        <Button
                          size="sm"
                          kind="danger--tertiary"
                          disabled={Boolean(busyAction)}
                          onClick={() => setRecoveryIntent({
                            operation,
                            action: 'ABANDON_AND_AUTHORIZE_RETRY',
                          })}
                        >
                          {isZh ? '放弃未知结果并授权重试一次' : 'Abandon and authorize one retry'}
                        </Button>
                      ) : null}
                    </div>
                  </article>
                ))}
              </section>
            ) : null}

            {recoveryIntent ? (
              <section className="guided-recovery-confirmation" role="alert">
                <Warning size={22} weight="fill" aria-hidden="true" />
                <div>
                  <h3>{recoveryIntent.action === 'RETRY_CACHED_COMMIT'
                    ? isZh ? '确认提交缓存结果？' : 'Commit the cached result?'
                    : isZh ? '确认放弃并产生一次新模型调用？' : 'Abandon and create one new model call?'}</h3>
                  <p>{recoveryIntent.action === 'RETRY_CACHED_COMMIT'
                    ? isZh
                      ? '该操作只提交服务器已校验并缓存的候选，不会请求供应商，也不会新增模型费用。'
                      : 'This commits the validated candidate already cached by the server. It does not contact the provider or add model cost.'
                    : isZh
                      ? '原调用可能已经计费。确认后系统会永久标记原结果为已放弃，并仅授权一个有审计关联的新请求 ID。'
                      : 'The original call may already have been billed. Confirmation permanently abandons it and authorizes exactly one linked request ID.'}</p>
                  <div>
                    <Button
                      size="sm"
                      kind={recoveryIntent.action === 'RETRY_CACHED_COMMIT' ? 'primary' : 'danger'}
                      disabled={Boolean(busyAction)}
                      onClick={() => void decideRecovery()}
                    >
                      {isZh ? '确认执行' : 'Confirm'}
                    </Button>
                    <Button
                      size="sm"
                      kind="ghost"
                      disabled={Boolean(busyAction)}
                      onClick={() => setRecoveryIntent(undefined)}
                    >
                      {isZh ? '取消' : 'Cancel'}
                    </Button>
                  </div>
                </div>
              </section>
            ) : null}

            {operationError ? (
              <InlineNotification
                kind="warning"
                lowContrast
                hideCloseButton
                title={isZh ? '操作审计记录暂时无法加载' : 'Operation audit history is unavailable'}
                subtitle={operationError}
              />
            ) : null}

            {turnOperations.length > 0 ? (
              <details className="guided-operation-history">
                <summary>
                  {isZh
                    ? `模型调用与恢复记录（${turnOperations.length}）`
                    : `Model call and recovery history (${turnOperations.length})`}
                </summary>
                <ol>
                  {turnOperations.map((operation, index) => (
                    <li key={operation.clientRequestId}>
                      <div>
                        <strong>{isZh
                          ? `第 ${index + 1} 次调用 · ${guidedOperationStatus(operation.status, isZh)}`
                          : `Call ${index + 1} · ${guidedOperationStatus(operation.status, isZh)}`}</strong>
                        <time dateTime={operation.updatedAt}>
                          {safeDate(operation.updatedAt, language)}
                        </time>
                      </div>
                      <details className="guided-operation-history__technical">
                        <summary>{isZh ? '技术详情' : 'Technical details'}</summary>
                        <code>{operation.clientRequestId}</code>
                        {operation.supersedesClientRequestId ? (
                          <span>
                            {isZh ? '替代调用：' : 'Supersedes: '}
                            <code>{operation.supersedesClientRequestId}</code>
                          </span>
                        ) : null}
                        {operation.providerRequestId ? (
                          <span>
                            {isZh ? '供应商请求：' : 'Provider request: '}
                            <code>{operation.providerRequestId}</code>
                          </span>
                        ) : null}
                      </details>
                    </li>
                  ))}
                </ol>
              </details>
            ) : null}

            {pendingProposal ? (
              <section
                className={`guided-proposal${advanceError?.targetId === 'guided-proposal-heading' ? ' is-invalid' : ''}`}
                aria-labelledby="guided-proposal-heading"
              >
                <header>
                  <div>
                    <span>{isZh ? '待人工决定的候选' : 'Candidate awaiting a human decision'}</span>
                    <h3 id="guided-proposal-heading" tabIndex={-1}>{stageLabel(pendingProposal.stage, isZh)}</h3>
                  </div>
                  <Tag type={pendingProposal.readyForHumanReview ? 'green' : 'warm-gray'}>
                    {pendingProposal.readyForHumanReview
                      ? isZh ? '可供审核' : 'Ready for review'
                      : isZh ? '需要补充' : 'Needs clarification'}
                  </Tag>
                </header>
                {advanceError?.targetId === 'guided-proposal-heading' ? (
                  <InlineNotification
                    kind="error"
                    lowContrast
                    hideCloseButton
                    title={isZh ? '先处理当前候选' : 'Resolve the current candidate first'}
                    subtitle={advanceError.message}
                  />
                ) : null}
                <ProposalDetails proposal={pendingProposal} isZh={isZh} />
                <p className="guided-proposal__instruction">
                  {isZh
                    ? '请逐字段核对。若需要修改，请在下方直接说明哪一项应改成什么，助手会生成新的候选；确认无误后才应用。'
                    : 'Review every field. To edit it, state exactly what should change in the message field below; the assistant will return a new candidate. Apply only after it is correct.'}
                </p>
                <Button
                  renderIcon={ClipboardText}
                  disabled={Boolean(busyAction) || !pendingProposal.readyForHumanReview}
                  onClick={applyProposal}
                >
                  {busyAction === 'apply'
                    ? isZh ? '正在应用' : 'Applying'
                    : isZh ? '应用已核对的候选' : 'Apply reviewed candidate'}
                </Button>
              </section>
            ) : null}

            {pendingProposal?.nextQuestionOptions.length ? (
              <div className="guided-suggestions" aria-label={isZh ? '建议回答' : 'Suggested answers'}>
                {pendingProposal.nextQuestionOptions.map((option) => (
                  <button type="button" key={option} onClick={() => setMessage(option)}>{option}</button>
                ))}
              </div>
            ) : null}

            {workflow.archivedProposals && workflow.archivedProposals.length > 0 ? (
              <details className="guided-proposal-archive">
                <summary>
                  {isZh
                    ? `查看已归档候选（${workflow.archivedProposals.length}）`
                    : `View archived candidates (${workflow.archivedProposals.length})`}
                </summary>
                <ol>
                  {workflow.archivedProposals.map((archived) => (
                    <li key={archived.id}>
                      <div>
                        <strong>{stageLabel(archived.proposal.stage, isZh)}</strong>
                        <StatusBadge status={archived.status} />
                      </div>
                      <p>{archived.proposal.assistantMessage}</p>
                      <time dateTime={archived.archivedAt}>
                        {safeDate(archived.archivedAt, language)}
                      </time>
                    </li>
                  ))}
                </ol>
              </details>
            ) : null}

            {workflow.status === 'ACTIVE' ? (
              <form className="guided-composer" onSubmit={(event) => void sendMessage(event)}>
                <TextArea
                  id="guided-message"
                  labelText={isZh ? '回复当前阶段，或逐字段提出修改' : 'Answer this stage, or request field-level changes'}
                  placeholder={isZh ? '不要输入 API Key、密码、身份证件、私人通信或其他不必要的个人信息。' : 'Do not enter API keys, passwords, identification documents, private correspondence, or unnecessary personal data.'}
                  value={message}
                  maxCount={2_000}
                  enableCounter
                  disabled={Boolean(busyAction)}
                  invalid={advanceError?.targetId === 'guided-message'}
                  invalidText={advanceError?.targetId === 'guided-message'
                    ? advanceError.message
                    : undefined}
                  onChange={(event) => setMessage(event.target.value)}
                />
                <Button
                  type="submit"
                  renderIcon={PaperPlaneTilt}
                  disabled={Boolean(busyAction) || !message.trim()}
                >
                  {busyAction === 'turn'
                    ? `${localTurnProgress(
                      turnElapsedSeconds,
                      isZh,
                      currentTurnOperation,
                    )} · ${turnElapsedSeconds}s`
                    : isZh ? '发送并生成候选' : 'Send and propose'}
                </Button>
              </form>
            ) : null}

            {needsExternalReview ? (
              <section
                className={`guided-review-link${advanceError?.targetId === 'guided-review-link-heading' ? ' is-invalid' : ''}`}
                aria-labelledby="guided-review-link-heading"
              >
                <div>
                  <h3 id="guided-review-link-heading" tabIndex={-1}>{isZh ? '在专业页面完成审核' : 'Complete review in the dedicated workspace'}</h3>
                  <p>{isZh
                    ? '审核页保留完整字段、证据和冻结护栏。创建、生成或保存成功后，页面会把服务器返回的真实对象关联到本引导；这里不接受手工粘贴 ID。'
                    : 'The dedicated page retains complete fields, evidence, and freeze guardrails. After a successful create, materialize, or save, it links the real server-returned object to this workflow; pasted IDs are not accepted here.'}</p>
                </div>
                {advanceError?.targetId === 'guided-review-link-heading' ? (
                  <InlineNotification
                    kind="error"
                    lowContrast
                    hideCloseButton
                    title={isZh ? '专业页面还有未完成项' : 'The dedicated workspace is incomplete'}
                    subtitle={advanceError.message}
                  />
                ) : null}
                {stageAction ? (
                  <Button
                    id="guided-stage-workspace-action"
                    kind="tertiary"
                    renderIcon={Factory}
                    disabled={Boolean(busyAction)}
                    onClick={() => void openStageWorkspace()}
                  >
                    {stageAction.label}
                  </Button>
                ) : null}
                <Button
                  kind="ghost"
                  renderIcon={ArrowClockwise}
                  disabled={Boolean(busyAction)}
                  onClick={() => void run(
                    'refresh',
                    () => api.getGuidedWorkflow(workflow.id),
                  )}
                >
                  {busyAction === 'refresh'
                    ? isZh ? '正在核对服务器状态' : 'Checking server state'
                    : isZh ? '刷新并核对真实对象' : 'Refresh verified artifacts'}
                </Button>
              </section>
            ) : stageAction ? (
              <div className={`guided-stage-action${advanceError?.targetId === 'guided-stage-workspace-action' ? ' is-invalid' : ''}`}>
                {advanceError?.targetId === 'guided-stage-workspace-action' ? (
                  <InlineNotification
                    kind="error"
                    lowContrast
                    hideCloseButton
                    title={isZh ? '情景尚未准备好' : 'The scenario is not ready'}
                    subtitle={advanceError.message}
                  />
                ) : null}
                <Button
                  id="guided-stage-workspace-action"
                  kind="tertiary"
                  renderIcon={ArrowRight}
                  disabled={Boolean(busyAction)}
                  onClick={() => void openStageWorkspace()}
                >
                  {stageAction.label}
                </Button>
              </div>
            ) : null}

            {workflow.status === 'ACTIVE' ? (
              <div className={`guided-advance${advanceError?.targetId === 'guided-advance-heading' ? ' is-invalid' : ''}`}>
                <div>
                  <strong id="guided-advance-heading" tabIndex={-1}>{isZh ? '阶段确认' : 'Stage confirmation'}</strong>
                  <p>{isZh
                    ? '只有在候选已应用、需要的对象已关联，并且你亲自核对当前阶段后才能继续。'
                    : 'Continue only after the candidate is applied, required artifacts are linked, and you personally reviewed this stage.'}</p>
                </div>
                {advanceError?.targetId === 'guided-advance-heading' ? (
                  <InlineNotification
                    kind="error"
                    lowContrast
                    hideCloseButton
                    title={isZh ? '暂时不能进入下一阶段' : 'The next stage is not ready'}
                    subtitle={advanceError.message}
                  />
                ) : null}
                <Button
                  kind="primary"
                  renderIcon={ArrowRight}
                  disabled={Boolean(busyAction)}
                  onClick={advanceWorkflow}
                >
                  {busyAction === 'advance'
                    ? isZh ? '正在检查阶段' : 'Checking stage'
                    : isZh ? '我已人工检查，继续' : 'I reviewed this stage, continue'}
                </Button>
              </div>
            ) : null}
          </section>
        </div>
      )}
    </div>
  );
}
