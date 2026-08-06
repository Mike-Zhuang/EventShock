import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { EventPack } from '../api/types';
import { I18nProvider } from '../i18n';
import { useWorkflow } from '../state/workflow-context';
import { EventPackPage } from './event-pack-page';

vi.mock('../state/workflow-context', () => ({
  useWorkflow: vi.fn(),
}));

vi.mock('../components/event-pack-upload-modal', () => ({
  EventPackUploadModal: () => null,
}));

const EVENT_PACK: EventPack = {
  id: 'pack-review',
  name: 'Review pack',
  status: 'DRAFT',
  editableExtraction: true,
  limitations: [],
  limitationsZh: [],
  sources: [{ id: 'source-one', title: 'Official source', sourceType: 'OFFICIAL' }],
  claims: [
    {
      id: 'claim-one',
      text: 'First candidate claim for review.',
      status: 'AI_PROPOSED',
      sourceIds: ['source-one'],
      sourceTier: 'OFFICIAL',
      confidence: 0.91,
      impactChannels: ['belief'],
      bulkApprovalEligible: true,
    },
    {
      id: 'claim-two',
      text: 'Second candidate claim for review.',
      status: 'AI_PROPOSED',
      sourceIds: ['source-one'],
      sourceTier: 'OFFICIAL',
      confidence: 0.88,
      impactChannels: ['liquidity'],
      bulkApprovalEligible: true,
    },
    { id: 'claim-edited', text: 'Already edited claim.', status: 'EDITED' },
  ],
};

describe('Event Pack 批量审核警告', () => {
  const approveAllPendingClaims = vi.fn(async () => undefined);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    vi.mocked(useWorkflow).mockReturnValue({
      eventPack: EVENT_PACK,
      eventPackState: 'success',
      eventPackError: undefined,
      claimBusyId: undefined,
      reviewClaim: vi.fn(async () => undefined),
      approveAllPendingClaims,
      freezeEventPack: vi.fn(async () => undefined),
    } as unknown as ReturnType<typeof useWorkflow>);
  });

  it('第一次点击只显示警告，确认后才提交屏幕上的待审核 ID', async () => {
    const user = userEvent.setup();
    render(<I18nProvider><EventPackPage navigate={vi.fn()} /></I18nProvider>);

    await user.click(screen.getByRole('button', { name: 'Approve eligible (2)' }));

    expect(approveAllPendingClaims).not.toHaveBeenCalled();
    expect(screen.getByText('This does not replace source verification')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'I understand — approve 2' }));

    await waitFor(() => expect(approveAllPendingClaims).toHaveBeenCalledTimes(1));
    expect(approveAllPendingClaims).toHaveBeenCalledWith({
      acknowledgedBulkApproval: true,
      expectedClaimIds: ['claim-one', 'claim-two'],
      rationale: 'User acknowledged the bulk-approval warning in the Event Pack review interface.',
    });
  });

  it('规则回退候选禁用批量批准，并在审核工具栏提供重新抽取入口', () => {
    vi.mocked(useWorkflow).mockReturnValue({
      eventPack: {
        ...EVENT_PACK,
        editableExtraction: true,
        extractionMode: 'RULE_FALLBACK_NO_LLM_CONFIG',
        contentSecurity: {
          schemaVersion: '1',
          decision: 'REVIEW',
          acknowledged: true,
          sourceCount: 1,
          findingCount: 0,
          findingsTruncated: false,
          rawContentRetained: false,
          findings: [],
          sources: [],
        },
        claims: [
          {
            ...EVENT_PACK.claims[0],
            impactChannels: ['belief', 'informationLatency'],
            bulkApprovalEligible: false,
          },
          {
            ...EVENT_PACK.claims[1],
            bulkApprovalEligible: false,
          },
          ...EVENT_PACK.claims.slice(2),
        ],
      },
      eventPackState: 'success',
      eventPackError: undefined,
      claimBusyId: undefined,
      reviewClaim: vi.fn(async () => undefined),
      approveAllPendingClaims,
      freezeEventPack: vi.fn(async () => undefined),
    } as unknown as ReturnType<typeof useWorkflow>);

    render(<I18nProvider><EventPackPage navigate={vi.fn()} /></I18nProvider>);

    expect(screen.getByText('Rule-fallback candidates require individual review'))
      .toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve eligible (0)' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Re-extract candidates' })).toBeInTheDocument();
    expect(screen.getAllByText('Belief update').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Information latency').length).toBeGreaterThan(0);
    expect(screen.getAllByText(/How delayed availability may change/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/not eligible for evidence extraction/).length)
      .toBeGreaterThan(0);
    expect(screen.getByText('Upload content safety: Human review required'))
      .toBeInTheDocument();
    expect(screen.queryByText('Upload content safety: REVIEW')).not.toBeInTheDocument();
    screen.getAllByText('EXTRACTION_NOT_ELIGIBLE').forEach((code) => {
      expect(code).not.toBeVisible();
    });
  });
});
