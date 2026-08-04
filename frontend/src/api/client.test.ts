import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, AUTH_SESSION_EXPIRED_EVENT, setCsrfToken } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  window.localStorage.clear();
});

describe('API client event stream', () => {
  it('parses chunked experiment SSE updates and ignores heartbeats', async () => {
    window.localStorage.setItem('eventshockSessionId', 'test-session');
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(': keep-alive\n\nid: 1\nevent: experi'));
        controller.enqueue(encoder.encode('ment\ndata: {"id":"exp-1","status":"RUNNING","request":{"eventPackId":"pack-1","intervention":{"parameter":"marketMakerCapacity","baselineValue":1,"interventionValue":0.5},"seedCount":10,"populationSize":56,"steps":120},"progress":0.25,"logs":[]}\n\n'));
        controller.close();
      },
    });
    const fetchMock = vi.fn(async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    const updates: string[] = [];

    await api.streamExperiment('exp-1', (experiment) => {
      updates.push(`${experiment.status}:${experiment.progress}`);
    }, new AbortController().signal);

    expect(updates).toEqual(['RUNNING:25']);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/experiments/exp-1/events',
      expect.objectContaining({ cache: 'no-store' }),
    );
  });

  it('uses same-origin cookies and keeps the CSRF token only in request memory', async () => {
    window.localStorage.setItem('eventshockSessionId', 'test-session');
    setCsrfToken('csrf-memory-only');
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    await api.logout();

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/logout', expect.objectContaining({
      method: 'POST',
      credentials: 'same-origin',
      headers: expect.objectContaining({
        'X-CSRF-Token': 'csrf-memory-only',
        'X-Session-ID': 'test-session',
      }),
    }));
    expect(window.localStorage.getItem('eventshockCsrfToken')).toBeNull();
  });

  it('requests a cognition-only rule continuation without cancelling the experiment', async () => {
    window.localStorage.setItem('eventshockSessionId', 'test-session');
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      id: 'exp-hybrid',
      status: 'RUNNING',
      cognition_fallback_requested: true,
      request: {
        eventPackId: 'pack-1',
        intervention: {
          parameter: 'marketMakerCapacity',
          baselineValue: 1,
          interventionValue: 0.5,
        },
        seedCount: 10,
        populationSize: 56,
        steps: 120,
      },
      progress: 0.02,
      logs: [],
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    const experiment = await api.continueCognitionWithRules('exp-hybrid');

    expect(experiment.cognitionFallbackRequested).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/experiments/exp-hybrid/cognition/continue-with-rules',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('re-verifies account export and deletion with explicit same-origin payloads', async () => {
    window.localStorage.setItem('eventshockSessionId', 'test-session');
    setCsrfToken('csrf-memory-only');
    const responses = [
      new Response(JSON.stringify({
        schema_version: 'account_data_export_v1.0.0',
        generated_at: '2026-07-29T12:00:00Z',
        retention_notice: 'Backups follow normal retention.',
        excluded_secrets: ['password hashes', 'session tokens'],
        data: {
          account: [{ id: 'user-1', email: 'analyst@example.com' }],
          preferences: [],
        },
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
      new Response(JSON.stringify({
        deleted: true,
        deleted_record_count: 17,
        backup_retention_notice: 'Backups follow normal retention.',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    ];
    const fetchMock = vi.fn(async () => {
      const response = responses.shift();
      if (!response) throw new Error('Unexpected account API request.');
      return response;
    });
    vi.stubGlobal('fetch', fetchMock);

    const exported = await api.exportAccountData({
      currentPassword: 'Current password 123!',
    });
    const deleted = await api.deleteAccount({
      currentPassword: 'Current password 123!',
      confirmation: 'DELETE',
    });

    expect(exported).toMatchObject({
      schemaVersion: 'account_data_export_v1.0.0',
      data: { account: [{ id: 'user-1' }] },
    });
    expect(deleted).toEqual({
      deleted: true,
      deletedRecordCount: 17,
      backupRetentionNotice: 'Backups follow normal retention.',
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/account/data-export',
      expect.objectContaining({
        method: 'POST',
        credentials: 'same-origin',
        body: JSON.stringify({ password: 'Current password 123!' }),
        headers: expect.objectContaining({
          'X-CSRF-Token': 'csrf-memory-only',
          'X-Session-ID': 'test-session',
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/account',
      expect.objectContaining({
        method: 'DELETE',
        credentials: 'same-origin',
        body: JSON.stringify({
          password: 'Current password 123!',
          confirmation: 'DELETE',
        }),
        headers: expect.objectContaining({
          'X-CSRF-Token': 'csrf-memory-only',
          'X-Session-ID': 'test-session',
        }),
      }),
    );
  });

  it('does not expire the session when current-password re-verification returns 401', async () => {
    const listener = vi.fn();
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, listener);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({
        error: {
          code: 'AUTHENTICATION_FAILED',
          message: 'Invalid current password.',
        },
      }),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    )));

    await expect(api.exportAccountData({
      currentPassword: 'dummy-incorrect-password',
    })).rejects.toMatchObject({
      status: 401,
      code: 'AUTHENTICATION_FAILED',
    });

    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, listener);
  });

  it('does not expire the session when administrator credential re-verification returns 403', async () => {
    const listener = vi.fn();
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, listener);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({
        error: {
          code: 'ADMIN_REAUTHENTICATION_FAILED',
          message: 'The current administrator password is incorrect.',
        },
      }),
      { status: 403, headers: { 'Content-Type': 'application/json' } },
    )));

    await expect(api.deleteAdminLlmCredential({
      currentPassword: 'dummy-incorrect-password',
    })).rejects.toMatchObject({
      status: 403,
      code: 'ADMIN_REAUTHENTICATION_FAILED',
    });

    expect(listener).not.toHaveBeenCalled();
    window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, listener);
  });

  it('updates administrator model settings without sending provider or API key', async () => {
    setCsrfToken('csrf-memory-only');
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({
      available: true,
      configured: true,
      storageScope: 'ADMIN_SERVER_ENCRYPTED',
      provider: 'zhipu',
      model: 'glm-5.2',
      credentialHint: '••••7391',
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await api.updateAdminLlmCredential({
      currentPassword: 'dummy-current-password',
      model: 'glm-5.2',
      thinkingEnabled: false,
      maxTokens: 4_096,
      advancedParameters: { temperature: 0.2 },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/admin/llm-credential',
      expect.objectContaining({
        method: 'PATCH',
        body: expect.not.stringContaining('apiKey'),
      }),
    );
    const requestBody = JSON.parse(
      (fetchMock.mock.calls[0]?.[1] as RequestInit | undefined)?.body as string,
    ) as Record<string, unknown>;
    expect(requestBody).not.toHaveProperty('provider');
    expect(requestBody).not.toHaveProperty('apiKey');
  });

  it('expires the session when an administrator credential request receives a real 401', async () => {
    const listener = vi.fn();
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, listener);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ error: { code: 'AUTHENTICATION_FAILED', message: 'Session expired.' } }),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    )));

    await expect(api.deleteAdminLlmCredential({
      currentPassword: 'dummy-session-expiry',
    })).rejects.toMatchObject({ status: 401 });

    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, listener);
  });

  it('broadcasts session expiry when an authenticated business request returns 401', async () => {
    const listener = vi.fn();
    window.addEventListener(AUTH_SESSION_EXPIRED_EVENT, listener);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(
      JSON.stringify({ error: { code: 'AUTH_REQUIRED', message: 'Authentication required.' } }),
      { status: 401, headers: { 'Content-Type': 'application/json' } },
    )));

    await expect(api.getCases()).rejects.toMatchObject({ status: 401 });

    expect(listener).toHaveBeenCalledTimes(1);
    window.removeEventListener(AUTH_SESSION_EXPIRED_EVENT, listener);
  });

  it('loads the read-only governance deployment evidence endpoint', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      schema_version: '1.0.0',
      deployed_commit: 'a'.repeat(40),
      health_commit: 'a'.repeat(40),
      github_main_commit: 'b'.repeat(40),
      required_checks: [
        { name: 'Backend / Python 3.12.13', status: 'PASS' },
        { name: 'Frontend / Node 22', status: 'PENDING' },
        { name: 'Production container', status: 'UNKNOWN' },
      ],
      required_checks_status: 'FAIL',
      last_sync_result: 'FAILED',
      status_source: 'RESTRICTED_STATUS_FILE',
      status_file_state: 'VERIFIED',
      observed_at: '2026-07-29T10:07:00Z',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    const status = await api.getDeploymentStatus();

    expect(status).toMatchObject({
      deployedCommit: 'a'.repeat(40),
      githubMainCommit: 'b'.repeat(40),
      requiredChecksStatus: 'FAIL',
      lastSyncResult: 'FAILED',
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/governance/deployment-status',
      expect.objectContaining({
        credentials: 'same-origin',
      }),
    );
  });

  it('submits one acknowledged bulk-approval request with the reviewed queue snapshot', async () => {
    setCsrfToken('csrf-memory-only');
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      eventPackId: 'pack-review',
      title: 'Review pack',
      status: 'DRAFT',
      sources: [],
      claims: [],
      limitations: [],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);

    await api.approveAllClaims('pack-review', {
      acknowledgedBulkApproval: true,
      expectedClaimIds: ['claim-one', 'claim-two'],
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/event-packs/pack-review/claims/approve-all',
      expect.objectContaining({
        method: 'POST',
        credentials: 'same-origin',
        body: JSON.stringify({
          acknowledgedBulkApproval: true,
          expectedClaimIds: ['claim-one', 'claim-two'],
        }),
      }),
    );
  });

  it('keeps Factory revision, Reader, review, materialization, and deletion payloads explicit', async () => {
    const build = {
      id: 'epfb-12345678',
      ownerUserId: 'user-1',
      title: 'New event',
      status: 'DRAFT',
      revision: 4,
      createdAt: '2026-07-22T10:00:00Z',
      updatedAt: '2026-07-22T10:02:00Z',
      retentionExpiresAt: '2026-07-29T10:02:00Z',
    };
    const mutationResponse = () => new Response(JSON.stringify({
      build,
      sources: [],
      searchRun: null,
    }), { status: 200, headers: { 'Content-Type': 'application/json' } });
    const fetchMock = vi.fn(async (path: string) => path.endsWith('/materialize')
      ? new Response(JSON.stringify({
        eventPackId: 'pack-factory',
        title: 'Factory pack',
        status: 'DRAFT',
        sources: [],
        claims: [],
        limitations: [],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
      : path.endsWith('/epfb-12345678') && fetchMock.mock.calls.length === 4
        ? new Response(null, { status: 204 })
        : mutationResponse());
    vi.stubGlobal('fetch', fetchMock);

    await api.addFactoryReaderSource(
      build.id,
      3,
      'epfsrc-search-1234',
      '2026-07-22T10:01:00Z',
      'factory-reader-request-1234',
    );
    await api.reviewFactorySource(build.id, 'epfsrc-reader-1234', 4, 'APPROVED');
    await api.materializeFactoryBuild(build.id, 5, {
      title: 'Factory pack',
      summary: 'A bounded research summary.',
      asOf: '2026-07-22T10:01:00Z',
      instrument: 'EXAMPLE',
      maximumClaims: 16,
      requestedImpactChannels: ['belief', 'socialAmplification'],
      acknowledgedContentReview: true,
    }, 'factory-materialize-request-1234');
    await api.deleteFactoryBuild(build.id, 6);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/event-pack-factory/builds/epfb-12345678/reader',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          clientRequestId: 'factory-reader-request-1234',
          expectedRevision: 3,
          searchResultSourceId: 'epfsrc-search-1234',
          knownAt: '2026-07-22T10:01:00Z',
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/event-pack-factory/builds/epfb-12345678/sources/epfsrc-reader-1234/review',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ expectedRevision: 4, status: 'APPROVED' }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/v1/event-pack-factory/builds/epfb-12345678/materialize',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          clientRequestId: 'factory-materialize-request-1234',
          expectedRevision: 5,
          title: 'Factory pack',
          summary: 'A bounded research summary.',
          asOf: '2026-07-22T10:01:00Z',
          instrument: 'EXAMPLE',
          maximumClaims: 16,
          requestedImpactChannels: ['belief', 'socialAmplification'],
          acknowledgedContentReview: true,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      '/api/v1/event-pack-factory/builds/epfb-12345678',
      expect.objectContaining({
        method: 'DELETE',
        body: JSON.stringify({ expectedRevision: 6 }),
      }),
    );
  });

  it('loads and edits owner-only Factory raw text without cache reuse', async () => {
    const build = {
      id: 'epfb-12345678',
      ownerUserId: 'user-1',
      title: 'New event',
      status: 'DRAFT',
      revision: 5,
      createdAt: '2026-07-22T10:00:00Z',
      updatedAt: '2026-07-22T10:03:00Z',
      retentionExpiresAt: '2026-07-29T10:03:00Z',
    };
    const rawResponse = {
      buildId: build.id,
      sourceId: 'epfsrc-reader-1234',
      revision: 4,
      rawText: 'Original retained source body.',
      contentHash: 'a'.repeat(64),
      contentLength: 30,
      retentionExpiresAt: build.retentionExpiresAt,
    };
    const fetchMock = vi.fn(async (_path: string, options?: RequestInit) => (
      options?.method === 'PUT'
        ? new Response(JSON.stringify({
          build,
          sources: [],
          searchRun: null,
          idempotencyReplayed: false,
        }), { status: 200, headers: { 'Content-Type': 'application/json' } })
        : new Response(JSON.stringify(rawResponse), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        })
    ));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.getFactorySourceRawText(build.id, rawResponse.sourceId))
      .resolves.toMatchObject({
        rawText: rawResponse.rawText,
        contentHash: rawResponse.contentHash,
      });
    await api.updateFactorySourceRawText(
      build.id,
      rawResponse.sourceId,
      rawResponse.revision,
      'Corrected retained source body.',
    );

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/event-pack-factory/builds/epfb-12345678/sources/epfsrc-reader-1234/raw-text',
      expect.objectContaining({ cache: 'no-store' }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/event-pack-factory/builds/epfb-12345678/sources/epfsrc-reader-1234/raw-text',
      expect.objectContaining({
        method: 'PUT',
        cache: 'no-store',
        body: JSON.stringify({
          expectedRevision: 4,
          rawText: 'Corrected retained source body.',
        }),
      }),
    );
  });

  it('sends guided proposals and stage acknowledgements through separate endpoints', async () => {
    const guidedResponse = {
      schemaVersion: '1.0.0',
      id: 'guided-12345678',
      stage: 'EVENT_GOAL',
      status: 'ACTIVE',
      version: 2,
      language: 'en',
      draft: {
        eventMetadata: null,
        sourceMethod: null,
        searchQueries: [],
        intervention: null,
        eventPackBuildId: null,
        eventPackId: null,
        scenarioId: null,
      },
      pendingProposal: null,
      pendingProposalId: null,
      messages: [],
      createdAt: '2026-07-22T10:00:00Z',
      updatedAt: '2026-07-22T10:01:00Z',
    };
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(guidedResponse), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await api.sendGuidedTurn(guidedResponse.id, {
      message: 'Study an index-inclusion event.',
      language: 'en',
      expectedVersion: 1,
      clientRequestId: 'guided-request-12345678',
    });
    await api.applyGuidedProposal(guidedResponse.id, 'proposal-12345678', 2);
    await api.advanceGuidedWorkflow(guidedResponse.id, 3);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      '/api/v1/guided-workflows/guided-12345678/turn',
      expect.objectContaining({
        body: JSON.stringify({
          message: 'Study an index-inclusion event.',
          language: 'en',
          expectedVersion: 1,
          clientRequestId: 'guided-request-12345678',
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/guided-workflows/guided-12345678/apply',
      expect.objectContaining({
        body: JSON.stringify({ proposalId: 'proposal-12345678', expectedVersion: 2 }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      '/api/v1/guided-workflows/guided-12345678/advance',
      expect.objectContaining({
        body: JSON.stringify({ expectedVersion: 3, acknowledgedHumanReview: true }),
      }),
    );
  });

  it('loads, recovers, and archives guided operations through explicit endpoints', async () => {
    const operation = {
      schemaVersion: '1.0.0',
      workflowId: 'guided-12345678',
      clientRequestId: 'guided-request-12345678',
      expectedVersion: 1,
      status: 'UNKNOWN',
      errorCode: 'MODEL_TIMEOUT',
      requestMessage: 'Study one bounded event.',
      language: 'en',
      cachedProposalAvailable: false,
      supersedesClientRequestId: null,
      authorizedRetryClientRequestId: null,
      recoveryOptions: ['ABANDON_AND_AUTHORIZE_RETRY'],
      providerRequestId: 'guided-provider-1',
      httpResponseReceived: false,
      usageReceived: false,
      parseCompleted: false,
      failureStage: 'PROVIDER_RESPONSE_FAILED',
      createdAt: '2026-07-29T10:00:00Z',
      updatedAt: '2026-07-29T10:01:00Z',
    };
    const archivedWorkflow = {
      schemaVersion: '1.0.0',
      id: operation.workflowId,
      stage: 'EVENT_GOAL',
      status: 'ARCHIVED',
      version: 2,
      language: 'en',
      draft: { searchQueries: [] },
      pendingProposal: null,
      pendingProposalId: null,
      messages: [],
      createdAt: '2026-07-29T10:00:00Z',
      updatedAt: '2026-07-29T10:02:00Z',
    };
    const responses = [
      { items: [operation] },
      {
        kind: 'OPERATION',
        operation: {
          ...operation,
          status: 'ABANDONED_BY_USER',
          authorizedRetryClientRequestId: 'guided-retry-12345678',
          recoveryOptions: [],
        },
      },
      archivedWorkflow,
    ];
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(responses.shift()), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.getGuidedTurnOperations(operation.workflowId))
      .resolves.toMatchObject([{ status: 'UNKNOWN', providerRequestId: 'guided-provider-1' }]);
    await expect(api.recoverGuidedTurn(
      operation.workflowId,
      operation.clientRequestId,
      {
        recoveryRequestId: 'recovery-request-12345678',
        action: 'ABANDON_AND_AUTHORIZE_RETRY',
        expectedVersion: 1,
        newClientRequestId: 'guided-retry-12345678',
      },
    )).resolves.toMatchObject({
      kind: 'OPERATION',
      operation: { status: 'ABANDONED_BY_USER' },
    });
    await expect(api.archiveGuidedWorkflow(operation.workflowId, 1))
      .resolves.toMatchObject({ status: 'ARCHIVED' });

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/guided-workflows/guided-12345678/operations/guided-request-12345678/recover',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          recoveryRequestId: 'recovery-request-12345678',
          action: 'ABANDON_AND_AUTHORIZE_RETRY',
          expectedVersion: 1,
          newClientRequestId: 'guided-retry-12345678',
        }),
      }),
    );
  });
});
