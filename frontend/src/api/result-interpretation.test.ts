import { describe, expect, it } from 'vitest';
import {
  normalizeResultInterpretationChatResponse,
  normalizeResultInterpretationConversation,
  normalizeResultInterpretationConversationDeleteResult,
  normalizeResultInterpretationConversationList,
  normalizeResultInterpretationStreamError,
  normalizeResultInterpretationStreamProgress,
} from './normalize';

const VALID_RESPONSE = {
  schema_version: '1.0.0',
  conversation_id: 'conversation-one',
  client_request_id: 'request-one',
  experiment_id: 'experiment-one',
  result_hash: 'abc123',
  history_persisted: true,
  message: {
    id: 'message-one',
    role: 'assistant',
    language: 'zh-CN',
    answer: '价差扩大，但区间仍与零重叠。',
    analysis_summary: '先检查主要指标，再核对配对差异。',
    grounding_references: ['result:metric-summary'],
    follow_up_suggestions: ['这个差异有多稳定？'],
    tool_activity: [{
      tool: 'METRIC_SUMMARY',
      label: '指标汇总',
      item_count: 3,
      truncated: false,
      evidence_id: 'result:metric-summary',
    }],
    provider: 'zhipu',
    model: 'glm-5',
    prompt_tokens: 120,
    completion_tokens: 80,
    cached_tokens: 0,
    total_tokens: 200,
    model_calls: 1,
    cache_hit: false,
    repair_used: true,
    planner_used: false,
    semantic_validation_status: 'REPAIRED',
    deterministic_fallback_used: false,
    prompt_version: 'result_interpretation_v1.0.0',
    latency_ms: 125.5,
    created_at: '2026-07-22T12:00:00Z',
  },
};

