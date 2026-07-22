import { describe, expect, it } from 'vitest';
import { normalizeResultInterpretationChatResponse } from './normalize';

const VALID_RESPONSE = {
  schema_version: '1.0.0',
  conversation_id: 'conversation-one',
  client_request_id: 'request-one',
  experiment_id: 'experiment-one',
  result_hash: 'abc123',
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
      },
    });
  });

  it.each([
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
    ['invalid timestamp', { ...VALID_RESPONSE, message: { ...VALID_RESPONSE.message, created_at: 'not-a-date' } }],
  ])('拒绝不完整或类型漂移的响应：%s', (_name, payload) => {
    expect(() => normalizeResultInterpretationChatResponse(payload)).toThrow(TypeError);
  });
});
