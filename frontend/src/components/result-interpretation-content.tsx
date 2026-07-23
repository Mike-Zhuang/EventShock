import { Button } from '@carbon/react';
import {
  ArrowRight,
  BookOpenText,
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
} from './result-evidence';
import { SafeMarkdown } from './safe-markdown';

interface ResultInterpretationContentProps {
  experimentId: string;
  message: ResultInterpretationAssistantMessage;
  navigate: Navigate;
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
  const { language } = useI18n();
  const isZh = language === 'zh-CN';
  const secondaryLanguage = isZh ? 'en' : 'zh-CN';
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
      <SafeMarkdown
        className="result-assistant__answer"
        content={message.answer}
        citationNumbering={audit.numbering}
        renderCitation={renderCitation}
        formatCitationLabel={formatCitationLabel}
      />

      {message.analysisSummary ? (
        <details className="result-assistant__disclosure">
          <summary>{isZh ? '分析摘要（不是思维链）' : 'Analysis summary (not chain-of-thought)'}</summary>
          <SafeMarkdown
            className="result-assistant__analysis-summary"
            content={message.analysisSummary}
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
              {audit.unreferencedToolActivity.map((evidenceId) => {
                const activity = message.toolActivity.filter((item) => item.evidenceId === evidenceId);
                return (
                  <li key={`uncited-${evidenceId}`}>
                    <code>{evidenceId}</code>
                    <span>{isZh ? '已读取但未在回答中引用' : 'Inspected but not cited'}: {' '}
                      {activity.map((item) => item.tool).join(', ')}</span>
                  </li>
                );
              })}
            </ul>
          </details>
        </details>
      ) : null}
    </>
  );
}
