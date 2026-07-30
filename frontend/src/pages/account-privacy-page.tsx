import {
  Button,
  InlineNotification,
  PasswordInput,
  TextInput,
} from '@carbon/react';
import {
  Database,
  DownloadSimple,
  Key,
  ShieldCheck,
  SignOut,
  Trash,
  WarningCircle,
} from '@phosphor-icons/react';
import { useState, type FormEvent } from 'react';
import {
  api,
  ApiError,
  AUTH_SESSION_EXPIRED_EVENT,
} from '../api/client';
import type { AccountDataExport } from '../api/types';
import { PageHeader } from '../components/common';
import { useI18n } from '../i18n';
import { useAuth } from '../state/auth-context';

const ACCOUNT_EXPORT_FILENAME = 'eventshock-account-data.json';

function downloadJson(payload: AccountDataExport): void {
  const blob = new Blob(
    [`${JSON.stringify(payload, null, 2)}\n`],
    { type: 'application/json;charset=utf-8' },
  );
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = objectUrl;
  link.download = ACCOUNT_EXPORT_FILENAME;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

export function AccountPrivacyPage() {
  const { language, t } = useI18n();
  const { user } = useAuth();
  const [exportPassword, setExportPassword] = useState('');
  const [deletePassword, setDeletePassword] = useState('');
  const [deleteConfirmation, setDeleteConfirmation] = useState('');
  const [exportBusy, setExportBusy] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [exportNotice, setExportNotice] = useState<
    { kind: 'success' | 'error'; message: string } | undefined
  >();
  const [deleteError, setDeleteError] = useState<string>();
  const anyRequestBusy = exportBusy || deleteBusy;
  const deletionConfirmed = deleteConfirmation === 'DELETE';
  const confirmationInvalid = deleteConfirmation.length > 0 && !deletionConfirmed;
  const memberSince = user?.createdAt && Number.isFinite(Date.parse(user.createdAt))
    ? new Intl.DateTimeFormat(language, { dateStyle: 'medium' }).format(
      new Date(user.createdAt),
    )
    : t('common.unavailable');

  const accountRequestError = (
    error: unknown,
    action: 'export' | 'delete',
  ): string => {
    if (error instanceof ApiError) {
      if (error.status === 401) return t('account.errorPassword');
      if (error.status === 429) return t('account.errorRateLimit');
      if (error.code === 'LAST_ADMINISTRATOR_DELETION_FORBIDDEN') {
        return t('account.errorLastAdmin');
      }
    }
    return action === 'export' ? t('account.errorExport') : t('account.errorDelete');
  };

  const exportAccountData = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!exportPassword || anyRequestBusy) return;
    setExportBusy(true);
    setExportNotice(undefined);
    try {
      const exported = await api.exportAccountData({
        currentPassword: exportPassword,
      });
      downloadJson(exported);
      setExportPassword('');
      setExportNotice({ kind: 'success', message: t('account.exportSuccess') });
    } catch (error) {
      setExportNotice({
        kind: 'error',
        message: accountRequestError(error, 'export'),
      });
    } finally {
      setExportBusy(false);
    }
  };

  const deleteAccount = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!deletePassword || !deletionConfirmed || anyRequestBusy) return;
    setDeleteBusy(true);
    setDeleteError(undefined);
    try {
      await api.deleteAccount({
        currentPassword: deletePassword,
        confirmation: 'DELETE',
      });
      setDeletePassword('');
      setDeleteConfirmation('');
      // 删除端点已经撤销服务端会话 Cookie。复用统一失效事件清空 CSRF、
      // 用户资料和工作流 owner 状态，避免浏览器仍显示已删除账户。
      window.history.replaceState(null, '', '#/cases');
      window.dispatchEvent(new Event(AUTH_SESSION_EXPIRED_EVENT));
    } catch (error) {
      setDeleteError(accountRequestError(error, 'delete'));
      setDeleteBusy(false);
    }
  };

  return (
    <div className="page page--account-privacy">
      <PageHeader
        title={t('account.title')}
        subtitle={t('account.subtitle')}
      />

      <section
        className="account-identity"
        aria-labelledby="account-identity-heading"
      >
        <div className="account-identity__heading">
          <ShieldCheck size={24} weight="duotone" aria-hidden="true" />
          <div>
            <h2 id="account-identity-heading">{t('account.identityHeading')}</h2>
            <p>{t('account.identityBody')}</p>
          </div>
        </div>
        <dl>
          <div>
            <dt>{t('account.email')}</dt>
            <dd>{user?.email ?? t('common.unavailable')}</dd>
          </div>
          <div>
            <dt>{t('account.role')}</dt>
            <dd>
              {user?.role === 'ADMIN'
                ? t('account.roleAdmin')
                : t('account.roleUser')}
            </dd>
          </div>
          <div>
            <dt>{t('account.memberSince')}</dt>
            <dd>{memberSince}</dd>
          </div>
        </dl>
      </section>

      <section
        className="account-privacy-section account-export-section"
        aria-labelledby="account-export-heading"
      >
        <div className="account-section-copy">
          <div className="account-section-heading">
            <DownloadSimple size={27} weight="duotone" aria-hidden="true" />
            <div>
              <h2 id="account-export-heading">{t('account.exportHeading')}</h2>
              <p>{t('account.exportBody')}</p>
            </div>
          </div>
          <div className="account-export-boundary">
            <div>
              <Database size={19} weight="duotone" aria-hidden="true" />
              <p>{t('account.exportIncludes')}</p>
            </div>
            <div>
              <Key size={19} weight="duotone" aria-hidden="true" />
              <p>{t('account.exportExcludes')}</p>
            </div>
          </div>
          <p className="account-retention-note">{t('account.exportRetention')}</p>
        </div>

        <form
          className="account-privacy-form"
          onSubmit={(event) => void exportAccountData(event)}
        >
          {exportNotice ? (
            <InlineNotification
              kind={exportNotice.kind}
              lowContrast
              hideCloseButton
              title={
                exportNotice.kind === 'success'
                  ? t('account.exportReady')
                  : t('account.errorTitle')
              }
              subtitle={exportNotice.message}
            />
          ) : null}
          <PasswordInput
            id="account-export-password"
            labelText={t('account.currentPassword')}
            helperText={t('account.passwordHint')}
            value={exportPassword}
            maxLength={128}
            autoComplete="current-password"
            required
            disabled={anyRequestBusy}
            onChange={(event) => setExportPassword(event.target.value)}
          />
          <Button
            type="submit"
            renderIcon={DownloadSimple}
            disabled={!exportPassword || anyRequestBusy}
          >
            {exportBusy ? t('account.exportBusy') : t('account.exportButton')}
          </Button>
        </form>
      </section>

      <section
        className="account-privacy-section account-danger-section"
        aria-labelledby="account-delete-heading"
      >
        <div className="account-danger-copy">
          <div className="account-section-heading">
            <WarningCircle size={27} weight="duotone" aria-hidden="true" />
            <div>
              <h2 id="account-delete-heading">{t('account.deleteHeading')}</h2>
              <p>{t('account.deleteBody')}</p>
            </div>
          </div>

          <ul className="account-delete-consequences">
            <li>
              <DownloadSimple size={19} weight="duotone" aria-hidden="true" />
              <span>{t('account.deleteBackupFirst')}</span>
            </li>
            <li>
              <Trash size={19} weight="duotone" aria-hidden="true" />
              <span>{t('account.deleteIrreversible')}</span>
            </li>
            <li>
              <Database size={19} weight="duotone" aria-hidden="true" />
              <span>{t('account.deleteBackupRetention')}</span>
            </li>
            <li>
              <SignOut size={19} weight="duotone" aria-hidden="true" />
              <span>{t('account.deleteSignsOut')}</span>
            </li>
          </ul>
        </div>

        <form
          className="account-privacy-form account-delete-form"
          onSubmit={(event) => void deleteAccount(event)}
        >
          {deleteError ? (
            <InlineNotification
              kind="error"
              lowContrast
              hideCloseButton
              title={t('account.errorTitle')}
              subtitle={deleteError}
            />
          ) : null}
          <PasswordInput
            id="account-delete-password"
            labelText={t('account.currentPassword')}
            helperText={t('account.passwordHint')}
            value={deletePassword}
            maxLength={128}
            autoComplete="current-password"
            required
            disabled={anyRequestBusy}
            onChange={(event) => setDeletePassword(event.target.value)}
          />
          <TextInput
            id="account-delete-confirmation"
            labelText={t('account.confirmationLabel')}
            helperText={t('account.confirmationHint')}
            value={deleteConfirmation}
            maxLength={6}
            autoComplete="off"
            required
            disabled={anyRequestBusy}
            invalid={confirmationInvalid}
            invalidText={t('account.confirmationInvalid')}
            onChange={(event) => setDeleteConfirmation(event.target.value.slice(0, 6))}
          />
          <Button
            type="submit"
            kind="danger"
            renderIcon={Trash}
            disabled={!deletePassword || !deletionConfirmed || anyRequestBusy}
          >
            {deleteBusy ? t('account.deleteBusy') : t('account.deleteButton')}
          </Button>
        </form>
      </section>
    </div>
  );
}
