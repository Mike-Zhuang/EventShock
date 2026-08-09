import { Button, InlineNotification } from '@carbon/react';
import {
  ArrowRight,
  FloppyDiskBack,
  Moon,
  SignOut,
  Sparkle,
  Sun,
  UserFocus,
} from '@phosphor-icons/react';
import { useMemo, useState, type FormEvent } from 'react';
import type {
  AssistancePreference,
  ExperienceLevel,
  FirstGoal,
  WorkspaceMode,
} from '../api/types';
import { useI18n } from '../i18n';
import { useAuth } from '../state/auth-context';

interface ChoiceOption<T extends string> {
  value: T;
  label: string;
  description: string;
}

function ChoiceGroup<T extends string>({
  name,
  legend,
  body,
  value,
  options,
  onChange,
}: {
  name: string;
  legend: string;
  body: string;
  value?: T;
  options: ChoiceOption<T>[];
  onChange: (value: T) => void;
}) {
  return (
    <fieldset className="onboarding-question">
      <legend>{legend}</legend>
      <p>{body}</p>
      <div className="onboarding-options">
        {options.map((option) => (
          <label key={option.value} className={value === option.value ? 'is-selected' : ''}>
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            <span>
              <strong>{option.label}</strong>
              <small>{option.description}</small>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function OnboardingPage({
  isDark,
  onToggleTheme,
}: {
  isDark: boolean;
  onToggleTheme: () => void;
}) {
  const { language, setLanguage, t } = useI18n();
  const { user, completeOnboarding, logout } = useAuth();
  const [experienceLevel, setExperienceLevel] = useState<ExperienceLevel>();
  const [assistancePreference, setAssistancePreference] = useState<AssistancePreference>();
  const [firstGoal, setFirstGoal] = useState<FirstGoal>();
  const [workspaceMode, setWorkspaceMode] = useState<WorkspaceMode>();
  const [busy, setBusy] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string>();

  const experienceOptions = useMemo<ChoiceOption<ExperienceLevel>[]>(() => [
    { value: 'NEW', label: t('onboarding.experienceNew'), description: t('onboarding.experienceNewBody') },
    { value: 'INTERMEDIATE', label: t('onboarding.experienceIntermediate'), description: t('onboarding.experienceIntermediateBody') },
    { value: 'ADVANCED', label: t('onboarding.experienceAdvanced'), description: t('onboarding.experienceAdvancedBody') },
  ], [t]);
  const assistanceOptions = useMemo<ChoiceOption<AssistancePreference>[]>(() => [
    { value: 'STEP_BY_STEP', label: t('onboarding.assistanceStep'), description: t('onboarding.assistanceStepBody') },
    { value: 'PROPOSE_AND_ADJUST', label: t('onboarding.assistancePropose'), description: t('onboarding.assistanceProposeBody') },
    { value: 'DIRECT_CONTROL', label: t('onboarding.assistanceDirect'), description: t('onboarding.assistanceDirectBody') },
  ], [t]);
  const goalOptions = useMemo<ChoiceOption<FirstGoal>[]>(() => [
    { value: 'TRY_DEMO', label: t('onboarding.goalDemo'), description: t('onboarding.goalDemoBody') },
    { value: 'RESEARCH_NEW_EVENT', label: t('onboarding.goalResearch'), description: t('onboarding.goalResearchBody') },
    { value: 'DESIGN_FULL_EXPERIMENT', label: t('onboarding.goalExperiment'), description: t('onboarding.goalExperimentBody') },
  ], [t]);
  const modeOptions = useMemo<ChoiceOption<WorkspaceMode>[]>(() => [
    { value: 'GUIDED', label: t('onboarding.modeGuided'), description: t('onboarding.modeGuidedBody') },
    { value: 'EXPERT', label: t('onboarding.modeExpert'), description: t('onboarding.modeExpertBody') },
  ], [t]);

  const recommendation: WorkspaceMode | undefined = !experienceLevel || !assistancePreference
    ? undefined
    : experienceLevel === 'NEW' || assistancePreference === 'STEP_BY_STEP'
      ? 'GUIDED'
      : 'EXPERT';
  const complete = Boolean(experienceLevel && assistancePreference && firstGoal && workspaceMode);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!experienceLevel || !assistancePreference || !firstGoal || !workspaceMode) {
      setError(t('onboarding.missing'));
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      await completeOnboarding({
        experienceLevel,
        workspaceMode,
        assistancePreference,
        firstGoal,
      });
      // 研究工作台是高级验证工具，不应成为首次登录后的默认入口。
      // 专家仍可从侧栏直接进入，但登录后先恢复/开始完整实验主流程。
      window.history.replaceState(null, '', '#/guided');
    } catch {
      setError(t('onboarding.saveFailed'));
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
    <div className="onboarding-shell">
      <header className="auth-topbar">
        <div className="topbar__brand">
          <div className="brand-mark" aria-hidden="true"><FloppyDiskBack size={22} weight="duotone" /></div>
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
          <Button kind="ghost" size="sm" renderIcon={SignOut} disabled={signingOut} onClick={() => void signOut()}>
            {signingOut ? t('app.signingOut') : t('app.signOut')}
          </Button>
        </div>
      </header>

      <main className="onboarding-main">
        <header className="onboarding-heading">
          <span className="eyebrow"><UserFocus size={18} weight="duotone" />{t('onboarding.eyebrow')}</span>
          <h1>{t('onboarding.title')}</h1>
          <p>{t('onboarding.body')}</p>
          <p className="onboarding-heading__boundary">{t('onboarding.useBoundary')}</p>
        </header>

        {error ? (
          <InlineNotification
            kind="error"
            lowContrast
            hideCloseButton
            title={t('onboarding.requestFailed')}
            subtitle={error}
          />
        ) : null}

        <form className="onboarding-form" onSubmit={(event) => void submit(event)}>
          <ChoiceGroup
            name="experience"
            legend={t('onboarding.experienceLegend')}
            body={t('onboarding.experienceBody')}
            value={experienceLevel}
            options={experienceOptions}
            onChange={setExperienceLevel}
          />
          <ChoiceGroup
            name="assistance"
            legend={t('onboarding.assistanceLegend')}
            body={t('onboarding.assistanceBody')}
            value={assistancePreference}
            options={assistanceOptions}
            onChange={setAssistancePreference}
          />
          <ChoiceGroup
            name="goal"
            legend={t('onboarding.goalLegend')}
            body={t('onboarding.goalBody')}
            value={firstGoal}
            options={goalOptions}
            onChange={setFirstGoal}
          />

          {recommendation ? (
            <aside className="onboarding-recommendation">
              <Sparkle size={24} weight="duotone" aria-hidden="true" />
              <div>
                <strong>{t('onboarding.recommendation')}</strong>
                <p>{recommendation === 'GUIDED' ? t('onboarding.recommendGuided') : t('onboarding.recommendExpert')}</p>
              </div>
            </aside>
          ) : null}

          <ChoiceGroup
            name="workspace-mode"
            legend={t('onboarding.modeLegend')}
            body={t('onboarding.modeBody')}
            value={workspaceMode}
            options={modeOptions}
            onChange={setWorkspaceMode}
          />
          <div className="onboarding-submit">
            <p>{t('onboarding.changeLater')}</p>
            <Button type="submit" renderIcon={ArrowRight} disabled={busy || !complete}>
              {busy ? t('onboarding.saving') : t('onboarding.continue')}
            </Button>
          </div>
        </form>
      </main>
    </div>
  );
}
