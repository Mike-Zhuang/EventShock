import type { LegalDocument } from '../api/types';

export function LegalDocumentContent({
  document,
  compact = false,
}: {
  document: LegalDocument;
  compact?: boolean;
}) {
  return (
    <article className={`legal-document${compact ? ' legal-document--compact' : ''}`}>
      <header className="legal-document__header">
        {compact
          ? <h4 className="legal-document__title">{document.title}</h4>
          : <h2 className="legal-document__title">{document.title}</h2>}
        <p>{document.summary}</p>
        <dl className="legal-document__metadata">
          <div>
            <dt>{document.locale === 'zh-CN' ? '版本' : 'Version'}</dt>
            <dd>{document.version}</dd>
          </div>
          <div>
            <dt>{document.locale === 'zh-CN' ? '生效日期' : 'Effective date'}</dt>
            <dd>{document.effectiveDate}</dd>
          </div>
          <div>
            <dt>{document.locale === 'zh-CN' ? '运营方' : 'Operator'}</dt>
            <dd>{document.operatorLabel}</dd>
          </div>
        </dl>
      </header>
      <div className="legal-document__sections">
        {document.sections.map((section) => (
          <section key={section.id} id={`legal-${section.id}`}>
            {compact ? <h5>{section.title}</h5> : <h3>{section.title}</h3>}
            {section.body.map((paragraph, index) => (
              <p key={`${section.id}-${index}`}>{paragraph}</p>
            ))}
          </section>
        ))}
      </div>
      <aside className="legal-document__review-notice">
        <strong>{document.locale === 'zh-CN' ? '法律审阅提示' : 'Legal review notice'}</strong>
        <p>{document.legalReviewNotice}</p>
      </aside>
    </article>
  );
}
