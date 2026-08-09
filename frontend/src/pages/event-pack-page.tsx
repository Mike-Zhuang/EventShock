import { Button, InlineNotification, Modal, Tag, TextArea } from '@carbon/react';
import {
  ArrowRight,
  ArrowCounterClockwise,
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
import { IMPACT_CHANNEL_DEFINITIONS, impactChannelDisplay } from '../impact-channels';
import { useWorkflow } from '../state/workflow-context';
import type { EventClaim } from '../api/types';
import { EventPackUploadModal } from '../components/event-pack-upload-modal';
import { TechnicalCodeDisplay, technicalCodeLabel } from '../components/technical-code';

function extractionModeLabel(mode: string | undefined, language: 'en' | 'zh-CN'): string {
  if (!mode) return language === 'zh-CN' ? '预先整理的事件包' : 'Pre-curated Event Pack';
  if (mode === 'RULE_ONLY') {
    return language === 'zh-CN' ? '确定性规则抽取' : 'Deterministic rule extraction';
  }
  if (/RULE_FALLBACK|_ABSTAINED_RULE_FALLBACK|_FALLBACK$/i.test(mode)) {
    return language === 'zh-CN'
      ? '低质量规则回退'
      : 'Lower-quality rule fallback';
  }
  return language === 'zh-CN' ? '结构化模型抽取' : 'Structured model extraction';
}

const BULK_CONFIDENCE_THRESHOLD = 0.75;

function confidenceBand(value: number, language: 'en' | 'zh-CN'): string {
  if (value >= 0.8) return language === 'zh-CN' ? '较高' : 'Higher';
  if (value >= 0.6) return language === 'zh-CN' ? '中等' : 'Moderate';
  return language === 'zh-CN' ? '较低' : 'Lower';
}

function claimBulkExclusionReasons(
  claim: EventClaim,
  reviewSourceIds: Set<string>,
): string[] {
  if (claim.bulkApprovalExclusionReasons?.length) {
    return claim.bulkApprovalExclusionReasons;
  }
  const reasons: string[] = [];
  if ((claim.confidence ?? -1) < (claim.bulkApprovalMinimumConfidence ?? BULK_CONFIDENCE_THRESHOLD)) {
    reasons.push('LOW_CONFIDENCE');
  }
  if ((claim.impactChannels?.length ?? 0) > 1) reasons.push('MULTIPLE_IMPACT_CHANNELS');
  const sourceIds = claim.sourceIds?.length
    ? claim.sourceIds
    : claim.sourceId
      ? [claim.sourceId]
      : [];
  if (sourceIds.some((sourceId) => reviewSourceIds.has(sourceId))) {
    reasons.push('CONTENT_SAFETY_REVIEW');
  }
  if ((claim.sourceTier ?? '').toUpperCase() !== 'OFFICIAL') {
    reasons.push('NON_OFFICIAL_SOURCE');
  }
  if (claim.bulkApprovalEligible === false) reasons.push('EXTRACTION_NOT_ELIGIBLE');
  return [...new Set(reasons)];
}

function safetyGuidanceLabel(code: string | undefined, language: 'en' | 'zh-CN'): string {
  const labels: Record<string, { en: string; 'zh-CN': string }> = {
    REMOVE_ROTATE_AND_RESUBMIT: {
      en: 'Remove, rotate the credential, then resubmit',
      'zh-CN': '删除内容、轮换凭据后重新提交',
    },
    REMOVE_AND_RESUBMIT: {
      en: 'Remove the high-risk content and resubmit',
      'zh-CN': '删除高风险内容后重新提交',
    },
    VERIFY_PUBLIC_CONTACT_OR_REDACT: {
      en: 'Verify it is a public institutional contact, or redact it',
      'zh-CN': '确认其为公开机构联系方式，否则遮盖',
    },
    REDACT_OR_EDIT: {
      en: 'Redact or edit the field',
      'zh-CN': '遮盖或编辑该字段',
    },
    REVIEW_EDIT_OR_REMOVE: {
      en: 'Review, edit, or remove the field',
      'zh-CN': '复核、编辑或删除该字段',
    },
  };
  return code && labels[code]
    ? labels[code][language]
    : language === 'zh-CN'
      ? '复核数据策略并编辑或删除'
      : 'Review the data policy, then edit or remove';
}

function contentSafetyDecisionLabel(
  decision: string,
  language: 'en' | 'zh-CN',
): string {
  const labels: Record<string, { en: string; 'zh-CN': string }> = {
    ALLOW: { en: 'No blocking finding', 'zh-CN': '未发现阻塞项' },
    REVIEW: { en: 'Human review required', 'zh-CN': '需要人工复核' },
    BLOCK: { en: 'Blocked for safety', 'zh-CN': '已因安全原因阻止' },
  };
  return labels[decision]?.[language] ?? technicalCodeLabel(decision, language);
}

function contentSafetySeverityLabel(
  severity: string,
  language: 'en' | 'zh-CN',
): string {
  const labels: Record<string, { en: string; 'zh-CN': string }> = {
    CRITICAL: { en: 'Critical', 'zh-CN': '严重' },
    HIGH: { en: 'High', 'zh-CN': '高' },
    MEDIUM: { en: 'Medium', 'zh-CN': '中' },
    LOW: { en: 'Low', 'zh-CN': '低' },
  };
  return labels[severity]?.[language] ?? technicalCodeLabel(severity, language);
}

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
  const [editedImpactChannels, setEditedImpactChannels] = useState<string[]>([]);
  const [editedChannelReasons, setEditedChannelReasons] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string>();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [reextractOpen, setReextractOpen] = useState(false);
  const [bulkApproveOpen, setBulkApproveOpen] = useState(false);
  const [bulkApproveError, setBulkApproveError] = useState<string>();

  const pendingClaims = useMemo(
    () => eventPack?.claims.filter((claim) => claim.status === 'AI_PROPOSED') ?? [],
    [eventPack],
  );
  const unresolvedCount = pendingClaims.length;
  const contentReviewSourceIds = useMemo(
    () => new Set(
      eventPack?.contentSecurity?.sources
        .filter((source) => source.decision === 'REVIEW')
        .map((source) => source.sourceId) ?? [],
    ),
    [eventPack],
  );
  const bulkReviewSummary = useMemo(() => {
    const reasonMap = new Map(
      pendingClaims.map((claim) => [
        claim.id,
        claimBulkExclusionReasons(claim, contentReviewSourceIds),
      ]),
    );
    const eligible = pendingClaims.filter((claim) => (reasonMap.get(claim.id)?.length ?? 0) === 0);
    const count = (reason: string) => [...reasonMap.values()]
      .filter((reasons) => reasons.includes(reason)).length;
    return {
      eligible,
      lowConfidence: count('LOW_CONFIDENCE'),
      multiChannel: count('MULTIPLE_IMPACT_CHANNELS'),
      contentReview: count('CONTENT_SAFETY_REVIEW'),
      nonOfficial: count('NON_OFFICIAL_SOURCE'),
      mechanismInferred: pendingClaims.filter((claim) => claim.channelMappingIsInference).length,
    };
  }, [contentReviewSourceIds, pendingClaims]);
  const lowQualityRuleFallback = Boolean(
    eventPack?.extractionMode
    && /RULE_FALLBACK|_ABSTAINED_RULE_FALLBACK|_FALLBACK$/i.test(eventPack.extractionMode),
  );
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

  const undoClaimReview = async (claimId: string) => {
    setActionError(undefined);
    try {
      await reviewClaim(claimId, { status: 'AI_PROPOSED' });
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  const openEdit = (claim: EventClaim) => {
    setEditingClaim(claim);
    setEditedText(claim.text);
    setEditedTextZh(claim.textZh ?? '');
    setEditedImpactChannels(claim.impactChannels ?? []);
    setEditedChannelReasons(Object.fromEntries(
      (claim.impactChannels ?? []).map((channel) => {
        const rationale = claim.impactChannelRationale?.find((item) => item.channel === channel);
        return [
          channel,
          language === 'zh-CN'
            ? rationale?.reasonZh ?? rationale?.reason ?? impactChannelDisplay(channel, language).description
            : rationale?.reason ?? impactChannelDisplay(channel, language).description,
        ];
      }),
    ));
  };

  const submitEdit = async () => {
    if (!editingClaim || editedText.trim().length === 0) return;
    setActionError(undefined);
    try {
      await reviewClaim(editingClaim.id, {
        status: 'EDITED',
        editedText: editedText.trim(),
        editedTextZh: editedTextZh.trim() || undefined,
        editedImpactChannels,
        editedImpactChannelRationale: editedImpactChannels.map((channel) => {
          const display = impactChannelDisplay(channel, language);
          return {
            channel,
            reason: editedChannelReasons[channel]?.trim() || display.description,
            reasonZh: language === 'zh-CN'
              ? editedChannelReasons[channel]?.trim() || display.description
              : undefined,
            evidenceType: 'MECHANISM_HYPOTHESIS',
            simulatorParameter: display.simulatorParameter,
          };
        }),
      });
      setEditingClaim(undefined);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  };

  const toggleEditedChannel = (channel: string) => {
    setEditedImpactChannels((current) => {
      if (current.includes(channel)) return current.filter((item) => item !== channel);
      if (current.length >= 2) return current;
      const display = impactChannelDisplay(channel, language);
      setEditedChannelReasons((reasons) => ({
        ...reasons,
        [channel]: reasons[channel] ?? display.description,
      }));
      return [...current, channel];
    });
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
    if (bulkReviewSummary.eligible.length === 0) return;
    setBulkApproveError(undefined);
    try {
      await approveAllPendingClaims({
        acknowledgedBulkApproval: true,
        expectedClaimIds: bulkReviewSummary.eligible.map((claim) => claim.id),
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
            <Button kind="ghost" onClick={() => navigate('guided')}>
              {language === 'zh-CN' ? '返回 AI 引导' : 'Return to AI guide'}
            </Button>
            <Button kind="tertiary" renderIcon={UploadSimple} onClick={() => setUploadOpen(true)}>
              {language === 'zh-CN' ? '新建 Event Pack' : 'New Event Pack'}
            </Button>
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
            ? `上传内容安全检查：${contentSafetyDecisionLabel(eventPack.contentSecurity.decision, language)}`
            : `Upload content safety: ${contentSafetyDecisionLabel(eventPack.contentSecurity.decision, language)}`}
          subtitle={language === 'zh-CN'
            ? `已扫描 ${eventPack.contentSecurity.sourceCount} 个来源，记录 ${eventPack.contentSecurity.findingCount} 个安全分类；${eventPack.contentSecurity.rawContentRetained === false ? '后端明确报告未保留原始上传正文。' : eventPack.contentSecurity.rawContentRetained === true ? '后端报告保留了原始正文，请停止并复核数据策略。' : '后端未报告原始正文保留状态。'}${eventPack.contentSecurity.acknowledged ? '需复核内容已经人工确认并在处理前脱敏。' : ''}`
            : `${eventPack.contentSecurity.sourceCount} source(s) scanned with ${eventPack.contentSecurity.findingCount} safety classification(s). ${eventPack.contentSecurity.rawContentRetained === false ? 'The backend explicitly reports that raw uploaded text was not retained.' : eventPack.contentSecurity.rawContentRetained === true ? 'The backend reports raw-text retention; stop and review the data policy.' : 'Raw-text retention status was not reported by the backend.'}${eventPack.contentSecurity.acknowledged ? ' Reviewable content was acknowledged and redacted before processing.' : ''}`}
        />
      ) : null}

      <div className="pack-extraction-toolbar" role="region" aria-label={language === 'zh-CN' ? '抽取审核工具栏' : 'Extraction review toolbar'}>
        <div>
          <span>{language === 'zh-CN' ? '抽取模式' : 'Extraction mode'}</span>
          <strong>{extractionModeLabel(eventPack.extractionMode, language)}</strong>
          <span>{language === 'zh-CN' ? `${unresolvedCount} 项待审核` : `${unresolvedCount} pending`}</span>
          {lowQualityRuleFallback ? (
            <Tag type="red" size="sm">
              {language === 'zh-CN' ? '规则回退 · 必须逐条审核' : 'Rule fallback · individual review required'}
            </Tag>
          ) : null}
        </div>
        <div className="pack-extraction-toolbar__actions">
          {eventPack.extractionMode ? (
            <details>
              <summary>{language === 'zh-CN' ? '技术详情' : 'Technical details'}</summary>
              <code>{eventPack.extractionMode}</code>
            </details>
          ) : null}
          {!isFrozen && eventPack.editableExtraction ? (
            <Button
              kind="tertiary"
              size="sm"
              renderIcon={ArrowCounterClockwise}
              disabled={reviewBusy}
              onClick={() => setReextractOpen(true)}
            >
              {language === 'zh-CN' ? '重新抽取' : 'Re-extract'}
            </Button>
          ) : null}
        </div>
      </div>

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
          <strong className="pack-summary__long-value">
            {extractionModeLabel(eventPack.extractionMode, language)}
          </strong>
        </div>
        {eventPack.contentSecurity ? (
          <div>
            <span>{language === 'zh-CN' ? '内容安全' : 'Content safety'}</span>
            <strong>{contentSafetyDecisionLabel(eventPack.contentSecurity.decision, language)} · {eventPack.contentSecurity.findingCount}</strong>
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
          {eventPack.contentSecurity.modelInputSummary ? (
            <dl className="pack-security-counts">
              <div>
                <dt>{language === 'zh-CN' ? '发送模型前保留字段' : 'Fields retained before model'}</dt>
                <dd>{eventPack.contentSecurity.modelInputSummary.retainedFieldCount}</dd>
              </div>
              <div>
                <dt>{language === 'zh-CN' ? '发送模型前移除字段' : 'Fields removed before model'}</dt>
                <dd>{eventPack.contentSecurity.modelInputSummary.removedFieldCount}</dd>
              </div>
              <div>
                <dt>{language === 'zh-CN' ? '发送模型前遮盖字段' : 'Fields redacted before model'}</dt>
                <dd>{eventPack.contentSecurity.modelInputSummary.redactedFieldCount}</dd>
              </div>
            </dl>
          ) : null}
          <div className="pack-security-findings">
            {eventPack.contentSecurity.findings.map((finding, index) => (
              <article key={`${finding.sourceId ?? 'metadata'}-${finding.field}-${finding.offset}-${index}`}>
                <div>
                  <Tag type={finding.severity === 'CRITICAL' || finding.severity === 'HIGH' ? 'red' : 'warm-gray'} size="sm">
                    {contentSafetySeverityLabel(finding.severity, language)}
                  </Tag>
                  <strong>{technicalCodeLabel(finding.riskCategory ?? finding.code, language)}</strong>
                </div>
                <p>
                  {language === 'zh-CN' ? '位置' : 'Location'}: {finding.sourceId ?? 'event-pack-metadata'} · {finding.field} · {finding.offset}
                </p>
                <p>{safetyGuidanceLabel(finding.recommendedAction, language)}</p>
              </article>
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
          <div className="section-heading section-heading--with-control">
            <div>
              <h2 id="claim-queue-heading">{t('pack.claimQueue')}</h2>
              <p>{t('pack.claimQueueHelp')}</p>
              <Tag type={lowQualityRuleFallback ? 'warm-gray' : 'cool-gray'} size="sm">
                {extractionModeLabel(eventPack.extractionMode, language)}
              </Tag>
            </div>
            {!isFrozen && eventPack.editableExtraction ? (
              <Button
                kind="ghost"
                size="sm"
                renderIcon={FileText}
                disabled={reviewBusy}
                onClick={() => setReextractOpen(true)}
              >
                {language === 'zh-CN' ? '重新抽取候选' : 'Re-extract candidates'}
              </Button>
            ) : null}
          </div>
          {lowQualityRuleFallback && unresolvedCount > 0 ? (
            <InlineNotification
              kind="warning"
              lowContrast
              hideCloseButton
              title={language === 'zh-CN'
                ? '规则回退候选必须逐条审核'
                : 'Rule-fallback candidates require individual review'}
              subtitle={language === 'zh-CN'
                ? '本次抽取未获得完整的结构化模型结果。为防止碎片化或低忠实度候选被一次性批准，批量批准已禁用；请逐条核对，或从此处重新抽取。'
                : 'This extraction did not produce a complete structured-model result. Bulk approval is disabled to prevent fragmented or low-fidelity candidates from being accepted together. Review each claim or re-extract here.'}
            />
          ) : null}
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
                disabled={reviewBusy || bulkReviewSummary.eligible.length === 0}
                title={bulkReviewSummary.eligible.length === 0
                  ? language === 'zh-CN'
                    ? '当前没有满足质量门禁的批量可批准项'
                    : 'No pending claim currently satisfies the bulk quality gate'
                  : undefined}
                onClick={() => { setBulkApproveError(undefined); setBulkApproveOpen(true); }}
              >
                {language === 'zh-CN'
                  ? `批准符合条件项（${bulkReviewSummary.eligible.length}）`
                  : `Approve eligible (${bulkReviewSummary.eligible.length})`}
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
                      {claim.confidence !== undefined ? <span><ExplainedLabel label={confidenceBand(claim.confidence, language)} explanation={language === 'zh-CN' ? '这是抽取质量的复核优先级，不表示该主张为真的概率。精确技术分数收在下方详情中。' : 'This is an extraction-quality review priority, not the probability that the claim is true. Exact technical scores are available in the details below.'} /></span> : null}
                    </div>
                    <p className="claim-item__text">{language === 'zh-CN' ? claim.textZh ?? claim.text : claim.text}</p>
                    {claim.confidenceComponents ? (
                      <details className="claim-confidence-details">
                        <summary>{language === 'zh-CN' ? '为什么是这个复核优先级？' : 'Why this review priority?'}</summary>
                        <p>{language === 'zh-CN'
                          ? '文本忠实度衡量候选是否贴近来源；来源层级反映来源类型；时间边界确定性反映发布时间与可见时间是否清楚。它们只帮助安排人工复核。'
                          : 'Textual fidelity measures closeness to the source, source tier reflects provenance, and time-boundary certainty reflects publication and visibility timing. They only prioritize human review.'}</p>
                        <dl className="claim-confidence-components" aria-label={language === 'zh-CN' ? '抽取质量技术组成' : 'Technical extraction-quality components'}>
                          <div>
                            <dt>{language === 'zh-CN' ? '文本忠实度' : 'Textual fidelity'}</dt>
                            <dd>{Math.round((claim.confidenceComponents.textualFidelity ?? 0) * 100)}%</dd>
                          </div>
                          <div>
                            <dt>{language === 'zh-CN' ? '来源层级强度' : 'Source-tier strength'}</dt>
                            <dd>{Math.round((claim.confidenceComponents.sourceTierStrength ?? 0) * 100)}%</dd>
                          </div>
                          <div>
                            <dt>{language === 'zh-CN' ? '时间边界确定性' : 'Time-boundary certainty'}</dt>
                            <dd>{Math.round((claim.confidenceComponents.timeBoundaryCertainty ?? 0) * 100)}%</dd>
                          </div>
                        </dl>
                      </details>
                    ) : null}
                    {claim.impactChannels && claim.impactChannels.length > 0 ? (
                      <div
                        className="claim-item__channels"
                        aria-label={language === 'zh-CN' ? '影响通道' : 'Impact channels'}
                      >
                        {claim.impactChannels.map((channel) => {
                          const display = impactChannelDisplay(channel, language);
                          const rationale = claim.impactChannelRationale?.find(
                            (item) => item.channel === channel,
                          );
                          return (
                            <article key={channel} className="claim-channel-card">
                              <div>
                                <Tag type="cool-gray" size="sm">{display.name}</Tag>
                                <Tag type="gray" size="sm">
                                  {rationale?.evidenceType === 'FACT'
                                    ? language === 'zh-CN' ? '事实' : 'Fact'
                                    : language === 'zh-CN' ? '机制假设' : 'Mechanism hypothesis'}
                                </Tag>
                              </div>
                              <p>{language === 'zh-CN'
                                ? rationale?.reasonZh ?? rationale?.reason ?? display.description
                                : rationale?.reason ?? display.description}</p>
                              <dl>
                                <div>
                                  <dt>{language === 'zh-CN' ? '对应仿真参数' : 'Simulator parameter'}</dt>
                                  <dd><code>{rationale?.simulatorParameter ?? display.simulatorParameter}</code></dd>
                                </div>
                                <div>
                                  <dt>{language === 'zh-CN' ? '示例' : 'Example'}</dt>
                                  <dd>{display.example}</dd>
                                </div>
                              </dl>
                            </article>
                          );
                        })}
                        <details className="claim-channel-unselected">
                          <summary>{language === 'zh-CN' ? '未选择通道代表什么' : 'What unselected channels mean'}</summary>
                          <ul>
                            {IMPACT_CHANNEL_DEFINITIONS
                              .filter((definition) => !claim.impactChannels?.includes(definition.id))
                              .map((definition) => {
                                const display = impactChannelDisplay(definition.id, language);
                                return <li key={definition.id}><strong>{display.name}：</strong>{display.unselectedMeaning}</li>;
                              })}
                          </ul>
                        </details>
                      </div>
                    ) : (
                      <details className="claim-channel-unselected">
                        <summary>{language === 'zh-CN' ? '未选择任何影响通道' : 'No impact channel selected'}</summary>
                        <p>{language === 'zh-CN'
                          ? '该主张目前只作为来源约束事实保留，不直接驱动任何仿真机制。'
                          : 'The claim remains a source-bound fact and does not directly drive a simulator mechanism.'}</p>
                      </details>
                    )}
                    {claim.status === 'AI_PROPOSED' && claimBulkExclusionReasons(claim, contentReviewSourceIds).length > 0 ? (
                      <div className="claim-bulk-exclusion">
                        {language === 'zh-CN' ? '仅支持逐条审核：' : 'Individual review only: '}
                        <TechnicalCodeDisplay
                          codes={claimBulkExclusionReasons(claim, contentReviewSourceIds)}
                          language={language}
                        />
                      </div>
                    ) : null}
                    <div className="claim-item__evidence" aria-label={language === 'zh-CN' ? '来源关联' : 'Source links'}>
                      {(claim.sourceIds?.length ? claim.sourceIds : claim.sourceId ? [claim.sourceId] : []).map((sourceId) => (
                        <Tag key={sourceId} type="cool-gray" size="sm">{sourceId}</Tag>
                      ))}
                      {claim.publishedAt ? <span>{language === 'zh-CN' ? '发布时间' : 'Published at'} {new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(claim.publishedAt))}</span> : null}
                      {claim.knownAt ? <span>{language === 'zh-CN' ? '可见时间' : 'Known at'} {new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(claim.knownAt))}</span> : null}
                    </div>
                    <div className="claim-item__actions">
                      {claim.status !== 'AI_PROPOSED' ? (
                        <Button
                          kind="ghost"
                          size="sm"
                          renderIcon={ArrowCounterClockwise}
                          disabled={disabled}
                          onClick={() => void undoClaimReview(claim.id)}
                        >
                          {language === 'zh-CN' ? '撤销审核' : 'Undo review'}
                        </Button>
                      ) : null}
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
        modalHeading={language === 'zh-CN'
          ? `批准 ${bulkReviewSummary.eligible.length} 项符合条件的主张？`
          : `Approve ${bulkReviewSummary.eligible.length} eligible claim(s)?`}
        primaryButtonText={reviewBusy
          ? language === 'zh-CN' ? '正在批准' : 'Approving'
          : language === 'zh-CN'
            ? `我已理解，批准 ${bulkReviewSummary.eligible.length} 项`
            : `I understand — approve ${bulkReviewSummary.eligible.length}`}
        secondaryButtonText={t('common.cancel')}
        primaryButtonDisabled={reviewBusy || bulkReviewSummary.eligible.length === 0}
        onRequestClose={() => { if (!reviewBusy) setBulkApproveOpen(false); }}
        onRequestSubmit={() => void approveAll()}
      >
        <InlineNotification
          kind="warning"
          lowContrast
          hideCloseButton
          title={language === 'zh-CN' ? '这不是来源核验的替代品' : 'This does not replace source verification'}
          subtitle={language === 'zh-CN'
            ? '确认后，仅满足质量门禁的候选会被标为“人工批准”。低置信度、多通道、安全复核和非官方来源候选仍留在队列中，必须逐条处理；事件包不会自动冻结。'
            : 'Only candidates that satisfy the quality gate will be marked human-approved. Low-confidence, multi-channel, safety-review, and non-official candidates remain pending for individual review; the Event Pack will not freeze automatically.'}
        />
        <p className="modal-help">{language === 'zh-CN'
          ? '如果另一标签页已经改变待审核队列，服务器会拒绝本次操作并要求你重新确认。'
          : 'If another tab changed the pending queue, the server will reject this request and require a fresh confirmation.'}</p>
        <dl className="bulk-review-counts">
          <div><dt>{language === 'zh-CN' ? '本次批准' : 'Approve now'}</dt><dd>{bulkReviewSummary.eligible.length}</dd></div>
          <div><dt>{language === 'zh-CN' ? '低置信度排除' : 'Low confidence excluded'}</dt><dd>{bulkReviewSummary.lowConfidence}</dd></div>
          <div><dt>{language === 'zh-CN' ? '多通道排除' : 'Multi-channel excluded'}</dt><dd>{bulkReviewSummary.multiChannel}</dd></div>
          <div><dt>{language === 'zh-CN' ? '安全复核排除' : 'Safety REVIEW excluded'}</dt><dd>{bulkReviewSummary.contentReview}</dd></div>
          <div><dt>{language === 'zh-CN' ? '非官方来源排除' : 'Non-official excluded'}</dt><dd>{bulkReviewSummary.nonOfficial}</dd></div>
          <div><dt>{language === 'zh-CN' ? '机制映射为推断' : 'Mechanism mapping inferred'}</dt><dd>{bulkReviewSummary.mechanismInferred}</dd></div>
        </dl>
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
        <fieldset className="claim-channel-editor">
          <legend>{language === 'zh-CN' ? '影响通道（最多 2 个）' : 'Impact channels (maximum 2)'}</legend>
          <p>{language === 'zh-CN'
            ? '通道描述的是仿真机制映射，不是事实为真的概率。'
            : 'Channels describe simulator-mechanism mappings, not the probability that a fact is true.'}</p>
          <div className="claim-channel-editor__options">
            {IMPACT_CHANNEL_DEFINITIONS.map((definition) => {
              const display = impactChannelDisplay(definition.id, language);
              const checked = editedImpactChannels.includes(definition.id);
              return (
                <label key={definition.id}>
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!checked && editedImpactChannels.length >= 2}
                    onChange={() => toggleEditedChannel(definition.id)}
                  />
                  <span><strong>{display.name}</strong><small>{display.description}</small></span>
                </label>
              );
            })}
          </div>
          {editedImpactChannels.map((channel) => {
            const display = impactChannelDisplay(channel, language);
            return (
              <TextArea
                key={channel}
                id={`edited-channel-reason-${channel}`}
                labelText={`${display.name} · ${language === 'zh-CN' ? '映射理由' : 'Mapping rationale'}`}
                value={editedChannelReasons[channel] ?? ''}
                rows={3}
                onChange={(event) => setEditedChannelReasons((current) => ({
                  ...current,
                  [channel]: event.target.value,
                }))}
                helperText={`${language === 'zh-CN' ? '对应参数' : 'Simulator parameter'}: ${display.simulatorParameter}`}
              />
            );
          })}
        </fieldset>
      </Modal>
      <EventPackUploadModal open={uploadOpen} onClose={() => setUploadOpen(false)} />
      <EventPackUploadModal open={reextractOpen} onClose={() => setReextractOpen(false)} existingEventPack={eventPack} />
    </div>
  );
}
