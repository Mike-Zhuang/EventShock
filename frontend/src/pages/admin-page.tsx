import { Button, InlineNotification, Select, SelectItem, Tag } from '@carbon/react';
import { ArrowClockwise, ClockCounterClockwise, UsersThree } from '@phosphor-icons/react';
import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { AdminActivityPage, AdminUserPage } from '../api/types';
import { EmptyState, LoadingPanel, PageHeader } from '../components/common';
import { useI18n } from '../i18n';
import { getPageGuide } from '../page-guidance';
import { useAuth } from '../state/auth-context';

const USER_PAGE_SIZE = 25;
const ACTIVITY_PAGE_SIZE = 50;

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function actionLabel(action: string, isZh: boolean): string {
  const labels: Record<string, [string, string]> = {
    LOGIN_SUCCEEDED: ['Signed in', '登录成功'],
    LOGIN_ATTEMPT: ['Failed sign-in attempt', '登录尝试失败'],
    LOGOUT: ['Signed out', '退出登录'],
    ACCOUNT_REGISTERED: ['Created account', '创建账户'],
    PASSWORD_RESET: ['Reset password', '重置密码'],
    ADMIN_BOOTSTRAPPED: ['Initialized administrator', '初始化管理员'],
    ACCOUNT_STATUS_CHANGED: ['Changed account status', '更改账户状态'],
    EVENT_PACK_CREATE: ['Created Event Pack', '创建事件包'],
    EVENT_PACK_REVIEW: ['Reviewed a claim', '审核候选主张'],
    EVENT_PACK_FREEZE: ['Froze Event Pack', '冻结事件包'],
    CLAIMS_EXTRACTED: ['Extracted candidate claims', '抽取候选主张'],
    HUMAN_APPROVED: ['Approved a claim', '批准候选主张'],
    BULK_CLAIMS_APPROVED: ['Bulk-approved pending claims', '批量批准待审核主张'],
    EDITED: ['Edited a claim', '修改候选主张'],
    REJECTED: ['Rejected a claim', '拒绝候选主张'],
    FROZEN: ['Froze Event Pack', '冻结事件包'],
    SCENARIO_CREATE: ['Created scenario', '创建情景'],
    SCENARIO_UPDATE: ['Updated scenario', '更新情景'],
    SCENARIO_FREEZE: ['Froze scenario', '冻结情景'],
    EXPERIMENT_CREATE: ['Created experiment', '创建实验'],
    EXPERIMENT_START: ['Started experiment', '启动实验'],
    EXPERIMENT_CANCEL: ['Cancelled experiment', '取消实验'],
    EXPERIMENT_INVALIDATE: ['Invalidated experiment', '作废实验'],
    EXPERIMENT_EXPORT: ['Exported experiment', '导出实验'],
    STUDY_RUN: ['Ran study', '运行研究'],
    MODEL_CONFIG: ['Changed temporary AI configuration', '更改临时 AI 配置'],
    EXPERIMENT_CREATED: ['Created experiment', '创建实验'],
    RUN_QUEUED: ['Queued experiment', '实验进入队列'],
    RUN_COMPLETED: ['Completed experiment', '完成实验'],
    RUN_FAILED: ['Experiment failed', '实验失败'],
    RUN_CANCEL_REQUESTED: ['Requested experiment cancellation', '请求取消实验'],
    RUN_CANCELLED: ['Cancelled experiment', '取消实验'],
    EXPERIMENT_INVALIDATED: ['Invalidated experiment', '作废实验'],
    EXPORT_CREATED: ['Exported experiment', '导出实验'],
    STUDY_COMPLETED: ['Completed study', '完成研究'],
  };
  const normalized = action.toUpperCase();
  const label = labels[normalized];
  if (label) return isZh ? label[1] : label[0];
  return normalized.replaceAll('_', ' ').toLowerCase();
}

function roleLabel(role: 'ADMIN' | 'USER', isZh: boolean): string {
  if (!isZh) return role === 'ADMIN' ? 'Administrator' : 'User';
  return role === 'ADMIN' ? '管理员' : '普通用户';
}

function statusLabel(status: 'ACTIVE' | 'DISABLED', isZh: boolean): string {
  if (!isZh) return status === 'ACTIVE' ? 'Active' : 'Disabled';
  return status === 'ACTIVE' ? '启用' : '已停用';
}

