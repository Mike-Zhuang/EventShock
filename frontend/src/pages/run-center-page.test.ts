import { describe, expect, it } from 'vitest';
import { cognitionStatusLabel, runtimeLogMessage } from './run-center-page';

describe('run center localization', () => {
  it('renders stable runtime event codes in the active interface language', () => {
    const entry = {
      timestamp: '2026-07-29T17:48:38Z',
      level: 'INFO',
      message: 'Matched pair 2 completed and checkpointed.',
      seed: 2_026_071_709,
      code: 'MATCHED_PAIR_COMPLETED',
      parameters: { pairIndex: 2 },
    };

    expect(runtimeLogMessage(entry, 'zh-CN')).toBe('第 2 组配对已完成并写入检查点。');
    expect(runtimeLogMessage(entry, 'en')).toBe('Matched pair 2 completed and checkpointed.');
  });

  it('keeps unknown raw codes out of the primary log message', () => {
    const entry = {
      timestamp: '2026-07-29T17:48:38Z',
      level: 'INFO',
      message: 'Legacy worker detail.',
      code: 'LEGACY_UNKNOWN_EVENT',
    };

    expect(runtimeLogMessage(entry, 'zh-CN')).toBe('未收录的运行事件');
    expect(runtimeLogMessage(entry, 'en')).toBe('Unknown run event');
  });

  it('localizes cognition progress without exposing an empty status', () => {
    expect(cognitionStatusLabel({ status: 'MODEL_CALL_IN_PROGRESS' }, 'zh-CN')).toBe(
      '正在等待当前模型响应',
    );
    expect(cognitionStatusLabel({ status: 'RULE_CONTINUATION_REQUESTED' }, 'zh-CN')).toBe(
      '正在停止后续模型调用',
    );
    expect(cognitionStatusLabel({ status: 'MODEL_STREAM_RECEIVING' }, 'zh-CN')).toBe(
      '正在接收模型响应流',
    );
    expect(cognitionStatusLabel({ status: 'MODEL_REPAIRING' }, 'en')).toBe(
      'Repairing an invalid structured response',
    );
    expect(cognitionStatusLabel({ status: 'COMPLETED_WITH_RULE_CONTINUATION' }, 'en')).toBe(
      'Continued with deterministic rules',
    );
    expect(cognitionStatusLabel({}, 'en')).toBe('Preparing');
  });
});
