import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type {
  ResultInterpretationAssistantMessage,
  ResultInterpretationChatInput,
  ResultInterpretationChatResponse,
} from '../api/types';
import { I18nProvider } from '../i18n';
import { ResultInterpretationAssistant } from './result-interpretation-assistant';

vi.mock('../api/client', () => ({
  api: {
    getLlmConfig: vi.fn(),
    chatAboutResults: vi.fn(),
  },
}));

const EXPERIMENT_ID = 'exp-result-chat-test';

function createAssistantMessage(
  overrides: Partial<ResultInterpretationAssistantMessage> = {},
): ResultInterpretationAssistantMessage {
  return {
    id: 'assistant-message-1',
    role: 'assistant',
    language: 'en',
    answer: 'The intervention produced a small, model-dependent spread change.',
    analysisSummary: 'I compared the paired-seed effect and the registered limitations.',
    groundingReferences: ['metrics.pairedEffects.spreadBps', 'limitations[0]'],
    followUpSuggestions: ['How stable is this difference?'],
    toolActivity: [{
      tool: 'read_experiment_results',
      label: 'Paired effects',
      itemCount: 2,
      truncated: false,
      evidenceId: 'result:paired-deltas',
    }],
    provider: 'zhipu',
    model: 'glm-5',
    promptTokens: 240,
    completionTokens: 80,
    cachedTokens: 0,
    totalTokens: 320,
    modelCalls: 1,
    cacheHit: false,
    repairUsed: false,
    plannerUsed: false,
    promptVersion: 'result_interpretation_v1.0.0',
    latencyMs: 350,
    createdAt: '2026-07-22T18:30:00.000Z',
    ...overrides,
  };
}

function createResponse(
  input: ResultInterpretationChatInput,
  overrides: Partial<ResultInterpretationAssistantMessage> = {},
): ResultInterpretationChatResponse {
  return {
    schemaVersion: '1.0.0',
    conversationId: input.conversationId,
    clientRequestId: input.clientRequestId,
    experimentId: EXPERIMENT_ID,
    resultHash: 'sha256:result-chat-test',
    message: createAssistantMessage({
      id: `assistant-${input.mode.toLowerCase()}`,
      language: input.language,
      ...overrides,
    }),
  };
}

function renderAssistant(navigate = vi.fn()) {
  render(
    <I18nProvider>
      <ResultInterpretationAssistant experimentId={EXPERIMENT_ID} navigate={navigate} />
    </I18nProvider>,
  );
  return navigate;
}

