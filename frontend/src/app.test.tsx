import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './app';

vi.mock('./api/client', () => ({
  api: {
    getHealth: vi.fn(async () => ({ status: 'ok' })),
    getCases: vi.fn(async () => []),
    getExperiments: vi.fn(async () => []),
  },
}));

describe('移动主导航', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, '', '#/cases');
    document.body.style.overflow = '';
    vi.stubGlobal('scrollTo', vi.fn());
    vi.stubGlobal('matchMedia', vi.fn().mockImplementation((query: string) => ({
      matches: query === '(max-width: 920px)',
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
  });

  it('打开抽屉后聚焦当前页面，并在选择导航项后自动关闭', async () => {
    const user = userEvent.setup();
    render(<App />);

    const menuButton = screen.getByRole('button', { name: 'Open navigation' });
    const drawer = document.getElementById('mobile-primary-navigation');
    expect(drawer).not.toBeNull();
    if (!drawer) throw new Error('移动导航抽屉未渲染。');
    expect(menuButton).toHaveAttribute('aria-controls', drawer.id);
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    expect(drawer).not.toBeVisible();

    await user.click(menuButton);

    expect(menuButton).toHaveAttribute('aria-expanded', 'true');
    expect(drawer).toBeVisible();
    await waitFor(() => {
      expect(within(drawer).getByRole('button', { name: 'Case Library' })).toHaveFocus();
    });

    await user.click(within(drawer).getByRole('button', { name: 'Event Pack Review' }));

    expect(drawer).not.toBeVisible();
    expect(menuButton).toHaveAttribute('aria-expanded', 'false');
    expect(window.location.hash).toBe('#/pack');
    expect(document.getElementById('main-content')).toHaveFocus();
  });

  it('支持 Escape 关闭并将焦点返回菜单按钮', async () => {
    const user = userEvent.setup();
    render(<App />);

    const menuButton = screen.getByRole('button', { name: 'Open navigation' });
    const drawer = document.getElementById('mobile-primary-navigation');
    expect(drawer).not.toBeNull();
    if (!drawer) throw new Error('移动导航抽屉未渲染。');
    await user.click(menuButton);
    await waitFor(() => expect(drawer).toBeVisible());

    await user.keyboard('{Escape}');

    expect(drawer).not.toBeVisible();
    expect(menuButton).toHaveFocus();
    expect(document.body.style.overflow).toBe('');
  });

  it('切换为简体中文后同步更新菜单和主导航名称', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: '中文' }));

    const menuButton = screen.getByRole('button', { name: '打开导航' });
    await user.click(menuButton);
    const drawer = screen.getByRole('dialog', { name: '主导航' });
    expect(within(drawer).getByRole('button', { name: '案例库' })).toBeInTheDocument();
    expect(menuButton).toHaveAccessibleName('关闭导航');
    expect(menuButton).toHaveAttribute('aria-expanded', 'true');
  });
});
