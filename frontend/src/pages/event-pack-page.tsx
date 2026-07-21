import { Button, InlineNotification, Modal, Tag, TextArea } from '@carbon/react';
import {
  ArrowRight,
  Check,
  FileText,
  Link as LinkIcon,
  LockKey,
  PencilSimple,
  UploadSimple,
  Warning,
  X,
} from '@phosphor-icons/react';
import { useMemo, useState } from 'react';
import type { ViewId } from '../app';
import { EmptyState, ErrorPanel, ExplainedLabel, LoadingPanel, PageHeader, StatusBadge } from '../components/common';
import { useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { getParameterHelp } from '../parameter-help';
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
    approveAllPendingClaims,
    freezeEventPack,
  } = useWorkflow();
  const [editingClaim, setEditingClaim] = useState<EventClaim>();
  const [editedText, setEditedText] = useState('');
  const [editedTextZh, setEditedTextZh] = useState('');
  const [actionError, setActionError] = useState<string>();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [reextractOpen, setReextractOpen] = useState(false);
  const [bulkApproveOpen, setBulkApproveOpen] = useState(false);
  const [bulkApproveError, setBulkApproveError] = useState<string>();

  const pendingClaimIds = useMemo(
    () => eventPack?.claims.filter((claim) => claim.status === 'AI_PROPOSED').map((claim) => claim.id) ?? [],
    [eventPack],
  );
  const unresolvedCount = pendingClaimIds.length;
  const isFrozen = eventPack?.status.toUpperCase() === 'FROZEN' || Boolean(eventPack?.frozenAt);
  const reviewBusy = Boolean(claimBusyId);

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

  const approveAll = async () => {
    if (pendingClaimIds.length === 0) return;
    setBulkApproveError(undefined);
    try {
      await approveAllPendingClaims({
        acknowledgedBulkApproval: true,
        expectedClaimIds: pendingClaimIds,
        rationale: 'User acknowledged the bulk-approval warning in the Event Pack review interface.',
      });
      setBulkApproveOpen(false);
    } catch (error) {
      setBulkApproveError(error instanceof Error ? error.message : String(error));
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
        guide={getPageGuide('pack', language)}
        actions={(
          <div className="page-header-action-group">
            <Button kind="tertiary" renderIcon={UploadSimple} onClick={() => setUploadOpen(true)}>
              {language === 'zh-CN' ? '新建 Event Pack' : 'New Event Pack'}
            </Button>
            {!isFrozen && eventPack.editableExtraction ? (
              <Button kind="ghost" renderIcon={FileText} disabled={reviewBusy} onClick={() => setReextractOpen(true)}>
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
          <span><ExplainedLabel label={t('pack.pointInTime')} explanation={getParameterHelp('asOf', language) ?? ''} /></span>
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
                    {source.tier ? <div><dt><ExplainedLabel label={t('common.tier')} explanation={language === 'zh-CN' ? '来源层级描述证据类型与可靠性边界；它不是主张真实性的概率评分。' : 'The source tier records evidence type and reliability boundaries; it is not a probability that a claim is true.'} /></dt><dd>{source.tier}</dd></div> : null}
                    {source.publishedAt ? <div><dt><ExplainedLabel label={language === 'zh-CN' ? '发布时间' : 'Published at'} explanation={language === 'zh-CN' ? '来源首次公开发布的时间。' : 'Time when the source was first published publicly.'} /></dt><dd>{new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(source.publishedAt))}</dd></div> : null}
                    {source.knownAt ? <div><dt><ExplainedLabel label={language === 'zh-CN' ? '可见时间' : 'Known at'} explanation={language === 'zh-CN' ? '研究者在时点约束下最早可使用该来源的时间，不一定等于发布时间。' : 'Earliest time the source may be used under the point-in-time constraint; it may differ from publication time.'} /></dt><dd>{new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(source.knownAt))}</dd></div> : null}
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
          {!isFrozen && unresolvedCount > 0 ? (
            <div className="bulk-review-callout">
              <div>
                <strong>{language === 'zh-CN' ? `${unresolvedCount} 项仍待人工审核` : `${unresolvedCount} claim(s) still require human review`}</strong>
                <p>{language === 'zh-CN' ? '建议逐条核对；批量批准必须先经过风险警告，并会留下单独审计记录。' : 'Review one by one when possible. Bulk approval requires a risk warning and leaves a separate audit record.'}</p>
              </div>
              <Button
                kind="danger--tertiary"
                size="sm"
                renderIcon={Warning}
                disabled={reviewBusy}
                onClick={() => { setBulkApproveError(undefined); setBulkApproveOpen(true); }}
              >
                {language === 'zh-CN' ? `批准全部待审核项（${unresolvedCount}）` : `Approve all pending (${unresolvedCount})`}
              </Button>
            </div>
          ) : null}
          {eventPack.claims.length === 0 ? <p className="empty-inline">{t('pack.noClaims')}</p> : (
            <div className="claim-list">
              {eventPack.claims.map((claim) => {
                const disabled = isFrozen || reviewBusy;
                return (
                  <article key={claim.id} className="claim-item">
                    <div className="claim-item__meta">
                      <StatusBadge status={claim.status} />
                      {claim.isRequired ? <span><ExplainedLabel label={t('pack.required')} explanation={language === 'zh-CN' ? '必需主张必须被批准或编辑后，事件包才允许冻结；不能仅拒绝。' : 'A required claim must be approved or edited before the Event Pack can freeze; rejection alone is not allowed.'} /></span> : null}
                      {claim.sourceTier ? <span>{claim.sourceTier}</span> : null}
                      {claim.confidence !== undefined ? <span><ExplainedLabel label={`${Math.round(claim.confidence * 100)}%`} explanation={language === 'zh-CN' ? '这是候选抽取置信度，用于排序人工复核，不表示该主张为真的概率。' : 'Candidate-extraction confidence for prioritizing review; it is not the probability that the claim is true.'} /></span> : null}
                    </div>
                    <p className="claim-item__text">{language === 'zh-CN' ? claim.textZh ?? claim.text : claim.text}</p>
                    {claim.impactChannels && claim.impactChannels.length > 0 ? (
                      <p className="claim-item__channels">{claim.impactChannels.join(', ')}</p>
                    ) : null}
                    <div className="claim-item__evidence" aria-label={language === 'zh-CN' ? '来源关联' : 'Source links'}>
                      {(claim.sourceIds?.length ? claim.sourceIds : claim.sourceId ? [claim.sourceId] : []).map((sourceId) => (
                        <Tag key={sourceId} type="cool-gray" size="sm">{sourceId}</Tag>
                      ))}
                      {claim.publishedAt ? <span>{language === 'zh-CN' ? '发布时间' : 'Published at'} {new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(claim.publishedAt))}</span> : null}
                      {claim.knownAt ? <span>{language === 'zh-CN' ? '可见时间' : 'Known at'} {new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(claim.knownAt))}</span> : null}
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
              disabled={isFrozen || unresolvedCount > 0 || reviewBusy}
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
        open={bulkApproveOpen}
        danger
        modalLabel={language === 'zh-CN' ? '人工审核警告' : 'Human-review warning'}
        modalHeading={language === 'zh-CN' ? `批准全部 ${unresolvedCount} 项待审核主张？` : `Approve all ${unresolvedCount} pending claims?`}
        primaryButtonText={reviewBusy
          ? language === 'zh-CN' ? '正在批准' : 'Approving'
          : language === 'zh-CN' ? `我已理解，批准 ${unresolvedCount} 项` : `I understand — approve ${unresolvedCount}`}
        secondaryButtonText={t('common.cancel')}
        primaryButtonDisabled={reviewBusy || unresolvedCount === 0}
        onRequestClose={() => { if (!reviewBusy) setBulkApproveOpen(false); }}
        onRequestSubmit={() => void approveAll()}
      >
        <InlineNotification
          kind="warning"
          lowContrast
          hideCloseButton
          title={language === 'zh-CN' ? '这不是来源核验的替代品' : 'This does not replace source verification'}
          subtitle={language === 'zh-CN'
            ? '确认后，当前所有待审核事实、估计与合成假设都会被标为“人工批准”。系统不会替你判断它们是否正确；已有修改、拒绝和批准保持不变，也不会自动冻结事件包。'
            : 'Every currently pending fact, estimate, and synthetic assumption will be marked human-approved. The system cannot decide whether they are correct. Existing edits, rejections, and approvals remain unchanged, and the Event Pack will not freeze automatically.'}
        />
        <p className="modal-help">{language === 'zh-CN'
          ? '如果另一标签页已经改变待审核队列，服务器会拒绝本次操作并要求你重新确认。'
          : 'If another tab changed the pending queue, the server will reject this request and require a fresh confirmation.'}</p>
        {bulkApproveError ? (
          <InlineNotification kind="error" lowContrast hideCloseButton title={t('common.errorTitle')} subtitle={bulkApproveError} />
        ) : null}
      </Modal>
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
