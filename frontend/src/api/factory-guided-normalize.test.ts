import { describe, expect, it } from 'vitest';
import {
  normalizeFactoryMutation,
  normalizeFactorySearchEngines,
  normalizeFactorySourceRawText,
  normalizeFactorySnapshot,
  normalizeGuidedWorkflow,
} from './normalize';

const build = {
  id: 'epfb-12345678',
  ownerUserId: 'user-1',
  title: 'New event',
  status: 'DRAFT',
  revision: 3,
  createdAt: '2026-07-22T10:00:00Z',
  updatedAt: '2026-07-22T10:02:00Z',
  retentionExpiresAt: '2026-07-29T10:02:00Z',
};

const source = {
  id: 'epfsrc-12345678',
  buildId: build.id,
  kind: 'READER',
  evidenceRole: 'EVIDENCE',
  reviewStatus: 'APPROVED',
  securityDecision: 'ALLOW',
  title: 'Official filing',
  publisher: 'Example Exchange',
  url: 'https://example.com/filing',
  publishedAt: '2026-07-22T09:00:00Z',
  knownAt: '2026-07-22T09:01:00Z',
  contentHash: 'a'.repeat(64),
  contentLength: 2_400,
  reviewSummary: 'A bounded review summary.',
  verifiedEvidenceQuotes: ['Exact source quote.'],
  createdAt: '2026-07-22T10:01:00Z',
  updatedAt: '2026-07-22T10:02:00Z',
};

describe('Event Pack Factory normalizers', () => {
  it('preserves provider price and capability boundaries', () => {
    expect(normalizeFactorySearchEngines({
      items: [{
        engine: 'search_pro',
        displayName: 'Web Search Pro',
        priceCnyPerCall: 0.03,
        supportsCount: true,
        supportedCounts: [10, 20, 30, 40, 50],
        supportsDomainFilter: true,
        supportsRecencyFilter: true,
        supportsContentSize: true,
      }],
    })).toEqual([expect.objectContaining({
      engine: 'search_pro',
      priceCnyPerCall: 0.03,
      supportedCounts: [10, 20, 30, 40, 50],
    })]);
  });

  it('normalizes a complete snapshot and mutation without retaining unknown rich objects', () => {
    expect(normalizeFactorySnapshot({
      build,
      sources: [source],
      searchRuns: [{
        id: 'epfsr-12345678',
        buildId: build.id,
        engine: 'search_std',
        query: 'official filing',
        queryHash: 'b'.repeat(64),
        requestParameters: { count: 10, nested: { must: 'not leak' } },
        providerRequestId: 'provider-1',
        estimatedCostCny: 0.01,
        resultCount: 1,
        droppedResultCount: 0,
        createdAt: '2026-07-22T10:01:00Z',
      }],
    })).toMatchObject({
      build: { id: build.id, revision: 3 },
      sources: [{ id: source.id, evidenceRole: 'EVIDENCE' }],
      searchRuns: [{ requestParameters: { count: 10 } }],
    });

    expect(normalizeFactoryMutation({ build, sources: [source] })).toMatchObject({
      build: { id: build.id },
      sources: [{ reviewStatus: 'APPROVED' }],
    });
  });

  it('fails closed for unknown enum values and malformed collections', () => {
    expect(() => normalizeFactorySnapshot({
      build,
      sources: [{ ...source, evidenceRole: 'SEARCH_IS_EVIDENCE' }],
      searchRuns: [],
    })).toThrow(/evidenceRole/);
    expect(() => normalizeFactorySearchEngines({ items: [{ engine: 'made-up' }] }))
      .toThrow(/engine/);
    expect(() => normalizeFactoryMutation({ build, sources: 'not-an-array' }))
      .toThrow(/sources/);
  });

  it('normalizes owner-only raw text without accepting malformed sensitive fields', () => {
    expect(normalizeFactorySourceRawText({
      buildId: build.id,
      sourceId: source.id,
      revision: 3,
      rawText: 'Exact retained source body.',
      contentHash: 'c'.repeat(64),
      contentLength: 27,
      retentionExpiresAt: build.retentionExpiresAt,
    })).toEqual({
      buildId: build.id,
      sourceId: source.id,
      revision: 3,
      rawText: 'Exact retained source body.',
      contentHash: 'c'.repeat(64),
      contentLength: 27,
      retentionExpiresAt: build.retentionExpiresAt,
    });

    expect(() => normalizeFactorySourceRawText({
      buildId: build.id,
      sourceId: source.id,
      revision: 3,
      rawText: { nested: 'must not be coerced' },
      contentHash: 'c'.repeat(64),
      contentLength: 27,
      retentionExpiresAt: build.retentionExpiresAt,
    })).toThrow(/rawText/);
  });
});