export function AdminPage() {
  const { language, t } = useI18n();
  const { user } = useAuth();
  const isZh = language === 'zh-CN';
  const [users, setUsers] = useState<AdminUserPage>();
  const [activity, setActivity] = useState<AdminActivityPage>();
  const [userOffset, setUserOffset] = useState(0);
  const [activityOffset, setActivityOffset] = useState(0);
  const [selectedUserId, setSelectedUserId] = useState('');
  const [usersLoading, setUsersLoading] = useState(true);
  const [activityLoading, setActivityLoading] = useState(true);
  const [error, setError] = useState<string>();

  const loadUsers = useCallback(async () => {
    if (user?.role !== 'ADMIN') return;
    setUsersLoading(true);
    setError(undefined);
    try {
      setUsers(await api.getAdminUsers(USER_PAGE_SIZE, userOffset));
    } catch (loadError) {
      setError(messageOf(loadError));
    } finally {
      setUsersLoading(false);
    }
  }, [user?.role, userOffset]);

  const loadActivity = useCallback(async () => {
    if (user?.role !== 'ADMIN') return;
    setActivityLoading(true);
    setError(undefined);
    try {
      setActivity(await api.getAdminActivity(
        ACTIVITY_PAGE_SIZE,
        activityOffset,
        selectedUserId || undefined,
      ));
    } catch (loadError) {
      setError(messageOf(loadError));
    } finally {
      setActivityLoading(false);
    }
  }, [activityOffset, selectedUserId, user?.role]);

  useEffect(() => {
    void loadUsers();
  }, [loadUsers]);

  useEffect(() => {
    void loadActivity();
  }, [loadActivity]);

  const formatDate = (value?: string) => value
    ? new Intl.DateTimeFormat(language, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
    : t('common.unavailable');

  if (user?.role !== 'ADMIN') {
    return (
      <div className="page">
        <PageHeader title={t('admin.title')} subtitle={t('admin.denied')} />
        <EmptyState title={t('admin.deniedTitle')} body={t('admin.denied')} />
      </div>
    );
  }

  return (
    <div className="page page--admin">
      <PageHeader
        title={t('admin.title')}
        subtitle={t('admin.subtitle')}
        guide={getPageGuide('admin', language)}
        actions={(
          <Button kind="ghost" size="sm" renderIcon={ArrowClockwise} onClick={() => { void loadUsers(); void loadActivity(); }}>
            {t('admin.refresh')}
          </Button>
        )}
      />

      {error ? (
        <InlineNotification kind="error" lowContrast hideCloseButton title={t('admin.loadFailed')} subtitle={error} />
      ) : null}

      {users ? (
        <section className="admin-summary" aria-label={t('admin.summary')}>
          <div><span>{t('admin.totalUsers')}</span><strong>{users.summary.totalUsers.toLocaleString(language)}</strong></div>
          <div><span>{t('admin.verifiedUsers')}</span><strong>{users.summary.verifiedUsers.toLocaleString(language)}</strong></div>
          <div><span>{t('admin.activeSevenDays')}</span><strong>{users.summary.activeUsersLastSevenDays.toLocaleString(language)}</strong></div>
          <div><span>{t('admin.totalActivities')}</span><strong>{users.summary.totalActivities.toLocaleString(language)}</strong></div>
        </section>
      ) : null}

      <section className="admin-panel" aria-labelledby="admin-users-heading">
        <div className="section-heading">
          <h2 id="admin-users-heading"><UsersThree size={21} weight="duotone" />{t('admin.usersHeading')}</h2>
          <p>{t('admin.usersBody')}</p>
        </div>
        {usersLoading ? <LoadingPanel /> : null}
        {!usersLoading && users?.items.length === 0 ? <EmptyState title={t('admin.noUsers')} body={t('admin.noUsersBody')} /> : null}
        {!usersLoading && users && users.items.length > 0 ? (
          <>
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead><tr><th>{t('admin.email')}</th><th>{t('admin.role')}</th><th>{t('admin.status')}</th><th>{t('admin.created')}</th><th>{t('admin.lastLogin')}</th><th>{t('admin.lastActivity')}</th><th>{t('admin.experimentCount')}</th><th>{t('admin.activityCount')}</th></tr></thead>
                <tbody>
                  {users.items.map((item) => (
                    <tr key={item.id} className={selectedUserId === item.id ? 'is-selected' : undefined}>
                      <td><button type="button" onClick={() => { setSelectedUserId(item.id); setActivityOffset(0); }}>{item.email}</button></td>
                      <td><Tag type={item.role === 'ADMIN' ? 'blue' : 'gray'} size="sm">{roleLabel(item.role, isZh)}</Tag></td>
                      <td><Tag type={item.status === 'ACTIVE' ? 'green' : 'red'} size="sm">{statusLabel(item.status, isZh)}</Tag></td>
                      <td>{formatDate(item.createdAt)}</td>
                      <td>{formatDate(item.lastLoginAt)}</td>
                      <td>{formatDate(item.lastActivityAt)}</td>
                      <td>{item.experimentCount.toLocaleString(language)}</td>
                      <td>{item.activityCount.toLocaleString(language)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="admin-pagination">
              <Button kind="ghost" size="sm" disabled={userOffset === 0} onClick={() => setUserOffset(Math.max(0, userOffset - USER_PAGE_SIZE))}>{t('admin.previous')}</Button>
              <span>{t('admin.range', { start: userOffset + 1, end: Math.min(userOffset + users.items.length, users.total), total: users.total })}</span>
              <Button kind="ghost" size="sm" disabled={userOffset + users.items.length >= users.total} onClick={() => setUserOffset(userOffset + USER_PAGE_SIZE)}>{t('admin.next')}</Button>
            </div>
          </>
        ) : null}
      </section>

      <section className="admin-panel" aria-labelledby="admin-activity-heading">
        <div className="admin-panel__toolbar">
          <div className="section-heading">
            <h2 id="admin-activity-heading"><ClockCounterClockwise size={21} weight="duotone" />{t('admin.activityHeading')}</h2>
            <p>{t('admin.activityBody')}</p>
          </div>
          <Select
            id="admin-activity-user"
            labelText={t('admin.filterUser')}
            value={selectedUserId}
            onChange={(event) => { setSelectedUserId(event.target.value); setActivityOffset(0); }}
          >
            <SelectItem value="" text={t('admin.allUsers')} />
            {users?.items.map((item) => <SelectItem key={item.id} value={item.id} text={item.email} />)}
          </Select>
        </div>
        {activityLoading ? <LoadingPanel /> : null}
        {!activityLoading && activity?.items.length === 0 ? <EmptyState title={t('admin.noActivity')} body={t('admin.noActivityBody')} /> : null}
        {!activityLoading && activity && activity.items.length > 0 ? (
          <>
            <ol className="admin-activity-list">
              {activity.items.map((item) => (
                <li key={item.id}>
                  <div>
                    <strong>{actionLabel(item.action, isZh)}</strong>
                    <span>{item.userEmail ?? users?.items.find((candidate) => candidate.id === item.userId)?.email ?? item.userId ?? t('common.unavailable')}</span>
                  </div>
                  <div>
                    {item.entityType ? <code>{item.entityType}{item.entityId ? ` / ${item.entityId}` : ''}</code> : null}
                    <Tag type={item.outcome === 'SUCCEEDED' ? 'green' : 'red'} size="sm">{item.outcome === 'SUCCEEDED' ? t('admin.succeeded') : t('admin.failed')}</Tag>
                    <time dateTime={item.createdAt}>{formatDate(item.createdAt)}</time>
                  </div>
                </li>
              ))}
            </ol>
            <div className="admin-pagination">
              <Button kind="ghost" size="sm" disabled={activityOffset === 0} onClick={() => setActivityOffset(Math.max(0, activityOffset - ACTIVITY_PAGE_SIZE))}>{t('admin.previous')}</Button>
              <span>{t('admin.range', { start: activityOffset + 1, end: Math.min(activityOffset + activity.items.length, activity.total), total: activity.total })}</span>
              <Button kind="ghost" size="sm" disabled={activityOffset + activity.items.length >= activity.total} onClick={() => setActivityOffset(activityOffset + ACTIVITY_PAGE_SIZE)}>{t('admin.next')}</Button>
            </div>
          </>
        ) : null}
      </section>

      <p className="admin-privacy-note">{t('admin.privacyBoundary')}</p>
    </div>
  );
}
