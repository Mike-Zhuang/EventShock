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
});
