import {
  Button,
  InlineNotification,
  Modal,
  NumberInput,
  Select,
  SelectItem,
  TextArea,
  TextInput,
  Toggle,
} from '@carbon/react';
import { FilePlus, Trash } from '@phosphor-icons/react';
import { useState } from 'react';
import type { EventPack, EventPackCreateInput, EventSourceUpload } from '../api/types';
import { useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';

interface SourceDraft {
  localId: string;
  title: string;
  publisher: string;
  url: string;
  sourceType: EventSourceUpload['sourceType'];
  publishedAt: string;
  knownAt: string;
  rawText: string;
  fileName: string;
}

function localDateTimeNow(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function toLocalDateTime(value?: string): string {
  if (!value) return localDateTimeNow();
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return localDateTimeNow();
  return new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function createSourceDraft(index: number, defaultDateTime = localDateTimeNow()): SourceDraft {
  return {
    localId: `source-draft-${Date.now().toString(36)}-${index}`,
    title: '',
    publisher: '',
    url: '',
    sourceType: 'OFFICIAL',
    publishedAt: defaultDateTime,
    knownAt: defaultDateTime,
    rawText: '',
    fileName: '',
  };
}

function sourceIdFromTitle(title: string, index: number): string {
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48);
  return `source-${slug || 'upload'}-${Date.now().toString(36)}-${index + 1}`;
}

export function EventPackUploadModal({
  open,
  onClose,
  existingEventPack,
}: {
  open: boolean;
  onClose: () => void;
  existingEventPack?: EventPack;
}) {
  const { language } = useI18n();
  const isZh = language === 'zh-CN';
  const { createEventPack, reextractEventPack } = useWorkflow();
  const isReextract = Boolean(existingEventPack);
  const [title, setTitle] = useState('');
  const [titleZh, setTitleZh] = useState('');
  const [summary, setSummary] = useState('');
  const [summaryZh, setSummaryZh] = useState('');
  const [instrument, setInstrument] = useState('SPCX');
  const [asOf, setAsOf] = useState(() => toLocalDateTime(existingEventPack?.pointInTime));
  const [useLlm, setUseLlm] = useState(true);
  const [maximumClaims, setMaximumClaims] = useState(16);
  const [acknowledgedContentReview, setAcknowledgedContentReview] = useState(false);
  const [sources, setSources] = useState<SourceDraft[]>(() => [createSourceDraft(0, toLocalDateTime(existingEventPack?.pointInTime))]);
  const [activeSourceId, setActiveSourceId] = useState(() => sources[0]?.localId ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const activeSource = sources.find((source) => source.localId === activeSourceId) ?? sources[0];

  const reset = () => {
    const cutoffDateTime = toLocalDateTime(existingEventPack?.pointInTime);
    const firstSource = createSourceDraft(0, cutoffDateTime);
    setTitle('');
    setTitleZh('');
    setSummary('');
    setSummaryZh('');
    setInstrument('SPCX');
    setAsOf(cutoffDateTime);
    setUseLlm(true);
    setMaximumClaims(16);
    setAcknowledgedContentReview(false);
    setSources([firstSource]);
    setActiveSourceId(firstSource.localId);
    setError(undefined);
  };

  const close = () => {
    if (busy) return;
    onClose();
  };

  const updateSource = (partial: Partial<SourceDraft>) => {
    setSources((current) => current.map((source) => source.localId === activeSource?.localId ? { ...source, ...partial } : source));
  };

  const addSource = () => {
    if (sources.length >= 8) return;
    const nextSource = createSourceDraft(sources.length, asOf || localDateTimeNow());
    setSources((current) => [...current, nextSource]);
    setActiveSourceId(nextSource.localId);
  };

  const removeSource = () => {
    if (!activeSource || sources.length <= 1) return;
    const activeIndex = sources.findIndex((source) => source.localId === activeSource.localId);
    const nextSources = sources.filter((source) => source.localId !== activeSource.localId);
    setSources(nextSources);
    setActiveSourceId(nextSources[Math.max(0, activeIndex - 1)]?.localId ?? nextSources[0].localId);
  };

  const readFile = async (file?: File) => {
    setError(undefined);
    if (!file || !activeSource) return;
    if (file.size > 50_000) {
      setError(isZh ? '单个文本文件不能超过 50 KB。' : 'A text file cannot exceed 50 KB.');
      return;
    }
    const text = await file.text();
    updateSource({
      rawText: text,
      fileName: file.name,
      title: activeSource.title || file.name.replace(/\.[^.]+$/, '').slice(0, 200),
    });
  };

  const sourceIsValid = (source: SourceDraft) => source.title.trim().length >= 3
    && source.publisher.trim().length > 0
    && source.rawText.trim().length >= 20
    && new Date(source.publishedAt).getTime() <= new Date(source.knownAt).getTime()
    && new Date(source.knownAt).getTime() <= new Date(asOf).getTime();
  const valid = (isReextract || (title.trim().length >= 3
    && summary.trim().length >= 8
    && instrument.trim().length > 0))
    && sources.length >= 1
    && sources.length <= 8
    && sources.every(sourceIsValid);

  const submit = async () => {
    if (!valid) {
      setError(isZh
        ? '请填写事件包和每个来源的必填字段，并确保 publishedAt 不晚于 knownAt，knownAt 不晚于 asOf。'
        : 'Complete the Event Pack and every source, with publishedAt at or before knownAt and knownAt at or before asOf.');
      return;
    }
    setBusy(true);
    setError(undefined);
    const normalizedSources: EventSourceUpload[] = sources.map((source, index) => ({
      sourceId: sourceIdFromTitle(source.title, index),
      title: source.title.trim(),
      publisher: source.publisher.trim(),
      url: source.url.trim() || undefined,
      sourceType: source.sourceType,
      publishedAt: new Date(source.publishedAt).toISOString(),
      knownAt: new Date(source.knownAt).toISOString(),
      rawText: source.rawText.trim(),
    }));
    const input: EventPackCreateInput = {
      title: title.trim(),
      titleZh: titleZh.trim() || undefined,
      summary: summary.trim(),
      summaryZh: summaryZh.trim() || undefined,
      asOf: new Date(asOf).toISOString(),
      instrument: instrument.trim(),
      sources: normalizedSources,
      acknowledgedContentReview,
    };
    try {
      if (isReextract) {
        await reextractEventPack(
          normalizedSources,
          useLlm,
          maximumClaims,
          acknowledgedContentReview,
        );
      }
      else await createEventPack(input);
      reset();
      onClose();
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : String(submitError));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      modalHeading={isReextract
        ? isZh ? '重新抽取候选主张' : 'Re-extract candidate claims'
        : isZh ? '从来源文本创建 Event Pack' : 'Create Event Pack from source text'}
      modalLabel={isZh ? '证据抽取' : 'Evidence extraction'}
      primaryButtonText={busy
        ? isZh ? '处理中' : 'Processing'
        : isReextract
          ? isZh ? '替换候选主张' : 'Replace candidate claims'
          : isZh ? '创建并提取候选主张' : 'Create and extract candidates'}
      secondaryButtonText={isZh ? '取消' : 'Cancel'}
      primaryButtonDisabled={!valid || busy}
      preventCloseOnClickOutside
      onRequestClose={close}
      onSecondarySubmit={close}
      onRequestSubmit={() => void submit()}
      size="lg"
    >
      <p className="modal-help">
        {isZh
          ? '上传内容被视为不可信数据。完整 raw source document 不落盘；系统保存来源元数据、内容哈希，以及从原文抽取的短候选 claim 文本，供人工审核与冻结。已配置智谱 API 时使用结构化 LLM 抽取，否则明确使用规则抽取。'
          : 'Uploads are treated as untrusted data. The full raw source document is not persisted. The system stores source metadata, a content hash, and short candidate claim text extracted for human review and freezing. A configured Zhipu API uses structured LLM extraction; otherwise extraction explicitly falls back to rules.'}
      </p>
      {error ? (
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={isZh ? '无法创建 Event Pack' : 'Event Pack could not be created'}
          subtitle={error}
        />
      ) : null}

      {!isReextract ? <section className="upload-pack-fields" aria-labelledby="upload-pack-heading">
        <h3 id="upload-pack-heading">{isZh ? '事件包' : 'Event Pack'}</h3>
        <div className="upload-form-grid">
          <TextInput id="upload-pack-title" labelText={isZh ? '英文标题' : 'English title'} value={title} maxLength={200} onChange={(event) => setTitle(event.target.value)} />
          <TextInput id="upload-pack-title-zh" labelText={isZh ? '中文标题（可选）' : 'Chinese title (optional)'} value={titleZh} maxLength={200} onChange={(event) => setTitleZh(event.target.value)} />
          <TextArea id="upload-pack-summary" labelText={isZh ? '英文研究摘要' : 'English research summary'} value={summary} maxCount={1_000} enableCounter onChange={(event) => setSummary(event.target.value)} />
          <TextArea id="upload-pack-summary-zh" labelText={isZh ? '中文研究摘要（可选）' : 'Chinese research summary (optional)'} value={summaryZh} maxCount={1_000} enableCounter onChange={(event) => setSummaryZh(event.target.value)} />
          <TextInput id="upload-instrument" labelText={isZh ? '证券代码' : 'Instrument symbol'} value={instrument} maxLength={32} onChange={(event) => setInstrument(event.target.value.toUpperCase())} />
          <TextInput id="upload-as-of" type="datetime-local" labelText={isZh ? '事件包截止时间 (asOf)' : 'Event Pack cutoff (asOf)'} value={asOf} onChange={(event) => setAsOf(event.target.value)} />
        </div>
      </section> : (
        <section className="upload-pack-fields" aria-labelledby="reextract-settings-heading">
          <h3 id="reextract-settings-heading">{isZh ? '抽取设置' : 'Extraction settings'}</h3>
          <p className="modal-help">{isZh
            ? `正在为 ${existingEventPack?.nameZh ?? existingEventPack?.name ?? ''} 重新提供来源原文。现有原文未被服务器保留。`
            : `Provide source text again for ${existingEventPack?.name ?? ''}. The previous raw documents were not retained by the server.`}</p>
          <div className="upload-form-grid">
            <Toggle id="reextract-use-llm" labelText={isZh ? '使用已配置的智谱结构化抽取' : 'Use configured Zhipu structured extraction'} labelA={isZh ? '规则' : 'Rules'} labelB={isZh ? '智谱' : 'Zhipu'} toggled={useLlm} onToggle={setUseLlm} />
            <NumberInput id="reextract-maximum-claims" label={isZh ? '最多候选主张' : 'Maximum candidate claims'} min={1} max={50} step={1} value={maximumClaims} onChange={(_event, state) => { const value = Number(state.value); if (Number.isFinite(value)) setMaximumClaims(Math.max(1, Math.min(50, Math.round(value)))); }} />
          </div>
        </section>
      )}

      <section className="upload-source-fields" aria-labelledby="upload-source-heading">
        <div className="source-editor-heading">
          <div><h3 id="upload-source-heading">{isZh ? '来源文档' : 'Source documents'}</h3><p>{isZh ? '支持 1 至 8 个来源。每个来源独立记录发布时间、可见时间和哈希。' : 'Add 1 to 8 sources. Each source keeps its own publication time, known time, and hash.'}</p></div>
          <div>
            <Button kind="ghost" size="sm" renderIcon={FilePlus} disabled={sources.length >= 8} onClick={addSource}>{isZh ? '添加来源' : 'Add source'}</Button>
            <Button kind="danger--ghost" size="sm" renderIcon={Trash} disabled={sources.length <= 1} onClick={removeSource}>{isZh ? '删除当前来源' : 'Remove current'}</Button>
          </div>
        </div>
        <div className="source-editor-tabs" role="tablist" aria-label={isZh ? '来源文档' : 'Source documents'}>
          {sources.map((source, index) => (
            <button
              key={source.localId}
              type="button"
              role="tab"
              aria-selected={source.localId === activeSource?.localId}
              className={source.localId === activeSource?.localId ? 'is-active' : ''}
              onClick={() => setActiveSourceId(source.localId)}
            >
              <span>{index + 1}</span>{source.title || (isZh ? '未命名来源' : 'Untitled source')}
            </button>
          ))}
        </div>

        {activeSource ? (
          <div className="source-editor-panel" role="tabpanel">
            <div className="upload-form-grid">
              <TextInput id="upload-source-title" labelText={isZh ? '来源标题' : 'Source title'} value={activeSource.title} maxLength={200} onChange={(event) => updateSource({ title: event.target.value })} />
              <TextInput id="upload-publisher" labelText={isZh ? '发布者' : 'Publisher'} value={activeSource.publisher} maxLength={200} onChange={(event) => updateSource({ publisher: event.target.value })} />
              <TextInput id="upload-source-url" type="url" labelText={isZh ? '来源 URL（可选）' : 'Source URL (optional)'} value={activeSource.url} maxLength={2_000} onChange={(event) => updateSource({ url: event.target.value })} />
              <Select id="upload-source-type" labelText={isZh ? '来源类型' : 'Source type'} value={activeSource.sourceType} onChange={(event) => updateSource({ sourceType: event.target.value as EventSourceUpload['sourceType'] })}>
                <SelectItem value="OFFICIAL" text={isZh ? '官方来源' : 'Official source'} />
                <SelectItem value="REPORTING" text={isZh ? '新闻报道' : 'Reporting'} />
                <SelectItem value="ESTIMATE" text={isZh ? '具名估计' : 'Attributed estimate'} />
                <SelectItem value="USER_PROVIDED" text={isZh ? '用户提供' : 'User provided'} />
              </Select>
              <TextInput id="upload-published-at" type="datetime-local" labelText={isZh ? '发布时间 (publishedAt)' : 'Publication time (publishedAt)'} value={activeSource.publishedAt} onChange={(event) => updateSource({ publishedAt: event.target.value })} />
              <TextInput id="upload-known-at" type="datetime-local" labelText={isZh ? '用户可见时间 (knownAt)' : 'User-visible time (knownAt)'} value={activeSource.knownAt} onChange={(event) => updateSource({ knownAt: event.target.value })} />
              <label className="native-file-field" htmlFor="event-source-file">
                <span>{isZh ? '文本文件（TXT、MD 或 JSON）' : 'Text file (TXT, MD, or JSON)'}</span>
                <input id="event-source-file" key={activeSource.localId} type="file" accept=".txt,.md,.json,text/plain,text/markdown,application/json" onChange={(event) => void readFile(event.target.files?.[0])} />
              </label>
            </div>
            <TextArea
              id="upload-source-text"
              labelText={isZh ? '来源原文' : 'Source text'}
              helperText={isZh ? '最多 50,000 字符，可以粘贴或从文件读取。' : 'Up to 50,000 characters. Paste text or load a file.'}
              value={activeSource.rawText}
              maxCount={50_000}
              enableCounter
              rows={9}
              onChange={(event) => updateSource({ rawText: event.target.value })}
            />
          </div>
        ) : null}
        <label className="confirmation-row upload-security-acknowledgement">
          <input
            type="checkbox"
            checked={acknowledgedContentReview}
            onChange={(event) => setAcknowledgedContentReview(event.target.checked)}
          />
          <span aria-hidden="true" />
          <strong>{isZh
            ? '如果安全扫描仅要求人工复核，我确认这些来源会继续按不可信数据处理；密钥、可执行内容等高风险命中仍会被阻断。'
            : 'If the safety scan requires review, I acknowledge that these sources remain untrusted data. Credentials and executable content are still blocked.'}</strong>
        </label>
      </section>
    </Modal>
  );
}
