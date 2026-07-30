import { act, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ResultInterpretationStreamError } from '../api/client';
import type {
  ResultInterpretationAssistantMessage,
  ResultInterpretationChatInput,
  ResultInterpretationChatResponse,
  ResultInterpretationConversation,
  ResultInterpretationConversationSummary,
  ResultInterpretationStreamResult,
} from '../api/types';
import { I18nProvider } from '../i18n';
import { ResultInterpretationAssistant } from './result-interpretation-assistant';

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getLlmConfig: vi.fn(),
      getResultInterpretationConversations: vi.fn(),
      getResultInterpretationConversation: vi.fn(),
      deleteResultInterpretationConversation: vi.fn(),
      chatAboutResults: vi.fn(),
      streamChatAboutResults: vi.fn(),
    },
  };
});

const EXPERIMENT_ID = 'exp-result-chat-test';
const SAVED_CONVERSATION_ID = 'saved-conversation-one';

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
    historyPersisted: true,
    message: createAssistantMessage({
      id: `assistant-${input.mode.toLowerCase()}`,
      language: input.language,
      ...overrides,
    }),
  };
}

function createStreamResult(
  input: ResultInterpretationChatInput,
  overrides: Partial<ResultInterpretationAssistantMessage> = {},
): ResultInterpretationStreamResult {
  return {
    response: createResponse(input, overrides),
    transport: 'sse',
    receivedEventCount: 3,
    elapsedMs: 420,
  };
}

function createSavedSummary(
  overrides: Partial<ResultInterpretationConversationSummary> = {},
): ResultInterpretationConversationSummary {
  return {
    conversationId: SAVED_CONVERSATION_ID,
    experimentId: EXPERIMENT_ID,
    language: 'en',
    exchangeCount: 1,
    lastUserMessage: 'Explain the saved liquidity result.',
    createdAt: '2026-07-22T18:00:00.000Z',
    updatedAt: '2026-07-22T18:30:00.000Z',
    ...overrides,
  };
}

function createSavedConversation(
  assistantOverrides: Partial<ResultInterpretationAssistantMessage> = {},
): ResultInterpretationConversation {
  const summary = createSavedSummary();
  return {
    schemaVersion: '1.0.0',
    conversationId: summary.conversationId,
    experimentId: summary.experimentId,
    language: summary.language,
    createdAt: summary.createdAt,
    updatedAt: summary.updatedAt,
    messages: [{
      id: 'saved-user-one',
      role: 'user',
      language: 'en',
      content: summary.lastUserMessage,
      createdAt: summary.createdAt,
    }, createAssistantMessage({
      id: 'saved-assistant-one',
      answer: 'This validated answer was restored from server history.',
      createdAt: summary.updatedAt,
      ...assistantOverrides,
    })],
  };
}

