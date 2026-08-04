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
import { api, ApiError } from '../api/client';
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
  GuidedWorkflow,
} from '../api/types';
import {
  EmptyState,
  ErrorPanel,
  LoadingPanel,
  PageHeader,
  StatusBadge,
} from '../components/common';
import { SyntheticInstrumentLabel } from '../components/synthetic-instrument-label';
import {
  clearFactoryGuidedHandoff,
  readFactoryGuidedHandoff,
} from '../guided-handoff';
import {
  IMPACT_CHANNEL_DEFINITIONS,
  impactChannelDisplay,
} from '../impact-channels';
import { useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';

const FACTORY_BUILD_STORAGE_KEY = 'eventshock:last-factory-build-id';
const MAX_PASTE_SOURCES = 24;

type FactoryErrorSection = 'general' | 'paste' | 'search' | 'review' | 'materialize';
type FactorySourceFilter =
  | 'ALL'
  | 'DISCOVERY_CLUES'
  | 'AWAITING_READ'
  | 'PENDING_EVIDENCE'
  | 'APPROVED_EVIDENCE'
  | 'EXCLUDED';
type MaterializeValidationField =
  | 'sourceReview'
  | 'title'
  | 'summary'
  | 'instrument'
  | 'asOf'
  | 'impactChannels'
  | 'acknowledgedReview';

interface FactoryActionError {
  action: string;
  section: FactoryErrorSection;
  message: string;
  code?: string;
}

type MaterializeValidationErrors = Partial<Record<MaterializeValidationField, string>>;

const MATERIALIZE_FIELD_ORDER: MaterializeValidationField[] = [
  'sourceReview',
  'title',
  'summary',
  'instrument',
  'asOf',
  'impactChannels',
  'acknowledgedReview',
];

const MATERIALIZE_TARGETS: Record<MaterializeValidationField, string> = {
  sourceReview: 'factory-review-heading',
  title: 'factory-pack-title',
  summary: 'factory-pack-summary',
  instrument: 'factory-pack-instrument',
  asOf: 'factory-pack-asof',
  impactChannels: 'factory-impact-channels',
  acknowledgedReview: 'factory-acknowledge-review',
};

function factoryErrorSection(action: string): FactoryErrorSection {
  if (action === 'paste') return 'paste';
  if (action === 'search') return 'search';
  if (
    action.startsWith('reader-')
    || action.startsWith('review-')
    || action.startsWith('raw-')
    || action.startsWith('selection-')
  ) return 'review';
  if (action === 'materialize' || action === 'guided-link-pack') return 'materialize';
  return 'general';
}

function factoryErrorMessage(error: unknown, isZh: boolean): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : String(error);
  }
  const localizedMessages: Record<string, { en: string; zh: string }> = {
    ZHIPU_TEMPORARY_CREDENTIAL_REQUIRED: {
      en: 'Configure a temporary Zhipu API key in AI configuration, then retry this action.',
      zh: '请先在“AI 配置”中填写本次会话使用的智谱 API Key，然后重试。',
    },
    EVENT_PACK_FACTORY_REVISION_CONFLICT: {
      en: 'This build changed in another action. The latest revision has been reloaded; review it before retrying.',
      zh: '该构建任务已被其他操作更新。页面已重新载入最新修订，请核对后重试。',
    },
    EVENT_PACK_FACTORY_SOURCE_REVIEW_REQUIRED: {
      en: 'This source still needs an explicit human review decision before the next action.',
      zh: '该来源仍需明确的人工审核决定，完成批准或拒绝后才能继续。',
    },
    EVENT_PACK_FACTORY_READER_SOURCE_NOT_ALLOWED: {
      en: 'Reader can only open an approved search result from this build. Refresh the source list and review the discovery result first.',
      zh: 'Reader 只能读取当前任务中已经人工批准的搜索结果。请刷新来源列表并先审核该发现线索。',
    },
    EVENT_PACK_FACTORY_READER_SOURCE_IDENTITY_INVALID: {
      en: 'Reader can only open a discovery result created by this build. Refresh the source list and choose a search result from this build.',
      zh: 'Reader 只能读取当前构建任务生成的发现线索。请刷新来源列表，并选择本任务中的搜索结果。',
    },
    EVENT_PACK_FACTORY_UNSAFE_SOURCE_URL: {
      en: 'This address was blocked by the public-web safety boundary. Use a credential-free public HTTPS URL on port 443; localhost, private-network and ambiguous addresses are not accepted.',
      zh: '该地址被公网网页安全边界阻止。请使用不含凭据、端口为 443 的公开 HTTPS 地址；localhost、私网地址和歧义地址均不接受。',
    },
    EVENT_PACK_FACTORY_READER_AUTHENTICATION_FAILED: {
      en: 'Reader could not authenticate. Re-enter the temporary Zhipu API key in AI configuration, test it, and retry.',
      zh: 'Reader 鉴权失败。请在“AI 配置”中重新填写本次会话的智谱 API Key，测试通过后重试。',
    },
    EVENT_PACK_FACTORY_BUILD_NOT_READY: {
      en: 'At least one approved pasted or Reader full-text source is required before claim extraction.',
      zh: '抽取主张前至少需要一个已批准的粘贴原文或 Reader 全文证据来源。',
    },
    REQUEST_VALIDATION_ERROR: {
      en: 'The submitted values no longer match the server requirements. Recheck every input in this step and retry.',
      zh: '提交值与服务器要求不一致，请重新核对本步骤的全部输入后重试。',
    },
    GUIDED_ARTIFACT_INVALID: {
      en: 'This guided workflow already links a different artifact. Return to its linked build or start a new guided workflow.',
      zh: '该 AI 引导已经关联了另一个工件。请返回已关联的构建任务，或新建一个 AI 引导。',
    },
  };
  const localized = error.code ? localizedMessages[error.code] : undefined;
  return localized ? (isZh ? localized.zh : localized.en) : error.message;
}

