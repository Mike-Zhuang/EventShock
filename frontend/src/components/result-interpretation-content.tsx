import { Button } from '@carbon/react';
import {
  ArrowRight,
  BookOpenText,
  DownloadSimple,
  WarningCircle,
} from '@phosphor-icons/react';
import {
  useMemo,
  useRef,
  type RefCallback,
} from 'react';
import type { Navigate } from '../app';
import type { ResultInterpretationAssistantMessage } from '../api/types';
import { useI18n } from '../i18n';
import {
  auditResultEvidence,
  getLocalizedResultEvidence,
  type ResultEvidenceCitationAudit,
  type ResultEvidenceAudit,
} from './result-evidence';
import { SafeMarkdown } from './safe-markdown';
import {
  extractTechnicalCodes,
  humanizeTechnicalText,
  TechnicalCodeDisplay,
} from './technical-code';

interface ResultInterpretationContentProps {
  experimentId: string;
  message: ResultInterpretationAssistantMessage;
  navigate: Navigate;
}

function auditJson(
  message: ResultInterpretationAssistantMessage,
  audit: ResultEvidenceAudit,
): string {
  return JSON.stringify({
    schemaVersion: 'result_evidence_audit_v1.0.0',
    message: {
      id: message.id,
      createdAt: message.createdAt,
      provider: message.provider,
      model: message.model,
      promptVersion: message.promptVersion,
      semanticValidationStatus: message.semanticValidationStatus,
      deterministicFallbackUsed: message.deterministicFallbackUsed,
    },
    integrity: {
      issues: audit.issues,
      missingFromGrounding: audit.missingFromGrounding,
      missingFromText: audit.missingFromText,
      missingToolActivity: audit.missingToolActivity,
      unreferencedToolActivity: audit.unreferencedToolActivity,
      unknownEvidenceIds: audit.unknownEvidenceIds,
      mismatchedToolEvidenceIds: audit.mismatchedToolEvidenceIds,
      citations: audit.citations,
    },
    groundingReferences: message.groundingReferences,
    toolActivity: message.toolActivity,
  }, null, 2);
}

function integrityIssueLabel(issue: string, isZh: boolean): string {
  const labels: Record<string, { en: string; zh: string }> = {
    missing: { en: 'Missing citation or read record', zh: '引用或读取记录缺失' },
    unknown: { en: 'Legacy or unknown evidence reference', zh: '旧版或未知证据引用' },
    mismatch: { en: 'Evidence tool and reference do not match', zh: '证据工具与引用不匹配' },
  };
  const label = labels[issue];
  return label
    ? isZh ? label.zh : label.en
    : isZh ? '其他完整性异常' : 'Other integrity issue';
}

function evidenceStatusText(
  citation: ResultEvidenceCitationAudit,
  isZh: boolean,
): string {
  if (!citation.known) {
    return isZh
      ? '历史证据引用，当前无法定位'
      : 'Historical evidence reference; currently unavailable';
  }
  if (!citation.toolActivityPresent) {
    return isZh ? '未返回读取记录' : 'No read activity was returned';
  }
  const itemText = isZh
    ? `${citation.itemCount.toLocaleString('zh-CN')} 项`
    : `${citation.itemCount.toLocaleString('en')} items`;
  return citation.truncated
    ? `${itemText} · ${isZh ? '有限视图' : 'limited view'}`
    : `${itemText} · ${isZh ? '未截断' : 'not truncated'}`;
}