function renderAssistant(
  navigate = vi.fn(),
  onCreateExperimentDraft?: (suggestion: string) => void,
) {
  render(
    <I18nProvider>
      <ResultInterpretationAssistant
        experimentId={EXPERIMENT_ID}
        navigate={navigate}
        onCreateExperimentDraft={onCreateExperimentDraft}
      />
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
    vi.mocked(api.getResultInterpretationConversations).mockResolvedValue({
      schemaVersion: '1.0.0',
      items: [],
    });
    vi.mocked(api.getResultInterpretationConversation).mockResolvedValue(
      createSavedConversation(),
    );
    vi.mocked(api.deleteResultInterpretationConversation).mockResolvedValue({
      schemaVersion: '1.0.0',
      deleted: true,
      conversationId: SAVED_CONVERSATION_ID,
    });
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input)
    ));
  });

  it('未配置 API Key 时不调用模型，并将配置按钮导航到 AI 配置页', async () => {
    vi.mocked(api.getLlmConfig).mockResolvedValue({ configured: false });
    const navigate = renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Open AI Configuration' }));

    expect(api.streamChatAboutResults).not.toHaveBeenCalled();
    expect(navigate).toHaveBeenCalledWith('ai');
  });

  it('没有 API Key 也能读取服务器历史，但继续追问仍要求临时配置', async () => {
    vi.mocked(api.getLlmConfig).mockResolvedValue({ configured: false });
    vi.mocked(api.getResultInterpretationConversations).mockResolvedValue({
      schemaVersion: '1.0.0',
      items: [createSavedSummary()],
    });
    renderAssistant();
    const user = userEvent.setup();

    const savedQuestion = await screen.findByText('Explain the saved liquidity result.');
    await user.click(savedQuestion.closest('button')!);

    expect(await screen.findByText(
      'This validated answer was restored from server history.',
    )).toBeInTheDocument();
    expect(screen.getByText('Saved conversation opened in read-only mode')).toBeInTheDocument();
    expect(screen.queryByLabelText('Ask about this experiment')).not.toBeInTheDocument();
    expect(api.streamChatAboutResults).not.toHaveBeenCalled();
    expect(api.getResultInterpretationConversation).toHaveBeenCalledWith(
      EXPERIMENT_ID,
      SAVED_CONVERSATION_ID,
    );
  });

  it('打开已保存对话后可在原 conversationId 继续追问', async () => {
    vi.mocked(api.getResultInterpretationConversations).mockResolvedValue({
      schemaVersion: '1.0.0',
      items: [createSavedSummary()],
    });
    renderAssistant();
    const user = userEvent.setup();

    const savedQuestion = await screen.findByText('Explain the saved liquidity result.');
    await user.click(savedQuestion.closest('button')!);
    const composer = await screen.findByLabelText('Ask about this experiment');
    await user.type(composer, 'What is the strongest limitation?');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.streamChatAboutResults).mock.calls[0][1]).toMatchObject({
      conversationId: SAVED_CONVERSATION_ID,
      mode: 'FOLLOW_UP',
      messages: [
        { role: 'user', content: 'Explain the saved liquidity result.' },
        { role: 'assistant', content: 'This validated answer was restored from server history.' },
        { role: 'user', content: 'What is the strongest limitation?' },
      ],
    });
  });

  it('旧历史建议中的内部证据 ID 会以可读名称显示并写入输入框', async () => {
    vi.mocked(api.getResultInterpretationConversations).mockResolvedValue({
      schemaVersion: '1.0.0',
      items: [createSavedSummary()],
    });
    vi.mocked(api.getResultInterpretationConversation).mockResolvedValue(
      createSavedConversation({
        followUpSuggestions: [
          'Compare [result:overview] with [result:legacy.v1].',
        ],
      }),
    );
    renderAssistant();
    const user = userEvent.setup();

    const savedQuestion = await screen.findByText('Explain the saved liquidity result.');
    await user.click(savedQuestion.closest('button')!);
    const safeSuggestion = await screen.findByRole('button', {
      name: 'Compare Experiment overview with Legacy evidence reference.',
    });

    expect(document.body).not.toHaveTextContent('result:overview');
    expect(document.body).not.toHaveTextContent('result:legacy.v1');
    await user.click(safeSuggestion);
    expect(screen.getByLabelText('Ask about this experiment')).toHaveValue(
      'Compare Experiment overview with Legacy evidence reference.',
    );
  });

  it('删除已保存对话前要求明确确认，并只调用当前实验的删除端点', async () => {
    vi.mocked(api.getResultInterpretationConversations).mockResolvedValue({
      schemaVersion: '1.0.0',
      items: [createSavedSummary()],
    });
    renderAssistant();
    const user = userEvent.setup();

    await screen.findByText('Explain the saved liquidity result.');
    await user.click(screen.getByRole('button', {
      name: 'Delete saved conversation: Explain the saved liquidity result.',
    }));
    expect(api.deleteResultInterpretationConversation).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Delete conversation' }));

    await waitFor(() => expect(api.deleteResultInterpretationConversation).toHaveBeenCalledWith(
      EXPERIMENT_ID,
      SAVED_CONVERSATION_ID,
    ));
    expect(screen.queryByText('Explain the saved liquidity result.')).not.toBeInTheDocument();
  });

  it('只有明确点击才发起 INITIAL 请求，并安全渲染模型回答', async () => {
    const unsafeAnswer = 'Literal <img src=x onerror=alert(1)> and <script>alert("x")</script>.';
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input, { answer: unsafeAnswer })
    ));
    const { container } = render(
      <I18nProvider>
        <ResultInterpretationAssistant experimentId={EXPERIMENT_ID} navigate={vi.fn()} />
      </I18nProvider>,
    );
    const user = userEvent.setup();

    const generateButton = await screen.findByRole('button', { name: 'Generate explanation' });
    expect(api.streamChatAboutResults).not.toHaveBeenCalled();
    await user.click(generateButton);

    await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(1));
    const [experimentId, input] = vi.mocked(api.streamChatAboutResults).mock.calls[0];
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

    const unsafeAnswerNode = await screen.findByText(/Literal/);
    expect(unsafeAnswerNode).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('img')).toBeNull();
    const assistantCard = unsafeAnswerNode.closest('.result-assistant__message--assistant');
    expect(assistantCard).not.toBeNull();
    expect(within(assistantCard as HTMLElement).getByText(
      'This is scenario analysis conditional on synthetic assumptions, not a prediction and not investment advice.',
    )).toBeInTheDocument();
    expect(within(assistantCard as HTMLElement).getByText(
      'This explanation cannot establish real-world outcomes, recommend a trade, or generalize beyond the tested assumptions.',
    )).toBeInTheDocument();

    const reasoningSummary = screen.getByText('Analysis summary (not chain-of-thought)');
    const reasoningDetails = reasoningSummary.closest('details');
    expect(reasoningDetails).not.toHaveAttribute('open');
    expect(reasoningDetails).toHaveTextContent(
      'I compared the paired-seed effect and the registered limitations.',
    );
    expect(screen.getByText('Evidence used').closest('details')).not.toHaveAttribute('open');
    expect(screen.getByText('Technical details').closest('details')).not.toHaveAttribute('open');
    const suggestion = screen.getByRole('button', { name: 'How stable is this difference?' });
    await user.click(suggestion);
    expect(screen.getByLabelText('Ask about this experiment')).toHaveValue('How stable is this difference?');
    expect(api.streamChatAboutResults).toHaveBeenCalledTimes(1);
  });

  it('marks unrun experiment suggestions and creates only a prefilled draft', async () => {
    const createDraft = vi.fn();
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input, {
        followUpSuggestions: [
          'What changes with 50 matched seeds?',
          'Which interval can the current result explain?',
          'Compare against external historical market data.',
        ],
      })
    ));
    renderAssistant(vi.fn(), createDraft);
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));

    expect(await screen.findByText('New experiment required')).toBeInTheDocument();
    expect(screen.getByText('Not run')).toBeInTheDocument();
    expect(screen.getByText('Answerable from current result')).toBeInTheDocument();
    expect(screen.getByText('External data required')).toBeInTheDocument();
    expect(screen.queryByRole('button', {
      name: 'Compare against external historical market data.',
    })).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Create prefilled scenario draft' }));

    expect(createDraft).toHaveBeenCalledWith('What changes with 50 matched seeds?');
    expect(api.streamChatAboutResults).toHaveBeenCalledTimes(1);
  });

  it('服务端回答已包含前置边界时仍使用醒目边界卡片且不重复正文', async () => {
    const boundary = 'This is scenario analysis conditional on synthetic assumptions, not a prediction and not investment advice.';
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input, {
        answer: `${boundary}\n\nThe matched result remains model-dependent.`,
        analysisSummary: undefined,
      })
    ));
    const { container } = render(
      <I18nProvider>
        <ResultInterpretationAssistant experimentId={EXPERIMENT_ID} navigate={vi.fn()} />
      </I18nProvider>,
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));

    const boundaryCards = container.querySelectorAll('.result-assistant__fixed-boundary');
    expect(boundaryCards).toHaveLength(1);
    expect(boundaryCards.item(0)).toHaveTextContent(boundary);
    expect(screen.getByText('The matched result remains model-dependent.')).toBeInTheDocument();
    expect(screen.getAllByText(boundary)).toHaveLength(1);
  });

  it('在助手消息中渲染 GFM，复用首次引用编号并隐藏内部证据 ID', async () => {
    const markdownAnswer = [
      '# Evidence-backed result',
      '',
      '**Spread changed** [result:paired-deltas].',
      '',
      '- Matched seeds were used.',
      '- The same evidence is reused [result:paired-deltas].',
      '',
      '| Metric | Delta |',
      '| --- | ---: |',
      '| Spread | 4.8 bps |',
      '',
      '<script>window.__unsafe = true</script>',
    ].join('\n');
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input, {
        answer: markdownAnswer,
        analysisSummary: 'Registered limits remain important [result:limitations].',
        groundingReferences: ['result:paired-deltas', 'result:limitations'],
        toolActivity: [
          {
            tool: 'PAIRED_DELTAS',
            label: 'Paired effects',
            itemCount: 10,
            truncated: false,
            evidenceId: 'result:paired-deltas',
          },
          {
            tool: 'LIMITATIONS',
            label: 'Limitations',
            itemCount: 4,
            truncated: false,
            evidenceId: 'result:limitations',
          },
        ],
      })
    ));
    const { container } = render(
      <I18nProvider>
        <ResultInterpretationAssistant experimentId={EXPERIMENT_ID} navigate={vi.fn()} />
      </I18nProvider>,
    );
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));

    const assistantMessage = (await screen.findByText('Evidence-backed result'))
      .closest('.result-assistant__message--assistant');
    expect(assistantMessage).not.toBeNull();
    expect(within(assistantMessage as HTMLElement).getByRole('heading', {
      level: 3,
      name: 'Evidence-backed result',
    })).toBeInTheDocument();
    expect(within(assistantMessage as HTMLElement).getByText('Spread changed').tagName).toBe('STRONG');
    const answerRegion = assistantMessage?.querySelector('.result-assistant__answer');
    expect(answerRegion?.querySelector('ul')).toBeInTheDocument();
    expect(answerRegion?.querySelector('table')).toBeInTheDocument();
    expect(container.querySelector('script')).toBeNull();

    const pairedCitations = within(assistantMessage as HTMLElement).getAllByRole('button', {
      name: 'View evidence 1: Paired-seed differences',
    });
    expect(pairedCitations).toHaveLength(2);
    expect(within(assistantMessage as HTMLElement).getByRole('button', {
      name: 'View evidence 2: Limitations',
    })).toBeInTheDocument();
    for (const markdownRegion of assistantMessage?.querySelectorAll('.safe-markdown') ?? []) {
      expect(markdownRegion).not.toHaveTextContent('result:');
    }

    pairedCitations[0].focus();
    await user.keyboard('{Enter}');
    const evidenceDetails = within(assistantMessage as HTMLElement)
      .getByText('Evidence used').closest('details');
    expect(evidenceDetails).toHaveAttribute('open');
    const pairedEvidenceItem = within(assistantMessage as HTMLElement)
      .getByText('Paired-seed differences').closest('li');
    expect(pairedEvidenceItem).toHaveFocus();
    expect(pairedEvidenceItem?.scrollIntoView).toHaveBeenCalledWith({
      block: 'nearest',
      behavior: 'auto',
    });
  });

  it('从证据面板定位结果与追踪区段，并传递实验深链', async () => {
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input, {
        answer: 'Compare paired effects [result:paired-deltas] and inspect the trace [result:trace].',
        analysisSummary: undefined,
        groundingReferences: ['result:paired-deltas', 'result:trace'],
        toolActivity: [
          {
            tool: 'PAIRED_DELTAS',
            label: 'Paired effects',
            itemCount: 10,
            truncated: false,
            evidenceId: 'result:paired-deltas',
          },
          {
            tool: 'TRACE',
            label: 'Mechanism trace',
            itemCount: 12,
            truncated: false,
            evidenceId: 'result:trace',
          },
        ],
      })
    ));
    const navigate = renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    await user.click(await screen.findByRole('button', {
      name: 'View evidence 1: Paired-seed differences',
    }));
    const pairedItem = screen.getByText('Paired-seed differences').closest('li');
    await user.click(within(pairedItem as HTMLElement).getByRole('button', {
      name: 'View result section',
    }));
    expect(navigate).toHaveBeenCalledWith('results', {
      experimentId: EXPERIMENT_ID,
      target: 'paired-heading',
    });

    await user.click(screen.getByRole('button', {
      name: 'View evidence 2: Mechanism trace',
    }));
    const traceItem = screen.getByText('Mechanism trace').closest('li');
    await user.click(within(traceItem as HTMLElement).getByRole('button', {
      name: 'View result section',
    }));
    expect(navigate).toHaveBeenCalledWith('trace', {
      experimentId: EXPERIMENT_ID,
      target: 'trace-timeline-heading',
    });
  });

  it('旧历史回答无需迁移，未知引用保留审计但禁用定位', async () => {
    vi.mocked(api.getResultInterpretationConversations).mockResolvedValue({
      schemaVersion: '1.0.0',
      items: [createSavedSummary()],
    });
    vi.mocked(api.getResultInterpretationConversation).mockResolvedValue(
      createSavedConversation({
        answer: 'A legacy result remains available [result:legacy.v2:detail].',
        analysisSummary: undefined,
        groundingReferences: ['result:legacy.v2:detail'],
        toolActivity: [{
          tool: 'LEGACY_DETAIL',
          label: 'Legacy detail',
          itemCount: 1,
          truncated: false,
          evidenceId: 'result:legacy.v2:detail',
        }],
        promptVersion: 'result_interpretation_v1.0.0',
      }),
    );
    const { container } = render(
      <I18nProvider>
        <ResultInterpretationAssistant experimentId={EXPERIMENT_ID} navigate={vi.fn()} />
      </I18nProvider>,
    );
    const user = userEvent.setup();

    const savedQuestion = await screen.findByText('Explain the saved liquidity result.');
    await user.click(savedQuestion.closest('button')!);
    const citation = await screen.findByRole('button', {
      name: 'View evidence 1: Legacy evidence reference',
    });
    expect(citation).toBeInTheDocument();
    expect(container.querySelector('.safe-markdown')).not.toHaveTextContent('result:legacy.v2:detail');
    await user.click(citation);
    expect(screen.getByText('Historical evidence reference; currently unavailable'))
      .toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Location unavailable' })).toBeDisabled();
    expect(screen.getByText('Some evidence references could not be fully reconciled'))
      .toBeInTheDocument();
  });

  it('引用正文、groundingReferences 与工具活动不一致时明确告警', async () => {
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input, {
        answer: 'The paired result is cited here [result:paired-deltas].',
        analysisSummary: undefined,
        groundingReferences: [],
        toolActivity: [{
          tool: 'PAIRED_DELTAS',
          label: 'Paired effects',
          itemCount: 10,
          truncated: false,
          evidenceId: 'result:paired-deltas',
        }],
      })
    ));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));

    const warning = (await screen.findByText(
      'Some evidence references could not be fully reconciled',
    )).closest('[role="alert"]');
    expect(warning).toHaveTextContent('Some evidence references could not be fully reconciled');
    expect(warning).toHaveTextContent('missing, legacy, or mismatched references');
  });

  it('用户消息保持纯文本与独立角色布局类，不解析 Markdown', async () => {
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input, { analysisSummary: undefined })
    ));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    const composer = await screen.findByLabelText('Ask about this experiment');
    await user.click(composer);
    await user.paste('**Keep this literal** [reference](https://example.com)');
    await user.click(screen.getByRole('button', { name: 'Send' }));

    await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(2));
    const userCards = document.querySelectorAll('.result-assistant__message--user');
    const userCard = userCards.item(userCards.length - 1) as HTMLElement;
    const literalMessage = userCard.querySelector('.result-assistant__answer--user');
    expect(literalMessage).toHaveTextContent('**Keep this literal** [reference](https://example.com)');
    expect(literalMessage).toHaveClass('result-assistant__answer--user');
    expect(literalMessage?.querySelector('strong')).toBeNull();
    expect(literalMessage?.querySelector('a')).toBeNull();
    expect(userCard).toHaveClass('result-assistant__message', 'result-assistant__message--user');
    expect(within(userCard).getByText('You')).toBeInTheDocument();
    expect(within(userCard).queryByText(/scenario analysis conditional on synthetic assumptions/))
      .not.toBeInTheDocument();
  });

  it('最终回答未能持久化时保留可见回答并明确警告用户', async () => {
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => {
      const result = createStreamResult(input);
      result.response.historyPersisted = false;
      return result;
    });
    renderAssistant();
    const user = userEvent.setup();

    await screen.findByText('No validated AI conversation has been saved for this experiment yet.');
    await user.click(screen.getByRole('button', { name: 'Generate explanation' }));

    expect(await screen.findByText('This answer is not in server history')).toBeInTheDocument();
    expect(screen.getByText(
      'The intervention produced a small, model-dependent spread change.',
    )).toBeInTheDocument();
    expect(screen.getByText(/Follow-up is disabled because the server cannot safely reconstruct/))
      .toBeInTheDocument();
    expect(screen.queryByLabelText('Ask about this experiment')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'How stable is this difference?' }))
      .toBeDisabled();
    expect(api.getResultInterpretationConversations).toHaveBeenCalledTimes(1);
  });

  it('完整展示后端返回的 300 条会话历史，不在前端自行截断', async () => {
    vi.mocked(api.getResultInterpretationConversations).mockResolvedValue({
      schemaVersion: '1.0.0',
      items: Array.from({ length: 300 }, (_value, index) => createSavedSummary({
        conversationId: `saved-conversation-${index}`,
        lastUserMessage: `Saved question ${index + 1}`,
      })),
    });
    renderAssistant();

    expect(await screen.findByText('Saved question 300')).toBeInTheDocument();
    expect(document.querySelectorAll('.result-assistant__history-list > li')).toHaveLength(300);
  });

  it('显示安全流式阶段、接收块数和耗时，不展示服务端消息或隐藏推理', async () => {
    let finishRequest: (() => void) | undefined;
    vi.mocked(api.streamChatAboutResults).mockImplementation(
      async (_experimentId, input, onUpdate) => new Promise((resolve) => {
        onUpdate({
          kind: 'progress',
          progress: {
            schemaVersion: '1.0.0',
            stage: 'REASONING',
            elapsedMs: 1_250,
            chunkCount: 7,
            answerChunkCount: 5,
            reasoningChunkCount: 2,
          },
          receivedEventCount: 2,
        });
        finishRequest = () => resolve(createStreamResult(input));
      }),
    );
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));

    expect(await screen.findByText('Provider processing; private reasoning stays hidden')).toBeInTheDocument();
    const counters = screen.getByText(/7 provider chunks/);
    expect(counters).toBeInTheDocument();
    expect(counters).toHaveAttribute('aria-hidden', 'true');
    expect(screen.getByText(/2 status events/)).toBeInTheDocument();
    expect(screen.getByText(/answer drafts and private chain-of-thought are never streamed/)).toBeInTheDocument();
    expect(screen.queryByText('private implementation detail')).not.toBeInTheDocument();
    const stageStatus = screen.getByRole('status');
    expect(stageStatus).toHaveTextContent('Provider processing; private reasoning stays hidden');
    expect(stageStatus).not.toHaveTextContent('7 provider chunks');
    expect(screen.getByRole('button', { name: 'Stop waiting' }).closest('[role="status"]')).toBeNull();

    await act(async () => finishRequest?.());
    expect(await screen.findByText(
      'The intervention produced a small, model-dependent spread change.',
    )).toBeInTheDocument();
  });

  it('停止等待会中止浏览器请求、保留待重试输入，并拒绝迟到的最终响应', async () => {
    let capturedSignal: AbortSignal | undefined;
    let finishRequest: (() => void) | undefined;
    vi.mocked(api.streamChatAboutResults).mockImplementation(
      (_experimentId, input, _onUpdate, signal) => {
        capturedSignal = signal;
        return new Promise((resolve) => {
          finishRequest = () => resolve(createStreamResult(input));
        });
      },
    );
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    await user.click(await screen.findByRole('button', { name: 'Stop waiting' }));

    expect(capturedSignal?.aborted).toBe(true);
    expect(screen.getByText(/Provider processing may continue, and a charge may still occur/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Resume the same request' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Review retry and cost warning' })).not.toBeInTheDocument();

    await act(async () => finishRequest?.());
    expect(screen.queryByText(
      'The intervention produced a small, model-dependent spread change.',
    )).not.toBeInTheDocument();
    expect(api.streamChatAboutResults).toHaveBeenCalledTimes(1);
  });

  it('传输中断先复用原请求标识恢复，明确终态失败后才允许确认新请求', async () => {
    let firstRequestId: string | undefined;
    vi.mocked(api.streamChatAboutResults)
      .mockImplementationOnce(async (_experimentId, input) => {
        firstRequestId = input.clientRequestId;
        throw new ResultInterpretationStreamError({
          code: 'RESULT_INTERPRETATION_STREAM_INTERRUPTED',
          message: 'connection interrupted',
          retryable: true,
          httpStatus: 502,
          uncertainBillableAttempts: 1,
        });
      })
      .mockRejectedValueOnce(new ResultInterpretationStreamError({
        code: 'MODEL_TIMEOUT',
        message: 'provider terminal timeout',
        retryable: true,
        httpStatus: 504,
        uncertainBillableAttempts: 1,
      }))
      .mockImplementation(async (_experimentId, input) => createStreamResult(input));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    await user.click(await screen.findByRole('button', { name: 'Resume the same request' }));
    await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(2));
    expect(vi.mocked(api.streamChatAboutResults).mock.calls[1][1].clientRequestId).toBe(firstRequestId);

    const reviewButton = await screen.findByRole('button', { name: 'Review retry and cost warning' });
    expect(screen.queryByRole('button', { name: 'Resume the same request' })).not.toBeInTheDocument();
    await user.click(reviewButton);
    await user.click(screen.getByRole('button', { name: 'Confirm new retry' }));
    await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(3));
    expect(vi.mocked(api.streamChatAboutResults).mock.calls[2][1].clientRequestId).not.toBe(firstRequestId);
  });

  it('分析摘要开关不跟随供应商 thinking，并明确解释两者差异', async () => {
    vi.mocked(api.getLlmConfig).mockResolvedValue({
      configured: true,
      provider: 'zhipu',
      model: 'glm-5',
      thinkingEnabled: true,
      maxTokens: 4_096,
    });
    renderAssistant();
    const user = userEvent.setup();

    const summaryToggle = await screen.findByRole('switch', { name: 'Include an analysis summary' });
    expect(summaryToggle).not.toBeChecked();
    expect(screen.getByText(/independent of “Provider thinking: on.”/)).toBeInTheDocument();
    expect(screen.getByText(/Private chain-of-thought is never returned or displayed/)).toBeInTheDocument();

    await user.click(summaryToggle);
    await user.click(screen.getByRole('button', { name: 'Generate explanation' }));
    await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(1));
    expect(vi.mocked(api.streamChatAboutResults).mock.calls[0][1].reasoningSummaryRequested).toBe(true);
  });

  it('沿用当前中文界面语言，并支持 Shift+Enter 换行和 Enter 发送多轮 FOLLOW_UP', async () => {
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input, {
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
    expect(api.streamChatAboutResults).toHaveBeenCalledTimes(1);
    expect(question).toHaveValue('为什么价差变化很小？\n');

    await user.type(question, '结果可靠吗？');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(2));
    const followUpInput = vi.mocked(api.streamChatAboutResults).mock.calls[1][1];
    const initialConversationId = vi.mocked(api.streamChatAboutResults).mock.calls[0][1].conversationId;
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

  it('拒绝语言与请求不一致的最终回答', async () => {
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input, {
        language: 'zh-CN',
        answer: '不应显示的错语言回答。',
      })
    ));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));

    expect(await screen.findByText(/The explanation could not be completed/)).toBeInTheDocument();
    expect(screen.queryByText('不应显示的错语言回答。')).not.toBeInTheDocument();
  });

  it('追问只发送最近的完整交替窗口，并遵守消息与字符上限', async () => {
    let responseIndex = 0;
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input, {
        id: `assistant-window-${responseIndex++}`,
        answer: 'A'.repeat(4_500),
        followUpSuggestions: [],
      })
    ));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(1));
    for (let index = 1; index <= 6; index += 1) {
      const question = screen.getByLabelText('Ask about this experiment');
      await user.clear(question);
      await user.type(question, `Question ${index}`);
      await user.click(screen.getByRole('button', { name: 'Send' }));
      await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(index + 1));
    }

    const finalInput = vi.mocked(api.streamChatAboutResults).mock.calls.at(-1)?.[1];
    expect(finalInput?.messages.length).toBeLessThanOrEqual(11);
    expect(finalInput?.messages[0].role).toBe('user');
    expect(finalInput?.messages.at(-1)?.role).toBe('user');
    expect(finalInput?.messages.map((message) => message.role)).toEqual(
      finalInput?.messages.map((_message, index) => index % 2 === 0 ? 'user' : 'assistant'),
    );
    expect(finalInput?.messages.every((message) => message.content.length <= 4_000)).toBe(true);
    expect(finalInput?.messages.reduce((total, message) => total + message.content.length, 0))
      .toBeLessThanOrEqual(16_000);
  }, 20_000);

  it('失败后先提示可能重复计费，再使用新的 clientRequestId 重试且不重复添加对话内容', async () => {
    let failedInput: ResultInterpretationChatInput | undefined;
    vi.mocked(api.streamChatAboutResults)
      .mockImplementationOnce(async (_experimentId, input) => {
        failedInput = input;
        throw new Error('Temporary provider failure');
      })
      .mockImplementation(async (_experimentId, input) => createStreamResult(input));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    const retryButton = await screen.findByRole('button', { name: 'Review retry and cost warning' });
    expect(screen.getByText(/The explanation could not be completed/)).toBeInTheDocument();
    await user.click(retryButton);
    expect(screen.getByText('A retry may create another provider charge')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Confirm new retry' }));

    await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(2));
    expect(failedInput).toBeDefined();
    expect(vi.mocked(api.streamChatAboutResults).mock.calls[1][1].clientRequestId)
      .not.toBe(failedInput?.clientRequestId);
    expect(vi.mocked(api.streamChatAboutResults).mock.calls[1][1].messages).toEqual([{
      role: 'user',
      content: expect.stringContaining('Explain all available results for a newcomer'),
    }]);
    expect(await screen.findAllByText(
      'The intervention produced a small, model-dependent spread change.',
    )).toHaveLength(1);
  });

  it('按当前中文界面把错误码翻译为友好说明，并显示无法确认的计费次数', async () => {
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    vi.mocked(api.streamChatAboutResults).mockRejectedValueOnce(
      new ResultInterpretationStreamError({
        code: 'MODEL_TIMEOUT',
        message: 'raw provider timeout',
        retryable: true,
        httpStatus: 502,
        uncertainBillableAttempts: 2,
        failureStage: 'REPAIRING',
        repairAttempted: true,
        repairUsed: false,
        billingConclusion: 'BILLING_UNCERTAIN',
        traceId: 'trace-safe',
      }),
    );
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: '生成解释' }));
    expect(await screen.findByText(/供应商未在时限内完成/)).toBeInTheDocument();
    expect(screen.queryByText('raw provider timeout')).not.toBeInTheDocument();
    expect(screen.getByText('MODEL_TIMEOUT')).toBeInTheDocument();
    expect(screen.getByText('REPAIRING')).toBeInTheDocument();
    expect(screen.getByText('已尝试，未采用修复结果')).toBeInTheDocument();
    expect(screen.getByText('计费状态不确定')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '查看重试与费用提示' }));
    expect(screen.getByText(/有 2 次供应商调用无法确认是否已计费/)).toBeInTheDocument();
  });

  it('敏感输入被拦截时用当前中文界面明确说明内容未发送给模型', async () => {
    window.localStorage.setItem('eventshock-language', 'zh-CN');
    vi.mocked(api.streamChatAboutResults).mockRejectedValueOnce(
      new ResultInterpretationStreamError({
        code: 'RESULT_INTERPRETATION_PRIVATE_INPUT',
        message: 'raw private input detail',
        retryable: false,
        httpStatus: 422,
        uncertainBillableAttempts: 0,
      }),
    );
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: '生成解释' }));

    expect(await screen.findByText(/系统已在发送给模型供应商之前拦截/)).toBeInTheDocument();
    expect(screen.getByText(/相关内容未发送给模型/)).toBeInTheDocument();
    expect(screen.queryByText('raw private input detail')).not.toBeInTheDocument();
  });

  it.each([
    {
      code: 'RESULT_INTERPRETATION_CONVERSATION_CONFLICT',
      expected: /already has saved server history.*not sent to the model/i,
    },
    {
      code: 'RESULT_INTERPRETATION_CONVERSATION_NOT_FOUND',
      expected: /no longer exists or has expired.*not sent to the model/i,
    },
    {
      code: 'RESULT_INTERPRETATION_CONVERSATION_MISMATCH',
      expected: /does not match the validated conversation.*not sent to the model/i,
    },
    {
      code: 'RESULT_INTERPRETATION_CONVERSATION_DELETED',
      expected: /was deleted.*blocked before reaching the model/i,
    },
  ])('会话完整性错误 $code 显示可操作的英文恢复提示', async ({ code, expected }) => {
    vi.mocked(api.streamChatAboutResults).mockRejectedValueOnce(
      new ResultInterpretationStreamError({
        code,
        message: 'raw conversation integrity detail',
        retryable: false,
        httpStatus: 409,
        uncertainBillableAttempts: 0,
      }),
    );
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));

    expect(await screen.findByText(expected)).toBeInTheDocument();
    expect(screen.queryByText('raw conversation integrity detail')).not.toBeInTheDocument();
  });

  it('不可重试失败后可替换最后一个问题并以新请求继续原会话', async () => {
    let failedInput: ResultInterpretationChatInput | undefined;
    vi.mocked(api.streamChatAboutResults)
      .mockImplementationOnce(async (_experimentId, input) => {
        failedInput = input;
        throw new ResultInterpretationStreamError({
          code: 'CONTENT_FILTERED',
          message: 'raw provider filter message',
          retryable: false,
          httpStatus: 502,
          uncertainBillableAttempts: 1,
        });
      })
      .mockImplementation(async (_experimentId, input) => createStreamResult(input, {
        answer: 'The revised question can be answered safely.',
      }));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    const revision = await screen.findByRole('textbox', { name: 'Revise and submit again' });
    expect((revision as HTMLTextAreaElement).value).toContain('Explain all available results');
    await user.clear(revision);
    await user.type(revision, 'Explain only the evidence-backed differences.');
    await user.click(screen.getByRole('button', { name: 'Submit revision as a new request' }));

    await waitFor(() => expect(api.streamChatAboutResults).toHaveBeenCalledTimes(2));
    const revisedInput = vi.mocked(api.streamChatAboutResults).mock.calls[1][1];
    expect(revisedInput.conversationId).toBe(failedInput?.conversationId);
    expect(revisedInput.clientRequestId).not.toBe(failedInput?.clientRequestId);
    expect(revisedInput.messages).toEqual([{
      role: 'user',
      content: 'Explain only the evidence-backed differences.',
    }]);
    expect(await screen.findByText('The revised question can be answered safely.')).toBeInTheDocument();
  });

  it('开始新对话只重置本地展示，并恢复显式生成入口', async () => {
    vi.mocked(api.streamChatAboutResults).mockImplementation(async (_experimentId, input) => (
      createStreamResult(input)
    ));
    renderAssistant();
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Generate explanation' }));
    expect(await screen.findByRole('log')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Start new conversation' }));

    expect(screen.queryByRole('log')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate explanation' })).toBeInTheDocument();
    expect(api.streamChatAboutResults).toHaveBeenCalledTimes(1);
  });
});
