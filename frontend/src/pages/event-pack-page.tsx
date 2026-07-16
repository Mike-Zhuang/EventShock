import { Button, InlineNotification, Modal, Tag, TextArea } from '@carbon/react';
import {
  ArrowRight,
  Check,
  FileText,
  Link as LinkIcon,
  LockKey,
  PencilSimple,
  UploadSimple,
  X,
} from '@phosphor-icons/react';
import { useMemo, useState } from 'react';
import type { ViewId } from '../app';
import { EmptyState, ErrorPanel, LoadingPanel, PageHeader, StatusBadge } from '../components/common';
import { useI18n } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import type { EventClaim } from '../api/types';
import { EventPackUploadModal } from '../components/event-pack-upload-modal';

export function EventPackPage({ navigate }: { navigate: (view: ViewId) => void }) {
  const { language, t } = useI18n();
  const {
    eventPack,
    eventPackState,
    eventPackError,
    claimBusyId,
    reviewClaim,
    freezeEventPack,
  } = useWorkflow();
  const [editingClaim, setEditingClaim] = useState<EventClaim>();
  const [editedText, setEditedText] = useState('');
  const [editedTextZh, setEditedTextZh] = useState('');
  const [actionError, setActionError] = useState<string>();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [reextractOpen, setReextractOpen] = useState(false);

  const unresolvedCount = useMemo(
    () => eventPack?.claims.filter((claim) => claim.status === 'AI_PROPOSED').length ?? 0,
    [eventPack],
  );
  const isFrozen = eventPack?.status.toUpperCase() === 'FROZEN' || Boolean(eventPack?.frozenAt);

  const decideClaim = async (claimId: string, status: 'HUMAN_APPROVED' | 'REJECTED') => {
    setActionError(undefined);
    try {
      await reviewClaim(claimId, { status });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  const openEdit = (claim: EventClaim) => {
    setEditingClaim(claim);
    setEditedText(claim.text);
    setEditedTextZh(claim.textZh ?? '');
  };

  const submitEdit = async () => {
    if (!editingClaim || editedText.trim().length === 0) return;
    setActionError(undefined);
    try {
      await reviewClaim(editingClaim.id, {
        status: 'EDITED',
        editedText: editedText.trim(),
        editedTextZh: editedTextZh.trim() || undefined,
      });
      setEditingClaim(undefined);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  const freeze = async () => {
    setActionError(undefined);
    try {
      await freezeEventPack();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  if (eventPackState === 'loading') return <div className="page"><PageHeader title={t('pack.title')} subtitle={t('pack.subtitle')} /><LoadingPanel /></div>;
  if (eventPackState === 'error') return (
    <div className="page">
      <PageHeader
        title={t('pack.title')}
        subtitle={t('pack.subtitle')}
        actions={<Button renderIcon={UploadSimple} onClick={() => setUploadOpen(true)}>{language === 'zh-CN' ? '上传来源' : 'Upload source'}</Button>}
      />
      <ErrorPanel detail={eventPackError} />
      <EventPackUploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} />
    </div>
  );
  if (!eventPack) {
    return (
      <div className="page">
        <PageHeader
          title={t('pack.title')}
          subtitle={t('pack.subtitle')}
          actions={<Button renderIcon={UploadSimple} onClick={() => setUploadOpen(true)}>{language === 'zh-CN' ? '上传来源' : 'Upload source'}</Button>}
        />
        <EmptyState
          title={t('pack.selectTitle')}
          body={t('pack.selectBody')}
          action={<Button kind="tertiary" onClick={() => navigate('cases')}>{t('nav.cases')}</Button>}
        />
        <EventPackUploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} />
      </div>
    );
  }

  return (
    <div className="page page--pack">
      <PageHeader
        title={language === 'zh-CN' ? eventPack.nameZh ?? eventPack.name : eventPack.name}
        subtitle={t('pack.subtitle')}
        actions={(
          <div className="page-header-action-group">
            <Button kind="tertiary" renderIcon={UploadSimple} onClick={() => setUploadOpen(true)}>
              {language === 'zh-CN' ? '新建 Event Pack' : 'New Event Pack'}
            </Button>
            {!isFrozen && eventPack.editableExtraction ? (
              <Button kind="ghost" renderIcon={FileText} onClick={() => setReextractOpen(true)}>
                {language === 'zh-CN' ? '重新抽取' : 'Re-extract'}
              </Button>
            ) : null}
            {isFrozen ? (
              <Button renderIcon={ArrowRight} onClick={() => navigate('scenario')}>{t('home.startScenario')}</Button>
            ) : null}
          </div>
        )}
      />

      {actionError || eventPackError ? (
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={t('common.errorTitle')}
          subtitle={t('error.claimReview')}
        />
      ) : null}
      {isFrozen ? (
        <InlineNotification kind="success" lowContrast hideCloseButton title={t('status.frozen')} subtitle={t('pack.frozenNotice')} />
      ) : null}
      {eventPack.isSynthetic ? (
        <InlineNotification
          kind="warning"
          lowContrast
          hideCloseButton
          title={language === 'zh-CN' ? '真实事件事实与合成市场必须分开阅读' : 'Real event facts and synthetic market mechanics are separate'}
          subtitle={language === 'zh-CN'
            ? eventPack.syntheticLabelZh ?? '来源支持的事件事实用于输入，但价格路径、订单流、价差、深度和智能体行为均为合成。'
            : eventPack.syntheticLabel ?? 'Event facts are source-backed, while price paths, order flow, spreads, depth, and agent behavior are synthetic.'}
        />
      ) : null}
      {eventPack.contentSecurity ? (
        <InlineNotification
          kind={eventPack.contentSecurity.decision === 'REVIEW' ? 'warning' : 'info'}
          lowContrast
          hideCloseButton
          title={language === 'zh-CN'
            ? `上传内容安全检查：${eventPack.contentSecurity.decision}`
            : `Upload content safety: ${eventPack.contentSecurity.decision}`}
          subtitle={language === 'zh-CN'
            ? `已扫描 ${eventPack.contentSecurity.sourceCount} 个来源，记录 ${eventPack.contentSecurity.findingCount} 个安全分类；${eventPack.contentSecurity.rawContentRetained === false ? '后端明确报告未保留原始上传正文。' : eventPack.contentSecurity.rawContentRetained === true ? '后端报告保留了原始正文，请停止并复核数据策略。' : '后端未报告原始正文保留状态。'}${eventPack.contentSecurity.acknowledged ? '需复核内容已经人工确认并在处理前脱敏。' : ''}`
            : `${eventPack.contentSecurity.sourceCount} source(s) scanned with ${eventPack.contentSecurity.findingCount} safety classification(s). ${eventPack.contentSecurity.rawContentRetained === false ? 'The backend explicitly reports that raw uploaded text was not retained.' : eventPack.contentSecurity.rawContentRetained === true ? 'The backend reports raw-text retention; stop and review the data policy.' : 'Raw-text retention status was not reported by the backend.'}${eventPack.contentSecurity.acknowledged ? ' Reviewable content was acknowledged and redacted before processing.' : ''}`}
        />
      ) : null}

      <section className="pack-summary">
        <div>
          <span>{t('common.sources')}</span>
          <strong>{eventPack.sources.length}</strong>
        </div>
        <div>
          <span>{t('common.claims')}</span>
          <strong>{eventPack.claims.length}</strong>
        </div>
        <div>
          <span>{t('pack.pointInTime')}</span>
          <strong>{eventPack.pointInTime ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(eventPack.pointInTime)) : t('common.unavailable')}</strong>
        </div>
        <div>
          <span>{language === 'zh-CN' ? '事件包状态' : 'Event Pack status'}</span>
          <StatusBadge status={eventPack.status} />
        </div>
        <div>
          <span>{language === 'zh-CN' ? '抽取模式' : 'Extraction mode'}</span>
          <strong>{eventPack.extractionMode ?? (language === 'zh-CN' ? '预先整理的事件包' : 'Pre-curated Event Pack')}</strong>
        </div>
        {eventPack.contentSecurity ? (
          <div>
            <span>{language === 'zh-CN' ? '内容安全' : 'Content safety'}</span>
            <strong>{eventPack.contentSecurity.decision} · {eventPack.contentSecurity.findingCount}</strong>
          </div>
        ) : null}
      </section>

      {eventPack.contentSecurity && eventPack.contentSecurity.findings.length > 0 ? (
        <section className="pack-limitations" aria-labelledby="content-security-heading">
          <div className="section-heading">
            <h2 id="content-security-heading">{language === 'zh-CN' ? '安全扫描摘要' : 'Content-safety summary'}</h2>
            <p>{language === 'zh-CN'
              ? '这里只显示安全分类与字段位置，不显示命中的原文、凭据或个人信息。'
              : 'Only safe classifications and field locations are shown; matched text, credentials, and personal data are never displayed.'}</p>
          </div>
          <div className="claim-item__evidence">
            {[...new Set(eventPack.contentSecurity.findings.map((finding) => finding.code))].map((code) => (
              <Tag key={code} type="warm-gray" size="sm">{code}</Tag>
            ))}
            {eventPack.contentSecurity.findingsTruncated ? (
              <span>{language === 'zh-CN' ? '摘要已截断' : 'Summary truncated'}</span>
            ) : null}
          </div>
        </section>
      ) : null}

      <div className="pack-workspace">
        <section className="pack-sources" aria-labelledby="source-ledger-heading">
          <div className="section-heading">
            <h2 id="source-ledger-heading">{t('pack.sourceLedger')}</h2>
            <p>{t('common.sources')}</p>
          </div>
          {eventPack.sources.length === 0 ? <p className="empty-inline">{t('pack.noSources')}</p> : (
            <div className="source-list">
              {eventPack.sources.map((source) => (
                <article key={source.id} className="source-item">
                  <div className="source-item__topline">
                    <FileText size={19} aria-hidden="true" />
                    <StatusBadge status={source.sourceType ?? source.tier ?? 'SOURCE'} />
                  </div>
                  <h3>{language === 'zh-CN' ? source.titleZh ?? source.title : source.title}</h3>
                  <p>{source.publisher ?? t('common.unavailable')}</p>
                  <dl>
                    <div><dt>{t('common.id')}</dt><dd>{source.id}</dd></div>
                    {source.tier ? <div><dt>{t('common.tier')}</dt><dd>{source.tier}</dd></div> : null}
                    {source.publishedAt ? <div><dt>{language === 'zh-CN' ? '发布时间' : 'Published at'}</dt><dd>{new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(source.publishedAt))}</dd></div> : null}
                    {source.knownAt ? <div><dt>{language === 'zh-CN' ? '可见时间' : 'Known at'}</dt><dd>{new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(source.knownAt))}</dd></div> : null}
                    {source.hash ? <div><dt>{t('common.hash')}</dt><dd title={source.hash}>{source.hash.slice(0, 14)}</dd></div> : null}
                  </dl>
                  {source.url ? <a href={source.url} target="_blank" rel="noreferrer"><LinkIcon size={16} />{t('common.source')}</a> : null}
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="pack-claims" aria-labelledby="claim-queue-heading">
          <div className="section-heading">
            <h2 id="claim-queue-heading">{t('pack.claimQueue')}</h2>
            <p>{t('pack.claimQueueHelp')}</p>
          </div>
          {eventPack.claims.length === 0 ? <p className="empty-inline">{t('pack.noClaims')}</p> : (
            <div className="claim-list">
              {eventPack.claims.map((claim) => {
                const disabled = isFrozen || claimBusyId === claim.id;
                return (
                  <article key={claim.id} className="claim-item">
                    <div className="claim-item__meta">
                      <StatusBadge status={claim.status} />
                      {claim.isRequired ? <span>{t('pack.required')}</span> : null}
                      {claim.sourceTier ? <span>{claim.sourceTier}</span> : null}
                      {claim.confidence !== undefined ? <span>{Math.round(claim.confidence * 100)}%</span> : null}
                    </div>
                    <p className="claim-item__text">{language === 'zh-CN' ? claim.textZh ?? claim.text : claim.text}</p>
                    {claim.impactChannels && claim.impactChannels.length > 0 ? (
                      <p className="claim-item__channels">{claim.impactChannels.join(', ')}</p>
                    ) : null}
                    <div className="claim-item__evidence" aria-label={language === 'zh-CN' ? '来源关联' : 'Source links'}>
                      {(claim.sourceIds?.length ? claim.sourceIds : claim.sourceId ? [claim.sourceId] : []).map((sourceId) => (
                        <Tag key={sourceId} type="cool-gray" size="sm">{sourceId}</Tag>
                      ))}
                      {claim.publishedAt ? <span>{language === 'zh-CN' ? '可见时间' : 'Known at'} {new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(claim.publishedAt))}</span> : null}
                    </div>
                    <div className="claim-item__actions">
                      <Button kind="ghost" size="sm" renderIcon={Check} disabled={disabled} onClick={() => void decideClaim(claim.id, 'HUMAN_APPROVED')}>
                        {t('pack.approve')}
                      </Button>
                      <Button kind="ghost" size="sm" renderIcon={PencilSimple} disabled={disabled} onClick={() => openEdit(claim)}>
                        {t('pack.edit')}
                      </Button>
                      <Button kind="danger--ghost" size="sm" renderIcon={X} disabled={disabled} onClick={() => void decideClaim(claim.id, 'REJECTED')}>
                        {t('pack.reject')}
                      </Button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
          <div className="freeze-bar">
            <div>
              <strong>{isFrozen ? t('pack.frozenNotice') : t('pack.freezeHelp')}</strong>
              {!isFrozen && unresolvedCount > 0 ? <p>{t('pack.freezeBlocked')}</p> : null}
            </div>
            <Button
              renderIcon={LockKey}
              disabled={isFrozen || unresolvedCount > 0}
              onClick={() => void freeze()}
            >
              {t('pack.freeze')}
            </Button>
          </div>
        </section>
      </div>

      <section className="pack-limitations" aria-labelledby="pack-limitations-heading">
        <div className="section-heading"><h2 id="pack-limitations-heading">{t('common.limitations')}</h2></div>
        {(language === 'zh-CN' ? eventPack.limitationsZh : eventPack.limitations).length > 0 ? (
          <ul>{(language === 'zh-CN' ? eventPack.limitationsZh : eventPack.limitations).map((limitation) => <li key={limitation}>{limitation}</li>)}</ul>
        ) : <p className="empty-inline">{language === 'zh-CN' ? '此自定义事件包尚未附加额外限制；仍受情景分析、合成机制和非投资建议边界约束。' : 'This custom Event Pack has no additional limitation record. Scenario-analysis, synthetic-mechanism, and non-advisory boundaries still apply.'}</p>}
      </section>

      <Modal
        open={Boolean(editingClaim)}
        modalHeading={t('pack.editTitle')}
        primaryButtonText={t('common.save')}
        secondaryButtonText={t('common.cancel')}
        primaryButtonDisabled={editedText.trim().length === 0}
        onRequestClose={() => setEditingClaim(undefined)}
        onRequestSubmit={() => void submitEdit()}
      >
        <p className="modal-help">{t('pack.editHelp')}</p>
        <TextArea
          id="edited-claim"
          labelText={t('pack.englishText')}
          value={editedText}
          rows={5}
          onChange={(event) => setEditedText(event.target.value)}
        />
        <TextArea
          id="edited-claim-zh"
          labelText={t('pack.chineseText')}
          value={editedTextZh}
          rows={5}
          onChange={(event) => setEditedTextZh(event.target.value)}
        />
      </Modal>
      <EventPackUploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} />
      <EventPackUploadModal open={reextractOpen} onClose={() => setReextractOpen(false)} existingEventPack={eventPack} />
    </div>
  );
}
