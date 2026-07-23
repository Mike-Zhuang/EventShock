import {
  Button,
  Checkbox,
  InlineNotification,
  NumberInput,
  Select,
  SelectItem,
  Tag,
  TextArea,
  TextInput,
} from '@carbon/react';
import {
  ArrowClockwise,
  ArrowRight,
  Check,
  FileText,
  Globe,
  MagnifyingGlass,
  Plus,
  ShieldCheck,
  Trash,
  Warning,
  X,
} from '@phosphor-icons/react';
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import type { Navigate } from '../app';
import { api } from '../api/client';
import type {
  EventPack,
  EventPackFactoryBuild,
  EventPackFactoryPasteSourceInput,
  EventPackFactorySnapshot,
  EventPackFactorySource,
  EventPackFactorySourceRawText,
  FactorySearchContentSize,
  FactorySearchEngineDescriptor,
  FactorySearchEngineId,
  FactorySearchRecency,
} from '../api/types';
import {
  EmptyState,
  ErrorPanel,
  LoadingPanel,
  PageHeader,
  StatusBadge,
} from '../components/common';
import {
  clearFactoryGuidedHandoff,
  readFactoryGuidedHandoff,
} from '../guided-handoff';
import { useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';

const FACTORY_BUILD_STORAGE_KEY = 'eventshock:last-factory-build-id';
const MAX_PASTE_SOURCES = 24;
const IMPACT_CHANNELS = [
  'belief',
  'socialAmplification',
  'liquidity',
  'passiveFlow',
  'stopLoss',
  'informationLatency',
] as const;

interface PasteDraft {
  localId: string;
  title: string;
  publisher: string;
  url: string;
  publishedAt: string;
  knownAt: string;
  rawText: string;
}

interface IdempotentAttempt<T> {
  signature: string;
  clientRequestId: string;
  payload: T;
}

function localDateTimeNow(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function localDateTimeValue(value: string): string {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return localDateTimeNow();
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function newPasteDraft(index: number): PasteDraft {
  return {
    localId: `paste-${crypto.randomUUID()}`,
    title: '',
    publisher: '',
    url: '',
    publishedAt: localDateTimeNow(),
    knownAt: localDateTimeNow(),
    rawText: '',
  };
}

function SourceCard({
  source,
  isZh,
  busy,
  readerEvidenceExists,
  onReview,
  onReader,
  onLoadRawText,
  onSaveRawText,
}: {
  source: EventPackFactorySource;
  isZh: boolean;
  busy: boolean;
  readerEvidenceExists: boolean;
  onReview: (source: EventPackFactorySource, status: 'APPROVED' | 'REJECTED') => void;
  onReader: (source: EventPackFactorySource) => void;
  onLoadRawText: (
    source: EventPackFactorySource,
  ) => Promise<EventPackFactorySourceRawText | undefined>;
  onSaveRawText: (
    source: EventPackFactorySource,
    rawText: string,
  ) => Promise<EventPackFactorySourceRawText | undefined>;
}) {
  const discoveryOnly = source.evidenceRole === 'DISCOVERY_ONLY';
  const readerAvailable = source.kind === 'SEARCH_RESULT' && source.reviewStatus === 'APPROVED';
  const rawTextAvailable = !discoveryOnly && source.reviewStatus !== 'REJECTED';
  const [rawText, setRawText] = useState<EventPackFactorySourceRawText>();
  const [rawDraft, setRawDraft] = useState('');
  const [rawError, setRawError] = useState<string>();
  const [rawLoading, setRawLoading] = useState(false);

  const loadRawText = async () => {
    if (!rawTextAvailable || rawText || rawLoading) return;
    setRawLoading(true);
    setRawError(undefined);
    try {
      const loaded = await onLoadRawText(source);
      if (loaded) {
        setRawText(loaded);
        setRawDraft(loaded.rawText);
      }
    } catch (loadError) {
      setRawError(loadError instanceof Error ? loadError.message : String(loadError));
    } finally {
      setRawLoading(false);
    }
  };

  const saveRawText = async () => {
    if (!rawText || rawDraft.trim().length === 0 || rawDraft === rawText.rawText) return;
    const confirmed = window.confirm(isZh
      ? '保存原文修订会重新执行内容安全扫描，并撤销该来源当前的批准状态。必须再次人工审核后才能用于物化。是否继续？'
      : 'Saving a raw-text revision reruns content safety checks and revokes the current approval. You must approve it again before materialization. Continue?');
    if (!confirmed) return;
    setRawLoading(true);
    setRawError(undefined);
    try {
      const revised = await onSaveRawText(source, rawDraft);
      if (revised) {
        setRawText(revised);
        setRawDraft(revised.rawText);
      }
    } catch (saveError) {
      setRawError(saveError instanceof Error ? saveError.message : String(saveError));
    } finally {
      setRawLoading(false);
    }
  };
  return (
    <article className="factory-source">
      <header>
        <div>
          <Tag type={discoveryOnly ? 'purple' : 'blue'} size="sm">
            {discoveryOnly
              ? isZh ? '发现线索，不能直接作证' : 'Discovery only, not evidence'
              : isZh ? '候选证据' : 'Candidate evidence'}
          </Tag>
          <StatusBadge status={source.reviewStatus} />
          {source.securityDecision === 'REVIEW' ? (
            <Tag type="warm-gray" size="sm">{isZh ? '内容需谨慎复核' : 'Content review required'}</Tag>
          ) : null}
        </div>
        <span>{source.kind.replaceAll('_', ' ')}</span>
      </header>
      <h3>{source.title}</h3>
      <p className="factory-source__publisher">{source.publisher}</p>
      <p>{source.reviewSummary}</p>
      <dl>
        <div><dt>{isZh ? '可见时间' : 'Known at'}</dt><dd>{new Intl.DateTimeFormat(isZh ? 'zh-CN' : 'en', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(source.knownAt))}</dd></div>
        <div><dt>{isZh ? '内容长度' : 'Content length'}</dt><dd>{source.contentLength.toLocaleString()} {isZh ? '字符' : 'characters'}</dd></div>
        <div><dt>{isZh ? '内容哈希' : 'Content hash'}</dt><dd><code title={source.contentHash}>{source.contentHash.slice(0, 16)}</code></dd></div>
      </dl>
      {source.url ? (
        <a href={source.url} target="_blank" rel="noopener noreferrer nofollow">
          <Globe size={16} aria-hidden="true" />
          {isZh ? '打开原网页' : 'Open original page'}
        </a>
      ) : null}
      {source.verifiedEvidenceQuotes.length > 0 ? (
        <details>
          <summary>{isZh ? `核对过的原文片段（${source.verifiedEvidenceQuotes.length}）` : `Verified source excerpts (${source.verifiedEvidenceQuotes.length})`}</summary>
          <blockquote>{source.verifiedEvidenceQuotes.join('\n\n')}</blockquote>
        </details>
      ) : null}
      {rawTextAvailable ? (
        <details
          className="factory-source__raw-text"
          onToggle={(event) => {
            if (event.currentTarget.open) void loadRawText();
          }}
        >
          <summary>{isZh ? '查看或修订完整原文（敏感）' : 'View or revise full raw text (sensitive)'}</summary>
          <p className="factory-source__raw-warning">
            {isZh
              ? '原文仅按需从服务器读取，不应包含密码、API Key 或不必要的个人信息；浏览器不会将它写入账号偏好。'
              : 'Raw text is fetched from the server only on demand. Do not include passwords, API keys, or unnecessary personal data; it is not written to account preferences.'}
          </p>
          {rawLoading && !rawText ? <p>{isZh ? '正在读取原文…' : 'Loading raw text…'}</p> : null}
          {rawError ? <InlineNotification kind="error" lowContrast hideCloseButton title={isZh ? '原文操作失败' : 'Raw-text action failed'} subtitle={rawError} /> : null}
          {rawText ? (
            <>
              <TextArea
                id={`factory-raw-${source.id}`}
                labelText={isZh ? '完整原文' : 'Full raw text'}
                value={rawDraft}
                maxCount={100_000}
                enableCounter
                rows={12}
                onChange={(event) => setRawDraft(event.target.value)}
              />
              <p className="factory-source__retention">
                {isZh ? '计划清理时间：' : 'Scheduled deletion: '}
                {new Intl.DateTimeFormat(isZh ? 'zh-CN' : 'en', {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                }).format(new Date(rawText.retentionExpiresAt))}
              </p>
              <Button
                kind="tertiary"
                size="sm"
                renderIcon={ShieldCheck}
                disabled={busy || rawLoading || rawDraft.trim().length === 0 || rawDraft === rawText.rawText}
                onClick={() => void saveRawText()}
              >
                {rawLoading
                  ? isZh ? '正在重新扫描' : 'Rescanning'
                  : isZh ? '保存为新修订并重新审核' : 'Save as new revision and review again'}
              </Button>
            </>
          ) : null}
        </details>
      ) : null}
      <div className="factory-source__actions">
        <Button
          kind="ghost"
          size="sm"
          renderIcon={Check}
          disabled={busy || source.reviewStatus === 'APPROVED'}
          onClick={() => onReview(source, 'APPROVED')}
        >
          {isZh ? '人工批准' : 'Approve source'}
        </Button>
        <Button
          kind="danger--ghost"
          size="sm"
          renderIcon={X}
          disabled={busy || source.reviewStatus === 'REJECTED'}
          onClick={() => onReview(source, 'REJECTED')}
        >
          {isZh ? '拒绝' : 'Reject'}
        </Button>
        {readerAvailable ? (
          <Button
            kind="tertiary"
            size="sm"
            renderIcon={FileText}
            disabled={busy || readerEvidenceExists}
            onClick={() => onReader(source)}
          >
            {readerEvidenceExists
              ? isZh ? '全文已导入，等待独立审核' : 'Full page imported; separate review pending'
              : isZh ? '读取全文，生成证据来源' : 'Read full page into evidence'}
          </Button>
        ) : null}
      </div>
    </article>
  );
}

export function EventPackFactoryPage({ navigate }: { navigate: Navigate }) {
  const { language } = useI18n();
  const isZh = language === 'zh-CN';
  const { selectCase } = useWorkflow();
  const [guidedHandoff] = useState(readFactoryGuidedHandoff);
  const [builds, setBuilds] = useState<EventPackFactoryBuild[]>([]);
  const [snapshot, setSnapshot] = useState<EventPackFactorySnapshot>();
  const [engines, setEngines] = useState<FactorySearchEngineDescriptor[]>([]);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [busyAction, setBusyAction] = useState<string>();
  const [error, setError] = useState<string>();
  const [buildTitle, setBuildTitle] = useState(guidedHandoff?.eventMetadata.title ?? '');
  const [pasteDrafts, setPasteDrafts] = useState<PasteDraft[]>([newPasteDraft(0)]);
  const [searchQuery, setSearchQuery] = useState(
    guidedHandoff?.searchQueries[0]?.slice(0, 70) ?? '',
  );
  const [searchEngine, setSearchEngine] = useState<FactorySearchEngineId>('search_std');
  const [searchCount, setSearchCount] = useState(10);
  const [domainFilter, setDomainFilter] = useState('');
  const [recency, setRecency] = useState<FactorySearchRecency>('noLimit');
  const [contentSize, setContentSize] = useState<FactorySearchContentSize>('medium');
  const [materializeTitle, setMaterializeTitle] = useState(
    guidedHandoff?.eventMetadata.title ?? '',
  );
  const [materializeTitleZh, setMaterializeTitleZh] = useState(
    guidedHandoff?.eventMetadata.titleZh ?? '',
  );
  const [summary, setSummary] = useState(guidedHandoff?.eventMetadata.summary ?? '');
  const [summaryZh, setSummaryZh] = useState(guidedHandoff?.eventMetadata.summaryZh ?? '');
  const [instrument, setInstrument] = useState(guidedHandoff?.eventMetadata.instrument ?? '');
  const [asOf, setAsOf] = useState(
    guidedHandoff ? localDateTimeValue(guidedHandoff.eventMetadata.asOf) : localDateTimeNow(),
  );
  const [maximumClaims, setMaximumClaims] = useState(16);
  const [impactChannels, setImpactChannels] = useState<string[]>(['belief', 'liquidity']);
  const [acknowledgedReview, setAcknowledgedReview] = useState(false);
  const [guidedLinkState, setGuidedLinkState] = useState<'BUILD' | 'EVENT_PACK'>();
  const [pendingGuidedPack, setPendingGuidedPack] = useState<EventPack>();
  const idempotentAttempts = useRef(new Map<string, IdempotentAttempt<unknown>>());

  const getIdempotentAttempt = <T,>(
    operation: string,
    signature: string,
    createPayload: () => T,
  ): IdempotentAttempt<T> => {
    const existing = idempotentAttempts.current.get(operation);
    if (existing?.signature === signature) return existing as IdempotentAttempt<T>;
    const next: IdempotentAttempt<T> = {
      signature,
      clientRequestId: `factory-${operation}-${crypto.randomUUID()}`,
      payload: createPayload(),
    };
    idempotentAttempts.current.set(operation, next);
    return next;
  };

  const completeIdempotentAttempt = (operation: string, clientRequestId: string) => {
    if (idempotentAttempts.current.get(operation)?.clientRequestId === clientRequestId) {
      idempotentAttempts.current.delete(operation);
    }
  };

  const selectedEngine = engines.find((item) => item.engine === searchEngine);

  const refreshSnapshot = async (buildId: string) => {
    const next = await api.getFactoryBuild(buildId);
    setSnapshot(next);
    setBuilds((current) => current.map((item) => item.id === next.build.id ? next.build : item));
    window.sessionStorage.setItem(FACTORY_BUILD_STORAGE_KEY, next.build.id);
    if (!materializeTitle) setMaterializeTitle(next.build.title);
    return next;
  };

  const load = async () => {
    setState('loading');
    setError(undefined);
    try {
      const [nextBuilds, nextEngines] = await Promise.all([
        api.getFactoryBuilds(),
        api.getFactorySearchEngines(),
      ]);
      setBuilds(nextBuilds);
      setEngines(nextEngines);
      const storedId = window.sessionStorage.getItem(FACTORY_BUILD_STORAGE_KEY);
      const selected = nextBuilds.find((item) => item.id === storedId) ?? nextBuilds[0];
      if (selected) await refreshSnapshot(selected.id);
      setState('ready');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : String(loadError));
      setState('error');
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const run = async <T,>(action: string, operation: () => Promise<T>): Promise<T | undefined> => {
    setBusyAction(action);
    setError(undefined);
    try {
      return await operation();
    } catch (operationError) {
      setError(operationError instanceof Error ? operationError.message : String(operationError));
      return undefined;
    } finally {
      setBusyAction(undefined);
    }
  };

  const linkGuidedArtifact = async (input: {
    eventPackBuildId?: string;
    eventPackId?: string;
  }) => {
    if (!guidedHandoff) return;
    const currentWorkflow = await api.getGuidedWorkflow(guidedHandoff.workflowId);
    if (
      input.eventPackId
      && currentWorkflow.draft.eventPackId
      && currentWorkflow.draft.eventPackId !== input.eventPackId
    ) {
      throw new Error(isZh
        ? '该引导已关联另一个 Event Pack；如需更换，请新建引导工作流。'
        : 'This guided workflow already links another Event Pack. Start a new workflow to replace it.');
    }
    // 服务器会重新验证旧构建是否仍存在：仍存在时不可替换；已删除或到期且尚未
    // 物化 Event Pack 时，允许把当前人工审核的新构建修复性关联回来。
    const eventPackBuildId = currentWorkflow.draft.eventPackBuildId === input.eventPackBuildId
      ? undefined
      : input.eventPackBuildId;
    const eventPackId = currentWorkflow.draft.eventPackId ? undefined : input.eventPackId;
    if (!eventPackBuildId && !eventPackId) return;
    await api.linkGuidedWorkflowArtifacts(currentWorkflow.id, {
      expectedVersion: currentWorkflow.version,
      eventPackBuildId,
      eventPackId,
    });
  };

  const createBuild = async (event: FormEvent) => {
    event.preventDefault();
    const title = buildTitle.trim();
    if (title.length < 3) return;
    await run('create', async () => {
      const build = await api.createFactoryBuild(title);
      setBuilds((current) => [build, ...current]);
      setBuildTitle('');
      setMaterializeTitle(build.title);
      await refreshSnapshot(build.id);
      if (guidedHandoff) {
        await linkGuidedArtifact({ eventPackBuildId: build.id });
        setGuidedLinkState('BUILD');
      }
    });
  };

  const deleteBuild = async () => {
    if (!snapshot) return;
    const confirmed = window.confirm(isZh
      ? `删除构建任务“${snapshot.build.title}”？这会删除任务中暂存的网页原文、来源、检索记录和审核状态，且无法撤销。已经生成的 Event Pack 不受影响。`
      : `Delete build "${snapshot.build.title}"? This permanently deletes its stored raw webpage text, sources, search records, and review state. Existing materialized Event Packs are not affected.`);
    if (!confirmed) return;
    await run('delete-build', async () => {
      await api.deleteFactoryBuild(snapshot.build.id, snapshot.build.revision);
      const remaining = builds.filter((item) => item.id !== snapshot.build.id);
      setBuilds(remaining);
      setSnapshot(undefined);
      window.sessionStorage.removeItem(FACTORY_BUILD_STORAGE_KEY);
      if (remaining[0]) await refreshSnapshot(remaining[0].id);
    });
  };

  const updatePasteDraft = (localId: string, patch: Partial<PasteDraft>) => {
    setPasteDrafts((current) => current.map((draft) => draft.localId === localId
      ? { ...draft, ...patch }
      : draft));
  };

  const validPasteDraft = (draft: PasteDraft) => draft.title.trim().length > 0
    && draft.publisher.trim().length > 0
    && draft.rawText.trim().length >= 20
    && (!draft.url.trim() || draft.url.trim().startsWith('https://'))
    && new Date(draft.publishedAt).getTime() <= new Date(draft.knownAt).getTime();

  const submitPasteSources = async () => {
    if (
      !snapshot
      || pasteDrafts.length > remainingSourceSlots
      || !pasteDrafts.every(validPasteDraft)
    ) {
      setError(isZh
        ? `请完整填写每个来源，使用 HTTPS 地址并检查时间；当前最多还能加入 ${remainingSourceSlots} 个有效证据来源。`
        : `Complete every source, use HTTPS URLs, and check timestamps. This build can accept ${remainingSourceSlots} more active evidence source(s).`);
      return;
    }
    await run('paste', async () => {
      let revision = snapshot.build.revision;
      try {
        for (const draft of pasteDrafts) {
          const source: EventPackFactoryPasteSourceInput = {
            title: draft.title.trim(),
            publisher: draft.publisher.trim(),
            rawText: draft.rawText.trim(),
            url: draft.url.trim() || undefined,
            publishedAt: new Date(draft.publishedAt).toISOString(),
            knownAt: new Date(draft.knownAt).toISOString(),
          };
          const mutation = await api.addFactoryPasteSource(snapshot.build.id, revision, source);
          revision = mutation.build.revision;
        }
        setPasteDrafts([newPasteDraft(0)]);
      } finally {
        // 批量请求不是事务：即使中途失败，前端也必须恢复服务器上的最新修订号，
        // 否则用户重试会持续触发 revision conflict。
        await refreshSnapshot(snapshot.build.id);
      }
    });
  };

  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!snapshot || !searchQuery.trim() || !selectedEngine) return;
    const searchInput = {
      query: searchQuery.trim(),
      engine: searchEngine,
      searchIntent: true,
      count: selectedEngine.supportsCount ? searchCount : undefined,
      domainFilter: selectedEngine.supportsDomainFilter && domainFilter.trim()
        ? domainFilter.trim()
        : undefined,
      recency: selectedEngine.supportsRecencyFilter ? recency : 'noLimit' as const,
      contentSize: selectedEngine.supportsContentSize ? contentSize : 'medium' as const,
    };
    const operation = 'search';
    const attempt = getIdempotentAttempt(
      operation,
      JSON.stringify({ revision: snapshot.build.revision, searchInput }),
      () => searchInput,
    );
    await run('search', async () => {
      await api.searchFactorySources(
        snapshot.build.id,
        snapshot.build.revision,
        attempt.payload,
        attempt.clientRequestId,
      );
      completeIdempotentAttempt(operation, attempt.clientRequestId);
      await refreshSnapshot(snapshot.build.id);
    });
  };

  const review = async (
    source: EventPackFactorySource,
    status: 'APPROVED' | 'REJECTED',
  ) => {
    if (!snapshot) return;
    await run(`review-${source.id}`, async () => {
      await api.reviewFactorySource(
        snapshot.build.id,
        source.id,
        snapshot.build.revision,
        status,
      );
      await refreshSnapshot(snapshot.build.id);
    });
  };

  const readSource = async (source: EventPackFactorySource) => {
    if (!snapshot) return;
    const operation = `reader:${source.id}`;
    const signature = JSON.stringify({
      revision: snapshot.build.revision,
      sourceId: source.id,
    });
    const attempt = getIdempotentAttempt(operation, signature, () => ({
      knownAt: new Date().toISOString(),
    }));
    await run(`reader-${source.id}`, async () => {
      await api.addFactoryReaderSource(
        snapshot.build.id,
        snapshot.build.revision,
        source.id,
        attempt.payload.knownAt,
        attempt.clientRequestId,
      );
      completeIdempotentAttempt(operation, attempt.clientRequestId);
      await refreshSnapshot(snapshot.build.id);
    });
  };

  const loadRawText = async (
    source: EventPackFactorySource,
  ): Promise<EventPackFactorySourceRawText | undefined> => run(
    `raw-load-${source.id}`,
    () => api.getFactorySourceRawText(source.buildId, source.id),
  );

  const saveRawText = async (
    source: EventPackFactorySource,
    rawText: string,
  ): Promise<EventPackFactorySourceRawText | undefined> => {
    if (!snapshot) return undefined;
    return run(`raw-save-${source.id}`, async () => {
      const mutation = await api.updateFactorySourceRawText(
        snapshot.build.id,
        source.id,
        snapshot.build.revision,
        rawText,
      );
      await refreshSnapshot(snapshot.build.id);
      const revised = mutation.sources[0];
      return {
        buildId: snapshot.build.id,
        sourceId: source.id,
        revision: mutation.build.revision,
        rawText,
        contentHash: revised.contentHash,
        contentLength: revised.contentLength,
        retentionExpiresAt: mutation.build.retentionExpiresAt,
      };
    });
  };

  const materialize = async (event: FormEvent) => {
    event.preventDefault();
    if (
      !snapshot
      || materializeTitle.trim().length < 3
      || summary.trim().length < 8
      || !instrument.trim()
      || !acknowledgedReview
      || impactChannels.length === 0
    ) {
      setError(isZh
        ? '请填写事件包元数据，选择至少一个影响通道，并确认已人工检查所有批准来源。'
        : 'Complete Event Pack metadata, choose an impact channel, and confirm human review of every approved source.');
      return;
    }
    const materializeInput = {
      title: materializeTitle.trim(),
      titleZh: materializeTitleZh.trim() || undefined,
      summary: summary.trim(),
      summaryZh: summaryZh.trim() || undefined,
      asOf: new Date(asOf).toISOString(),
      instrument: instrument.trim().toUpperCase(),
      maximumClaims,
      requestedImpactChannels: impactChannels,
      acknowledgedContentReview: true,
    };
    const operation = 'materialize';
    const attempt = getIdempotentAttempt(
      operation,
      JSON.stringify({ revision: snapshot.build.revision, materializeInput }),
      () => materializeInput,
    );
    await run('materialize', async () => {
      const pack = await api.materializeFactoryBuild(
        snapshot.build.id,
        snapshot.build.revision,
        attempt.payload,
        attempt.clientRequestId,
      );
      completeIdempotentAttempt(operation, attempt.clientRequestId);
      if (guidedHandoff) {
        setPendingGuidedPack(pack);
        await linkGuidedArtifact({
          eventPackBuildId: snapshot.build.id,
          eventPackId: pack.id,
        });
        setGuidedLinkState('EVENT_PACK');
        setPendingGuidedPack(undefined);
        clearFactoryGuidedHandoff();
      }
      await selectCase({
        id: pack.caseId ?? `case-${pack.id}`,
        eventPackId: pack.id,
        name: pack.name,
        nameZh: pack.nameZh,
        description: pack.description,
        descriptionZh: pack.descriptionZh,
        isSynthetic: false,
      });
      navigate('pack');
    });
  };

  const retryGuidedPackLink = async () => {
    if (!pendingGuidedPack || !snapshot) return;
    await run('guided-link-pack', async () => {
      await linkGuidedArtifact({
        eventPackBuildId: snapshot.build.id,
        eventPackId: pendingGuidedPack.id,
      });
      setGuidedLinkState('EVENT_PACK');
      clearFactoryGuidedHandoff();
      await selectCase({
        id: pendingGuidedPack.caseId ?? `case-${pendingGuidedPack.id}`,
        eventPackId: pendingGuidedPack.id,
        name: pendingGuidedPack.name,
        nameZh: pendingGuidedPack.nameZh,
        description: pendingGuidedPack.description,
        descriptionZh: pendingGuidedPack.descriptionZh,
        isSynthetic: false,
      });
      setPendingGuidedPack(undefined);
      navigate('pack');
    });
  };

  const approvedEvidence = snapshot?.sources.filter(
    (source) => source.evidenceRole === 'EVIDENCE' && source.reviewStatus === 'APPROVED',
  ) ?? [];
  const pendingSources = snapshot?.sources.filter((source) => source.reviewStatus === 'PENDING') ?? [];
  const rejectedSources = snapshot?.sources.filter((source) => source.reviewStatus === 'REJECTED') ?? [];
  const activeEvidenceCount = snapshot?.sources.filter(
    (source) => source.evidenceRole === 'EVIDENCE' && source.reviewStatus !== 'REJECTED',
  ).length ?? 0;
  const remainingSourceSlots = Math.max(0, MAX_PASTE_SOURCES - activeEvidenceCount);

  if (state === 'loading') {
    return <div className="page"><PageHeader title={isZh ? 'Event Pack 自动构建' : 'Event Pack Factory'} subtitle={isZh ? '正在恢复构建任务与来源目录。' : 'Restoring builds and source records.'} /><LoadingPanel /></div>;
  }
  if (state === 'error') {
    return <div className="page"><PageHeader title={isZh ? 'Event Pack 自动构建' : 'Event Pack Factory'} subtitle={isZh ? '从原始网页文字构建可审核事件包。' : 'Build reviewable Event Packs from raw webpage text.'} /><ErrorPanel detail={error} onRetry={() => void load()} /></div>;
  }

  return (
    <div className="page page--factory">
      <PageHeader
        title={isZh ? 'Event Pack 自动构建' : 'Event Pack Factory'}
        subtitle={isZh
          ? '批量粘贴网页原文或使用智谱联网搜索发现候选来源。搜索摘要仅用于发现；只有经全文读取、内容检查和人工批准的来源才能支持事件主张。'
          : 'Paste raw webpage text in batches or use Zhipu web search to discover candidate sources. Search snippets are discovery-only; only full-text, safety-checked, human-approved evidence may support claims.'}
        actions={(
          <Button kind="ghost" renderIcon={ArrowRight} onClick={() => navigate('pack')}>
            {isZh ? '使用手动上传' : 'Use manual upload'}
          </Button>
        )}
      />

      {error ? (
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={isZh ? 'Factory 操作没有完成' : 'Factory action was not completed'}
          subtitle={error}
        />
      ) : null}

      {guidedHandoff ? (
        <div className="inline-action-notice">
          <InlineNotification
            kind={guidedLinkState === 'EVENT_PACK' ? 'success' : 'info'}
            lowContrast
            hideCloseButton
            title={guidedLinkState === 'EVENT_PACK'
              ? isZh ? '真实 Event Pack 已关联回 AI 引导' : 'Real Event Pack linked back to AI guidance'
              : isZh ? '已载入 AI 引导中的可编辑事件草稿' : 'Editable guided event draft loaded'}
            subtitle={guidedLinkState === 'EVENT_PACK'
              ? isZh
                ? '请继续逐条审核主张；关联动作不会批准主张、冻结事件包或推进工作流。'
                : 'Continue with claim-by-claim review. Linking does not approve claims, freeze the pack, or advance the workflow.'
              : isZh
                ? '标题、摘要、证券、时点边界和检索式已经预填。请人工编辑并审核来源；创建任务后，服务器返回的真实 ID 会自动关联。'
                : 'Title, summary, instrument, cutoff, and search query are prefilled. Edit and review sources yourself; after creation, the real server-returned ID is linked automatically.'}
          />
          <Button kind="ghost" size="sm" onClick={() => navigate('guided')}>
            {isZh ? '返回 AI 引导' : 'Return to AI guidance'}
          </Button>
          {snapshot && guidedLinkState === undefined && !pendingGuidedPack ? (
            <Button
              kind="tertiary"
              size="sm"
              disabled={Boolean(busyAction)}
              onClick={() => void run('guided-link-build', async () => {
                await linkGuidedArtifact({ eventPackBuildId: snapshot.build.id });
                setGuidedLinkState('BUILD');
              })}
            >
              {isZh ? '关联当前构建任务' : 'Link current build'}
            </Button>
          ) : null}
          {pendingGuidedPack ? (
            <Button
              kind="tertiary"
              size="sm"
              disabled={Boolean(busyAction)}
              onClick={() => void retryGuidedPackLink()}
            >
              {isZh ? '重试关联已生成事件包' : 'Retry linking generated Event Pack'}
            </Button>
          ) : null}
        </div>
      ) : null}

      <InlineNotification
        kind="warning"
        lowContrast
        hideCloseButton
        title={isZh ? '来源与费用边界' : 'Source and cost boundary'}
        subtitle={isZh
          ? '联网检索和网页读取可能产生供应商费用，并可能遗漏、延迟或错误。Reader 价格尚未在本项目中核实，使用前请查看供应商控制台。请勿提交秘密或个人信息；所有来源仍必须打开原网页并人工核对。'
          : 'Search and Reader calls may incur provider charges and may be incomplete, delayed, or wrong. Reader pricing has not been verified by this project; check the provider console before use. Do not submit secrets or personal data; open the original page and review every source.'}
      />

      <div className="factory-layout">
        <aside className="factory-builds" aria-labelledby="factory-builds-heading">
          <h2 id="factory-builds-heading">{isZh ? '构建任务' : 'Builds'}</h2>
          <form onSubmit={(event) => void createBuild(event)}>
            <TextInput
              id="factory-build-title"
              labelText={isZh ? '内部任务名称' : 'Internal build title'}
              value={buildTitle}
              maxLength={200}
              onChange={(event) => setBuildTitle(event.target.value)}
            />
            <Button type="submit" size="sm" renderIcon={Plus} disabled={Boolean(busyAction) || buildTitle.trim().length < 3}>
              {isZh ? '新建任务' : 'Create build'}
            </Button>
          </form>
          <div className="factory-build-list">
            {builds.map((build) => (
              <button
                key={build.id}
                type="button"
                className={snapshot?.build.id === build.id ? 'is-active' : ''}
                aria-current={snapshot?.build.id === build.id ? 'true' : undefined}
                onClick={() => void run('select-build', () => refreshSnapshot(build.id))}
              >
                <strong>{build.title}</strong>
                <span>r{build.revision} · {build.status.replaceAll('_', ' ')}</span>
              </button>
            ))}
          </div>
        </aside>

        <div className="factory-workspace">
          {!snapshot ? (
            <EmptyState
              title={isZh ? '先创建一个构建任务' : 'Create a build first'}
              body={isZh
                ? '任务保存来源审核、检索费用和版本信息，最终生成一个新的待审核 Event Pack。'
                : 'A build records source review, search cost, and revisions, then materializes a new Event Pack for claim review.'}
            />
          ) : (
            <>
              <section className="factory-overview" aria-labelledby="factory-overview-heading">
                <div>
                  <span>{isZh ? '当前任务' : 'Current build'}</span>
                  <h2 id="factory-overview-heading">{snapshot.build.title}</h2>
                  <p><code>{snapshot.build.id}</code> · r{snapshot.build.revision}</p>
                  <p className="factory-overview__retention">
                    {isZh ? '暂存资料自动清理时间：' : 'Staged material expires: '}
                    {new Intl.DateTimeFormat(isZh ? 'zh-CN' : 'en', {
                      dateStyle: 'medium',
                      timeStyle: 'short',
                    }).format(new Date(snapshot.build.retentionExpiresAt))}
                  </p>
                </div>
                <div className="factory-overview__counts">
                  <div><span>{isZh ? '全部来源' : 'All sources'}</span><strong>{snapshot.sources.length}</strong></div>
                  <div><span>{isZh ? '已批准证据' : 'Approved evidence'}</span><strong>{approvedEvidence.length}</strong></div>
                  <div><span>{isZh ? '待审核' : 'Pending review'}</span><strong>{pendingSources.length}</strong></div>
                </div>
                <Button
                  kind="danger--ghost"
                  size="sm"
                  renderIcon={Trash}
                  disabled={Boolean(busyAction)}
                  onClick={() => void deleteBuild()}
                >
                  {busyAction === 'delete-build'
                    ? isZh ? '正在删除' : 'Deleting'
                    : isZh ? '删除任务与原文' : 'Delete build and raw text'}
                </Button>
              </section>

              <section className="factory-section" aria-labelledby="factory-paste-heading">
                <header className="section-heading">
                  <div>
                    <h2 id="factory-paste-heading">{isZh ? '1. 批量粘贴网页原文' : '1. Paste webpage text in batches'}</h2>
                    <p>{isZh
                      ? '每个区块代表一个独立来源，单个任务最多保留 24 个有效证据来源。完整原文会在服务器中暂存 7 天；每次实质修改会顺延清理时间，查看原文不会顺延。Event Pack 本身只保留来源元数据、哈希和短候选主张。'
                      : 'Each block is one source, with at most 24 active evidence sources per build. Full raw text is staged on the server for seven days; substantive mutations extend expiry, viewing does not. The Event Pack retains only source metadata, hashes, and short candidate claims.'}</p>
                  </div>
                  <Button
                    kind="ghost"
                    size="sm"
                    renderIcon={Plus}
                    disabled={
                      pasteDrafts.length >= remainingSourceSlots
                      || remainingSourceSlots === 0
                      || Boolean(busyAction)
                    }
                    onClick={() => setPasteDrafts((current) => [...current, newPasteDraft(current.length)])}
                  >
                    {isZh ? '增加来源' : 'Add source'}
                  </Button>
                </header>
                <div className="factory-paste-list">
                  {pasteDrafts.map((draft, index) => (
                    <fieldset key={draft.localId} className="factory-paste-source">
                      <legend>{isZh ? `来源 ${index + 1}` : `Source ${index + 1}`}</legend>
                      <div className="factory-form-grid">
                        <TextInput id={`${draft.localId}-title`} labelText={isZh ? '网页标题' : 'Page title'} value={draft.title} onChange={(event) => updatePasteDraft(draft.localId, { title: event.target.value })} />
                        <TextInput id={`${draft.localId}-publisher`} labelText={isZh ? '发布方' : 'Publisher'} value={draft.publisher} onChange={(event) => updatePasteDraft(draft.localId, { publisher: event.target.value })} />
                        <TextInput id={`${draft.localId}-url`} type="url" labelText={isZh ? 'HTTPS 网页地址（可选）' : 'HTTPS page URL (optional)'} value={draft.url} onChange={(event) => updatePasteDraft(draft.localId, { url: event.target.value })} />
                        <TextInput id={`${draft.localId}-published`} type="datetime-local" labelText={isZh ? '发布时间' : 'Published at'} value={draft.publishedAt} onChange={(event) => updatePasteDraft(draft.localId, { publishedAt: event.target.value })} />
                        <TextInput id={`${draft.localId}-known`} type="datetime-local" labelText={isZh ? '研究中可见时间' : 'Known at'} value={draft.knownAt} onChange={(event) => updatePasteDraft(draft.localId, { knownAt: event.target.value })} />
                      </div>
                      <TextArea
                        id={`${draft.localId}-raw`}
                        labelText={isZh ? '网页原文' : 'Raw webpage text'}
                        value={draft.rawText}
                        maxCount={100_000}
                        enableCounter
                        rows={8}
                        onChange={(event) => updatePasteDraft(draft.localId, { rawText: event.target.value })}
                      />
                      {pasteDrafts.length > 1 ? (
                        <Button kind="danger--ghost" size="sm" renderIcon={Trash} onClick={() => setPasteDrafts((current) => current.filter((item) => item.localId !== draft.localId))}>
                          {isZh ? '删除这个来源' : 'Remove source'}
                        </Button>
                      ) : null}
                    </fieldset>
                  ))}
                </div>
                <Button
                  renderIcon={FileText}
                  disabled={
                    Boolean(busyAction)
                    || pasteDrafts.length > remainingSourceSlots
                    || !pasteDrafts.every(validPasteDraft)
                  }
                  onClick={() => void submitPasteSources()}
                >
                  {busyAction === 'paste'
                    ? isZh ? '正在检查并加入' : 'Checking and adding'
                    : isZh ? `检查并加入 ${pasteDrafts.length} 个来源` : `Check and add ${pasteDrafts.length} source(s)`}
                </Button>
              </section>

              <section className="factory-section" aria-labelledby="factory-search-heading">
                <header className="section-heading">
                  <div>
                    <h2 id="factory-search-heading">{isZh ? '2. 联网发现候选来源' : '2. Discover candidate sources online'}</h2>
                    <p>{isZh
                      ? '这里调用的是智谱 Web Search 工具，不是聊天模型。搜索摘要只能帮助定位网页，不能直接支持事件主张。'
                      : 'This calls Zhipu Web Search tools, not a chat model. Search snippets help locate pages but cannot directly support claims.'}</p>
                  </div>
                  <Button kind="ghost" size="sm" onClick={() => navigate('ai')}>{isZh ? '检查临时 API 配置' : 'Check temporary API setup'}</Button>
                </header>
                <form className="factory-search-form" onSubmit={(event) => void search(event)}>
                  <TextInput id="factory-search-query" labelText={isZh ? '检索问题' : 'Search query'} value={searchQuery} maxLength={70} onChange={(event) => setSearchQuery(event.target.value)} />
                  <Select id="factory-search-engine" labelText={isZh ? '搜索引擎' : 'Search engine'} value={searchEngine} onChange={(event) => setSearchEngine(event.target.value as FactorySearchEngineId)}>
                    {engines.map((engine) => <SelectItem key={engine.engine} value={engine.engine} text={`${engine.displayName} · ¥${engine.priceCnyPerCall.toFixed(2)}/${isZh ? '次' : 'call'}`} />)}
                  </Select>
                  <NumberInput id="factory-search-count" label={isZh ? '结果数量' : 'Result count'} min={1} max={50} value={searchCount} disabled={!selectedEngine?.supportsCount} onChange={(_event, stateValue) => setSearchCount(Math.max(1, Math.min(50, Number(stateValue.value) || 10)))} />
                  <TextInput id="factory-domain-filter" labelText={isZh ? '限定域名（可选）' : 'Domain filter (optional)'} value={domainFilter} disabled={!selectedEngine?.supportsDomainFilter} onChange={(event) => setDomainFilter(event.target.value)} />
                  <Select id="factory-recency" labelText={isZh ? '时间范围' : 'Recency'} value={recency} disabled={!selectedEngine?.supportsRecencyFilter} onChange={(event) => setRecency(event.target.value as FactorySearchRecency)}>
                    <SelectItem value="noLimit" text={isZh ? '不限' : 'No limit'} />
                    <SelectItem value="oneDay" text={isZh ? '一天' : 'One day'} />
                    <SelectItem value="oneWeek" text={isZh ? '一周' : 'One week'} />
                    <SelectItem value="oneMonth" text={isZh ? '一个月' : 'One month'} />
                    <SelectItem value="oneYear" text={isZh ? '一年' : 'One year'} />
                  </Select>
                  <Select id="factory-content-size" labelText={isZh ? '摘要长度' : 'Content size'} value={contentSize} disabled={!selectedEngine?.supportsContentSize} onChange={(event) => setContentSize(event.target.value as FactorySearchContentSize)}>
                    <SelectItem value="medium" text={isZh ? '中等' : 'Medium'} />
                    <SelectItem value="high" text={isZh ? '较长' : 'High'} />
                  </Select>
                  <div className="factory-search-cost">
                    <Warning size={20} aria-hidden="true" />
                    <p>{isZh
                      ? `本次搜索预计收取 ¥${(selectedEngine?.priceCnyPerCall ?? 0).toFixed(2)}。未修改请求时重试会复用同一请求号，避免重复调度；修改参数会生成新请求并可能再次计费。Reader 价格仍需以供应商控制台为准。`
                      : `This search is estimated at ¥${(selectedEngine?.priceCnyPerCall ?? 0).toFixed(2)}. An unchanged retry reuses its request ID to avoid redispatch; changing parameters creates a new potentially billable request. Verify Reader pricing in the provider console.`}</p>
                  </div>
                  <Button type="submit" renderIcon={MagnifyingGlass} disabled={Boolean(busyAction) || !searchQuery.trim()}>
                    {busyAction === 'search' ? (isZh ? '正在联网搜索' : 'Searching the web') : (isZh ? '确认费用并搜索' : 'Confirm cost and search')}
                  </Button>
                </form>
                {snapshot.searchRuns.length > 0 ? (
                  <details className="factory-search-history">
                    <summary>{isZh ? `搜索记录（${snapshot.searchRuns.length}）` : `Search history (${snapshot.searchRuns.length})`}</summary>
                    <ul>{snapshot.searchRuns.map((run) => (
                      <li key={run.id}>
                        <strong>{run.query}</strong>
                        <span>{run.engine} · ¥{run.estimatedCostCny.toFixed(2)} · {run.resultCount} {isZh ? '条结果' : 'results'}{run.droppedResultCount ? ` · ${run.droppedResultCount} ${isZh ? '条丢弃' : 'dropped'}` : ''}</span>
                      </li>
                    ))}</ul>
                  </details>
                ) : null}
              </section>

              <section className="factory-section" aria-labelledby="factory-review-heading">
                <header className="section-heading">
                  <div>
                    <h2 id="factory-review-heading">{isZh ? '3. 逐个审核来源' : '3. Review every source'}</h2>
                    <p>{isZh
                      ? '先批准搜索线索再读取全文；Reader 返回的全文证据仍是新的待审核对象。任何批准都不能代替打开原网页核对。'
                      : 'Approve a discovery result before reading the full page. Reader evidence returns as a new pending object and still needs review. Approval never replaces checking the original page.'}</p>
                  </div>
                  <Button kind="ghost" size="sm" renderIcon={ArrowClockwise} disabled={Boolean(busyAction)} onClick={() => void refreshSnapshot(snapshot.build.id)}>
                    {isZh ? '刷新' : 'Refresh'}
                  </Button>
                </header>
                {snapshot.sources.length === 0 ? (
                  <EmptyState title={isZh ? '还没有来源' : 'No sources yet'} body={isZh ? '从上方粘贴原文或执行一次联网搜索。' : 'Paste source text or run a web search above.'} />
                ) : (
                  <div className="factory-source-list">
                    {snapshot.sources.map((source) => (
                      <SourceCard
                        key={source.id}
                        source={source}
                        isZh={isZh}
                        busy={Boolean(busyAction)}
                        readerEvidenceExists={snapshot.sources.some(
                          (candidate) => candidate.parentSourceId === source.id,
                        )}
                        onReview={(item, status) => void review(item, status)}
                        onReader={(item) => void readSource(item)}
                        onLoadRawText={loadRawText}
                        onSaveRawText={saveRawText}
                      />
                    ))}
                  </div>
                )}
                {rejectedSources.length > 0 ? (
                  <p className="factory-rejected-note">{isZh
                    ? `${rejectedSources.length} 个来源已拒绝并保留在审计历史中。`
                    : `${rejectedSources.length} rejected source(s) remain in the audit history.`}</p>
                ) : null}
              </section>

              <section className="factory-section factory-materialize" aria-labelledby="factory-materialize-heading">
                <header className="section-heading">
                  <div>
                    <h2 id="factory-materialize-heading">{isZh ? '4. 生成待审核 Event Pack' : '4. Materialize a reviewable Event Pack'}</h2>
                    <p>{isZh
                      ? '此操作只生成候选主张，不会批准主张或冻结事件包。生成后必须在“事件包审核”中逐条编辑、批准或拒绝。'
                      : 'This only generates candidate claims. It does not approve claims or freeze the Event Pack. Edit, approve, or reject every claim in Event Pack Review afterward.'}</p>
                  </div>
                  <div className="factory-evidence-ready">
                    <ShieldCheck size={21} aria-hidden="true" />
                    <span>{isZh ? `${approvedEvidence.length} 个已批准证据来源` : `${approvedEvidence.length} approved evidence source(s)`}</span>
                  </div>
                </header>
                <form onSubmit={(event) => void materialize(event)}>
                  <div className="factory-form-grid">
                    <TextInput id="factory-pack-title" labelText={isZh ? '英文标题' : 'English title'} value={materializeTitle} maxLength={200} onChange={(event) => setMaterializeTitle(event.target.value)} />
                    <TextInput id="factory-pack-title-zh" labelText={isZh ? '中文标题（可选）' : 'Chinese title (optional)'} value={materializeTitleZh} maxLength={200} onChange={(event) => setMaterializeTitleZh(event.target.value)} />
                    <TextArea id="factory-pack-summary" labelText={isZh ? '英文研究摘要' : 'English research summary'} value={summary} maxCount={1_000} enableCounter onChange={(event) => setSummary(event.target.value)} />
                    <TextArea id="factory-pack-summary-zh" labelText={isZh ? '中文研究摘要（可选）' : 'Chinese research summary (optional)'} value={summaryZh} maxCount={1_000} enableCounter onChange={(event) => setSummaryZh(event.target.value)} />
                    <TextInput id="factory-pack-instrument" labelText={isZh ? '证券代码' : 'Instrument symbol'} value={instrument} maxLength={32} onChange={(event) => setInstrument(event.target.value.toUpperCase())} />
                    <TextInput id="factory-pack-asof" type="datetime-local" labelText={isZh ? '时点边界 (asOf)' : 'Point-in-time cutoff (asOf)'} value={asOf} onChange={(event) => setAsOf(event.target.value)} />
                    <NumberInput id="factory-maximum-claims" label={isZh ? '最多候选主张' : 'Maximum candidate claims'} min={1} max={50} value={maximumClaims} onChange={(_event, stateValue) => setMaximumClaims(Math.max(1, Math.min(50, Number(stateValue.value) || 16)))} />
                  </div>
                  <fieldset className="factory-impact-channels">
                    <legend>{isZh ? '需要抽取的影响通道' : 'Impact channels to extract'}</legend>
                    {IMPACT_CHANNELS.map((channel) => (
                      <Checkbox
                        key={channel}
                        id={`factory-impact-${channel}`}
                        labelText={channel}
                        checked={impactChannels.includes(channel)}
                        onChange={(_event, stateValue) => setImpactChannels((current) => stateValue.checked
                          ? [...current, channel]
                          : current.filter((item) => item !== channel))}
                      />
                    ))}
                  </fieldset>
                  <Checkbox
                    id="factory-acknowledge-review"
                    labelText={isZh
                      ? '我已逐个打开并核对所有批准来源，确认其中不含秘密、无关个人信息或未处理的恶意指令；我理解搜索和 AI 输出可能错误。'
                      : 'I opened and reviewed every approved source, confirmed it contains no secrets, unnecessary personal data, or unhandled malicious instructions, and understand that search and AI output may be wrong.'}
                    checked={acknowledgedReview}
                    onChange={(_event, stateValue) => setAcknowledgedReview(stateValue.checked)}
                  />
                  <Button
                    type="submit"
                    renderIcon={ArrowRight}
                    disabled={Boolean(busyAction) || approvedEvidence.length === 0 || !acknowledgedReview}
                  >
                    {busyAction === 'materialize'
                      ? isZh ? '正在抽取候选主张' : 'Extracting candidate claims'
                      : isZh ? '生成并进入人工主张审核' : 'Generate and open human claim review'}
                  </Button>
                </form>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
