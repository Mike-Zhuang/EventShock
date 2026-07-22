import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, setCsrfToken } from './client';
import type { ResultInterpretationChatInput } from './types';

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  window.localStorage.clear();
});

describe('结果解释 API 客户端', () => {
  it('只向实验专属端点提交会话消息，不复制结果或 API Key', async () => {
    window.localStorage.setItem('eventshockSessionId', 'session-one');
    setCsrfToken('csrf-one');
    const payload = {
      schemaVersion: '1.0.0',
      conversationId: 'conversation-one',
      clientRequestId: 'request-one',
      experimentId: 'experiment/one',
      resultHash: 'abc123',
      message: {
        id: 'message-one',
        role: 'assistant',
        language: 'en',
        answer: 'The paired difference is small.',
        groundingReferences: ['result:metric-summary'],
        followUpSuggestions: [],
        toolActivity: [],
        provider: 'zhipu',
        model: 'glm-5',
        promptTokens: 10,
        completionTokens: 8,
        cachedTokens: 0,
        totalTokens: 18,
        modelCalls: 1,
        cacheHit: false,
        repairUsed: false,
        plannerUsed: false,
        promptVersion: 'result_interpretation_v1.0.0',
        latencyMs: 123,
        createdAt: '2026-07-22T12:00:00Z',
      },
    };
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0',
      conversationId: 'conversation-one',
      clientRequestId: 'request-one',
      mode: 'INITIAL',
      language: 'en',
      reasoningSummaryRequested: false,
      messages: [],
    };

    await expect(api.chatAboutResults('experiment/one', input)).resolves.toMatchObject({
      conversationId: 'conversation-one',
      message: { answer: 'The paired difference is small.' },
    });

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/experiments/experiment%2Fone/interpretation-chat',
      expect.objectContaining({
        method: 'POST',
        credentials: 'same-origin',
        headers: expect.objectContaining({
          'X-CSRF-Token': 'csrf-one',
          'X-Session-ID': 'session-one',
        }),
        body: JSON.stringify(input),
      }),
    );
    const requestBody = JSON.parse(fetchMock.mock.calls[0][1]?.body as string) as Record<string, unknown>;
    expect(requestBody).not.toHaveProperty('apiKey');
    expect(requestBody).not.toHaveProperty('results');
  });
});
