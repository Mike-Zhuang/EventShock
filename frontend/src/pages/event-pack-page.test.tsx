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
    { id: 'claim-one', text: 'First candidate claim for review.', status: 'AI_PROPOSED' },
    { id: 'claim-two', text: 'Second candidate claim for review.', status: 'AI_PROPOSED' },
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

    await user.click(screen.getByRole('button', { name: 'Approve all pending (2)' }));

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
});