function focusFactoryTarget(targetId: string): void {
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

interface PasteDraft {
  localId: string;
  title: string;
  publisher: string;
  url: string;
  publishedAt: string;
  knownAt: string;
  rawText: string;
}

type PasteValidationField =
  | 'title'
  | 'publisher'
  | 'url'
  | 'publishedAt'
  | 'knownAt'
  | 'rawText';

type PasteValidationErrors = Partial<Record<PasteValidationField, string>>;

const PASTE_FIELD_ORDER: PasteValidationField[] = [
  'title',
  'publisher',
  'url',
  'publishedAt',
  'knownAt',
  'rawText',
];

const PASTE_TARGET_SUFFIX: Record<PasteValidationField, string> = {
  title: 'title',
  publisher: 'publisher',
  url: 'url',
  publishedAt: 'published',
  knownAt: 'known',
  rawText: 'raw',
};

function validatePasteDraft(draft: PasteDraft, isZh: boolean): PasteValidationErrors {
  const errors: PasteValidationErrors = {};
  const publishedAt = new Date(draft.publishedAt).getTime();
  const knownAt = new Date(draft.knownAt).getTime();
  if (!draft.title.trim()) {
    errors.title = isZh ? '请填写网页标题。' : 'Enter the page title.';
  }
  if (!draft.publisher.trim()) {
    errors.publisher = isZh ? '请填写发布方。' : 'Enter the publisher.';
  }
  if (draft.url.trim() && !draft.url.trim().startsWith('https://')) {
    errors.url = isZh ? '网页地址必须使用 HTTPS。' : 'The page URL must use HTTPS.';
  }
  if (!Number.isFinite(publishedAt)) {
    errors.publishedAt = isZh ? '请选择有效的发布时间。' : 'Choose a valid publication time.';
  }
  if (!Number.isFinite(knownAt)) {
    errors.knownAt = isZh ? '请选择有效的研究可见时间。' : 'Choose a valid known-at time.';
  }
  if (Number.isFinite(publishedAt) && Number.isFinite(knownAt) && publishedAt > knownAt) {
    errors.knownAt = isZh
      ? '研究可见时间不能早于发布时间。'
      : 'Known-at time cannot be earlier than publication time.';
  }
  if (draft.rawText.trim().length < 20) {
    errors.rawText = isZh
      ? '网页原文至少需要 20 个字符。'
      : 'Raw webpage text must contain at least 20 characters.';
  }
  return errors;
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
  onSelection,
  onPermanentDelete,
  onReader,
  onLoadRawText,
  onSaveRawText,
}: {
  source: EventPackFactorySource;
  isZh: boolean;
  busy: boolean;
  readerEvidenceExists: boolean;
  onReview: (source: EventPackFactorySource, status: 'APPROVED') => void;
  onSelection: (source: EventPackFactorySource, included: boolean) => void;
  onPermanentDelete: (source: EventPackFactorySource) => void;
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
  const excluded = source.selectionStatus === 'EXCLUDED';
  const readerAvailable = source.kind === 'SEARCH_RESULT'
    && source.reviewStatus === 'APPROVED'
    && !excluded;
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
          {discoveryOnly && source.reviewStatus === 'APPROVED' ? (
            <Tag type="cyan" size="sm">
              {isZh ? '仅批准读取全文' : 'Approved for full-text retrieval only'}
            </Tag>
          ) : <StatusBadge status={source.reviewStatus} />}
          {source.securityDecision === 'REVIEW' ? (
            <Tag type="warm-gray" size="sm">{isZh ? '内容需谨慎复核' : 'Content review required'}</Tag>
          ) : null}
          {excluded ? (
            <Tag type="gray" size="sm">{isZh ? '已排除，可重新加入' : 'Excluded; can be restored'}</Tag>
          ) : null}
        </div>
        <span>{source.kind === 'PASTE'
          ? isZh ? '粘贴原文' : 'Pasted text'
          : source.kind === 'READER'
            ? isZh ? 'Reader 全文' : 'Reader full text'
            : isZh ? '搜索线索' : 'Search clue'}</span>
      </header>
      <h3>{source.title}</h3>
      <p className="factory-source__publisher">{source.publisher}</p>
      <p>{source.reviewSummary}</p>
      <dl>
        <div><dt>{isZh ? '可见时间' : 'Known at'}</dt><dd>{new Intl.DateTimeFormat(isZh ? 'zh-CN' : 'en', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(source.knownAt))}</dd></div>
        <div><dt>{isZh ? '内容长度' : 'Content length'}</dt><dd>{source.contentLength.toLocaleString()} {isZh ? '字符' : 'characters'}</dd></div>
        <div><dt>{isZh ? '内容哈希' : 'Content hash'}</dt><dd><code title={source.contentHash}>{source.contentHash.slice(0, 16)}</code></dd></div>
        <div><dt>{isZh ? '来源审查' : 'Source review'}</dt><dd>{source.officialHost
          ? `${isZh ? '官方域名' : 'Official host'} · ${source.officialHost}`
          : source.sourceReviewLabel}</dd></div>
      </dl>
      {source.securityFindings.length > 0 ? (
        <details className="factory-source__security">
          <summary>{isZh
            ? `安全发现（${source.securityFindings.length}）`
            : `Safety findings (${source.securityFindings.length})`}</summary>
          <p>{isZh
            ? '仅显示分类、字段位置与建议动作；不会回显命中的原文。'
            : 'Only category, field location, and a recommended action are shown; matched text is never echoed.'}</p>
          <ul>
            {source.securityFindings.map((finding, index) => (
              <li key={`${finding.field}-${finding.offset}-${finding.code}-${index}`}>
                <strong>{finding.riskCategory ?? finding.code}</strong>
                <span>{finding.severity} · {finding.field} · {finding.offset}</span>
                <span>{finding.recommendedAction}</span>
              </li>
            ))}
          </ul>
          <div className="factory-source__security-actions">
            {rawTextAvailable ? (
              <button
                type="button"
                className="factory-inline-link"
                onClick={() => focusFactoryTarget(`factory-raw-panel-${source.id}`)}
              >
                {isZh ? '查看并编辑原文' : 'Review and edit raw text'}
              </button>
            ) : null}
            <button
              type="button"
              className="factory-inline-link"
              onClick={() => focusFactoryTarget('factory-data-handling')}
            >
              {isZh ? '查看数据处理规则' : 'Review data-handling policy'}
            </button>
          </div>
        </details>
      ) : null}
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
          id={`factory-raw-panel-${source.id}`}
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
          disabled={busy || source.reviewStatus === 'APPROVED' || excluded}
          onClick={() => onReview(source, 'APPROVED')}
        >
          {discoveryOnly
            ? isZh ? '允许读取全文' : 'Allow full-text retrieval'
            : isZh ? '人工批准证据' : 'Approve evidence'}
        </Button>
        <Button
          kind="ghost"
          size="sm"
          renderIcon={X}
          disabled={busy || source.reviewStatus === 'REJECTED'}
          onClick={() => onSelection(source, excluded)}
        >
          {excluded
            ? isZh ? '重新加入当前证据集' : 'Restore to current evidence set'
            : isZh ? '从当前证据集排除' : 'Exclude from current evidence set'}
        </Button>
        <Button
          kind="danger--ghost"
          size="sm"
          renderIcon={Trash}
          disabled={busy || source.reviewStatus === 'REJECTED' || discoveryOnly}
          onClick={() => {
            const confirmed = window.confirm(isZh
              ? '这是不可逆操作：服务器会永久删除该来源原文；审计记录只保留哈希、长度与删除事实。若以后需要使用，必须重新导入。确认删除原文？'
              : 'This is irreversible: the server will permanently delete the source text. Audit keeps only the hash, length, and deletion event. Reuse requires a fresh import. Delete the raw text?');
            if (confirmed) onPermanentDelete(source);
          }}
        >
          {isZh ? '永久删除原文' : 'Permanently delete raw text'}
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
  const [actionError, setActionError] = useState<FactoryActionError>();
  const [materializeErrors, setMaterializeErrors] = useState<MaterializeValidationErrors>({});
  const [buildTitleError, setBuildTitleError] = useState<string>();
  const [pasteErrors, setPasteErrors] = useState<Record<string, PasteValidationErrors>>({});
  const [searchQueryError, setSearchQueryError] = useState<string>();
  const [sourceFilter, setSourceFilter] = useState<FactorySourceFilter>('ALL');
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
  const [guidedWorkflow, setGuidedWorkflow] = useState<GuidedWorkflow>();
  const [pendingGuidedPack, setPendingGuidedPack] = useState<EventPack>();
  const idempotentAttempts = useRef(new Map<string, IdempotentAttempt<unknown>>());

  const getIdempotentAttempt = <T,>(
    operation: string,
    signature: string,
    createPayload: () => T,
  ): IdempotentAttempt<T> => {
    const existing = idempotentAttempts.current.get(operation);
    if (existing?.signature === signature) return existing as IdempotentAttempt<T>;
    const operationKind = operation.split(':', 1)[0];
    const next: IdempotentAttempt<T> = {
      signature,
      // operation 可含完整 source ID，用它拼请求号会超过后端 80 字符上限。
      // Map 仍以完整 operation 隔离并发，本次请求号只保留固定操作类型。
      clientRequestId: `factory-${operationKind}-${crypto.randomUUID()}`,
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

  const selectBuild = async (buildId: string) => {
    const changingExistingBuild = Boolean(snapshot && snapshot.build.id !== buildId);
    if (snapshot?.build.id !== buildId) {
      setAcknowledgedReview(false);
      setMaterializeErrors({});
      setPasteErrors({});
      setActionError(undefined);
      setError(undefined);
      idempotentAttempts.current.clear();
    }
    const next = await refreshSnapshot(buildId);
    if (changingExistingBuild) {
      setMaterializeTitle(next.build.title);
      setMaterializeTitleZh('');
      setSummary('');
      setSummaryZh('');
      setInstrument('');
      setAsOf(localDateTimeNow());
      setImpactChannels(['belief', 'liquidity']);
    }
    return next;
  };

  const load = async () => {
    setState('loading');
    setError(undefined);
    try {
      let guidedLoadError: unknown;
      const [nextBuilds, nextEngines, nextGuidedWorkflow] = await Promise.all([
        api.getFactoryBuilds(),
        api.getFactorySearchEngines(),
        guidedHandoff
          ? api.getGuidedWorkflow(guidedHandoff.workflowId).catch((loadError: unknown) => {
            guidedLoadError = loadError;
            return undefined;
          })
          : Promise.resolve(undefined),
      ]);
      setBuilds(nextBuilds);
      setEngines(nextEngines);
      setGuidedWorkflow(nextGuidedWorkflow);
      setGuidedLinkState(nextGuidedWorkflow?.draft.eventPackId
        ? 'EVENT_PACK'
        : nextGuidedWorkflow?.draft.eventPackBuildId
          ? 'BUILD'
          : undefined);
      const storedId = window.sessionStorage.getItem(FACTORY_BUILD_STORAGE_KEY);
      // 从 AI 引导进入时优先恢复其已绑定任务，避免误在另一任务继续并触发
      // 后端的不可变工件保护。尚未绑定时不再自动选中上次或第一条任务，
      // 避免用户把旧构建误认为本次引导新建的对象。
      const linkedBuild = nextBuilds.find(
        (item) => item.id === nextGuidedWorkflow?.draft.eventPackBuildId,
      );
      const selected = linkedBuild ?? (!guidedHandoff
        ? nextBuilds.find((item) => item.id === storedId) ?? nextBuilds[0]
        : undefined);
      if (selected) await selectBuild(selected.id);
      if (guidedLoadError) {
        const message = factoryErrorMessage(guidedLoadError, isZh);
        setError(message);
        setActionError({
          action: 'guided-load',
          section: 'general',
          message,
          code: guidedLoadError instanceof ApiError ? guidedLoadError.code : undefined,
        });
      }
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
    setActionError(undefined);
    try {
      return await operation();
    } catch (operationError) {
      const message = factoryErrorMessage(operationError, isZh);
      if (
        operationError instanceof ApiError
        && operationError.code === 'EVENT_PACK_FACTORY_REVISION_CONFLICT'
        && snapshot
      ) {
        try {
          await refreshSnapshot(snapshot.build.id);
        } catch {
          // 原始冲突仍是主错误；刷新失败时保留它，避免用次要错误覆盖可操作原因。
        }
      }
      setError(message);
      setActionError({
        action,
        section: factoryErrorSection(action),
        message,
        code: operationError instanceof ApiError ? operationError.code : undefined,
      });
      if (
        action === 'materialize'
        && operationError instanceof ApiError
        && [
          'EVENT_PACK_FACTORY_BUILD_NOT_READY',
          'EVENT_PACK_FACTORY_SOURCE_REVIEW_REQUIRED',
        ].includes(operationError.code ?? '')
      ) {
        setMaterializeErrors((current) => ({
          ...current,
          sourceReview: message,
        }));
        focusFactoryTarget('factory-review-heading');
      }
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
    setGuidedWorkflow(currentWorkflow);
    setGuidedLinkState(currentWorkflow.draft.eventPackId
      ? 'EVENT_PACK'
      : currentWorkflow.draft.eventPackBuildId
        ? 'BUILD'
        : undefined);
    if (
      input.eventPackId
      && currentWorkflow.draft.eventPackId
      && currentWorkflow.draft.eventPackId !== input.eventPackId
    ) {
      throw new ApiError(
        isZh
          ? '该引导已关联另一个 Event Pack；如需更换，请新建引导工作流。'
          : 'This guided workflow already links another Event Pack. Start a new workflow to replace it.',
        422,
        undefined,
        'GUIDED_ARTIFACT_INVALID',
      );
    }
    if (
      input.eventPackBuildId
      && currentWorkflow.draft.eventPackBuildId
      && currentWorkflow.draft.eventPackBuildId !== input.eventPackBuildId
      && builds.some((build) => build.id === currentWorkflow.draft.eventPackBuildId)
    ) {
      throw new ApiError(
        isZh
          ? '该 AI 引导已经关联另一个仍然存在的构建任务。页面不会替换它；请打开原任务，或新建一个 AI 引导。'
          : 'This guided workflow already links another existing build. It will not be replaced; open the linked build or start a new guided workflow.',
        422,
        undefined,
        'GUIDED_ARTIFACT_INVALID',
      );
    }
    // 服务器会重新验证旧构建是否仍存在：仍存在时不可替换；已删除或到期且尚未
    // 物化 Event Pack 时，允许把当前人工审核的新构建修复性关联回来。
    const eventPackBuildId = currentWorkflow.draft.eventPackBuildId === input.eventPackBuildId
      ? undefined
      : input.eventPackBuildId;
    const eventPackId = currentWorkflow.draft.eventPackId ? undefined : input.eventPackId;
    if (!eventPackBuildId && !eventPackId) return;
    const linkedWorkflow = await api.linkGuidedWorkflowArtifacts(currentWorkflow.id, {
      expectedVersion: currentWorkflow.version,
      eventPackBuildId,
      eventPackId,
    });
    setGuidedWorkflow(linkedWorkflow);
    setGuidedLinkState(linkedWorkflow.draft.eventPackId
      ? 'EVENT_PACK'
      : linkedWorkflow.draft.eventPackBuildId
        ? 'BUILD'
        : undefined);
  };

  const createBuild = async (event: FormEvent) => {
    event.preventDefault();
    const title = buildTitle.trim();
    if (title.length < 3) {
      setBuildTitleError(isZh
        ? '内部任务名称至少需要 3 个字符。'
        : 'Internal build title must contain at least 3 characters.');
      focusFactoryTarget('factory-build-title');
      return;
    }
    setBuildTitleError(undefined);
    const linkedBuild = builds.find(
      (build) => build.id === guidedWorkflow?.draft.eventPackBuildId,
    );
    if (guidedHandoff && linkedBuild) {
      const message = isZh
        ? '当前 AI 引导已经关联了一个仍然存在的构建任务。页面已打开该任务；如需从头开始，请新建一个 AI 引导。'
        : 'This guided workflow already links an existing build. That build is now open; start a new guided workflow to begin again.';
      setError(message);
      setActionError({
        action: 'create',
        section: 'general',
        message,
        code: 'GUIDED_ARTIFACT_INVALID',
      });
      await selectBuild(linkedBuild.id);
      focusFactoryTarget('factory-overview-heading');
      return;
    }
    if (guidedHandoff && !window.confirm(isZh
      ? `创建任务“${title}”并将服务器返回的真实任务 ID 关联到当前 AI 引导？关联后，在任务仍存在期间不能用另一任务替换。`
      : `Create build "${title}" and link its server-returned ID to the current AI guidance? While it exists, another build cannot replace it.`)) {
      return;
    }
    await run('create', async () => {
      const build = await api.createFactoryBuild(title);
      setBuilds((current) => [build, ...current]);
      setBuildTitle('');
      setBuildTitleError(undefined);
      setMaterializeTitle(build.title);
      await selectBuild(build.id);
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
      setAcknowledgedReview(false);
      setMaterializeErrors({});
      idempotentAttempts.current.clear();
      window.sessionStorage.removeItem(FACTORY_BUILD_STORAGE_KEY);
      if (!guidedHandoff && remaining[0]) await selectBuild(remaining[0].id);
    });
  };

  const updatePasteDraft = (localId: string, patch: Partial<PasteDraft>) => {
    const currentDraft = pasteDrafts.find((draft) => draft.localId === localId);
    const nextDraft = currentDraft ? { ...currentDraft, ...patch } : undefined;
    setPasteDrafts((current) => current.map((draft) => draft.localId === localId
      ? { ...draft, ...patch }
      : draft));
    if (nextDraft && pasteErrors[localId]) {
      setPasteErrors((currentErrors) => ({
        ...currentErrors,
        [localId]: validatePasteDraft(nextDraft, isZh),
      }));
    }
  };

  const submitPasteSources = async () => {
    if (!snapshot) return;
    const nextPasteErrors = Object.fromEntries(
      pasteDrafts.map((draft) => [draft.localId, validatePasteDraft(draft, isZh)]),
    );
    setPasteErrors(nextPasteErrors);
    const firstInvalidDraft = pasteDrafts.find(
      (draft) => Object.keys(nextPasteErrors[draft.localId]).length > 0,
    );
    if (pasteDrafts.length > remainingSourceSlots || firstInvalidDraft) {
      const message = pasteDrafts.length > remainingSourceSlots
        ? isZh
          ? `当前最多还能加入 ${remainingSourceSlots} 个有效证据来源，请减少本次来源数量。`
          : `This build can accept only ${remainingSourceSlots} more active evidence source(s). Remove sources from this batch.`
        : isZh
          ? '请补全标红字段，并确认 HTTPS 地址和两个时间的先后顺序。'
          : 'Complete the highlighted fields and verify the HTTPS URL and timestamp order.';
      setError(undefined);
      setActionError({
        action: 'paste-validation',
        section: 'paste',
        message,
      });
      if (firstInvalidDraft) {
        const firstField = PASTE_FIELD_ORDER.find(
          (field) => Boolean(nextPasteErrors[firstInvalidDraft.localId][field]),
        );
        if (firstField) {
          focusFactoryTarget(
            `${firstInvalidDraft.localId}-${PASTE_TARGET_SUFFIX[firstField]}`,
          );
        }
      } else {
        focusFactoryTarget('factory-paste-heading');
      }
      return;
    }
    setActionError(undefined);
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
        setPasteErrors({});
      } finally {
        // 批量请求不是事务：即使中途失败，前端也必须恢复服务器上的最新修订号，
        // 否则用户重试会持续触发 revision conflict。
        await refreshSnapshot(snapshot.build.id);
      }
    });
  };

  const search = async (event: FormEvent) => {
    event.preventDefault();
    if (!snapshot || !selectedEngine) return;
    if (!searchQuery.trim()) {
      const message = isZh ? '请先填写检索问题。' : 'Enter a search query first.';
      setSearchQueryError(message);
      setError(undefined);
      setActionError({
        action: 'search-validation',
        section: 'search',
        message,
      });
      focusFactoryTarget('factory-search-query');
      return;
    }
    setSearchQueryError(undefined);
    setActionError(undefined);
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
      JSON.stringify({
        buildId: snapshot.build.id,
        revision: snapshot.build.revision,
        searchInput,
      }),
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

  const setSourceIncluded = async (
    source: EventPackFactorySource,
    included: boolean,
  ) => {
    if (!snapshot) return;
    await run(`selection-${source.id}`, async () => {
      await api.setFactorySourceIncluded(
        snapshot.build.id,
        source.id,
        snapshot.build.revision,
        included,
      );
      await refreshSnapshot(snapshot.build.id);
    });
  };

  const permanentlyDeleteSourceText = async (source: EventPackFactorySource) => {
    if (!snapshot) return;
    await run(`raw-delete-${source.id}`, async () => {
      await api.permanentlyDeleteFactorySourceText(
        snapshot.build.id,
        source.id,
        snapshot.build.revision,
      );
      await refreshSnapshot(snapshot.build.id);
    });
  };

  const readSource = async (source: EventPackFactorySource) => {
    if (!snapshot) return;
    const operation = `reader:${source.id}`;
    const signature = JSON.stringify({
      buildId: snapshot.build.id,
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

  const clearMaterializeError = (field: MaterializeValidationField) => {
    setMaterializeErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  };

  const materialize = async (event: FormEvent) => {
    event.preventDefault();
    if (!snapshot) return;
    const validationErrors: MaterializeValidationErrors = {};
    if (approvedEvidence.length === 0) {
      validationErrors.sourceReview = isZh
        ? '请先在第 3 步至少批准一个粘贴原文或 Reader 全文来源；搜索摘要只能用于发现，不能作为证据。'
        : 'Approve at least one pasted or Reader full-text source in step 3. Search snippets are discovery-only and cannot serve as evidence.';
    } else if (pendingEvidenceSources.length > 0) {
      validationErrors.sourceReview = isZh
        ? `还有 ${pendingEvidenceSources.length} 个当前证据集中的全文来源等待人工批准；不使用时可先从当前证据集排除。`
        : `${pendingEvidenceSources.length} full-text source(s) in the current evidence set still need approval; exclude any source you do not want to use.`;
    }
    if (materializeTitle.trim().length < 3) {
      validationErrors.title = isZh
        ? '英文标题至少需要 3 个字符。'
        : 'English title must contain at least 3 characters.';
    }
    if (summary.trim().length < 8) {
      validationErrors.summary = isZh
        ? '英文研究摘要至少需要 8 个字符。'
        : 'English research summary must contain at least 8 characters.';
    }
    if (!instrument.trim()) {
      validationErrors.instrument = isZh
        ? '请填写研究对象或证券代码。'
        : 'Enter the instrument or research object identifier.';
    }
    if (!asOf || !Number.isFinite(new Date(asOf).getTime())) {
      validationErrors.asOf = isZh
        ? '请选择有效的时点边界。'
        : 'Choose a valid point-in-time cutoff.';
    }
    if (impactChannels.length === 0) {
      validationErrors.impactChannels = isZh
        ? '至少选择一个需要抽取的影响通道。'
        : 'Select at least one impact channel to extract.';
    }
    if (!acknowledgedReview) {
      validationErrors.acknowledgedReview = isZh
        ? '请确认你已经逐个核对所有批准来源。'
        : 'Confirm that you reviewed every approved source.';
    }
    setMaterializeErrors(validationErrors);
    const firstInvalidField = MATERIALIZE_FIELD_ORDER.find(
      (field) => Boolean(validationErrors[field]),
    );
    if (firstInvalidField) {
      const message = isZh
        ? '尚有必填步骤未完成。页面已标红并定位到第一处问题。'
        : 'Required steps are incomplete. The first problem is highlighted and focused.';
      setError(undefined);
      setActionError({
        action: 'materialize-validation',
        section: 'materialize',
        message,
      });
      focusFactoryTarget(MATERIALIZE_TARGETS[firstInvalidField]);
      return;
    }
    const linkedBuild = builds.find(
      (build) => build.id === guidedWorkflow?.draft.eventPackBuildId,
    );
    if (guidedHandoff && linkedBuild && linkedBuild.id !== snapshot.build.id) {
      const message = isZh
        ? `当前 AI 引导仍关联构建任务“${linkedBuild.title}”。请先打开该任务；当前任务不能替换它。`
        : `This guided workflow remains linked to "${linkedBuild.title}". Open that build first; the current build cannot replace it.`;
      setError(undefined);
      setActionError({
        action: 'materialize',
        section: 'materialize',
        message,
        code: 'GUIDED_ARTIFACT_INVALID',
      });
      focusFactoryTarget('factory-overview-heading');
      return;
    }
    setActionError(undefined);
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
      JSON.stringify({
        buildId: snapshot.build.id,
        revision: snapshot.build.revision,
        materializeInput,
      }),
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
    (source) => source.evidenceRole === 'EVIDENCE'
      && source.reviewStatus === 'APPROVED'
      && source.selectionStatus !== 'EXCLUDED',
  ) ?? [];
  const pendingEvidenceSources = snapshot?.sources.filter(
    (source) => source.evidenceRole === 'EVIDENCE'
      && source.reviewStatus === 'PENDING'
      && source.selectionStatus !== 'EXCLUDED',
  ) ?? [];
  const pendingSources = snapshot?.sources.filter((source) => source.reviewStatus === 'PENDING') ?? [];
  const rejectedSources = snapshot?.sources.filter((source) => source.reviewStatus === 'REJECTED') ?? [];
  const excludedSources = snapshot?.sources.filter(
    (source) => source.selectionStatus === 'EXCLUDED' && source.reviewStatus !== 'REJECTED',
  ) ?? [];
  const filteredSources = snapshot?.sources.filter((source) => {
    if (sourceFilter === 'ALL') return true;
    if (sourceFilter === 'EXCLUDED') return source.selectionStatus === 'EXCLUDED';
    if (source.selectionStatus === 'EXCLUDED') return false;
    if (sourceFilter === 'DISCOVERY_CLUES') {
      return source.evidenceRole === 'DISCOVERY_ONLY' && source.reviewStatus === 'PENDING';
    }
    if (sourceFilter === 'AWAITING_READ') {
      return source.evidenceRole === 'DISCOVERY_ONLY' && source.reviewStatus === 'APPROVED';
    }
    if (sourceFilter === 'PENDING_EVIDENCE') {
      return source.evidenceRole === 'EVIDENCE' && source.reviewStatus === 'PENDING';
    }
    return source.evidenceRole === 'EVIDENCE' && source.reviewStatus === 'APPROVED';
  }) ?? [];
  const activeEvidenceCount = snapshot?.sources.filter(
    (source) => source.evidenceRole === 'EVIDENCE' && source.reviewStatus !== 'REJECTED',
  ).length ?? 0;
  const remainingSourceSlots = Math.max(0, MAX_PASTE_SOURCES - activeEvidenceCount);
  const linkedGuidedBuild = builds.find(
    (build) => build.id === guidedWorkflow?.draft.eventPackBuildId,
  );
  const selectedBuildIsGuided = Boolean(
    snapshot && linkedGuidedBuild?.id === snapshot.build.id,
  );
  const evidenceReviewFingerprint = useMemo(
    () => (snapshot?.sources ?? [])
      .filter((source) => source.evidenceRole === 'EVIDENCE')
      .map((source) => `${source.id}:${source.contentHash}:${source.reviewStatus}:${source.selectionStatus}`)
      .sort()
      .join('|'),
    [snapshot?.sources],
  );

  useEffect(() => {
    if (approvedEvidence.length === 0 || pendingEvidenceSources.length > 0) return;
    setMaterializeErrors((current) => {
      if (!current.sourceReview) return current;
      const next = { ...current };
      delete next.sourceReview;
      return next;
    });
  }, [approvedEvidence.length, pendingEvidenceSources.length]);

  useEffect(() => {
    // 来源正文、哈希或审核状态变化后，旧的“我已逐个核对”声明不再成立。
    setAcknowledgedReview(false);
  }, [evidenceReviewFingerprint]);

  useEffect(() => {
    if (
      Object.keys(materializeErrors).length === 0
      && actionError?.action === 'materialize-validation'
    ) {
      setActionError(undefined);
    }
  }, [actionError?.action, materializeErrors]);

  useEffect(() => {
    const hasPasteErrors = Object.values(pasteErrors).some(
      (errors) => Object.keys(errors).length > 0,
    );
    if (!hasPasteErrors && actionError?.action === 'paste-validation') {
      setActionError(undefined);
    }
  }, [actionError?.action, pasteErrors]);

  const renderActionError = (section: FactoryErrorSection) => (
    actionError?.section === section ? (
      <div className="factory-action-error">
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={isZh ? '此步骤尚未完成' : 'This step was not completed'}
          subtitle={actionError.message}
        />
        {actionError.code === 'ZHIPU_TEMPORARY_CREDENTIAL_REQUIRED' ? (
          <Button kind="tertiary" size="sm" onClick={() => navigate('ai')}>
            {isZh ? '前往 AI 配置' : 'Open AI configuration'}
          </Button>
        ) : null}
      </div>
    ) : null
  );

  if (state === 'loading') {
    return <div className="page"><PageHeader title={isZh ? '添加新案例' : 'Add a case'} subtitle={isZh ? '正在恢复构建任务与来源目录。' : 'Restoring builds and source records.'} /><LoadingPanel /></div>;
  }
  if (state === 'error') {
    return <div className="page"><PageHeader title={isZh ? '添加新案例' : 'Add a case'} subtitle={isZh ? '从原始网页文字构建可审核事件包。' : 'Build reviewable Event Packs from raw webpage text.'} /><ErrorPanel detail={error} onRetry={() => void load()} /></div>;
  }

  return (
    <div className="page page--factory">
      <PageHeader
        title={isZh ? '添加新案例' : 'Add a case'}
        subtitle={isZh
          ? '批量粘贴网页原文或使用智谱联网搜索发现候选来源。搜索摘要仅用于发现；只有经全文读取、内容检查和人工批准的来源才能支持事件主张。'
          : 'Paste raw webpage text in batches or use Zhipu web search to discover candidate sources. Search snippets are discovery-only; only full-text, safety-checked, human-approved evidence may support claims.'}
        actions={(
          <Button kind="ghost" renderIcon={ArrowRight} onClick={() => navigate('pack')}>
            {isZh ? '使用手动上传' : 'Use manual upload'}
          </Button>
        )}
      />

      {error && (!actionError || actionError.section === 'general') ? (
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
            kind={guidedLinkState === 'EVENT_PACK'
              ? 'success'
              : guidedLinkState === 'BUILD' && !linkedGuidedBuild
                ? 'warning'
                : 'info'}
            lowContrast
            hideCloseButton
            title={guidedLinkState === 'EVENT_PACK'
              ? isZh ? '真实 Event Pack 已关联回 AI 引导' : 'Real Event Pack linked back to AI guidance'
              : guidedLinkState === 'BUILD'
                ? linkedGuidedBuild
                  ? isZh ? 'AI 引导已有已关联构建任务' : 'The guided workflow already has a linked build'
                  : isZh ? '原已关联构建任务不可用' : 'The previously linked build is unavailable'
              : isZh ? '已载入 AI 引导中的可编辑事件草稿' : 'Editable guided event draft loaded'}
            subtitle={guidedLinkState === 'EVENT_PACK'
              ? isZh
                ? '请继续逐条审核主张；关联动作不会批准主张、冻结事件包或推进工作流。'
                : 'Continue with claim-by-claim review. Linking does not approve claims, freeze the pack, or advance the workflow.'
              : guidedLinkState === 'BUILD'
                ? linkedGuidedBuild
                  ? selectedBuildIsGuided
                    ? isZh
                      ? `当前正在编辑已关联任务“${linkedGuidedBuild.title}”。其他任务不能替换它。`
                      : `You are editing the linked build "${linkedGuidedBuild.title}". Other builds cannot replace it.`
                    : isZh
                      ? `本引导仍关联任务“${linkedGuidedBuild.title}”；当前选中的任务不能替换它。`
                      : `This workflow remains linked to "${linkedGuidedBuild.title}"; the selected build cannot replace it.`
                  : isZh
                    ? '服务器记录的原构建任务已不存在或已到期。只有确认这一状态后，才能显式关联当前任务进行修复。'
                    : 'The server-linked build no longer appears in your build list. Only after confirming that state should you explicitly link the current build as a repair.'
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
              onClick={() => {
                const confirmed = window.confirm(isZh
                  ? `将构建任务“${snapshot.build.title}”关联到当前 AI 引导？关联后，在该任务仍存在期间不能用另一任务替换。`
                  : `Link build "${snapshot.build.title}" to the current AI guidance? While it exists, another build cannot replace it.`);
                if (!confirmed) return;
                void run('guided-link-build', async () => {
                  await linkGuidedArtifact({ eventPackBuildId: snapshot.build.id });
                });
              }}
            >
              {isZh ? '关联当前构建任务' : 'Link current build'}
            </Button>
          ) : null}
          {guidedLinkState === 'BUILD' && linkedGuidedBuild && !selectedBuildIsGuided ? (
            <Button
              kind="tertiary"
              size="sm"
              disabled={Boolean(busyAction)}
              onClick={() => void run('select-build', () => selectBuild(linkedGuidedBuild.id))}
            >
              {isZh ? '打开已关联构建任务' : 'Open linked build'}
            </Button>
          ) : null}
          {guidedLinkState === 'BUILD' && selectedBuildIsGuided && snapshot ? (
            <Button
              kind="danger--ghost"
              size="sm"
              disabled={Boolean(busyAction)}
              onClick={() => void deleteBuild()}
            >
              {isZh ? '删除已关联草稿并重新开始' : 'Delete linked draft and start over'}
            </Button>
          ) : null}
          {guidedLinkState === 'BUILD' && !linkedGuidedBuild && snapshot && !pendingGuidedPack ? (
            <Button
              kind="danger--tertiary"
              size="sm"
              disabled={Boolean(busyAction)}
              onClick={() => {
                const confirmed = window.confirm(isZh
                  ? `服务器中的原关联任务已不可用。确认用“${snapshot.build.title}”修复当前引导关联？`
                  : `The previously linked build is unavailable. Repair this guidance link with "${snapshot.build.title}"?`);
                if (!confirmed) return;
                void run('guided-link-build', () => linkGuidedArtifact({
                  eventPackBuildId: snapshot.build.id,
                }));
              }}
            >
              {isZh ? '用当前任务修复关联' : 'Repair link with current build'}
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
          ? '联网检索和网页读取可能产生供应商费用，并可能遗漏、延迟或错误。应用会拒绝明显的本地、私网及非 HTTPS 地址，但 Reader 的目标 DNS、网络连接和网页重定向由智谱执行，本应用无法固定或逐跳复核供应商连接。Reader 价格也尚未在本项目中核实。请勿提交秘密或个人信息，并务必打开原网页核对 Reader 返回的来源身份和正文。'
          : 'Search and Reader calls may incur provider charges and may be incomplete, delayed, or wrong. The application blocks obvious local, private-network and non-HTTPS addresses, but Zhipu performs target DNS resolution, network access and webpage redirects; this application cannot pin or revalidate those provider-side hops. Reader pricing is also unverified. Do not submit secrets or personal data, and open the original page to verify the returned source identity and text.'}
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
              invalid={Boolean(buildTitleError)}
              invalidText={buildTitleError}
              onChange={(event) => {
                const value = event.target.value;
                setBuildTitle(value);
                if (value.trim().length >= 3) setBuildTitleError(undefined);
              }}
            />
            <Button type="submit" size="sm" renderIcon={Plus} disabled={Boolean(busyAction)}>
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
                onClick={() => void run('select-build', () => selectBuild(build.id))}
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
                    <h2 id="factory-paste-heading" tabIndex={-1}>{isZh ? '1. 批量粘贴网页原文' : '1. Paste webpage text in batches'}</h2>
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
                {renderActionError('paste')}
                <div className="factory-paste-list">
                  {pasteDrafts.map((draft, index) => (
                    <fieldset
                      key={draft.localId}
                      className={`factory-paste-source${Object.keys(pasteErrors[draft.localId] ?? {}).length > 0 ? ' is-invalid' : ''}`}
                      aria-invalid={Object.keys(pasteErrors[draft.localId] ?? {}).length > 0}
                    >
                      <legend>{isZh ? `来源 ${index + 1}` : `Source ${index + 1}`}</legend>
                      <div className="factory-form-grid">
                        <TextInput id={`${draft.localId}-title`} labelText={isZh ? '网页标题' : 'Page title'} value={draft.title} invalid={Boolean(pasteErrors[draft.localId]?.title)} invalidText={pasteErrors[draft.localId]?.title} onChange={(event) => updatePasteDraft(draft.localId, { title: event.target.value })} />
                        <TextInput id={`${draft.localId}-publisher`} labelText={isZh ? '发布方' : 'Publisher'} value={draft.publisher} invalid={Boolean(pasteErrors[draft.localId]?.publisher)} invalidText={pasteErrors[draft.localId]?.publisher} onChange={(event) => updatePasteDraft(draft.localId, { publisher: event.target.value })} />
                        <TextInput id={`${draft.localId}-url`} type="url" labelText={isZh ? 'HTTPS 网页地址（可选）' : 'HTTPS page URL (optional)'} value={draft.url} invalid={Boolean(pasteErrors[draft.localId]?.url)} invalidText={pasteErrors[draft.localId]?.url} onChange={(event) => updatePasteDraft(draft.localId, { url: event.target.value })} />
                        <TextInput id={`${draft.localId}-published`} type="datetime-local" labelText={isZh ? '发布时间' : 'Published at'} value={draft.publishedAt} invalid={Boolean(pasteErrors[draft.localId]?.publishedAt)} invalidText={pasteErrors[draft.localId]?.publishedAt} onChange={(event) => updatePasteDraft(draft.localId, { publishedAt: event.target.value })} />
                        <TextInput id={`${draft.localId}-known`} type="datetime-local" labelText={isZh ? '研究中可见时间' : 'Known at'} value={draft.knownAt} invalid={Boolean(pasteErrors[draft.localId]?.knownAt)} invalidText={pasteErrors[draft.localId]?.knownAt} onChange={(event) => updatePasteDraft(draft.localId, { knownAt: event.target.value })} />
                      </div>
                      <TextArea
                        id={`${draft.localId}-raw`}
                        labelText={isZh ? '网页原文' : 'Raw webpage text'}
                        value={draft.rawText}
                        maxCount={100_000}
                        enableCounter
                        rows={8}
                        invalid={Boolean(pasteErrors[draft.localId]?.rawText)}
                        invalidText={pasteErrors[draft.localId]?.rawText}
                        onChange={(event) => updatePasteDraft(draft.localId, { rawText: event.target.value })}
                      />
                      {pasteDrafts.length > 1 ? (
                        <Button kind="danger--ghost" size="sm" renderIcon={Trash} onClick={() => {
                          setPasteDrafts((current) => current.filter((item) => item.localId !== draft.localId));
                          setPasteErrors((current) => {
                            const next = { ...current };
                            delete next[draft.localId];
                            return next;
                          });
                        }}>
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
                {renderActionError('search')}
                <form className="factory-search-form" onSubmit={(event) => void search(event)}>
                  <TextInput
                    id="factory-search-query"
                    labelText={isZh ? '检索问题' : 'Search query'}
                    value={searchQuery}
                    maxLength={70}
                    invalid={Boolean(searchQueryError)}
                    invalidText={searchQueryError}
                    onChange={(event) => {
                      const value = event.target.value;
                      setSearchQuery(value);
                      if (value.trim()) {
                        setSearchQueryError(undefined);
                        if (actionError?.action === 'search-validation') {
                          setActionError(undefined);
                        }
                      }
                    }}
                  />
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
                  <Button type="submit" renderIcon={MagnifyingGlass} disabled={Boolean(busyAction)}>
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

              <section
                className={`factory-section${materializeErrors.sourceReview ? ' factory-section--invalid' : ''}`}
                aria-labelledby="factory-review-heading"
                aria-invalid={Boolean(materializeErrors.sourceReview)}
                aria-describedby={materializeErrors.sourceReview
                  ? 'factory-source-review-error'
                  : undefined}
              >
                <header className="section-heading">
                  <div>
                    <h2 id="factory-review-heading" tabIndex={-1}>{isZh ? '3. 逐个审核来源' : '3. Review every source'}</h2>
                    <p>{isZh
                      ? '先允许 Reader 读取搜索线索的全文；这不是证据批准。Reader 返回的全文会成为新的待审核证据，旧线索无需逐个拒绝。'
                      : 'Allow Reader to retrieve a discovery result; this is not evidence approval. The returned full text becomes a separate pending evidence item, and old clues do not need to be rejected.'}</p>
                  </div>
                  <Button kind="ghost" size="sm" renderIcon={ArrowClockwise} disabled={Boolean(busyAction)} onClick={() => void refreshSnapshot(snapshot.build.id)}>
                    {isZh ? '刷新' : 'Refresh'}
                  </Button>
                </header>
                {materializeErrors.sourceReview ? (
                  <InlineNotification
                    id="factory-source-review-error"
                    kind="error"
                    lowContrast
                    hideCloseButton
                    title={isZh ? '来源审核尚未完成' : 'Source review is incomplete'}
                    subtitle={materializeErrors.sourceReview}
                  />
                ) : null}
                {renderActionError('review')}
                <ol className="factory-source-chain" aria-label={isZh ? '来源转换链' : 'Source conversion chain'}>
                  <li><strong>{isZh ? '搜索线索' : 'Search clue'}</strong><span>{isZh ? '仅用于发现' : 'Discovery only'}</span></li>
                  <li><strong>{isZh ? '允许读取' : 'Read allowed'}</strong><span>{isZh ? '授权 Reader 获取全文' : 'Authorizes Reader retrieval'}</span></li>
                  <li><strong>{isZh ? '全文证据' : 'Full-text evidence'}</strong><span>{isZh ? '独立扫描与人工审核' : 'Separate scan and human review'}</span></li>
                  <li><strong>{isZh ? '批准证据' : 'Approved evidence'}</strong><span>{isZh ? '才可支持候选主张' : 'May support candidate claims'}</span></li>
                  <li><strong>{isZh ? '候选主张' : 'Candidate claim'}</strong><span>{isZh ? '仍需事件包审核' : 'Still requires Event Pack review'}</span></li>
                </ol>
                <div className="factory-source-filter">
                  <Select
                    id="factory-source-filter"
                    labelText={isZh ? '按来源状态筛选' : 'Filter by source status'}
                    value={sourceFilter}
                    onChange={(event) => setSourceFilter(event.target.value as FactorySourceFilter)}
                  >
                    <SelectItem value="ALL" text={isZh ? `全部（${snapshot.sources.length}）` : `All (${snapshot.sources.length})`} />
                    <SelectItem value="DISCOVERY_CLUES" text={isZh ? '发现线索' : 'Discovery clues'} />
                    <SelectItem value="AWAITING_READ" text={isZh ? '等待读取全文' : 'Awaiting full-text read'} />
                    <SelectItem value="PENDING_EVIDENCE" text={isZh ? '待审核证据' : 'Pending evidence'} />
                    <SelectItem value="APPROVED_EVIDENCE" text={isZh ? '已批准证据' : 'Approved evidence'} />
                    <SelectItem value="EXCLUDED" text={isZh ? `已排除（${excludedSources.length}）` : `Excluded (${excludedSources.length})`} />
                  </Select>
                </div>
                {snapshot.sources.length === 0 ? (
                  <EmptyState title={isZh ? '还没有来源' : 'No sources yet'} body={isZh ? '从上方粘贴原文或执行一次联网搜索。' : 'Paste source text or run a web search above.'} />
                ) : (
                  <div className="factory-source-list">
                    {filteredSources.map((source) => (
                      <SourceCard
                        key={source.id}
                        source={source}
                        isZh={isZh}
                        busy={Boolean(busyAction)}
                        readerEvidenceExists={snapshot.sources.some(
                          (candidate) => candidate.parentSourceId === source.id,
                        )}
                        onReview={(item, status) => void review(item, status)}
                        onSelection={(item, included) => void setSourceIncluded(item, included)}
                        onPermanentDelete={(item) => void permanentlyDeleteSourceText(item)}
                        onReader={(item) => void readSource(item)}
                        onLoadRawText={loadRawText}
                        onSaveRawText={saveRawText}
                      />
                    ))}
                  </div>
                )}
                {rejectedSources.length > 0 ? (
                  <p className="factory-rejected-note">{isZh
                    ? `${rejectedSources.length} 个来源的原文已永久删除；审计历史只保留删除事实。`
                    : `${rejectedSources.length} source text payload(s) were permanently deleted; audit retains only the deletion event.`}</p>
                ) : null}
                <aside id="factory-data-handling" className="factory-data-handling">
                  <strong>{isZh ? '排除与删除是两种不同操作' : 'Exclusion and deletion are different actions'}</strong>
                  <p>{isZh
                    ? '“从当前证据集排除”保留原文、安全摘要与审核历史，可随时重新加入；“永久删除原文”不可撤销，只保留哈希、长度和审计事件。所有未物化构建仍受页面所示计划清理时间约束。'
                    : 'Excluding from the current evidence set retains raw text, safety metadata, and review history so the source can be restored. Permanently deleting raw text is irreversible and retains only hash, length, and the audit event. Unmaterialized builds remain subject to the displayed scheduled-deletion time.'}</p>
                </aside>
              </section>

              <section className="factory-section factory-materialize" aria-labelledby="factory-materialize-heading">
                <header className="section-heading">
                  <div>
                    <h2 id="factory-materialize-heading">{isZh ? '4. 生成待审核 Event Pack' : '4. Materialize a reviewable Event Pack'}</h2>
                    <p>{isZh
                      ? '此操作只生成候选主张，不会批准主张或冻结事件包。生成后必须在“事件包审核”中逐条编辑、批准或拒绝。'
                      : 'This only generates candidate claims. It does not approve claims or freeze the Event Pack. Edit, approve, or reject every claim in Event Pack Review afterward.'}</p>
                  </div>
                  <div className={`factory-evidence-ready${materializeErrors.sourceReview ? ' is-invalid' : ''}`}>
                    <ShieldCheck size={21} aria-hidden="true" />
                    <span>{isZh ? `${approvedEvidence.length} 个已批准证据来源` : `${approvedEvidence.length} approved evidence source(s)`}</span>
                  </div>
                </header>
                {renderActionError('materialize')}
                {Object.keys(materializeErrors).length > 0 ? (
                  <div className="factory-validation-summary" role="alert">
                    <strong>{isZh ? '完成以下项目后才能生成 Event Pack：' : 'Complete these items before generating the Event Pack:'}</strong>
                    <ul>
                      {MATERIALIZE_FIELD_ORDER.flatMap((field) => {
                        const message = materializeErrors[field];
                        if (!message) return [];
                        return [(
                          <li key={field}>
                            <button
                              type="button"
                              onClick={() => focusFactoryTarget(MATERIALIZE_TARGETS[field])}
                            >
                              {message}
                            </button>
                          </li>
                        )];
                      })}
                    </ul>
                  </div>
                ) : null}
                <form onSubmit={(event) => void materialize(event)}>
                  <div className="factory-form-grid">
                    <TextInput
                      id="factory-pack-title"
                      labelText={isZh ? '英文标题' : 'English title'}
                      value={materializeTitle}
                      maxLength={200}
                      invalid={Boolean(materializeErrors.title)}
                      invalidText={materializeErrors.title}
                      onChange={(event) => {
                        const value = event.target.value;
                        setMaterializeTitle(value);
                        if (value.trim().length >= 3) clearMaterializeError('title');
                      }}
                    />
                    <TextInput id="factory-pack-title-zh" labelText={isZh ? '中文标题（可选）' : 'Chinese title (optional)'} value={materializeTitleZh} maxLength={200} onChange={(event) => setMaterializeTitleZh(event.target.value)} />
                    <TextArea
                      id="factory-pack-summary"
                      labelText={isZh ? '英文研究摘要' : 'English research summary'}
                      value={summary}
                      maxCount={1_000}
                      enableCounter
                      invalid={Boolean(materializeErrors.summary)}
                      invalidText={materializeErrors.summary}
                      onChange={(event) => {
                        const value = event.target.value;
                        setSummary(value);
                        if (value.trim().length >= 8) clearMaterializeError('summary');
                      }}
                    />
                    <TextArea id="factory-pack-summary-zh" labelText={isZh ? '中文研究摘要（可选）' : 'Chinese research summary (optional)'} value={summaryZh} maxCount={1_000} enableCounter onChange={(event) => setSummaryZh(event.target.value)} />
                    <TextInput
                      id="factory-pack-instrument"
                      labelText={isZh ? '研究对象或证券代码' : 'Instrument or research object'}
                      value={instrument}
                      maxLength={32}
                      invalid={Boolean(materializeErrors.instrument)}
                      invalidText={materializeErrors.instrument}
                      onChange={(event) => {
                        const value = event.target.value.toUpperCase();
                        setInstrument(value);
                        if (value.trim()) clearMaterializeError('instrument');
                      }}
                    />
                    {instrument.trim() ? (
                      <div className="synthetic-instrument-note">
                        <SyntheticInstrumentLabel instrument={instrument} />
                        <span>{isZh
                          ? '该对象进入实验后只作为合成市场代理；来源事实仍可指向真实实体，但模拟价格不是现实行情。'
                          : 'In experiments this object is only a synthetic market proxy. Sources may describe a real entity, but simulated prices are not real market data.'}</span>
                      </div>
                    ) : null}
                    <TextInput
                      id="factory-pack-asof"
                      type="datetime-local"
                      labelText={isZh ? '时点边界 (asOf)' : 'Point-in-time cutoff (asOf)'}
                      value={asOf}
                      invalid={Boolean(materializeErrors.asOf)}
                      invalidText={materializeErrors.asOf}
                      onChange={(event) => {
                        const value = event.target.value;
                        setAsOf(value);
                        if (value && Number.isFinite(new Date(value).getTime())) {
                          clearMaterializeError('asOf');
                        }
                      }}
                    />
                    <NumberInput id="factory-maximum-claims" label={isZh ? '最多候选主张' : 'Maximum candidate claims'} min={1} max={50} value={maximumClaims} onChange={(_event, stateValue) => setMaximumClaims(Math.max(1, Math.min(50, Number(stateValue.value) || 16)))} />
                  </div>
                  <fieldset
                    id="factory-impact-channels"
                    className={`factory-impact-channels${materializeErrors.impactChannels ? ' is-invalid' : ''}`}
                    aria-invalid={Boolean(materializeErrors.impactChannels)}
                    aria-describedby={materializeErrors.impactChannels
                      ? 'factory-impact-channels-error'
                      : undefined}
                    tabIndex={-1}
                  >
                    <legend>{isZh ? '需要抽取的影响通道' : 'Impact channels to extract'}</legend>
                    {IMPACT_CHANNEL_DEFINITIONS.map(({ id: channel }) => {
                      const display = impactChannelDisplay(channel, language);
                      return (
                        <Checkbox
                          key={channel}
                          id={`factory-impact-${channel}`}
                          labelText={(
                            <span className="factory-impact-channel-label">
                              <strong>{display.name}</strong>
                              <small>{display.description}</small>
                            </span>
                          )}
                          checked={impactChannels.includes(channel)}
                          onChange={(_event, stateValue) => {
                            setImpactChannels((current) => stateValue.checked
                              ? [...current, channel]
                              : current.filter((item) => item !== channel));
                            if (stateValue.checked) clearMaterializeError('impactChannels');
                          }}
                        />
                      );
                    })}
                    {materializeErrors.impactChannels ? (
                      <p id="factory-impact-channels-error" className="factory-field-error">
                        {materializeErrors.impactChannels}
                      </p>
                    ) : null}
                  </fieldset>
                  <div className={`factory-review-acknowledgement${materializeErrors.acknowledgedReview ? ' is-invalid' : ''}`}>
                    <Checkbox
                      id="factory-acknowledge-review"
                      labelText={isZh
                        ? '我已逐个打开并核对所有批准来源，确认其中不含秘密、无关个人信息或未处理的恶意指令；我理解搜索和 AI 输出可能错误。'
                        : 'I opened and reviewed every approved source, confirmed it contains no secrets, unnecessary personal data, or unhandled malicious instructions, and understand that search and AI output may be wrong.'}
                      checked={acknowledgedReview}
                      aria-describedby={materializeErrors.acknowledgedReview
                        ? 'factory-acknowledge-review-error'
                        : undefined}
                      onChange={(_event, stateValue) => {
                        setAcknowledgedReview(stateValue.checked);
                        if (stateValue.checked) clearMaterializeError('acknowledgedReview');
                      }}
                    />
                    {materializeErrors.acknowledgedReview ? (
                      <p id="factory-acknowledge-review-error" className="factory-field-error">
                        {materializeErrors.acknowledgedReview}
                      </p>
                    ) : null}
                  </div>
                  <Button
                    type="submit"
                    renderIcon={ArrowRight}
                    disabled={Boolean(busyAction)}
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
