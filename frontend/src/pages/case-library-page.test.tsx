import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { normalizeCases } from '../api/normalize';
import { I18nProvider } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { CaseLibraryPage } from './case-library-page';

vi.mock('../state/workflow-context', () => ({
  useWorkflow: vi.fn(),
}));

describe('CaseLibraryPage 验证边界', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useWorkflow).mockReturnValue({
      cases: normalizeCases([
        {
          id: 'historical-case',
          eventPackId: 'historical-pack',
          title: 'Historical mechanism case',
          summary: 'BA is used for a historical mechanism comparison.',
          instrument: 'BA',
          status: 'FROZEN',
          eventPackReviewState: 'FROZEN',
          caseRole: 'HISTORICAL_VALIDATION_CASE',
          validationStatus: {
            level: 'L5_CASE_AVAILABLE',
            empiricalCalibration: 'PENDING_HUMAN_STUDY',
            claim: 'Runnable historical mechanism case; external validation is pending.',
          },
        },
        {
          id: 'pending-case',
          eventPackId: 'pending-pack',
          title: 'Pending study case',
          summary: 'A runnable case awaiting human evidence.',
          status: 'DRAFT',
          eventPackReviewState: 'IN_PROGRESS',
          validationStatus: {
            empiricalCalibration: 'PENDING_HUMAN_STUDY',
          },
        },
      ]),
      casesState: 'success',
      casesError: undefined,
      selectedCase: undefined,
      refreshCases: vi.fn(),
      selectCase: vi.fn(),
    } as unknown as ReturnType<typeof useWorkflow>);
  });

  it('用人类可读声明替代内部验证枚举，并明确历史案例只作机制对照', () => {
    render(
      <I18nProvider>
        <CaseLibraryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(screen.getByText('Historical event · mechanism comparison only')).toBeInTheDocument();
    expect(screen.getByText('Runnable · not externally validated')).toBeInTheDocument();
    expect(screen.getAllByText('Human study pending')).toHaveLength(2);
    expect(screen.queryByText('L5_CASE_AVAILABLE')).not.toBeInTheDocument();
    expect(screen.queryByText('PENDING_HUMAN_STUDY')).not.toBeInTheDocument();
    expect(document.querySelector('[title="L5_CASE_AVAILABLE"]')).toBeNull();
  });

  it('按当前用户的证据状态进入审核或情景，并在描述中的代码旁持续标注合成代理', async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    const current = vi.mocked(useWorkflow)();
    const selectCase = vi.fn()
      .mockResolvedValueOnce({ status: 'DRAFT', frozenAt: undefined })
      .mockResolvedValueOnce({ status: 'FROZEN', frozenAt: '2026-08-05T00:00:00Z' });
    vi.mocked(useWorkflow).mockReturnValue({
      ...current,
      selectCase,
    } as ReturnType<typeof useWorkflow>);

    render(<I18nProvider><CaseLibraryPage navigate={navigate} /></I18nProvider>);

    expect(screen.getByText('synthetic market proxy')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Continue evidence review' }));
    expect(navigate).toHaveBeenLastCalledWith('pack');

    await user.click(screen.getByRole('button', { name: 'Build scenario' }));
    expect(navigate).toHaveBeenLastCalledWith('scenario');
  });
});
