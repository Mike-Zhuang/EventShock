import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
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
});
