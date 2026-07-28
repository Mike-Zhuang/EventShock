import {
  Button,
  InlineNotification,
  Tag,
  TextArea,
} from '@carbon/react';
import {
  ArrowClockwise,
  ArrowRight,
  CheckCircle,
  ClipboardText,
  Factory,
  PaperPlaneTilt,
  Plus,
  Robot,
  User,
} from '@phosphor-icons/react';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import type { Navigate } from '../app';
import { api, ApiError } from '../api/client';
import type {
  GuidedStage,
  GuidedWorkflow,
  GuidedWorkflowProposal,
} from '../api/types';
import { EmptyState, ErrorPanel, LoadingPanel, PageHeader, StatusBadge } from '../components/common';
import { SafeMarkdown } from '../components/safe-markdown';
import {
  writeFactoryGuidedHandoff,
  writeScenarioGuidedHandoff,
} from '../guided-handoff';
import { useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';

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

function stageLabel(stage: GuidedStage, isZh: boolean): string {
  return isZh ? STAGE_LABELS[stage].zh : STAGE_LABELS[stage].en;
}

interface GuidedAdvanceBlocker {
  message: string;
  targetId: string;
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

function ProposalDetails({
  proposal,
  isZh,
}: {
  proposal: GuidedWorkflowProposal;
  isZh: boolean;
}) {
  const metadata = proposal.proposedEventMetadata;
  const intervention = proposal.proposedIntervention;
  return (
    <div className="guided-proposal__details">
      {metadata ? (
        <dl>
          <div><dt>{isZh ? '标题' : 'Title'}</dt><dd>{isZh ? metadata.titleZh ?? metadata.title : metadata.title}</dd></div>
          <div><dt>{isZh ? '研究问题' : 'Research question'}</dt><dd>{metadata.researchQuestion}</dd></div>
          <div><dt>{isZh ? '证券代码' : 'Instrument'}</dt><dd><code>{metadata.instrument}</code></dd></div>
          <div><dt>{isZh ? '时点边界' : 'Point-in-time cutoff'}</dt><dd>{new Intl.DateTimeFormat(isZh ? 'zh-CN' : 'en', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(metadata.asOf))}</dd></div>
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
          <ul>{proposal.blockedReasons.map((reason) => <li key={reason}>{reason.replaceAll('_', ' ')}</li>)}</ul>
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
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [busyAction, setBusyAction] = useState<string>();
  const [error, setError] = useState<string>();
  const [advanceError, setAdvanceError] = useState<GuidedAdvanceBlocker>();

  const load = async () => {
    setState('loading');
    setError(undefined);
    try {
      const next = await api.getGuidedWorkflows();
      setWorkflows(next);
      if (next.length > 0) setWorkflow(await api.getGuidedWorkflow(next[0].id));
      setState('ready');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
      setState('error');
    }
  };

  useEffect(() => {
    void load();
  }, []);

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
    setMessage('');
    await run('turn', () => api.sendGuidedTurn(workflow.id, {
      message: content,
      language,
      expectedVersion: workflow.version,
      clientRequestId: `guided-${crypto.randomUUID()}`,
    }));
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

      {error && !advanceError ? (
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={isZh ? '操作没有完成' : 'Action was not completed'}
          subtitle={error}
        />
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
            </div>
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

            <div className="guided-conversation" aria-live="polite">
              {workflow.messages.map((item) => (
                <article key={item.id} className={`guided-message guided-message--${item.role}`}>
                  <header>
                    {item.role === 'assistant' ? <Robot size={18} aria-hidden="true" /> : <User size={18} aria-hidden="true" />}
                    <strong>{item.role === 'assistant' ? (isZh ? '引导助手' : 'Guided assistant') : (isZh ? '你' : 'You')}</strong>
                    <time dateTime={item.createdAt}>{new Intl.DateTimeFormat(language, { hour: '2-digit', minute: '2-digit' }).format(new Date(item.createdAt))}</time>
                  </header>
                  {item.role === 'assistant'
                    ? <SafeMarkdown content={item.content} />
                    : <p>{item.content}</p>}
                </article>
              ))}
            </div>

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
                  {busyAction === 'turn' ? (isZh ? '正在生成候选' : 'Generating candidate') : (isZh ? '发送并生成候选' : 'Send and propose')}
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
