import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { EventPackFactorySnapshot, GuidedWorkflow } from '../api/types';
import {
  readFactoryGuidedHandoff,
  synchronizeGuidedHandoffOwner,
  writeFactoryGuidedHandoff,
} from '../guided-handoff';
import { I18nProvider } from '../i18n';
import { EventPackFactoryPage } from './event-pack-factory-page';
import { GuidedWorkflowPage } from './guided-workflow-page';

const selectCase = vi.fn();

vi.mock('../state/workflow-context', () => ({
  useWorkflow: () => ({
    eventPack: undefined,
    selectCase,
  }),
}));

vi.mock('../api/client', () => ({
  api: {
    getFactoryBuilds: vi.fn(),
    getFactorySearchEngines: vi.fn(),
    getFactoryBuild: vi.fn(),
    createFactoryBuild: vi.fn(),
    deleteFactoryBuild: vi.fn(),
    addFactoryPasteSource: vi.fn(),
    searchFactorySources: vi.fn(),
    addFactoryReaderSource: vi.fn(),
    reviewFactorySource: vi.fn(),
    materializeFactoryBuild: vi.fn(),
    getFactorySourceRawText: vi.fn(),
    updateFactorySourceRawText: vi.fn(),
    getGuidedWorkflows: vi.fn(),
    createGuidedWorkflow: vi.fn(),
    getGuidedWorkflow: vi.fn(),
    sendGuidedTurn: vi.fn(),
    applyGuidedProposal: vi.fn(),
    advanceGuidedWorkflow: vi.fn(),
    linkGuidedWorkflowArtifacts: vi.fn(),
    getEventPack: vi.fn(),
    getScenario: vi.fn(),
  },
}));

const snapshot: EventPackFactorySnapshot = {
  build: {
    id: 'epfb-12345678',
    ownerUserId: 'user-1',
    title: 'Index inclusion sources',
    status: 'DRAFT',
    revision: 4,
    createdAt: '2026-07-22T10:00:00Z',
    updatedAt: '2026-07-22T10:02:00Z',
    retentionExpiresAt: '2026-07-29T10:02:00Z',
  },
  sources: [{
    id: 'epfsrc-search-1234',
    buildId: 'epfb-12345678',
    kind: 'SEARCH_RESULT',
    evidenceRole: 'DISCOVERY_ONLY',
    reviewStatus: 'APPROVED',
    securityDecision: 'ALLOW',
    title: 'Official index notice',
    publisher: 'Example Exchange',
    url: 'https://example.com/notice',
    knownAt: '2026-07-22T09:01:00Z',
    contentHash: 'a'.repeat(64),
    contentLength: 300,
    reviewSummary: 'A search summary that must not directly support claims.',
    verifiedEvidenceQuotes: [],
    searchRunId: 'epfsr-12345678',
    createdAt: '2026-07-22T10:01:00Z',
    updatedAt: '2026-07-22T10:02:00Z',
  }],
  searchRuns: [],
};

const guidedWorkflow: GuidedWorkflow = {
  schemaVersion: '1.0.0',
  id: 'guided-12345678',
  stage: 'EVENT_GOAL',
  status: 'ACTIVE',
  version: 2,
  language: 'en',
  draft: { searchQueries: [] },
  pendingProposal: {
    schemaVersion: 'guided_proposal_v1.0.0',
    stage: 'EVENT_GOAL',
    assistantMessage: 'Review this candidate before applying it.',
    clarificationRequired: false,
    proposedEventMetadata: {
      title: 'Index Inclusion Event',
      summary: 'A bounded event summary.',
      instrument: 'EXAMPLE',
      asOf: '2026-07-22T10:00:00Z',
      researchQuestion: 'How does one liquidity intervention propagate?',
    },
    proposedSearchQueries: [],
    nextQuestionOptions: ['Change the instrument to TEST.'],
    readyForHumanReview: true,
    blockedReasons: [],
  },
  pendingProposalId: 'proposal-12345678',
  messages: [
    {
      id: 'message-assistant',
      role: 'assistant',
      stage: 'EVENT_GOAL',
      content: '**Describe** the event and one bounded question.',
      createdAt: '2026-07-22T10:00:00Z',
    },
    {
      id: 'message-user',
      role: 'user',
      stage: 'EVENT_GOAL',
      content: 'Study an index-inclusion event.',
      createdAt: '2026-07-22T10:00:30Z',
    },
  ],
  createdAt: '2026-07-22T10:00:00Z',
  updatedAt: '2026-07-22T10:01:00Z',
};