export function ResultInterpretationContent({
  experimentId,
  message,
  navigate,
}: ResultInterpretationContentProps) {
  const { language, t } = useI18n();
  const isZh = language === 'zh-CN';
  const secondaryLanguage = isZh ? 'en' : 'zh-CN';
  const boundaryStart = t('results.assistantBoundaryStart');
  const normalizedAnswer = message.answer.trimStart();
  const visibleAnswer = normalizedAnswer.startsWith(boundaryStart)
    ? normalizedAnswer.slice(boundaryStart.length).trimStart()
    : message.answer;
  const humanReadableAnswer = humanizeTechnicalText(visibleAnswer, language);
  const humanReadableAnalysisSummary = humanizeTechnicalText(
    message.analysisSummary,
    language,
  );
  const answerTechnicalCodes = useMemo(() => extractTechnicalCodes(
    `${message.answer}\n${message.analysisSummary ?? ''}`,
  ), [message.analysisSummary, message.answer]);
  const evidenceDetailsRef = useRef<HTMLDetailsElement>(null);
  const evidenceItemRefs = useRef(new Map<string, HTMLLIElement>());
  const audit = useMemo(() => auditResultEvidence(
    message.answer,
    message.analysisSummary,
    message.groundingReferences,
    message.toolActivity,
  ), [
    message.analysisSummary,
    message.answer,
    message.groundingReferences,
    message.toolActivity,
  ]);

  const visibleCitations = audit.citations.filter(
    (citation) => citation.inline || citation.groundingListed,
  );
  const deterministicFallbackUsed = message.deterministicFallbackUsed === true
    || message.semanticValidationStatus === 'DETERMINISTIC_FALLBACK';

  const setEvidenceItemRef = (evidenceId: string): RefCallback<HTMLLIElement> => (element) => {
    if (element) evidenceItemRefs.current.set(evidenceId, element);
    else evidenceItemRefs.current.delete(evidenceId);
  };

  const revealEvidence = (evidenceId: string) => {
    if (evidenceDetailsRef.current) evidenceDetailsRef.current.open = true;
    window.requestAnimationFrame(() => {
      const item = evidenceItemRefs.current.get(evidenceId);
      item?.scrollIntoView({ block: 'nearest', behavior: 'auto' });
      item?.focus({ preventScroll: true });
    });
  };

  const locateEvidence = (citation: ResultEvidenceCitationAudit) => {
    const evidence = getLocalizedResultEvidence(citation.evidenceId, language);
    if (!evidence.known || !evidence.view || !evidence.target
      || !citation.toolActivityPresent || citation.itemCount < 1) return;
    navigate(evidence.view, {
      experimentId,
      target: evidence.target,
    });
  };

  const downloadAudit = () => {
    const blob = new Blob([auditJson(message, audit)], { type: 'application/json' });
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = objectUrl;
    anchor.download = `eventshock-result-audit-${message.id.replaceAll(/[^A-Za-z0-9_-]/g, '-')}.json`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(objectUrl);
  };

  const renderCitation = ({ evidenceId }: { evidenceId: string }) => {
    const evidence = getLocalizedResultEvidence(evidenceId, language);
    const number = audit.numbering.numberByEvidenceId.get(evidenceId);
    return (
      <button
        type="button"
        className="result-assistant__citation"
        aria-label={isZh
          ? `查看证据 ${number ?? '?'}：${evidence.label}`
          : `View evidence ${number ?? '?'}: ${evidence.label}`}
        onClick={() => revealEvidence(evidenceId)}
      >
        [{number ?? '?'}]
      </button>
    );
  };

  const formatCitationLabel = ({ evidenceId }: { evidenceId: string }) => {
    const number = audit.numbering.numberByEvidenceId.get(evidenceId);
    if (number === undefined) return isZh ? '[证据]' : '[evidence]';
    return `[${number}]`;
  };

  return (
    <>
      {deterministicFallbackUsed ? (
        <div className="result-assistant__source-status result-assistant__source-status--fallback" role="note">
          <WarningCircle size={18} weight="fill" aria-hidden="true" />
          <div>
            <strong>{isZh ? '服务端确定性回退文本' : 'Server deterministic fallback text'}</strong>
            <span>{isZh
              ? '模型候选未通过语义校验。本段由服务器根据已计算结果和固定模板生成，不是模型输出。'
              : 'The model candidate did not pass semantic validation. This text was generated by the server from computed results and a fixed template; it is not model output.'}</span>
          </div>
        </div>
      ) : message.semanticValidationStatus ? (
        <div className="result-assistant__source-status" role="note">
          <div>
            <strong>{message.semanticValidationStatus === 'REPAIRED'
              ? isZh ? '经修复并校验的模型解释' : 'Repaired and validated model interpretation'
              : isZh ? '已校验的模型解释' : 'Validated model interpretation'}</strong>
            <span>{isZh
              ? '本段来自所示模型，并已通过服务器结构与证据语义校验。'
              : 'This text came from the displayed model and passed server structure and evidence-semantic validation.'}</span>
          </div>
        </div>
      ) : null}
      <div className="result-assistant__fixed-boundary" role="note">
        <WarningCircle size={18} weight="fill" aria-hidden="true" />
        <strong>{boundaryStart}</strong>
      </div>
      {humanReadableAnswer ? (
        <SafeMarkdown
          className="result-assistant__answer"
          content={humanReadableAnswer}
          citationNumbering={audit.numbering}
          renderCitation={renderCitation}
          formatCitationLabel={formatCitationLabel}
        />
      ) : null}
      <p className="result-assistant__fixed-boundary-end">
        {t('results.assistantBoundaryEnd')}
      </p>

      {message.analysisSummary ? (
        <details className="result-assistant__disclosure">
          <summary>{isZh ? '分析摘要（不是思维链）' : 'Analysis summary (not chain-of-thought)'}</summary>
          <SafeMarkdown
            className="result-assistant__analysis-summary"
            content={humanReadableAnalysisSummary}
            citationNumbering={audit.numbering}
            renderCitation={renderCitation}
            formatCitationLabel={formatCitationLabel}
          />
        </details>
      ) : null}

      {audit.issues.length > 0 ? (
        <div className="result-assistant__evidence-warning" role="alert">
          <WarningCircle size={18} weight="fill" aria-hidden="true" />
          <div>
            <strong>{isZh ? '部分证据引用无法完整核对' : 'Some evidence references could not be fully reconciled'}</strong>
            <span>{isZh
              ? '回答仍按服务器原文显示；请在下方技术详情中核对缺失、旧版或不匹配的引用。'
              : 'The validated server text remains visible. Review missing, legacy, or mismatched references in the technical details below.'}</span>
          </div>
        </div>
      ) : null}

      {(visibleCitations.length > 0 || message.toolActivity.length > 0) ? (
        <details ref={evidenceDetailsRef} className="result-assistant__evidence">
          <summary>
            <BookOpenText size={16} aria-hidden="true" />
            {isZh ? '证据依据' : 'Evidence used'}
            <span>{visibleCitations.length}</span>
          </summary>
          {visibleCitations.length > 0 ? (
            <ol className="result-assistant__evidence-list">
              {visibleCitations.map((citation) => {
                const evidence = getLocalizedResultEvidence(citation.evidenceId, language);
                const secondaryEvidence = getLocalizedResultEvidence(
                  citation.evidenceId,
                  secondaryLanguage,
                );
                const canLocate = Boolean(
                  evidence.known
                  && evidence.view
                  && evidence.target
                  && citation.toolActivityPresent
                  && citation.itemCount > 0,
                );
                return (
                  <li
                    key={citation.evidenceId}
                    ref={setEvidenceItemRef(citation.evidenceId)}
                    tabIndex={-1}
                    className={!citation.known ? 'is-legacy' : undefined}
                  >
                    <span className="result-assistant__evidence-number" aria-hidden="true">
                      {citation.number ?? '·'}
                    </span>
                    <div>
                      <strong>
                        {evidence.label}
                        <span className="result-assistant__evidence-secondary-label">
                          {secondaryEvidence.label}
                        </span>
                      </strong>
                      <p>{evidence.description}</p>
                      <small>{evidenceStatusText(citation, isZh)}</small>
                    </div>
                    <Button
                      kind="ghost"
                      size="sm"
                      renderIcon={ArrowRight}
                      disabled={!canLocate}
                      onClick={() => locateEvidence(citation)}
                    >
                      {canLocate
                        ? isZh ? '查看对应结果' : 'View result section'
                        : isZh ? '当前无法定位' : 'Location unavailable'}
                    </Button>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="result-assistant__evidence-empty">
              {isZh
                ? '这条历史回答没有可编号的正文引用；已读取区段仍保留在技术详情中。'
                : 'This historical answer has no inline references to number. Inspected sections remain available in technical details.'}
            </p>
          )}

          <details className="result-assistant__technical-evidence">
            <summary>{isZh ? '技术详情' : 'Technical details'}</summary>
            {audit.issues.length > 0 ? (
              <div className="result-assistant__technical-alerts">
                <strong>{isZh ? '优先核对的异常' : 'Issues to review first'}</strong>
                <ul>
                  {[...new Set(audit.issues)].map((issue) => (
                    <li key={issue}>{integrityIssueLabel(issue, isZh)}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="result-assistant__technical-ok">
                {isZh ? '未发现证据引用完整性异常。' : 'No evidence-reference integrity issue was found.'}
              </p>
            )}
            {audit.unreferencedToolActivity.length > 0 ? (
              <p className="result-assistant__unreferenced-summary">
                <strong>{isZh ? '已读取但未引用：' : 'Inspected but not cited:'}</strong>{' '}
                {isZh
                  ? `${audit.unreferencedToolActivity.length} 个结果区段`
                  : `${audit.unreferencedToolActivity.length} result section(s)`}
              </p>
            ) : null}
            {answerTechnicalCodes.length > 0 ? (
              <div className="result-assistant__technical-codes">
                <strong>{isZh ? '回答中已转换的技术状态' : 'Technical statuses translated in the answer'}</strong>
                <TechnicalCodeDisplay codes={answerTechnicalCodes} language={language} />
              </div>
            ) : null}
            <ul>
              {audit.citations
                .filter((citation) => citation.inline || citation.groundingListed)
                .map((citation) => {
                  const activity = message.toolActivity.filter(
                    (item) => item.evidenceId === citation.evidenceId,
                  );
                  const definition = getLocalizedResultEvidence(citation.evidenceId, language);
                  const channelSummary = [
                    citation.inline
                      ? isZh ? '正文已引用' : 'cited in answer'
                      : isZh ? '正文未引用' : 'not cited in answer',
                    citation.groundingListed
                      ? isZh ? '引用集合已列出' : 'listed in grounding set'
                      : isZh ? '引用集合缺失' : 'missing from grounding set',
                    activity.length > 0
                      ? activity.map((item) => item.tool).join(', ')
                      : isZh ? '无工具记录' : 'no tool activity',
                  ];
                  if (!citation.toolMatchesDefinition && definition.tool) {
                    channelSummary.push(
                      isZh
                        ? `预期工具 ${definition.tool}`
                        : `expected tool ${definition.tool}`,
                    );
                  }
                  return (
                    <li key={citation.evidenceId}>
                      <code>{citation.evidenceId}</code>
                      <span>{channelSummary.join(' · ')}</span>
                    </li>
                  );
                })}
            </ul>
            <Button
              kind="tertiary"
              size="sm"
              renderIcon={DownloadSimple}
              onClick={downloadAudit}
            >
              {isZh ? '下载审计 JSON' : 'Download audit JSON'}
            </Button>
          </details>
        </details>
      ) : null}
    </>
  );
}
