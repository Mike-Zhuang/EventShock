import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from '../api/client';
import type {
  EventPackFactorySnapshot,
  GuidedTurnOperation,
  GuidedWorkflow,
} from '../api/types';
import {
  readFactoryGuidedHandoff,
  synchronizeGuidedHandoffOwner,
  writeFactoryGuidedHandoff,
} from '../guided-handoff';
import { I18nProvider } from '../i18n';
import { EventPackFactoryPage } from './event-pack-factory-page';
import { GuidedWorkflowPage } from './guided-workflow-page';

const selectCase = vi.fn();

afterEach(() => {
  vi.restoreAllMocks();
});

vi.mock('../state/workflow-context', () => ({
  useWorkflow: () => ({
    eventPack: undefined,
    selectCase,
  }),
}));

vi.mock('../api/client', () => ({
  ApiError: class MockApiError extends Error {
    status: number;
    detail?: string;
    code?: string;

    constructor(message: string, status: number, detail?: string, code?: string) {
      super(message);
      this.status = status;
      this.detail = detail;
      this.code = code;
    }
  },
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
    setFactorySourceIncluded: vi.fn(),
    permanentlyDeleteFactorySourceText: vi.fn(),
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
    getGuidedTurnOperations: vi.fn(),
    recoverGuidedTurn: vi.fn(),
    archiveGuidedWorkflow: vi.fn(),
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
    selectionStatus: 'INCLUDED',
    securityDecision: 'ALLOW',
    sourceReviewLabel: 'HOST_NOT_ALLOWLISTED',
    securityFindings: [],
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

const unknownGuidedOperation: GuidedTurnOperation = {
  schemaVersion: '1.0.0',
  workflowId: guidedWorkflow.id,
  clientRequestId: 'guided-request-unknown',
  expectedVersion: guidedWorkflow.version,
  status: 'UNKNOWN',
  errorCode: 'MODEL_RESPONSE_INVALID',
  requestMessage: 'Use the official filing cutoff.',
  language: 'en',
  cachedProposalAvailable: true,
  recoveryOptions: ['RETRY_CACHED_COMMIT', 'ABANDON_AND_AUTHORIZE_RETRY'],
  providerRequestId: 'guided-provider-request',
  httpResponseReceived: true,
  usageReceived: true,
  parseCompleted: true,
  failureStage: 'DATABASE_COMMIT_PENDING',
  createdAt: '2026-07-22T10:01:00Z',
  updatedAt: '2026-07-22T10:02:00Z',
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
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByRole('heading', { name: 'Add a case' })).toBeInTheDocument();
    expect(screen.getByText(/Full raw text is staged on the server for seven days/)).toBeInTheDocument();
    expect(screen.getByText('Discovery only, not evidence')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Read full page into evidence' })).toBeInTheDocument();
    expect(screen.getByText(/Reader pricing is also unverified/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Delete build and raw text' })).toBeInTheDocument();
    const materialize = screen.getByRole('button', {
      name: 'Generate and open human claim review',
    });
    expect(materialize).toBeEnabled();

    await user.click(materialize);

    expect(api.materializeFactoryBuild).not.toHaveBeenCalled();
    expect(screen.getAllByText(/Approve at least one pasted or Reader full-text source/).length)
      .toBeGreaterThan(0);
    expect(screen.getAllByText(
      'English research summary must contain at least 8 characters.',
    ).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByRole('heading', {
      name: '3. Review every source',
    })).toHaveFocus());
  });

  it('treats discovery approval as retrieval permission and keeps exclusion reversible', async () => {
    const user = userEvent.setup();
    vi.mocked(api.getFactoryBuild).mockResolvedValue({
      ...snapshot,
      sources: [{ ...snapshot.sources[0], reviewStatus: 'PENDING' }],
    });
    vi.mocked(api.setFactorySourceIncluded).mockResolvedValue({
      build: { ...snapshot.build, revision: snapshot.build.revision + 1 },
      sources: [],
      idempotencyReplayed: false,
    });

    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByRole('button', { name: 'Allow full-text retrieval' }))
      .toBeInTheDocument();
    expect(screen.getByText('Belief update')).toBeInTheDocument();
    expect(screen.getByText(/change simulated agents’ assessed direction/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Exclude from current evidence set' }));
    await waitFor(() => expect(api.setFactorySourceIncluded).toHaveBeenCalledWith(
      snapshot.build.id,
      snapshot.sources[0].id,
      snapshot.build.revision,
      false,
    ));
    expect(api.reviewFactorySource).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Permanently delete raw text' })).toBeDisabled();
  });

  it('keeps Reader request IDs within the backend schema limit', async () => {
    const user = userEvent.setup();
    vi.mocked(api.addFactoryReaderSource).mockResolvedValue({
      build: { ...snapshot.build, revision: 5 },
      sources: [],
      idempotencyReplayed: false,
    });

    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    await user.click(await screen.findByRole('button', {
      name: 'Read full page into evidence',
    }));

    await waitFor(() => expect(api.addFactoryReaderSource).toHaveBeenCalled());
    const clientRequestId = vi.mocked(api.addFactoryReaderSource).mock.calls[0][4];
    expect(clientRequestId).toMatch(/^factory-reader-[0-9a-f-]{36}$/);
    expect(clientRequestId.length).toBeLessThanOrEqual(80);
  });

  it('keeps incomplete actions clickable and highlights the exact missing inputs', async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    await screen.findByRole('heading', { name: 'Add a case' });

    const createButton = screen.getByRole('button', { name: 'Create build' });
    expect(createButton).toBeEnabled();
    await user.click(createButton);
    expect(screen.getByLabelText('Internal build title')).toHaveAttribute('aria-invalid', 'true');
    await waitFor(() => expect(screen.getByLabelText('Internal build title')).toHaveFocus());

    const pasteButton = screen.getByRole('button', { name: 'Check and add 1 source(s)' });
    expect(pasteButton).toBeEnabled();
    await user.click(pasteButton);
    expect(screen.getByLabelText('Page title')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Publisher')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('Raw webpage text')).toHaveAttribute('aria-invalid', 'true');
    await waitFor(() => expect(screen.getByLabelText('Page title')).toHaveFocus());
    expect(api.addFactoryPasteSource).not.toHaveBeenCalled();

    const searchButton = screen.getByRole('button', { name: 'Confirm cost and search' });
    expect(searchButton).toBeEnabled();
    await user.click(searchButton);
    expect(screen.getByLabelText('Search query')).toHaveAttribute('aria-invalid', 'true');
    await waitFor(() => expect(screen.getByLabelText('Search query')).toHaveFocus());
    expect(api.searchFactorySources).not.toHaveBeenCalled();
  });

  it('shows the missing temporary Zhipu credential beside the search step', async () => {
    const user = userEvent.setup();
    vi.mocked(api.searchFactorySources).mockRejectedValueOnce(new ApiError(
      'Configure a temporary Zhipu API key before using Web Search.',
      409,
      undefined,
      'ZHIPU_TEMPORARY_CREDENTIAL_REQUIRED',
    ));

    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    const query = await screen.findByLabelText('Search query');
    await user.type(query, 'official launch notice');
    await user.click(screen.getByRole('button', { name: 'Confirm cost and search' }));

    expect(await screen.findByText(
      'Configure a temporary Zhipu API key in AI configuration, then retry this action.',
    )).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Open AI configuration' })).toBeInTheDocument();
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
          selectionStatus: 'INCLUDED',
          securityDecision: 'ALLOW',
          sourceReviewLabel: 'HOST_NOT_ALLOWLISTED',
          securityFindings: [],
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

  it('restores the guided workflow linked build without offering an invalid replacement', async () => {
    const user = userEvent.setup();
    const linkedWorkflow: GuidedWorkflow = {
      ...guidedWorkflow,
      stage: 'SOURCE_REVIEW',
      pendingProposal: undefined,
      pendingProposalId: undefined,
      draft: {
        eventMetadata: guidedWorkflow.pendingProposal!.proposedEventMetadata,
        sourceMethod: 'COMBINED',
        searchQueries: ['official notice'],
        eventPackBuildId: snapshot.build.id,
      },
    };
    const otherBuild = {
      ...snapshot.build,
      id: 'epfb-other-1234',
      title: 'Unrelated current build',
    };
    writeFactoryGuidedHandoff(linkedWorkflow);
    vi.mocked(api.getGuidedWorkflow).mockResolvedValue(linkedWorkflow);
    vi.mocked(api.getFactoryBuilds).mockResolvedValue([otherBuild, snapshot.build]);
    vi.mocked(api.getFactoryBuild).mockImplementation(async (buildId) => (
      buildId === snapshot.build.id
        ? snapshot
        : { ...snapshot, build: otherBuild }
    ));
    window.sessionStorage.setItem('eventshock:last-factory-build-id', otherBuild.id);

    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByRole('heading', {
      name: snapshot.build.title,
    })).toBeInTheDocument();
    expect(screen.getByText('The guided workflow already has a linked build')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Link current build' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /Unrelated current build/ }));
    expect(await screen.findByRole('button', { name: 'Open linked build' })).toBeInTheDocument();
    expect(api.linkGuidedWorkflowArtifacts).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Open linked build' }));
    expect(await screen.findByRole('heading', {
      name: snapshot.build.title,
    })).toBeInTheDocument();
    expect(api.linkGuidedWorkflowArtifacts).not.toHaveBeenCalled();
  });

  it('does not select an unrelated saved build for an unlinked guided handoff', async () => {
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
    vi.mocked(api.getGuidedWorkflow).mockResolvedValue(sourceReviewWorkflow);
    window.sessionStorage.setItem('eventshock:last-factory-build-id', snapshot.build.id);

    render(
      <I18nProvider>
        <EventPackFactoryPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByDisplayValue('Index Inclusion Event')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Create a build first' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: snapshot.build.title })).not.toBeInTheDocument();
    expect(api.getFactoryBuild).not.toHaveBeenCalled();
  });

  it('prefills reviewed guided metadata and links only the server-returned build ID', async () => {
    const user = userEvent.setup();
    vi.spyOn(window, 'confirm').mockReturnValue(true);
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
    vi.mocked(api.getGuidedTurnOperations).mockResolvedValue([]);
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
    expect(advance).toBeEnabled();

    await user.click(advance);

    expect(api.advanceGuidedWorkflow).not.toHaveBeenCalled();
    expect(screen.getAllByText(/Review and apply the current candidate first/).length)
      .toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByRole('heading', {
      name: 'Event goal',
      level: 3,
    })).toHaveFocus());

    await user.click(screen.getByRole('button', { name: 'Apply reviewed candidate' }));

    await waitFor(() => expect(api.applyGuidedProposal).toHaveBeenCalledWith(
      guidedWorkflow.id,
      guidedWorkflow.pendingProposalId,
      guidedWorkflow.version,
    ));
    await waitFor(() => expect(advance).toBeEnabled());
    expect(api.advanceGuidedWorkflow).not.toHaveBeenCalled();
  });

  it('shows day precision and a friendly non-blocking future-event warning', async () => {
    const precisionWorkflow: GuidedWorkflow = {
      ...guidedWorkflow,
      pendingProposal: {
        ...guidedWorkflow.pendingProposal!,
        proposedEventMetadata: {
          ...guidedWorkflow.pendingProposal!.proposedEventMetadata!,
          asOfPrecision: 'DAY',
        },
        blockedReasons: ['FUTURE_EVENT_REQUIRES_HUMAN_CONFIRMATION'],
      },
    };
    vi.mocked(api.getGuidedWorkflows).mockResolvedValue([precisionWorkflow]);
    vi.mocked(api.getGuidedWorkflow).mockResolvedValue(precisionWorkflow);

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByText('Day precision; no time was inferred')).toBeInTheDocument();
    expect(screen.getByText(/This is a planned future-event scenario/)).toBeInTheDocument();
    expect(screen.queryByText('FUTURE_EVENT_REQUIRES_HUMAN_CONFIRMATION'))
      .not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply reviewed candidate' })).toBeEnabled();
  });

  it('updates event-goal field progress while the user completes the batch panel', async () => {
    const user = userEvent.setup();
    const incompleteWorkflow: GuidedWorkflow = {
      ...guidedWorkflow,
      pendingProposal: undefined,
      pendingProposalId: undefined,
    };
    vi.mocked(api.getGuidedWorkflows).mockResolvedValue([incompleteWorkflow]);
    vi.mocked(api.getGuidedWorkflow).mockResolvedValue(incompleteWorkflow);

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findByText('0/5 complete')).toBeInTheDocument();
    await user.click(screen.getByText('Complete every field in one batch'));
    await user.type(screen.getByLabelText('Event title'), 'A bounded event');
    expect(screen.getByText('1/5 complete')).toBeInTheDocument();
  });

  it('immediately keeps the submitted user message visible and shows local elapsed progress', async () => {
    const user = userEvent.setup();
    let resolveTurn: (value: GuidedWorkflow) => void = () => undefined;
    vi.mocked(api.sendGuidedTurn).mockReturnValueOnce(new Promise((resolve) => {
      resolveTurn = resolve;
    }));

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    const composer = await screen.findByLabelText(
      'Answer this stage, or request field-level changes',
    );
    await user.clear(composer);
    await user.type(composer, 'Use the official filing cutoff.');
    await user.click(screen.getByRole('button', { name: 'Send and propose' }));

    expect(screen.getByTestId('guided-local-turn')).toHaveTextContent(
      'Use the official filing cutoff.',
    );
    expect(screen.getByText('Request sent safely')).toBeInTheDocument();
    expect(screen.getByText(/Actual wait: 0 seconds/)).toBeInTheDocument();
    expect(composer).toHaveValue('');

    resolveTurn({
      ...guidedWorkflow,
      version: guidedWorkflow.version + 1,
      messages: [
        ...guidedWorkflow.messages,
        {
          id: 'message-user-new',
          role: 'user',
          stage: guidedWorkflow.stage,
          content: 'Use the official filing cutoff.',
          createdAt: '2026-07-22T10:02:00Z',
        },
      ],
    });

    await waitFor(() => expect(screen.queryByTestId('guided-local-turn')).not.toBeInTheDocument());
    expect(screen.getAllByText('Use the official filing cutoff.')).toHaveLength(1);
  });

  it('restores failed turn text to the composer without hiding the failed message', async () => {
    const user = userEvent.setup();
    vi.mocked(api.sendGuidedTurn).mockRejectedValueOnce(new Error('Temporary gateway failure'));

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    const composer = await screen.findByLabelText(
      'Answer this stage, or request field-level changes',
    );
    await user.clear(composer);
    await user.type(composer, 'Keep this text after failure.');
    await user.click(screen.getByRole('button', { name: 'Send and propose' }));

    expect(await screen.findByText('Temporary gateway failure')).toBeInTheDocument();
    expect(composer).toHaveValue('Keep this text after failure.');
    expect(screen.getByTestId('guided-local-turn')).toHaveTextContent(
      'Failed; input restored',
    );
  });

  it('preserves an expired-credential turn and links directly to AI configuration', async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();
    vi.mocked(api.sendGuidedTurn).mockRejectedValueOnce(new ApiError(
      'The temporary model credential expired.',
      409,
      undefined,
      'LLM_CREDENTIAL_EXPIRED',
    ));

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={navigate} />
      </I18nProvider>,
    );

    const composer = await screen.findByLabelText(
      'Answer this stage, or request field-level changes',
    );
    await user.clear(composer);
    await user.type(composer, 'Preserve this credential retry.');
    await user.click(screen.getByRole('button', { name: 'Send and propose' }));

    expect(await screen.findByText(/API key expired/i)).toBeInTheDocument();
    expect(composer).toHaveValue('Preserve this credential retry.');
    await user.click(screen.getByRole('button', { name: 'Open AI configuration' }));
    expect(navigate).toHaveBeenCalledWith('ai');
  });

  it('shows provider-backed progress instead of guessing only from elapsed time', async () => {
    const user = userEvent.setup();
    vi.spyOn(crypto, 'randomUUID').mockReturnValue(
      '11111111-1111-4111-8111-111111111111',
    );
    let resolveTurn: (value: GuidedWorkflow) => void = () => undefined;
    vi.mocked(api.sendGuidedTurn).mockReturnValueOnce(new Promise((resolve) => {
      resolveTurn = resolve;
    }));
    vi.mocked(api.getGuidedTurnOperations)
      .mockResolvedValueOnce([])
      .mockResolvedValue([{
        ...unknownGuidedOperation,
        clientRequestId: 'guided-11111111-1111-4111-8111-111111111111',
        status: 'PENDING',
        cachedProposalAvailable: false,
        recoveryOptions: [],
        failureStage: 'PROVIDER_DISPATCHED',
      }]);

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    const composer = await screen.findByLabelText(
      'Answer this stage, or request field-level changes',
    );
    await user.type(composer, 'Wait for the model.');
    await user.click(screen.getByRole('button', { name: 'Send and propose' }));

    expect(await screen.findByText('Model request sent; waiting for the provider'))
      .toBeInTheDocument();
    expect(screen.getByText(/Server stage: Model request sent to the provider/)).toBeInTheDocument();

    resolveTurn(guidedWorkflow);
  });

  it('commits a cached unknown result only after explicit confirmation', async () => {
    const user = userEvent.setup();
    vi.mocked(api.getGuidedTurnOperations).mockResolvedValue([unknownGuidedOperation]);
    vi.mocked(api.recoverGuidedTurn).mockResolvedValue({
      kind: 'WORKFLOW',
      workflow: {
        ...guidedWorkflow,
        version: guidedWorkflow.version + 1,
      },
    });

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    const rawRequestIds = await screen.findAllByText(unknownGuidedOperation.clientRequestId);
    rawRequestIds.forEach((item) => expect(item).not.toBeVisible());
    const operationHistory = screen.getByText(/Model call and recovery history/).closest('details');
    if (!operationHistory) throw new Error('模型调用历史未渲染。');
    await user.click(within(operationHistory).getByText(/Model call and recovery history/));
    const historyTechnical = within(operationHistory).getByText('Technical details');
    await user.click(historyTechnical);
    expect(within(operationHistory).getByText(unknownGuidedOperation.clientRequestId)).toBeVisible();

    await user.click(await screen.findByRole('button', {
      name: 'Use cached result; no model call',
    }));
    expect(screen.getByRole('heading', { name: 'Commit the cached result?' }))
      .toBeInTheDocument();
    expect(api.recoverGuidedTurn).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    await waitFor(() => expect(api.recoverGuidedTurn).toHaveBeenCalledWith(
      guidedWorkflow.id,
      unknownGuidedOperation.clientRequestId,
      expect.objectContaining({
        action: 'RETRY_CACHED_COMMIT',
        expectedVersion: guidedWorkflow.version,
      }),
    ));
    expect(api.sendGuidedTurn).not.toHaveBeenCalled();
  });

  it('labels saved conversation language when the interface language changes', async () => {
    window.localStorage.setItem('eventshock-language', 'zh-CN');

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    expect(await screen.findAllByText('此对话以英文生成')).not.toHaveLength(0);
  });

  it('abandons an unknown result and reuses exactly the server-authorized retry ID', async () => {
    const user = userEvent.setup();
    const authorizedRetryId = 'guided-authorized-retry';
    vi.mocked(api.getGuidedTurnOperations).mockResolvedValue([{
      ...unknownGuidedOperation,
      cachedProposalAvailable: false,
      recoveryOptions: ['ABANDON_AND_AUTHORIZE_RETRY'],
    }]);
    vi.mocked(api.recoverGuidedTurn).mockResolvedValue({
      kind: 'OPERATION',
      operation: {
        ...unknownGuidedOperation,
        status: 'ABANDONED_BY_USER',
        cachedProposalAvailable: false,
        recoveryOptions: [],
        authorizedRetryClientRequestId: authorizedRetryId,
      },
    });
    vi.mocked(api.sendGuidedTurn).mockResolvedValue({
      ...guidedWorkflow,
      version: guidedWorkflow.version + 1,
    });

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    await user.click(await screen.findByRole('button', {
      name: 'Abandon and authorize one retry',
    }));
    expect(screen.getByText(/original call may already have been billed/i)).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirm' }));

    await waitFor(() => expect(api.sendGuidedTurn).toHaveBeenCalledWith(
      guidedWorkflow.id,
      {
        message: unknownGuidedOperation.requestMessage,
        language: 'en',
        expectedVersion: unknownGuidedOperation.expectedVersion,
        clientRequestId: authorizedRetryId,
      },
    ));
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

    await user.click(screen.getByRole('button', {
      name: 'I reviewed this stage, continue',
    }));

    expect(api.advanceGuidedWorkflow).not.toHaveBeenCalled();
    expect(screen.getAllByText(/generate a real Event Pack/).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.getByRole('heading', {
      name: 'Complete review in the dedicated workspace',
    })).toHaveFocus());

    await user.click(screen.getByRole('button', { name: 'Open Event Pack Factory' }));

    expect(navigate).toHaveBeenCalledWith('factory');
    expect(readFactoryGuidedHandoff()).toMatchObject({
      workflowId: sourceReviewWorkflow.id,
      sourceMethod: 'PASTE',
      searchQueries: ['official event notice'],
    });
  });

  it('places a server-side review blocker beside the workspace that can fix it', async () => {
    const user = userEvent.setup();
    const claimReviewWorkflow: GuidedWorkflow = {
      ...guidedWorkflow,
      stage: 'CLAIM_REVIEW',
      pendingProposal: undefined,
      pendingProposalId: undefined,
      draft: {
        eventMetadata: guidedWorkflow.pendingProposal!.proposedEventMetadata,
        sourceMethod: 'PASTE',
        searchQueries: [],
        eventPackId: 'event-pack-12345678',
      },
    };
    vi.mocked(api.getGuidedWorkflows).mockResolvedValue([claimReviewWorkflow]);
    vi.mocked(api.getGuidedWorkflow).mockResolvedValue(claimReviewWorkflow);
    vi.mocked(api.advanceGuidedWorkflow).mockRejectedValueOnce(new ApiError(
      'every candidate claim needs an explicit human review decision',
      422,
      undefined,
      'GUIDED_WORKFLOW_STAGE_INCOMPLETE',
    ));

    render(
      <I18nProvider>
        <GuidedWorkflowPage navigate={vi.fn()} />
      </I18nProvider>,
    );

    await user.click(await screen.findByRole('button', {
      name: 'I reviewed this stage, continue',
    }));

    expect(await screen.findByText(
      'every candidate claim needs an explicit human review decision',
    )).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole('heading', {
      name: 'Complete review in the dedicated workspace',
    })).toHaveFocus());
    expect(screen.getByText('The dedicated workspace is incomplete')).toBeInTheDocument();
  });
});