describe('guided-workflow normalizer', () => {
  const workflow = {
    schemaVersion: '1.0.0',
    id: 'guided-12345678',
    stage: 'EVENT_GOAL',
    status: 'ACTIVE',
    version: 2,
    language: 'zh-CN',
    draft: {
      eventMetadata: null,
      sourceMethod: null,
      searchQueries: [],
      intervention: null,
      eventPackBuildId: null,
      eventPackId: null,
      scenarioId: null,
    },
    pendingProposal: {
      schemaVersion: 'guided_proposal_v1.0.0',
      stage: 'EVENT_GOAL',
      assistantMessage: '请检查这份候选事件元数据。',
      clarificationRequired: false,
      proposedEventMetadata: {
        title: 'Example Event',
        titleZh: '示例事件',
        summary: 'A bounded event summary.',
        summaryZh: '一段有边界的事件摘要。',
        instrument: 'EXAMPLE',
        asOf: '2026-07-22T10:00:00Z',
        researchQuestion: 'How does liquidity change under one intervention?',
      },
      proposedSourceMethod: null,
      proposedSearchQueries: [],
      proposedIntervention: null,
      nextQuestionOptions: ['Change the instrument.'],
      readyForHumanReview: true,
      blockedReasons: [],
    },
    pendingProposalId: 'proposal-12345678',
    messages: [{
      id: 'message-12345678',
      role: 'assistant',
      stage: 'EVENT_GOAL',
      content: '请描述事件。',
      proposalId: null,
      createdAt: '2026-07-22T10:00:00Z',
    }],
    createdAt: '2026-07-22T10:00:00Z',
    updatedAt: '2026-07-22T10:01:00Z',
  };

  it('preserves only the strict guided proposal and draft contract', () => {
    expect(normalizeGuidedWorkflow(workflow)).toMatchObject({
      id: workflow.id,
      stage: 'EVENT_GOAL',
      pendingProposal: {
        readyForHumanReview: true,
        proposedEventMetadata: { instrument: 'EXAMPLE' },
      },
      messages: [{ role: 'assistant' }],
    });
  });

  it('keeps unresolved fields separate when a proposal is not ready', () => {
    const normalized = normalizeGuidedWorkflow({
      ...workflow,
      pendingProposal: {
        ...workflow.pendingProposal,
        proposedEventMetadata: null,
        readyForHumanReview: false,
        clarificationRequired: true,
        missing_fields: ['instrument'],
        unresolved_fields: [{
          field: 'instrument',
          reason: 'The user has not identified the synthetic instrument.',
        }],
      },
    });

    expect(normalized.pendingProposal).toMatchObject({
      readyForHumanReview: false,
      proposedEventMetadata: undefined,
      missingFields: ['instrument'],
      unresolvedFields: [{
        field: 'instrument',
        reason: 'The user has not identified the synthetic instrument.',
      }],
    });
  });

  it('rejects unsupported stages, schema versions, and intervention parameters', () => {
    expect(() => normalizeGuidedWorkflow({ ...workflow, stage: 'FREE_PLAY_CHAT' }))
      .toThrow(/stage/);
    expect(() => normalizeGuidedWorkflow({ ...workflow, schemaVersion: '2.0.0' }))
      .toThrow(/schema/);
    expect(() => normalizeGuidedWorkflow({
      ...workflow,
      pendingProposal: {
        ...workflow.pendingProposal,
        proposedEventMetadata: null,
        proposedIntervention: {
          parameter: 'setPrice',
          baselineValue: 1,
          interventionValue: 2,
          explanation: 'This should be rejected.',
        },
      },
    })).toThrow(/parameter/);
  });
});
