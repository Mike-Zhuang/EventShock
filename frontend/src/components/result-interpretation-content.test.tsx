import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ResultInterpretationAssistantMessage } from '../api/types';
import { I18nProvider } from '../i18n';
import { ResultInterpretationContent } from './result-interpretation-content';

const MESSAGE: ResultInterpretationAssistantMessage = {
  id: 'assistant-audit-1',
  role: 'assistant',
  language: 'en',
  answer: 'The registered overview was checked [result:overview].',
  groundingReferences: ['result:overview'],
  followUpSuggestions: [],
  toolActivity: [
    {
      tool: 'OVERVIEW',
      label: 'Overview',
      itemCount: 1,
      truncated: false,
      evidenceId: 'result:overview',
    },
    {
      tool: 'TRACE',
      label: 'Trace',
      itemCount: 8,
      truncated: false,
      evidenceId: 'result:trace',
    },
  ],
  provider: 'zhipu',
  model: 'glm-5',
  promptTokens: 20,
  completionTokens: 10,
  cachedTokens: 0,
  totalTokens: 30,
  modelCalls: 1,
  cacheHit: false,
  repairUsed: false,
  plannerUsed: true,
  promptVersion: 'result_interpretation_v1.0.0',
  latencyMs: 120,
  createdAt: '2026-07-22T18:30:00.000Z',
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('ResultInterpretationContent 技术审计', () => {
  it('明确区分确定性回退文本与通过校验的模型解释', () => {
    const { rerender } = render(
      <I18nProvider>
        <ResultInterpretationContent
          experimentId="exp-audit"
          message={{
            ...MESSAGE,
            semanticValidationStatus: 'DETERMINISTIC_FALLBACK',
            deterministicFallbackUsed: true,
          }}
          navigate={vi.fn()}
        />
      </I18nProvider>,
    );

    expect(screen.getByText('Server deterministic fallback text')).toBeInTheDocument();
    expect(screen.getByText(/it is not model output/i)).toBeInTheDocument();

    rerender(
      <I18nProvider>
        <ResultInterpretationContent
          experimentId="exp-audit"
          message={{
            ...MESSAGE,
            semanticValidationStatus: 'REPAIRED',
            deterministicFallbackUsed: false,
          }}
          navigate={vi.fn()}
        />
      </I18nProvider>,
    );
    expect(screen.getByText('Repaired and validated model interpretation')).toBeInTheDocument();
    expect(screen.queryByText('Server deterministic fallback text')).not.toBeInTheDocument();
  });

  it('正文只显示技术状态的人类解释，原始枚举保留在折叠审计层', async () => {
    const user = userEvent.setup();
    const { container } = render(
      <I18nProvider>
        <ResultInterpretationContent
          experimentId="exp-audit"
          message={{
            ...MESSAGE,
            answer: 'A MODEL_RESPONSE_INVALID condition used rules [result:overview].',
          }}
          navigate={vi.fn()}
        />
      </I18nProvider>,
    );

    expect(container.querySelector('.result-assistant__answer'))
      .toHaveTextContent('The model response could not be validated');
    expect(container.querySelector('.result-assistant__answer'))
      .not.toHaveTextContent('MODEL_RESPONSE_INVALID');
    const rawCode = screen.getByText('MODEL_RESPONSE_INVALID');
    expect(rawCode).not.toBeVisible();

    await user.click(screen.getByText('Evidence used'));
    const auditDetails = container.querySelector<HTMLDetailsElement>(
      '.result-assistant__technical-evidence',
    );
    if (!auditDetails) throw new Error('解释审计技术详情未渲染。');
    await user.click(auditDetails.querySelector('summary')!);
    const codeDetails = auditDetails.querySelector<HTMLDetailsElement>(
      '.technical-code-display__details',
    );
    if (!codeDetails) throw new Error('技术枚举折叠层未渲染。');
    await user.click(codeDetails.querySelector('summary')!);
    expect(rawCode).toBeVisible();
  });

  it('默认折叠、合并未引用读取，并下载完整审计 JSON', async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn(() => 'blob:result-audit');
    const revokeObjectURL = vi.fn();
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: createObjectURL,
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: revokeObjectURL,
    });

    render(
      <I18nProvider>
        <ResultInterpretationContent
          experimentId="exp-audit"
          message={MESSAGE}
          navigate={vi.fn()}
        />
      </I18nProvider>,
    );

    const technical = screen.getByText('Technical details').closest('details');
    expect(technical).not.toHaveAttribute('open');
    expect(screen.getByText('Inspected but not cited:')).toBeInTheDocument();
    expect(screen.getByText('1 result section(s)')).toBeInTheDocument();
    expect(document.querySelector('.safe-markdown')).not.toHaveTextContent('result:');

    await user.click(screen.getByText('Evidence used'));
    await user.click(screen.getByText('Technical details'));
    await user.click(screen.getByRole('button', { name: 'Download audit JSON' }));

    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(anchorClick).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:result-audit');
  });
});
