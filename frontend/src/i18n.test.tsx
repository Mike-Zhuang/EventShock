import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { I18nProvider, useI18n } from './i18n';

function LanguageProbe() {
  const { language, setLanguage, t } = useI18n();
  return (
    <div>
      <span>{language}</span>
      <strong>{t('nav.cases')}</strong>
      <button type="button" onClick={() => setLanguage('zh-CN')}>中文</button>
    </div>
  );
}

describe('I18nProvider', () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.lang = '';
  });

  it('defaults to English and switches language without reloading state', async () => {
    const user = userEvent.setup();
    render(<I18nProvider><LanguageProbe /></I18nProvider>);
    expect(screen.getByText('Case Library')).toBeInTheDocument();
    expect(screen.getByText('en')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '中文' }));

    expect(screen.getByText('案例库')).toBeInTheDocument();
    expect(screen.getByText('zh-CN')).toBeInTheDocument();
    expect(window.localStorage.getItem('eventshock-language')).toBe('zh-CN');
    expect(document.documentElement.lang).toBe('zh-CN');
  });

  it('restores Simplified Chinese from localStorage', () => {
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    render(<I18nProvider><LanguageProbe /></I18nProvider>);
    expect(screen.getByText('案例库')).toBeInTheDocument();
  });
});