describe('结果解释助手', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    Object.defineProperty(Element.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
    Object.defineProperty(window, 'requestAnimationFrame', {
      configurable: true,
      value: (callback: FrameRequestCallback) => {
        callback(0);
        return 1;
      },
    });
    vi.mocked(api.getLlmConfig).mockResolvedValue({
      configured: true,
      provider: 'zhipu',
      model: 'glm-5',
      thinkingEnabled: false,
      maxTokens: 4_096,
    });
  });

  it('未配置 API Key 时不调用模型，并将配置按钮导航到 AI 配置页', async () => {
    vi.mocked(api.getLlmConfig).mockResolvedValue({ configured: false });
    const navigate = renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Open AI Configuration' }));

    expect(api.chatAboutResults).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith('ai');
  });

  it('只有明确点击才发起 INITIAL 请求，并将模型内容作为纯文本与折叠证据呈现', async () => {
    const unsafeAnswer = 'Literal <img src=x onerror=alert(1)> and <script>alert("x")</script>.';
    vi.mocked(api.chatAboutResults).mockImplementation(async (_experimentId, input) => (
      createResponse(input, { answer: unsafeAnswer })
    ));
    const { container } = render(
      <I18nProvider>
        <ResultInterpretationAssistant experimentId={EXPERIMENT_ID} navigate={vi.fn()} />
      </I18nProvider>,
    );
    const user = userEvent.setup();

    const generateButton = await screen.findByRole('button', { name: 'Generate explanation' });
    expect(api.chatAboutResults).not.toHaveBeenCalled();
    await user.click(generateButton);

    await waitFor(() => expect(api.chatAboutResults).toHaveBeenCalledTimes(1));
    const [experimentId, input] = vi.mocked(api.chatAboutResults).mock.calls[0];
    expect(experimentId).toBe(EXPERIMENT_ID);
    expect(input).toMatchObject({
      schemaVersion: '1.0.0',
      conversationId: expect.any(String),
      mode: 'INITIAL',
      language: 'en',
      reasoningSummaryRequested: false,
      messages: [{
        role: 'user',
        content: expect.stringContaining('Explain all available results for a newcomer'),
      }],
    });
    expect(input.clientRequestId).toEqual(expect.any(String));

    expect(await screen.findByText(unsafeAnswer)).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();

    const reasoningSummary = screen.getByText('Reasoning summary');
    const reasoningDetails = reasoningSummary.closest('details');
    expect(reasoningDetails).not.toHaveAttribute('open');
    expect(reasoningDetails).toHaveTextContent(
      'I compared the paired-seed effect and the registered limitations.',
    );
    expect(screen.getByText('Result sections inspected (1)').closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText('Grounding references (2)').closest('details')).not.toHaveAttribute('open');
    const suggestion = screen.getByRole('button', { name: 'How stable is this difference?' });
    await user.click(suggestion);
    expect(screen.getByLabelText('Ask about this experiment')).toHaveValue('How stable is this difference?');
    expect(api.chatAboutResults).toHaveBeenCalledTimes(1);
  });

  it('沿用当前中文界面语言，并支持 Shift+Enter 换行和 Enter 发送多轮 FOLLOW_UP', async () => {
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    vi.mocked(api.chatAboutResults).mockImplementation(async (_experimentId, input) => (
      createResponse(input, {
        answer: input.mode === 'INITIAL' ? '这是首次实验解释。' : '这是后续问题的回答。',
      })
    ));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: '生成解释' }));
    expect(await screen.findByText('这是首次实验解释。')).toBeInTheDocument();

    const question = screen.getByLabelText('继续询问本次实验');
    await user.click(question);
    await user.type(question, '为什么价差变化很小？');
    await user.keyboard('{Shift>}{Enter}{/Shift}');
    expect(api.chatAboutResults).toHaveBeenCalledTimes(1);
    expect(question).toHaveValue('为什么价差变化很小？\n');

    await user.type(question, '结果可靠吗？');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(api.chatAboutResults).toHaveBeenCalledTimes(2));
    const followUpInput = vi.mocked(api.chatAboutResults).mock.calls[1][1];
    const initialConversationId = vi.mocked(api.chatAboutResults).mock.calls[0][1].conversationId;
    expect(followUpInput).toMatchObject({
      schemaVersion: '1.0.0',
      conversationId: initialConversationId,
      mode: 'FOLLOW_UP',
      language: 'zh-CN',
      reasoningSummaryRequested: false,
      messages: [
        { role: 'user', content: expect.stringContaining('第一次接触本项目的新手') },
        { role: 'assistant', content: '这是首次实验解释。' },
        { role: 'user', content: '为什么价差变化很小？\n结果可靠吗？' },
      ],
    });
    expect(await screen.findByText('这是后续问题的回答。')).toBeInTheDocument();
  });

  it('追问只发送最近的完整交替窗口，并遵守消息与字符上限', async () => {
    let responseIndex = 0;
    vi.mocked(api.chatAboutResults).mockImplementation(async (_experimentId, input) => (
      createResponse(input, {
        id: `assistant-window-${responseIndex++}`,
        answer: 'A'.repeat(4_500),
        followUpSuggestions: [],
      })
    ));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    await waitFor(() => expect(api.chatAboutResults).toHaveBeenCalledTimes(1));
    for (let index = 1; index <= 6; index += 1) {
      const question = screen.getByLabelText('Ask about this experiment');
      await user.clear(question);
      await user.type(question, `Question ${index}`);
      await user.click(screen.getByRole('button', { name: 'Send' }));
      await waitFor(() => expect(api.chatAboutResults).toHaveBeenCalledTimes(index + 1));
    }

    const finalInput = vi.mocked(api.chatAboutResults).mock.calls.at(-1)?.[1];
    expect(finalInput?.messages.length).toBeLessThanOrEqual(11);
    expect(finalInput?.messages[0].role).toBe('user');
    expect(finalInput?.messages.at(-1)?.role).toBe('user');
    expect(finalInput?.messages.map((message) => message.role)).toEqual(
      finalInput?.messages.map((_message, index) => index % 2 === 0 ? 'user' : 'assistant'),
    );
    expect(finalInput?.messages.every((message) => message.content.length <= 4_000)).toBe(true);
    expect(finalInput?.messages.reduce((total, message) => total + message.content.length, 0))
      .toBeLessThanOrEqual(16_000);
  });

  it('失败后使用同一个 clientRequestId 重试，不重复添加对话内容', async () => {
    let failedInput: ResultInterpretationChatInput | undefined;
    vi.mocked(api.chatAboutResults)
      .mockImplementationOnce(async (_experimentId, input) => {
        failedInput = input;
        throw new Error('Temporary provider failure');
      })
      .mockImplementation(async (_experimentId, input) => createResponse(input));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    const retryButton = await screen.findByRole('button', { name: 'Retry this request' });
    expect(screen.getByText('Temporary provider failure')).toBeInTheDocument();
    await user.click(retryButton);

    await waitFor(() => expect(api.chatAboutResults).toHaveBeenCalledTimes(2));
    expect(failedInput).toBeDefined();
    expect(vi.mocked(api.chatAboutResults).mock.calls[1][1].clientRequestId)
      .toBe(failedInput?.clientRequestId);
    expect(vi.mocked(api.chatAboutResults).mock.calls[1][1].messages).toEqual([{
      role: 'user',
      content: expect.stringContaining('Explain all available results for a newcomer'),
    }]);
    expect(await screen.findAllByText(
      'The intervention produced a small, model-dependent spread change.',
    )).toHaveLength(1);
  });

  it('清空只重置本地对话，并恢复显式生成入口', async () => {
    vi.mocked(api.chatAboutResults).mockImplementation(async (_experimentId, input) => (
      createResponse(input)
    ));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    expect(await screen.findByRole('log')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Clear conversation' }));

    expect(screen.queryByRole('log')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate explanation' })).toBeInTheDocument();
    expect(api.chatAboutResults).toHaveBeenCalledTimes(1);
  });
});
