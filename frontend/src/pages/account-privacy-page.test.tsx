import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  api,
  AUTH_SESSION_EXPIRED_EVENT,
} from '../api/client';
import type { AccountDataExport } from '../api/types';
import { I18nProvider } from '../i18n';
import { AccountPrivacyPage } from './account-privacy-page';

vi.mock('../api/client', () => ({
  AUTH_SESSION_EXPIRED_EVENT: 'eventshock:auth-session-expired',
  ApiError: class MockApiError extends Error {
    status: number;
    code?: string;

    constructor(message: string, status: number, _detail?: string, code?: string) {
      super(message);
      this.status = status;
      this.code = code;
    }
  },
  api: {
    exportAccountData: vi.fn(),
    deleteAccount: vi.fn(),
  },
}));

vi.mock('../state/auth-context', () => ({
  useAuth: () => ({
    user: {
      id: 'user-1',
      email: 'analyst@example.com',
      role: 'USER',
      emailVerified: true,
      createdAt: '2026-07-20T00:00:00Z',
    },
  }),
}));

const ACCOUNT_EXPORT: AccountDataExport = {
  schemaVersion: 'account_data_export_v1.0.0',
  generatedAt: '2026-07-29T12:00:00Z',
  retentionNotice: 'Backups follow normal retention.',
  excludedSecrets: ['password hashes', 'session tokens'],
  data: {
    account: [{ id: 'user-1', email: 'analyst@example.com' }],
    preferences: [],
  },
};

describe('账户与隐私自助能力', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    window.history.replaceState(null, '', '#/account');
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:account-export'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('明确说明导出边界、备份留存、不可撤销和退出登录后果', () => {
    render(<I18nProvider><AccountPrivacyPage /></I18nProvider>);

    expect(screen.getByRole('heading', { name: 'Account & privacy' })).toBeInTheDocument();
    expect(screen.getByText(/Excludes password hashes, session and CSRF tokens/i))
      .toBeInTheDocument();
    expect(screen.getByText(/Deletion from the live application cannot be undone/i))
      .toBeInTheDocument();
    expect(screen.getByText(/backups are not immediately rewritten/i)).toBeInTheDocument();
    expect(screen.getByText(/ends this sign-in and returns this browser to the sign-in page/i))
      .toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Permanently delete account' }))
      .toBeDisabled();
  });

  it('复验当前密码并在浏览器下载完整 JSON 导出', async () => {
    const user = userEvent.setup();
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    vi.mocked(api.exportAccountData).mockResolvedValue(ACCOUNT_EXPORT);
    render(<I18nProvider><AccountPrivacyPage /></I18nProvider>);

    await user.type(
      screen.getAllByLabelText('Current password')[0],
      'Current password 123!',
    );
    await user.click(screen.getByRole('button', { name: 'Download account data' }));

    await waitFor(() => {
      expect(api.exportAccountData).toHaveBeenCalledWith({
        currentPassword: 'Current password 123!',
      });
      expect(anchorClick).toHaveBeenCalledTimes(1);
    });
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:account-export');
    expect(screen.getByText(/JSON file was created in this browser/i)).toBeInTheDocument();
  });

  it('仅在密码和精确 DELETE 确认齐备后删除，并触发统一会话清理', async () => {
    const user = userEvent.setup();
    const expired = vi.fn();
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, expired, { once: true });
    vi.mocked(api.deleteAccount).mockResolvedValue({
      deleted: true,
      deletedRecordCount: 17,
      backupRetentionNotice: 'Backups follow normal retention.',
    });
    render(<I18nProvider><AccountPrivacyPage /></I18nProvider>);

    const deleteButton = screen.getByRole('button', {
      name: 'Permanently delete account',
    });
    await user.type(
      screen.getAllByLabelText('Current password')[1],
      'Current password 123!',
    );
    await user.type(screen.getByLabelText('Type DELETE to confirm'), 'delete');
    expect(screen.getByText('Enter DELETE exactly.')).toBeInTheDocument();
    expect(deleteButton).toBeDisabled();

    await user.clear(screen.getByLabelText('Type DELETE to confirm'));
    await user.type(screen.getByLabelText('Type DELETE to confirm'), 'DELETE');
    expect(deleteButton).toBeEnabled();
    await user.click(deleteButton);

    await waitFor(() => {
      expect(api.deleteAccount).toHaveBeenCalledWith({
        currentPassword: 'Current password 123!',
        confirmation: 'DELETE',
      });
      expect(expired).toHaveBeenCalledTimes(1);
    });
    expect(window.location.hash).toBe('#/cases');
  });

  it('简体中文提供等价的敏感操作说明', () => {
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    render(<I18nProvider><AccountPrivacyPage /></I18nProvider>);

    expect(screen.getByRole('heading', { name: '账户与隐私' })).toBeInTheDocument();
    expect(screen.getByText(/在线应用中的删除不可撤销/)).toBeInTheDocument();
    expect(screen.getByText(/主机备份不会立即重写/)).toBeInTheDocument();
    expect(screen.getByText(/本次登录会立即结束/)).toBeInTheDocument();
  });
});