describe('Event Pack Factory page', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    vi.clearAllMocks();
    // 隔离页面测试没有 AuthProvider，需手动绑定 owner，交接写入才有合法账户作用域。
    synchronizeGuidedHandoffOwner('guided-user-0001');
    vi.mocked(api.getFactoryBuilds).mockResolvedValue([snapshot.build]);
    vi.mocked(api.getFactorySearchEngines).mockResolvedValue([{
      engine: 'search_std',
      displayName: 'Web Search Standard',
      priceCnyPerCall: 0.01,
      supportsCount: false,
      supportsDomainFilter: false,
      supportsRecencyFilter: false,
      supportsContentSize: false,
    }]);
    vi.mocked(api.getFactoryBuild).mockResolvedValue(snapshot);
  });

  it('separates discovery snippets from evidence and discloses raw-text retention', async () => {
    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByRole('heading', { name: 'Event Pack Factory' })).toBeInTheDocument();
    expect(screen.getByText(/Full raw text is staged on the server for seven days/)).toBeInTheDocument();
    expect(screen.getByText('Discovery only, not evidence')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Read full page into evidence' })).toBeInTheDocument();
    expect(screen.getByText(/Reader pricing has not been verified/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete build and raw text' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate and open human claim review' })).toBeDisabled();
  });

  it('prevents a reviewed search result from being imported through Reader twice', async () => {
    vi.mocked(api.getFactoryBuild).mockResolvedValue({
      ...snapshot,
      sources: [
        ...snapshot.sources,
        {
          id: 'epfsrc-reader-1234',
          buildId: snapshot.build.id,
          kind: 'READER',
          evidenceRole: 'EVIDENCE',
          reviewStatus: 'PENDING',
          securityDecision: 'ALLOW',
          title: 'Official index notice',
          publisher: 'Example Exchange',
          url: 'https://example.com/notice',
          knownAt: '2026-07-22T09:05:00Z',
          contentHash: 'b'.repeat(64),
          contentLength: 3_000,
          reviewSummary: 'Reader full text pending independent human review.',
          verifiedEvidenceQuotes: [],
          parentSourceId: snapshot.sources[0].id,
          createdAt: '2026-07-22T10:03:00Z',
          updatedAt: '2026-07-22T10:03:00Z',
        },
      ],
    });

    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByRole('button', {
      name: 'Full page imported; separate review pending',
    })).toBeDisabled();
  });

  it('fetches raw text on demand and requires confirmation before resetting review', async () => {
    const user = userEvent.setup();
    const evidenceSource = {
      ...snapshot.sources[0],
      id: 'epfsrc-reader-1234',
      kind: 'READER' as const,
      evidenceRole: 'EVIDENCE' as const,
      reviewStatus: 'APPROVED' as const,
      contentHash: 'b'.repeat(64),
      contentLength: 30,
      reviewSummary: 'Human-reviewed source.',
      searchRunId: undefined,
    };
    const evidenceSnapshot = { ...snapshot, sources: [evidenceSource] };
    vi.mocked(api.getFactoryBuild).mockResolvedValue(evidenceSnapshot);
    vi.mocked(api.getFactorySourceRawText).mockResolvedValue({
      buildId: snapshot.build.id,
      sourceId: evidenceSource.id,
      revision: snapshot.build.revision,
      rawText: 'Original retained source body.',
      contentHash: evidenceSource.contentHash,
      contentLength: evidenceSource.contentLength,
      retentionExpiresAt: snapshot.build.retentionExpiresAt,
    });
    vi.mocked(api.updateFactorySourceRawText).mockResolvedValue({
      build: { ...snapshot.build, revision: 5 },
      sources: [{
        ...evidenceSource,
        reviewStatus: 'PENDING',
        contentHash: 'c'.repeat(64),
        contentLength: 31,
      }],
      idempotencyReplayed: false,
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    await user.click(await screen.findByText('View or revise full raw text (sensitive)'));
    const rawInput = await screen.findByLabelText('Full raw text');
    expect(api.getFactorySourceRawText).toHaveBeenCalledWith(
      snapshot.build.id,
      evidenceSource.id,
    );

    await user.clear(rawInput);
    await user.type(rawInput, 'Corrected retained source body.');
    await user.click(screen.getByRole('button', {
      name: 'Save as new revision and review again',
    }));

    expect(window.confirm).toHaveBeenCalledWith(expect.stringMatching(/revokes the current approval/));
    expect(api.updateFactorySourceRawText).toHaveBeenCalledWith(
      snapshot.build.id,
      evidenceSource.id,
      snapshot.build.revision,
      'Corrected retained source body.',
    );
  });

  it('prefills reviewed guided metadata and links only the server-returned build ID', async () => {
    const user = userEvent.setup();
    const sourceReviewWorkflow: GuidedWorkflow = {
      ...guidedWorkflow,
      stage: 'SOURCE_REVIEW',
      version: 5,
      pendingProposal: undefined,
      pendingProposalId: undefined,
      draft: {
        eventMetadata: guidedWorkflow.pendingProposal!.proposedEventMetadata,
        sourceMethod: 'COMBINED',
        searchQueries: ['official index inclusion notice'],
      },
    };
    writeFactoryGuidedHandoff(sourceReviewWorkflow);
    vi.mocked(api.getFactoryBuilds).mockResolvedValue([]);
    vi.mocked(api.createFactoryBuild).mockResolvedValue(snapshot.build);
    vi.mocked(api.getGuidedWorkflow).mockResolvedValue(sourceReviewWorkflow);
    vi.mocked(api.linkGuidedWorkflowArtifacts).mockResolvedValue({
      ...sourceReviewWorkflow,
      version: 6,
      draft: { ...sourceReviewWorkflow.draft, eventPackBuildId: snapshot.build.id },
    });

    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByDisplayValue('Index Inclusion Event')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create build' }));

    expect(await screen.findByDisplayValue('A bounded event summary.')).toBeInTheDocument();
    expect(screen.getByDisplayValue('EXAMPLE')).toBeInTheDocument();
    expect(screen.getByDisplayValue('official index inclusion notice')).toBeInTheDocument();
    await waitFor(() => expect(api.linkGuidedWorkflowArtifacts).toHaveBeenCalledWith(
      sourceReviewWorkflow.id,
      {
        expectedVersion: sourceReviewWorkflow.version,
        eventPackBuildId: snapshot.build.id,
        eventPackId: undefined,
      },
    ));
  });
});

