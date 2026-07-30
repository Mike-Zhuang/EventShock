import { NumberInput, Select, SelectItem, TextInput } from '@carbon/react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { I18nProvider } from '../i18n';
import { ErrorPanel, PageHeader, ParameterHelp } from './common';

beforeEach(() => {
  window.localStorage.clear();
});

describe('PageHeader', () => {
  it('可为页面主标题提供稳定的深链锚点', () => {
    render(<PageHeader title="Results" subtitle="Experiment evidence" headingId="results-heading" />);

    expect(screen.getByRole('heading', { level: 1, name: 'Results' })).toHaveAttribute('id', 'results-heading');
  });
});

describe('ErrorPanel', () => {
  it('说明保存、费用、数据安全、下一步和脱敏反馈入口', () => {
    render(
      <I18nProvider>
        <ErrorPanel detail="MODEL_RESPONSE_INVALID trace: http-safe-trace-1" />
      </I18nProvider>,
    );

    expect(screen.getByText('Save status')).toBeInTheDocument();
    expect(screen.getByText('Cost status')).toBeInTheDocument();
    expect(screen.getByText('Data safety')).toBeInTheDocument();
    expect(screen.getByText('Next step')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'File a redacted issue' })).toHaveAttribute(
      'href',
      'https://github.com/Mike-Zhuang/EventShock/issues/new/choose',
    );
    expect(screen.getByText('http-safe-trace-1')).toBeInTheDocument();
  });

  it('在中文错误中保留明确下一步，并允许重试', async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    render(
      <I18nProvider>
        <ErrorPanel
          detail="请求失败，追踪号：trace-zh-1"
          savedState="草稿仍保存在服务器。"
          costState="本次请求未计费。"
          dataSafety="现有实验数据未被修改。"
          nextStep="检查网络后重试。"
          onRetry={onRetry}
        />
      </I18nProvider>,
    );

    expect(screen.getByText('保存状态')).toBeInTheDocument();
    expect(screen.getByText('草稿仍保存在服务器。')).toBeInTheDocument();
    expect(screen.getByText('费用状态')).toBeInTheDocument();
    expect(screen.getByText('本次请求未计费。')).toBeInTheDocument();
    expect(screen.getByText('数据安全')).toBeInTheDocument();
    expect(screen.getByText('现有实验数据未被修改。')).toBeInTheDocument();
    expect(screen.getByText('下一步')).toBeInTheDocument();
    expect(screen.getByText('检查网络后重试。')).toBeInTheDocument();
    expect(screen.getByText('trace-zh-1')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '提交脱敏 Issue' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: '重试' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe('ParameterHelp', () => {
  it('把帮助按钮放在 Carbon decorator 中，而不是嵌入原生表单标签', () => {
    render(
      <I18nProvider>
        <TextInput
          id="model-name"
          labelText="Model"
          decorator={<ParameterHelp label="Model" explanation="Model help" />}
        />
        <NumberInput
          id="seed-count"
          label="Seed count"
          decorator={<ParameterHelp label="Seed count" explanation="Seed help" />}
        />
        <Select
          id="network-type"
          labelText="Network type"
          decorator={<ParameterHelp label="Network type" explanation="Network help" />}
        >
          <SelectItem value="small-world" text="Small world" />
        </Select>
      </I18nProvider>,
    );

    expect(screen.getByRole('textbox', { name: 'Model' })).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: 'Seed count' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Network type' })).toBeInTheDocument();
    expect(document.querySelectorAll('label button')).toHaveLength(0);

    for (const label of ['Model', 'Seed count', 'Network type']) {
      const trigger = screen.getByRole('button', { name: `View parameter help for ${label}` });
      expect(trigger).toHaveAttribute('aria-describedby');
      expect(document.getElementById(trigger.getAttribute('aria-describedby') ?? '')).not.toBeNull();
    }
  });

  it('hover 离开后立即关闭，并为键盘焦点保留可读说明', async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <ParameterHelp label="Model" explanation="Model help" />
        <button type="button">Next control</button>
      </I18nProvider>,
    );
    const trigger = screen.getByRole('button', { name: 'View parameter help for Model' });

    await user.hover(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('tooltip')).toHaveTextContent('Model help');
    fireEvent.pointerDown(trigger);
    fireEvent.focus(trigger);
    await user.unhover(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    fireEvent.pointerUp(trigger);
    fireEvent.blur(trigger);

    await user.tab();
    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await user.hover(trigger);
    await user.unhover(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await user.tab();
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });

  it('点击可切换，并在外部点击、Esc、滚动和路由变化时关闭', async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <ParameterHelp label="Model" explanation="Model help" />
        <button type="button">Next control</button>
      </I18nProvider>,
    );
    const trigger = screen.getByRole('button', { name: 'View parameter help for Model' });
    const nextControl = screen.getByRole('button', { name: 'Next control' });

    await user.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    await user.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    await user.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    await user.click(trigger);
    fireEvent.scroll(window);
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    await user.click(trigger);
    fireEvent(window, new HashChangeEvent('hashchange'));
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    await user.click(trigger);
    await user.click(nextControl);
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
  });

  it('同一时间只展示一个说明，并在说明内容刷新后关闭', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <I18nProvider>
        <ParameterHelp label="Model" explanation="Model help" />
        <ParameterHelp label="Seed" explanation="Seed help" />
      </I18nProvider>,
    );
    const modelTrigger = screen.getByRole('button', { name: 'View parameter help for Model' });
    const seedTrigger = screen.getByRole('button', { name: 'View parameter help for Seed' });

    await user.click(modelTrigger);
    expect(modelTrigger).toHaveAttribute('aria-expanded', 'true');
    await user.click(seedTrigger);
    expect(modelTrigger).toHaveAttribute('aria-expanded', 'false');
    expect(seedTrigger).toHaveAttribute('aria-expanded', 'true');

    rerender(
      <I18nProvider>
        <ParameterHelp label="Model" explanation="Updated model help" />
        <ParameterHelp label="Seed" explanation="Updated seed help" />
      </I18nProvider>,
    );
    expect(screen.getByRole('button', { name: 'View parameter help for Seed' }))
      .toHaveAttribute('aria-expanded', 'false');
  });
});
