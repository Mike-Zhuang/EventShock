import { Button, InlineNotification } from '@carbon/react';
import {
  FloppyDiskBack,
  Moon,
  Printer,
  ShieldCheck,
  SignOut,
  Sun,
} from '@phosphor-icons/react';
import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError } from '../api/client';
import type { LegalDocument } from '../api/types';
import { LoadingPanel } from '../components/common';
import { LegalDocumentContent } from '../components/legal-document-content';
import { useI18n } from '../i18n';
import { useAuth } from '../state/auth-context';

export function LegalAcceptancePage({
  isDark,
  onToggleTheme,
}: {
  isDark: boolean;
  onToggleTheme: () => void;
}) {
  const { language, setLanguage, t } = useI18n();
  const { user, acceptLegalDocuments, logout } = useAuth();
  const [document, setDocument] = useState<LegalDocument>();
  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [acknowledgedPrivacy, setAcknowledgedPrivacy] = useState(false);
  const [acknowledgedAgeAndAi, setAcknowledgedAgeAndAi] = useState(false);
  const [busy, setBusy] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string>();
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setDocument(undefined);
    setError(undefined);
    setAcceptedTerms(false);
    setAcknowledgedPrivacy(false);
    setAcknowledgedAgeAndAi(false);
    void api.getLegalDocument(language)
      .then((nextDocument) => {
        if (active) setDocument(nextDocument);
      })
      .catch(() => {
        if (active) setError(t('legal.loadFailed'));
      });
    return () => {
      active = false;
    };
  }, [language, reloadKey, t]);

  const allAccepted = acceptedTerms && acknowledgedPrivacy && acknowledgedAgeAndAi;

  const submitAcceptance = async (event: FormEvent) => {
    event.preventDefault();
    if (!document || !allAccepted) {
      setError(t('legal.acceptAll'));
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      await acceptLegalDocuments({
        language,
        version: document.version,
        documentHash: document.documentHash,
        acceptedTerms,
        acknowledgedPrivacy,
        confirmedMinimumAge: acknowledgedAgeAndAi,
        acknowledgedAiBoundary: acknowledgedAgeAndAi,
      });
    } catch (acceptanceError) {
      if (acceptanceError instanceof ApiError && acceptanceError.code === 'LEGAL_DOCUMENT_VERSION_STALE') {
        setError(t('legal.stale'));
        setReloadKey((current) => current + 1);
      } else {
        setError(t('legal.acceptFailed'));
      }
    } finally {
      setBusy(false);
    }
  };

  const signOut = async () => {
    setSigningOut(true);
    setError(undefined);
    try {
      await logout();
    } catch {
      setError(t('app.signOutFailedBody'));
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <div className="legal-gate-shell">
      <header className="auth-topbar legal-gate-topbar">
        <div className="topbar__brand">
          <div className="brand-mark" aria-hidden="true">
            <FloppyDiskBack size={22} weight="duotone" />
          </div>
          <div><strong>{t('app.name')}</strong><span>{t('app.workspace')}</span></div>
        </div>
        <div className="legal-gate-account">
          <span>{user?.email}</span>
          <div className="language-toggle" role="group" aria-label={t('app.language')}>
            <button type="button" className={language === 'en' ? 'is-active' : ''} onClick={() => setLanguage('en')}>EN</button>
            <button type="button" className={language === 'zh-CN' ? 'is-active' : ''} onClick={() => setLanguage('zh-CN')}>中文</button>
          </div>
          <button type="button" className="auth-theme-button" aria-label={isDark ? t('app.themeLight') : t('app.themeDark')} onClick={onToggleTheme}>
            {isDark ? <Sun size={19} /> : <Moon size={19} />}
          </button>
        </div>
      </header>

      <main className="legal-gate-main">
        <header className="legal-gate-heading">
          <span className="eyebrow"><ShieldCheck size={18} weight="duotone" />{t('legal.gateEyebrow')}</span>
          <h1>{t('legal.gateTitle')}</h1>
          <p>{t('legal.gateBody')}</p>
          <div className="legal-gate-heading__actions">
            <Button kind="secondary" size="sm" renderIcon={Printer} onClick={() => window.print()}>
              {t('legal.print')}
            </Button>
            <Button kind="ghost" size="sm" renderIcon={SignOut} disabled={signingOut} onClick={() => void signOut()}>
              {signingOut ? t('app.signingOut') : t('app.signOut')}
            </Button>
          </div>
        </header>

        {error ? (
          <InlineNotification
            kind="error"
            lowContrast
            hideCloseButton
            title={t('legal.requestFailed')}
            subtitle={error}
          />
        ) : null}

        {!document && !error ? (
          <LoadingPanel />
        ) : null}
        {!document && error ? (
          <Button kind="ghost" onClick={() => setReloadKey((current) => current + 1)}>
            {t('common.retry')}
          </Button>
        ) : null}
        {document ? (
          <>
            <LegalDocumentContent document={document} />
            <form className="legal-acceptance-form" onSubmit={(event) => void submitAcceptance(event)}>
              <div className="legal-acceptance-form__heading">
                <h2>{t('legal.acceptanceHeading')}</h2>
                <p>{t('legal.acceptanceBody')}</p>
              </div>
              <label className="consent-control">
                <input type="checkbox" checked={acceptedTerms} onChange={(event) => setAcceptedTerms(event.target.checked)} />
                <span>{document.acceptanceStatements[0] ?? t('legal.acceptTerms')}</span>
              </label>
              <label className="consent-control">
                <input type="checkbox" checked={acknowledgedPrivacy} onChange={(event) => setAcknowledgedPrivacy(event.target.checked)} />
                <span>{t('legal.acceptPrivacy')}</span>
              </label>
              <label className="consent-control">
                <input type="checkbox" checked={acknowledgedAgeAndAi} onChange={(event) => setAcknowledgedAgeAndAi(event.target.checked)} />
                <span>{t('legal.acceptAgeAndAi', { value: document.minimumAge })}</span>
              </label>
              <Button type="submit" disabled={busy || !allAccepted}>
                {busy ? t('legal.accepting') : t('legal.acceptAndContinue')}
              </Button>
            </form>
          </>
        ) : null}
      </main>
    </div>
  );
}