describe('guided workflow page', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    vi.clearAllMocks();
    // 隔离页面测试没有 AuthProvider，需手动绑定 owner，交接写入才有合法账户作用域。
    synchronizeGuidedHandoffOwner('guided-user-0001');
    vi.mocked(api.getGuidedWorkflows).mockResolvedValue([guidedWorkflow]);
    vi.mocked(api.getGuidedWorkflow).mockResolvedValue(guidedWorkflow);
    vi.mocked(api.applyGuidedProposal).mockResolvedValue({
      ...guidedWorkflow,
      version: 3,
      draft: {
        ...guidedWorkflow.draft,
        eventMetadata: guidedWorkflow.pendingProposal?.proposedEventMetadata,
      },
      pendingProposal: undefined,
      pendingProposalId: undefined,
    });
  });

  it('keeps proposal application and stage advancement as separate human actions', async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByRole('heading', { name: 'AI-guided workflow' })).toBeInTheDocument();
    expect(screen.getByText('Describe')).toHaveStyle({ fontWeight: 'bold' });
    expect(screen.getByText('Study an index-inclusion event.').closest('article'))
      .toHaveClass('guided-message--user');
    const advance = screen.getByRole('button', { name: 'I reviewed this stage, continue' });
    expect(advance).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Apply reviewed candidate' }));

    await waitFor(() => expect(api.applyGuidedProposal).toHaveBeenCalledWith(
      guidedWorkflow.id,
      guidedWorkflow.pendingProposalId,
      guidedWorkflow.version,
    ));
    await waitFor(() => expect(advance).toBeEnabled());
    expect(api.advanceGuidedWorkflow).not.toHaveBeenCalled();
  });

  it('hands reviewed metadata to Factory without exposing a pasted artifact-ID field', async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    const sourceReviewWorkflow: GuidedWorkflow = {
      ...guidedWorkflow,
      stage: 'SOURCE_REVIEW',
      version: 5,
      pendingProposal: undefined,
      pendingProposalId: undefined,
      draft: {
        eventMetadata: guidedWorkflow.pendingProposal!.proposedEventMetadata,
        sourceMethod: 'PASTE',
        searchQueries: ['official event notice'],
      },
    };
    vi.mocked(api.getGuidedWorkflows).mockResolvedValue([sourceReviewWorkflow]);
    vi.mocked(api.getGuidedWorkflow).mockResolvedValue(sourceReviewWorkflow);

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={navigate} />
      </I18nProvider>,
    );

    expect(await screen.findByRole('button', { name: 'Open Event Pack Factory' }))
      .toBeInTheDocument();
    expect(screen.queryByLabelText('Human-saved scenario ID')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Open Event Pack Factory' }));

    expect(navigate).toHaveBeenCalledWith('factory');
    expect(readFactoryGuidedHandoff()).toMatchObject({
      workflowId: sourceReviewWorkflow.id,
      sourceMethod: 'PASTE',
      searchQueries: ['official event notice'],
    });
  });
});
