import {
  Button,
  InlineNotification,
  PasswordInput,
  TextInput,
} from '@carbon/react';
import {
  ArrowLeft,
  ArrowRight,
  EnvelopeSimple,
  FloppyDiskBack,
  Flask,
  Moon,
  ShieldCheck,
  Sun,
  UsersThree,
} from '@phosphor-icons/react';
import { useEffect, useState, type FormEvent } from 'react';
import { ApiError } from '../api/client';
import type { VerificationPurpose } from '../api/types';
import {
  GITHUB_ISSUE_CHOOSER_URL,
  GITHUB_REPOSITORY_URL,
} from '../external-links';
import { useI18n } from '../i18n';
import { useAuth } from '../state/auth-context';

type AuthenticationMode = 'login' | 'register' | 'reset';
type VerificationStage = 'details' | 'code';

function isEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export function AuthenticationPage({
  isDark,
  onToggleTheme,
}: {
  isDark: boolean;
  onToggleTheme: () => void;
}) {
  const { language, setLanguage, t } = useI18n();
  const {
    error: sessionError,
    login,
    register,
    requestVerificationCode,
    resetPassword,
    refreshSession,
  } = useAuth();
  const [mode, setMode] = useState<AuthenticationMode>('login');
  const [stage, setStage] = useState<VerificationStage>('details');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [verificationCode, setVerificationCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [cooldown, setCooldown] = useState(0);
  const [expiresInSeconds, setExpiresInSeconds] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setInterval(() => {
      setCooldown((current) => Math.max(0, current - 1));
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [cooldown]);

  const switchMode = (nextMode: AuthenticationMode) => {
    setMode(nextMode);
    setStage('details');
    setPassword('');
    setConfirmPassword('');
    setVerificationCode('');
    setFormError(undefined);
    setNotice(undefined);
    setCooldown(0);
    setExpiresInSeconds(0);
  };

  const safeErrorMessage = (error: unknown): string => {
    if (!(error instanceof ApiError)) return t('auth.errorGeneric');
    if (error.status === 401 || error.code === 'INVALID_CREDENTIALS') return t('auth.errorCredentials');
    if (error.status === 429 || error.code === 'RATE_LIMITED') return t('auth.errorRateLimit');
    if (error.status === 409 || error.code === 'EMAIL_ALREADY_REGISTERED') return t('auth.errorAccountExists');
    if (error.code?.includes('VERIFICATION') || error.code?.includes('CODE')) return t('auth.errorCode');
    return t('auth.errorGeneric');
  };

  const validateEmail = (): boolean => {
    if (isEmail(email.trim())) return true;
    setFormError(t('auth.errorEmail'));
    return false;
  };

  const validatePassword = (): boolean => {
    if (password.length < 8) {
      setFormError(t('auth.errorPasswordLength'));
      return false;
    }
    if (password !== confirmPassword) {
      setFormError(t('auth.errorPasswordMatch'));
      return false;
    }
    return true;
  };

  const requestCode = async (purpose: VerificationPurpose) => {
    if (!validateEmail()) return;
    if (purpose === 'REGISTER' && !validatePassword()) return;
    setBusy(true);
    setFormError(undefined);
    setNotice(undefined);
    try {
      const receipt = await requestVerificationCode(email.trim(), purpose, language);
      setCooldown(Math.max(0, Math.round(receipt.retryAfterSeconds)));
      setExpiresInSeconds(Math.max(0, Math.round(receipt.expiresInSeconds)));
      setStage('code');
      setNotice(t('auth.codeSent'));
    } catch (error) {
      setFormError(safeErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const submitLogin = async (event: FormEvent) => {
    event.preventDefault();
    if (!validateEmail() || !password) {
      if (!password) setFormError(t('auth.errorPasswordRequired'));
      return;
    }
    setBusy(true);
    setFormError(undefined);
    try {
      await login(email.trim(), password, language);
    } catch (error) {
      setFormError(safeErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const submitRegistration = async (event: FormEvent) => {
    event.preventDefault();
    if (!/^\d{6}$/.test(verificationCode)) {
      setFormError(t('auth.errorCode'));
      return;
    }
    setBusy(true);
    setFormError(undefined);
    try {
      await register(email.trim(), password, verificationCode, language);
    } catch (error) {
      setFormError(safeErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const submitReset = async (event: FormEvent) => {
    event.preventDefault();
    if (!validatePassword() || !/^\d{6}$/.test(verificationCode)) {
      if (!/^\d{6}$/.test(verificationCode)) setFormError(t('auth.errorCode'));
      return;
    }
    setBusy(true);
    setFormError(undefined);
    try {
      await resetPassword(email.trim(), password, verificationCode, language);
      switchMode('login');
      setNotice(t('auth.resetSuccess'));
    } catch (error) {
      setFormError(safeErrorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const renderCodeStatus = (purpose: VerificationPurpose) => (
    <div className="auth-code-status">
      <EnvelopeSimple size={20} weight="duotone" aria-hidden="true" />
      <div>
        <strong>{t('auth.codeSentTo')}</strong>
        <span>{email.trim()}</span>
        {expiresInSeconds > 0 ? (
          <small>{t('auth.codeExpires', { value: Math.ceil(expiresInSeconds / 60) })}</small>
        ) : null}
      </div>
      <Button
        type="button"
        kind="ghost"
        size="sm"
        disabled={busy || cooldown > 0}
        onClick={() => void requestCode(purpose)}
      >
        {cooldown > 0 ? t('auth.resendCountdown', { value: cooldown }) : t('auth.resend')}
      </Button>
    </div>
  );

  const renderPasswordFields = (includeCurrentAutocomplete = false) => (
    <>
      <PasswordInput
        id={`${mode}-password`}
        labelText={mode === 'login' ? t('auth.password') : t('auth.newPassword')}
        helperText={mode === 'login' ? undefined : t('auth.passwordHint')}
        value={password}
        maxLength={128}
        autoComplete={includeCurrentAutocomplete ? 'current-password' : 'new-password'}
        required
        onChange={(event) => setPassword(event.target.value)}
      />
      {mode !== 'login' ? (
        <PasswordInput
          id={`${mode}-confirm-password`}
          labelText={t('auth.confirmPassword')}
          value={confirmPassword}
          maxLength={128}
          autoComplete="new-password"
          required
          onChange={(event) => setConfirmPassword(event.target.value)}
        />
      ) : null}
    </>
  );

  return (
    <div className="auth-shell">
      <header className="auth-topbar">
        <div className="topbar__brand">
          <div className="brand-mark" aria-hidden="true"><FloppyDiskBack size={22} weight="duotone" /></div>
          <div><strong>{t('app.name')}</strong><span>{t('app.workspace')}</span></div>
        </div>
        <div className="topbar__controls">
          <div className="language-toggle" role="group" aria-label={t('app.language')}>
            <button type="button" className={language === 'en' ? 'is-active' : ''} onClick={() => setLanguage('en')}>EN</button>
            <button type="button" className={language === 'zh-CN' ? 'is-active' : ''} onClick={() => setLanguage('zh-CN')}>中文</button>
          </div>
          <button type="button" className="auth-theme-button" aria-label={isDark ? t('app.themeLight') : t('app.themeDark')} onClick={onToggleTheme}>
            {isDark ? <Sun size={19} /> : <Moon size={19} />}
          </button>
        </div>
      </header>

      <main className="auth-main">
        <section className="auth-intro" aria-labelledby="auth-product-title">
          <div>
            <span className="eyebrow">{t('auth.eyebrow')}</span>
            <h1 id="auth-product-title">{t('auth.productTitle')}</h1>
            <p>{t('auth.productBody')}</p>
          </div>
          <section className="home-audience" aria-labelledby="auth-audience-title">
            <div className="home-audience__label"><UsersThree size={20} weight="duotone" /><span>{t('home.audienceLabel')}</span></div>
            <div><h2 id="auth-audience-title">{t('home.audienceTitle')}</h2><p>{t('home.audienceBody')}</p></div>
          </section>
          <div className="auth-guardrails">
            <div><ShieldCheck size={21} weight="duotone" /><span>{t('home.disclaimerForecast')}</span></div>
            <div><Flask size={21} weight="duotone" /><span>{t('home.disclaimerSynthetic')}</span></div>
          </div>
        </section>

        <section className="auth-panel" aria-labelledby="auth-form-title">
          <div className="auth-panel__heading">
            <span>{mode === 'login' ? t('auth.signInLabel') : mode === 'register' ? t('auth.registerLabel') : t('auth.resetLabel')}</span>
            <h2 id="auth-form-title">{mode === 'login' ? t('auth.signInTitle') : mode === 'register' ? t('auth.registerTitle') : t('auth.resetTitle')}</h2>
            <p>{mode === 'login' ? t('auth.signInBody') : mode === 'register' ? t('auth.registerBody') : t('auth.resetBody')}</p>
          </div>

          {sessionError ? (
            <div className="auth-session-error">
              <InlineNotification
                kind="error"
                lowContrast
                hideCloseButton
                title={t('auth.sessionCheckFailed')}
                subtitle={t('auth.sessionCheckFailedBody')}
              />
              <Button kind="ghost" size="sm" onClick={() => void refreshSession()}>{t('common.retry')}</Button>
            </div>
          ) : null}
          {formError ? <InlineNotification kind="error" lowContrast hideCloseButton title={t('auth.requestFailed')} subtitle={formError} /> : null}
          {notice ? <InlineNotification kind="success" lowContrast hideCloseButton title={t('auth.notice')} subtitle={notice} /> : null}

          {mode === 'login' ? (
            <form className="auth-form" onSubmit={(event) => void submitLogin(event)}>
              <TextInput id="login-email" type="email" labelText={t('auth.email')} value={email} autoComplete="email" required onChange={(event) => setEmail(event.target.value)} />
              {renderPasswordFields(true)}
              <Button type="submit" renderIcon={ArrowRight} disabled={busy}>{busy ? t('auth.signingIn') : t('auth.signIn')}</Button>
              <div className="auth-form__links">
                <button type="button" onClick={() => switchMode('reset')}>{t('auth.forgotPassword')}</button>
                <button type="button" onClick={() => switchMode('register')}>{t('auth.createAccount')}</button>
              </div>
            </form>
          ) : null}

          {mode === 'register' && stage === 'details' ? (
            <form className="auth-form" onSubmit={(event) => { event.preventDefault(); void requestCode('REGISTER'); }}>
              <TextInput id="register-email" type="email" labelText={t('auth.email')} value={email} autoComplete="email" required onChange={(event) => setEmail(event.target.value)} />
              {renderPasswordFields()}
              <Button type="submit" renderIcon={EnvelopeSimple} disabled={busy}>{busy ? t('auth.sendingCode') : t('auth.sendCode')}</Button>
              <button type="button" className="auth-back-link" onClick={() => switchMode('login')}><ArrowLeft size={16} />{t('auth.backToLogin')}</button>
            </form>
          ) : null}

          {mode === 'register' && stage === 'code' ? (
            <form className="auth-form" onSubmit={(event) => void submitRegistration(event)}>
              {renderCodeStatus('REGISTER')}
              <TextInput id="register-code" labelText={t('auth.verificationCode')} value={verificationCode} inputMode="numeric" autoComplete="one-time-code" maxLength={6} required onChange={(event) => setVerificationCode(event.target.value.replace(/\D/g, '').slice(0, 6))} />
              <Button type="submit" renderIcon={ArrowRight} disabled={busy}>{busy ? t('auth.creatingAccount') : t('auth.completeRegistration')}</Button>
              <button type="button" className="auth-back-link" onClick={() => setStage('details')}><ArrowLeft size={16} />{t('auth.changeDetails')}</button>
            </form>
          ) : null}

          {mode === 'reset' && stage === 'details' ? (
            <form className="auth-form" onSubmit={(event) => { event.preventDefault(); void requestCode('RESET_PASSWORD'); }}>
              <TextInput id="reset-email" type="email" labelText={t('auth.email')} value={email} autoComplete="email" required onChange={(event) => setEmail(event.target.value)} />
              <Button type="submit" renderIcon={EnvelopeSimple} disabled={busy}>{busy ? t('auth.sendingCode') : t('auth.sendResetCode')}</Button>
              <button type="button" className="auth-back-link" onClick={() => switchMode('login')}><ArrowLeft size={16} />{t('auth.backToLogin')}</button>
            </form>
          ) : null}

          {mode === 'reset' && stage === 'code' ? (
            <form className="auth-form" onSubmit={(event) => void submitReset(event)}>
              {renderCodeStatus('RESET_PASSWORD')}
              <TextInput id="reset-code" labelText={t('auth.verificationCode')} value={verificationCode} inputMode="numeric" autoComplete="one-time-code" maxLength={6} required onChange={(event) => setVerificationCode(event.target.value.replace(/\D/g, '').slice(0, 6))} />
              {renderPasswordFields()}
              <Button type="submit" renderIcon={ArrowRight} disabled={busy}>{busy ? t('auth.resettingPassword') : t('auth.resetPassword')}</Button>
              <button type="button" className="auth-back-link" onClick={() => setStage('details')}><ArrowLeft size={16} />{t('auth.changeEmail')}</button>
            </form>
          ) : null}

          <div className="auth-privacy">
            <ShieldCheck size={19} weight="duotone" aria-hidden="true" />
            <p>{t('auth.privacy')}</p>
          </div>
        </section>
      </main>

      <footer className="auth-footer">
        <p>{t('footer.copyright')}</p>
        <p>
          {t('footer.license')}{' '}
          <a href={GITHUB_REPOSITORY_URL} target="_blank" rel="noopener noreferrer">
            {t('footer.github')}
          </a>{' · '}
          <a href={GITHUB_ISSUE_CHOOSER_URL} target="_blank" rel="noopener noreferrer">
            {t('footer.issue')}
          </a>
        </p>
        <p>{t('footer.disclaimer')}</p>
      </footer>
    </div>
  );
}