describe('结果解释响应归一化', () => {
  it('兼容 snake_case 并保留可核验的工具与用量元数据', () => {
    const response = normalizeResultInterpretationChatResponse(VALID_RESPONSE);

    expect(response).toMatchObject({
      schemaVersion: '1.0.0',
      conversationId: 'conversation-one',
      clientRequestId: 'request-one',
      experimentId: 'experiment-one',
      resultHash: 'abc123',
      historyPersisted: true,
      message: {
        role: 'assistant',
        language: 'zh-CN',
        answer: '价差扩大，但区间仍与零重叠。',
        analysisSummary: '先检查主要指标，再核对配对差异。',
        groundingReferences: ['result:metric-summary'],
        followUpSuggestions: ['这个差异有多稳定？'],
        toolActivity: [{ itemCount: 3, truncated: false }],
        totalTokens: 200,
        latencyMs: 125.5,
        repairUsed: true,
        semanticValidationStatus: 'REPAIRED',
        deterministicFallbackUsed: false,
      },
    });
  });

  it('接受可用但带自动复核提示的模型解释状态', () => {
    const response = normalizeResultInterpretationChatResponse({
      ...VALID_RESPONSE,
      message: {
        ...VALID_RESPONSE.message,
        semantic_validation_status: 'COMPLETED_WITH_WARNINGS',
      },
    });

    expect(response.message.semanticValidationStatus).toBe('COMPLETED_WITH_WARNINGS');
  });

  it('只保留固定流式阶段与安全计数，不保留服务端自由文本', () => {
    const progress = normalizeResultInterpretationStreamProgress({
      schema_version: '1.0.0',
      stage: 'REASONING',
      elapsed_ms: 1250,
      chunk_count: 9,
      answer_chunk_count: 6,
      reasoning_chunk_count: 3,
      message: 'private implementation detail',
    });

    expect(progress).toEqual({
      schemaVersion: '1.0.0',
      stage: 'REASONING',
      elapsedMs: 1250,
      chunkCount: 9,
      answerChunkCount: 6,
      reasoningChunkCount: 3,
    });
    expect(progress).not.toHaveProperty('message');
    expect(() => normalizeResultInterpretationStreamProgress({
      schemaVersion: '1.0.0', stage: 'RAW_CHAIN_OF_THOUGHT', elapsedMs: 1,
    })).toThrow(TypeError);
  });

  it('严格解析当前实验的已保存对话列表和完整交替消息', () => {
    const list = normalizeResultInterpretationConversationList({
      schema_version: '1.0.0',
      items: [{
        conversation_id: 'conversation-one',
        experiment_id: 'experiment-one',
        language: 'zh-CN',
        exchange_count: 1,
        last_user_message: '请解释主要差异。',
        created_at: '2026-07-22T12:00:00Z',
        updated_at: '2026-07-22T12:01:00Z',
      }],
    });
    expect(list.items[0]).toMatchObject({
      conversationId: 'conversation-one',
      exchangeCount: 1,
      lastUserMessage: '请解释主要差异。',
    });

    const conversation = normalizeResultInterpretationConversation({
      schemaVersion: '1.0.0',
      conversationId: 'conversation-one',
      experimentId: 'experiment-one',
      language: 'zh-CN',
      createdAt: '2026-07-22T12:00:00Z',
      updatedAt: '2026-07-22T12:01:00Z',
      messages: [{
        id: 'user-one',
        role: 'user',
        language: 'zh-CN',
        content: '请解释主要差异。',
        createdAt: '2026-07-22T12:00:00Z',
      }, VALID_RESPONSE.message],
    });
    expect(conversation.messages).toHaveLength(2);
    expect(conversation.messages[0]).toMatchObject({ role: 'user', content: '请解释主要差异。' });
    expect(conversation.messages[1]).toMatchObject({ role: 'assistant', answer: '价差扩大，但区间仍与零重叠。' });
    expect(normalizeResultInterpretationConversationDeleteResult({
      schema_version: '1.0.0',
      deleted: true,
      conversation_id: 'conversation-one',
    })).toEqual({
      schemaVersion: '1.0.0',
      deleted: true,
      conversationId: 'conversation-one',
    });
  });

  it('拒绝非交替、重复标识或未确认删除的历史契约', () => {
    const baseConversation = {
      schemaVersion: '1.0.0',
      conversationId: 'conversation-one',
      experimentId: 'experiment-one',
      language: 'zh-CN',
      createdAt: '2026-07-22T12:00:00Z',
      updatedAt: '2026-07-22T12:01:00Z',
    };
    expect(() => normalizeResultInterpretationConversation({
      ...baseConversation,
      messages: [VALID_RESPONSE.message, VALID_RESPONSE.message],
    })).toThrow(TypeError);
    expect(() => normalizeResultInterpretationConversationDeleteResult({
      schemaVersion: '1.0.0', deleted: false, conversationId: 'conversation-one',
    })).toThrow(TypeError);
  });

  it('归一化流式错误中的可重试性与计费不确定性', () => {
    expect(normalizeResultInterpretationStreamError({
      code: 'MODEL_TIMEOUT',
      message: 'provider timeout',
      retryable: true,
      http_status: 502,
      uncertain_billable_attempts: 2,
      trace_id: 'trace-two',
    })).toEqual({
      code: 'MODEL_TIMEOUT',
      message: 'provider timeout',
      retryable: true,
      httpStatus: 502,
      uncertainBillableAttempts: 2,
      traceId: 'trace-two',
    });

    expect(normalizeResultInterpretationStreamError({
      code: 'RESULT_INTERPRETATION_BUSY',
      message: 'another request is active',
      retryable: true,
      httpStatus: 409,
    })).toEqual({
      code: 'RESULT_INTERPRETATION_BUSY',
      message: 'another request is active',
      retryable: true,
      httpStatus: 409,
      uncertainBillableAttempts: 0,
      traceId: undefined,
    });
  });

  it.each([
    ['unsupported schema', { ...VALID_RESPONSE, schema_version: '2.0.0' }],
    ['missing persistence status', { ...VALID_RESPONSE, history_persisted: undefined }],
    ['missing answer', { ...VALID_RESPONSE, message: { ...VALID_RESPONSE.message, answer: '' } }],
    ['wrong role', { ...VALID_RESPONSE, message: { ...VALID_RESPONSE.message, role: 'user' } }],
    ['invalid count', {
      ...VALID_RESPONSE,
      message: {
        ...VALID_RESPONSE.message,
        tool_activity: [{ ...VALID_RESPONSE.message.tool_activity[0], item_count: -1 }],
      },
    }],
    ['missing boolean', { ...VALID_RESPONSE, message: { ...VALID_RESPONSE.message, cache_hit: undefined } }],
    ['invalid semantic status', {
      ...VALID_RESPONSE,
      message: { ...VALID_RESPONSE.message, semantic_validation_status: 'UNVERIFIED' },
    }],
    ['invalid fallback flag', {
      ...VALID_RESPONSE,
      message: { ...VALID_RESPONSE.message, deterministic_fallback_used: 'false' },
    }],
    ['invalid timestamp', { ...VALID_RESPONSE, message: { ...VALID_RESPONSE.message, created_at: 'not-a-date' } }],
  ])('拒绝不完整或类型漂移的响应：%s', (_name, payload) => {
    expect(() => normalizeResultInterpretationChatResponse(payload)).toThrow(TypeError);
  });
});
