import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ResultInterpretationStreamError, setCsrfToken } from './client';
import type { ResultInterpretationChatInput } from './types';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setCsrfToken(undefined);
  window.localStorage.clear();
});

function validFinalPayload(
  input: ResultInterpretationChatInput,
  experimentId: string,
  answer = 'Validated final answer.',
) {
  return {
    schemaVersion: '1.0.0',
    conversationId: input.conversationId,
    clientRequestId: input.clientRequestId,
    experimentId,
    resultHash: 'sha256:validated-final',
    historyPersisted: true,
    message: {
      id: `message-${input.clientRequestId}`,
      role: 'assistant',
      language: input.language,
      answer,
      groundingReferences: ['result:overview'],
      followUpSuggestions: [],
      toolActivity: [],
      provider: 'zhipu',
      model: 'glm-5',
      promptTokens: 1,
      completionTokens: 1,
      cachedTokens: 0,
      totalTokens: 2,
      modelCalls: 1,
      cacheHit: false,
      repairUsed: false,
      plannerUsed: false,
      promptVersion: 'result_interpretation_v1.0.0',
      latencyMs: 20,
      createdAt: '2026-07-22T12:00:00Z',
    },
  };
}

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
      historyPersisted: true,
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

  it('使用账户隔离的 GET/DELETE 端点读取和删除解释历史', async () => {
    window.localStorage.setItem('eventshockSessionId', 'session-history');
    setCsrfToken('csrf-history');
    const conversationId = 'conversation/one';
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0',
      conversationId,
      clientRequestId: 'request-history',
      mode: 'INITIAL',
      language: 'en',
      reasoningSummaryRequested: false,
      messages: [{ role: 'user', content: 'Explain the result.' }],
    };
    const summary = {
      conversationId,
      experimentId: 'experiment/history',
      language: 'en',
      exchangeCount: 1,
      lastUserMessage: 'Explain the result.',
      createdAt: '2026-07-22T12:00:00Z',
      updatedAt: '2026-07-22T12:01:00Z',
    };
    const fetchMock = vi.fn(async (request: RequestInfo | URL, init?: RequestInit) => {
      const url = String(request);
      const payload = init?.method === 'DELETE'
        ? { schemaVersion: '1.0.0', deleted: true, conversationId }
        : url.endsWith('/conversation%2Fone')
          ? {
            schemaVersion: '1.0.0',
            conversationId,
            experimentId: 'experiment/history',
            language: 'en',
            createdAt: summary.createdAt,
            updatedAt: summary.updatedAt,
            messages: [{
              id: 'user-history', role: 'user', language: 'en',
              content: 'Explain the result.', createdAt: summary.createdAt,
            }, validFinalPayload(input, 'experiment/history').message],
          }
          : { schemaVersion: '1.0.0', items: [summary] };
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.getResultInterpretationConversations('experiment/history'))
      .resolves.toMatchObject({ items: [{ conversationId, exchangeCount: 1 }] });
    await expect(api.getResultInterpretationConversation('experiment/history', conversationId))
      .resolves.toMatchObject({ conversationId, messages: [{ role: 'user' }, { role: 'assistant' }] });
    await expect(api.deleteResultInterpretationConversation('experiment/history', conversationId))
      .resolves.toEqual({ schemaVersion: '1.0.0', deleted: true, conversationId });

    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      '/api/v1/experiments/experiment%2Fhistory/interpretation-conversations',
      '/api/v1/experiments/experiment%2Fhistory/interpretation-conversations/conversation%2Fone',
      '/api/v1/experiments/experiment%2Fhistory/interpretation-conversations/conversation%2Fone',
    ]);
    expect(fetchMock.mock.calls[2][1]).toEqual(expect.objectContaining({
      method: 'DELETE',
      headers: expect.objectContaining({ 'X-CSRF-Token': 'csrf-history' }),
    }));
  });

  it('通过 POST SSE 解析分块阶段与最终结构化响应，不暴露服务端自由文本', async () => {
    window.localStorage.setItem('eventshockSessionId', 'session-stream');
    setCsrfToken('csrf-stream');
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0',
      conversationId: 'conversation-stream',
      clientRequestId: 'request-stream',
      mode: 'INITIAL',
      language: 'zh-CN',
      reasoningSummaryRequested: true,
      messages: [{ role: 'user', content: '解释结果' }],
    };
    const finalPayload = {
      schemaVersion: '1.0.0',
      conversationId: input.conversationId,
      clientRequestId: input.clientRequestId,
      experimentId: 'experiment/stream',
      resultHash: 'sha256:stream',
      historyPersisted: true,
      message: {
        id: 'message-stream', role: 'assistant', language: 'zh-CN', answer: '结果解释。',
        analysisSummary: '核对了主要指标。', groundingReferences: ['result:overview'],
        followUpSuggestions: [], toolActivity: [], provider: 'zhipu', model: 'glm-5',
        promptTokens: 10, completionTokens: 8, cachedTokens: 0, totalTokens: 18,
        modelCalls: 1, cacheHit: false, repairUsed: false, plannerUsed: false,
        promptVersion: 'result_interpretation_v1.0.0', latencyMs: 800,
        createdAt: '2026-07-22T12:00:00Z',
      },
    };
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        // 特意把 CRLF 拆在两个网络块之间，覆盖 Safari/代理常见的分块边界。
        controller.enqueue(encoder.encode(': heartbeat\r'));
        controller.enqueue(encoder.encode('\n\r\nevent: sta'));
        controller.enqueue(encoder.encode('tus\r\ndata: {"schemaVersion":"1.0.0","stage":"PREPARING","elapsedMs":10,"message":"do not display this"}\r'));
        controller.enqueue(encoder.encode('\n\r\n'));
        controller.enqueue(encoder.encode('event: progress\ndata: {"schemaVersion":"1.0.0","stage":"GENERATING","elapsedMs":720,"chunkCount":7,"answerChunkCount":5,"reasoningChunkCount":2}\n\n'));
        controller.enqueue(encoder.encode(`event: final\ndata: ${JSON.stringify(finalPayload)}\n\n`));
        controller.close();
      },
    });
    const fetchMock = vi.fn(async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
    }));
    vi.stubGlobal('fetch', fetchMock);
    const updates: unknown[] = [];

    const result = await api.streamChatAboutResults(
      'experiment/stream',
      input,
      (update) => updates.push(update),
    );

    expect(result).toMatchObject({
      transport: 'sse',
      receivedEventCount: 3,
      response: { message: { answer: '结果解释。' } },
    });
    expect(updates).toEqual([
      expect.objectContaining({
        kind: 'status',
        receivedEventCount: 1,
        progress: { schemaVersion: '1.0.0', stage: 'PREPARING', elapsedMs: 10 },
      }),
      expect.objectContaining({
        kind: 'progress',
        receivedEventCount: 2,
        progress: expect.objectContaining({ stage: 'GENERATING', chunkCount: 7 }),
      }),
    ]);
    expect(updates).not.toContainEqual(expect.objectContaining({ message: expect.anything() }));
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v1/experiments/experiment%2Fstream/interpretation-chat/stream',
      expect.objectContaining({
        method: 'POST',
        cache: 'no-store',
        body: JSON.stringify(input),
        headers: expect.objectContaining({
          Accept: 'text/event-stream',
          'X-CSRF-Token': 'csrf-stream',
          'X-Session-ID': 'session-stream',
        }),
      }),
    );
  });

  it('将 SSE error 事件转为包含重试与计费不确定性的类型化错误', async () => {
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0', conversationId: 'conversation-error',
      clientRequestId: 'request-error', mode: 'FOLLOW_UP', language: 'en',
      reasoningSummaryRequested: false, messages: [{ role: 'user', content: 'Why?' }],
    };
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: error\ndata: {"code":"MODEL_TIMEOUT","message":"provider timeout","retryable":true,"httpStatus":502,"uncertainBillableAttempts":1,"traceId":"trace-one"}\n\n'));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })));

    const promise = api.streamChatAboutResults('experiment-error', input, vi.fn());
    await expect(promise).rejects.toMatchObject({
      name: 'ResultInterpretationStreamError',
      code: 'MODEL_TIMEOUT',
      retryable: true,
      uncertainBillableAttempts: 1,
      traceId: 'trace-one',
    });
    await promise.catch((error: unknown) => {
      expect(error).toBeInstanceOf(ResultInterpretationStreamError);
    });
  });

  it('最终响应已验证后忽略 reader.cancel 清理失败', async () => {
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0', conversationId: 'conversation-cancel-cleanup',
      clientRequestId: 'request-cancel-cleanup', mode: 'INITIAL', language: 'en',
      reasoningSummaryRequested: false, messages: [{ role: 'user', content: 'Explain.' }],
    };
    const encoder = new TextEncoder();
    const payload = validFinalPayload(input, 'experiment-cancel-cleanup');
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(`event: final\ndata: ${JSON.stringify(payload)}\n\n`));
      },
      cancel() {
        throw new Error('underlying cancel failed');
      },
    });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })));

    await expect(api.streamChatAboutResults('experiment-cancel-cleanup', input, vi.fn()))
      .resolves.toMatchObject({
        transport: 'sse',
        response: { message: { answer: 'Validated final answer.' } },
      });
  });

  it('将 200 application/json 的无效结构映射为类型化 CONTRACT_INVALID', async () => {
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0', conversationId: 'conversation-invalid-json',
      clientRequestId: 'request-invalid-json', mode: 'INITIAL', language: 'en',
      reasoningSummaryRequested: false, messages: [{ role: 'user', content: 'Explain.' }],
    };
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ invalid: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })));

    await expect(api.streamChatAboutResults('experiment-invalid-json', input, vi.fn()))
      .rejects.toMatchObject({
        name: 'ResultInterpretationStreamError',
        code: 'RESULT_INTERPRETATION_STREAM_CONTRACT_INVALID',
        uncertainBillableAttempts: 1,
      });
  });

  it('流式端点不存在时以同一请求内容回退旧 JSON API', async () => {
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0', conversationId: 'conversation-fallback',
      clientRequestId: 'request-fallback', mode: 'INITIAL', language: 'en',
      reasoningSummaryRequested: false, messages: [{ role: 'user', content: 'Explain.' }],
    };
    const payload = {
      schemaVersion: '1.0.0', conversationId: input.conversationId,
      clientRequestId: input.clientRequestId, experimentId: 'experiment-fallback',
      resultHash: 'sha256:fallback',
      historyPersisted: true,
      message: {
        id: 'message-fallback', role: 'assistant', language: 'en', answer: 'Fallback answer.',
        groundingReferences: ['result:overview'], followUpSuggestions: [], toolActivity: [],
        provider: 'zhipu', model: 'glm-5', promptTokens: 1, completionTokens: 1,
        cachedTokens: 0, totalTokens: 2, modelCalls: 1, cacheHit: false,
        repairUsed: false, plannerUsed: false, promptVersion: 'result_interpretation_v1.0.0',
        latencyMs: 20, createdAt: '2026-07-22T12:00:00Z',
      },
    };
    const updates: unknown[] = [];
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.streamChatAboutResults(
      'experiment-fallback',
      input,
      (update) => updates.push(update),
    ))
      .resolves.toMatchObject({
        transport: 'json-fallback',
        response: { clientRequestId: 'request-fallback' },
      });
    expect(updates).toEqual([
      expect.objectContaining({
        kind: 'fallback',
        receivedEventCount: 0,
        elapsedMs: expect.any(Number),
      }),
    ]);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      '/api/v1/experiments/experiment-fallback/interpretation-chat',
      expect.objectContaining({ body: JSON.stringify(input) }),
    );
  });

  it('JSON fallback 保留服务端明确的可重试性与无法确认计费次数', async () => {
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0', conversationId: 'conversation-fallback-error',
      clientRequestId: 'request-fallback-error', mode: 'FOLLOW_UP', language: 'en',
      reasoningSummaryRequested: false, messages: [{ role: 'user', content: 'Explain safely.' }],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        error: {
          code: 'CONTENT_FILTERED',
          message: 'provider filtered content',
          retryable: false,
          uncertainBillableAttempts: 2,
          traceId: 'trace-fallback-error',
        },
      }), {
        status: 502,
        headers: { 'Content-Type': 'application/json' },
      }));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api.streamChatAboutResults('experiment-fallback-error', input, vi.fn()))
      .rejects.toMatchObject({
        name: 'ResultInterpretationStreamError',
        code: 'CONTENT_FILTERED',
        retryable: false,
        uncertainBillableAttempts: 2,
        traceId: 'trace-fallback-error',
      });
  });

  it('将 JSON fallback 的 fetch 网络 TypeError 映射为可同 ID 恢复的 INTERRUPTED', async () => {
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0', conversationId: 'conversation-fallback-network',
      clientRequestId: 'request-fallback-network', mode: 'INITIAL', language: 'en',
      reasoningSummaryRequested: false, messages: [{ role: 'user', content: 'Explain.' }],
    };
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 404 }))
      .mockRejectedValueOnce(new TypeError('Failed to fetch')));

    await expect(api.streamChatAboutResults('experiment-fallback-network', input, vi.fn()))
      .rejects.toMatchObject({
        name: 'ResultInterpretationStreamError',
        code: 'RESULT_INTERPRETATION_STREAM_INTERRUPTED',
        retryable: true,
        uncertainBillableAttempts: 1,
      });
  });

  it.each([
    ['frame', `${'x'.repeat(300_000)}\n\n`, 'RESULT_INTERPRETATION_STREAM_FRAME_LIMIT_EXCEEDED'],
    ['buffer', 'x'.repeat(520_000), 'RESULT_INTERPRETATION_STREAM_BUFFER_LIMIT_EXCEEDED'],
  ])('拒绝超过安全上限的 SSE %s', async (_kind, oversizedContent, expectedCode) => {
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0', conversationId: 'conversation-oversized',
      clientRequestId: `request-${expectedCode}`, mode: 'INITIAL', language: 'en',
      reasoningSummaryRequested: false, messages: [{ role: 'user', content: 'Explain.' }],
    };
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(oversizedContent));
        controller.close();
      },
    });
    vi.stubGlobal('fetch', vi.fn(async () => new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    })));

    await expect(api.streamChatAboutResults('experiment-oversized', input, vi.fn()))
      .rejects.toMatchObject({
        name: 'ResultInterpretationStreamError',
        code: expectedCode,
        uncertainBillableAttempts: 1,
      });
  });

  it('每次收到心跳数据都会重置无活动超时', async () => {
    vi.useFakeTimers();
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0', conversationId: 'conversation-heartbeat',
      clientRequestId: 'request-heartbeat', mode: 'INITIAL', language: 'en',
      reasoningSummaryRequested: false, messages: [{ role: 'user', content: 'Explain.' }],
    };
    const encoder = new TextEncoder();
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode(': heartbeat\n\n'));
          window.setTimeout(() => controller.enqueue(encoder.encode(': heartbeat\n\n')), 20_000);
          init?.signal?.addEventListener('abort', () => {
            controller.error(new DOMException('Aborted', 'AbortError'));
          }, { once: true });
        },
      });
      return new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const promise = api.streamChatAboutResults('experiment-heartbeat', input, vi.fn());
    let settled = false;
    void promise.then(() => { settled = true; }, () => { settled = true; });
    await vi.advanceTimersByTimeAsync(20_000);
    await vi.advanceTimersByTimeAsync(29_000);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1_001);
    await expect(promise).rejects.toMatchObject({
      code: 'RESULT_INTERPRETATION_STREAM_TIMEOUT',
      retryable: true,
    });
  });

  it('持续心跳不能绕过十分钟硬上限', async () => {
    vi.useFakeTimers();
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0', conversationId: 'conversation-hard-timeout',
      clientRequestId: 'request-hard-timeout', mode: 'INITIAL', language: 'en',
      reasoningSummaryRequested: false, messages: [{ role: 'user', content: 'Explain.' }],
    };
    const encoder = new TextEncoder();
    vi.stubGlobal('fetch', vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode(': heartbeat\n\n'));
          const heartbeat = window.setInterval(() => {
            controller.enqueue(encoder.encode(': heartbeat\n\n'));
          }, 20_000);
          init?.signal?.addEventListener('abort', () => {
            window.clearInterval(heartbeat);
            controller.error(new DOMException('Aborted', 'AbortError'));
          }, { once: true });
        },
      });
      return new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      });
    }));

    const promise = api.streamChatAboutResults('experiment-hard-timeout', input, vi.fn());
    let settled = false;
    void promise.then(() => { settled = true; }, () => { settled = true; });
    await vi.advanceTimersByTimeAsync(590_000);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(10_001);
    await expect(promise).rejects.toMatchObject({
      code: 'RESULT_INTERPRETATION_STREAM_TIMEOUT',
      retryable: true,
    });
  });
});
