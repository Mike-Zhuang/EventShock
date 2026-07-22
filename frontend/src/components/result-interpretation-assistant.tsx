import {
  Button,
  InlineNotification,
  Tag,
  TextArea,
  Toggle,
} from '@carbon/react';
import {
  ArrowClockwise,
  Brain,
  PaperPlaneTilt,
  Trash,
  Wrench,
} from '@phosphor-icons/react';
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import type { Navigate } from '../app';
import { api } from '../api/client';
import type {
  LlmConfigView,
  ResultInterpretationAssistantMessage,
  ResultInterpretationChatInput,
  ResultInterpretationLanguage,
} from '../api/types';
import { LoadingPanel, Notice } from './common';
import { useI18n } from '../i18n';

const MAX_QUESTION_CHARACTERS = 2_000;
const MAX_HISTORY_MESSAGES = 11;
const MAX_HISTORY_CHARACTERS = 16_000;
const MAX_MESSAGE_CHARACTERS = 4_000;

interface UserMessage {
  id: string;
  role: 'user';
  language: ResultInterpretationLanguage;
  content: string;
  createdAt: string;
}

type DisplayMessage = UserMessage | ResultInterpretationAssistantMessage;

interface FailedRequest {
  input: ResultInterpretationChatInput;
}

function messageText(message: DisplayMessage): string {
  return message.role === 'user' ? message.content : message.answer;
}

function messageLanguage(message: DisplayMessage): ResultInterpretationLanguage {
  return message.language;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function boundedConversation(messages: DisplayMessage[]): ResultInterpretationChatInput['messages'] {
  const turns = messages.map((message) => ({
    role: message.role,
    content: messageText(message).slice(0, MAX_MESSAGE_CHARACTERS),
  }));
  const latest = turns.at(-1);
  if (!latest || latest.role !== 'user') return [];

  let totalCharacters = latest.content.length;
  let bounded = [latest];
  // 从末尾成对保留完整的 user/assistant 交流，避免裁剪后破坏角色交替。
  for (let index = turns.length - 2; index >= 1; index -= 2) {
    const assistantTurn = turns[index];
    const userTurn = turns[index - 1];
    if (assistantTurn.role !== 'assistant' || userTurn.role !== 'user') break;
    const pairCharacters = assistantTurn.content.length + userTurn.content.length;
    if (bounded.length + 2 > MAX_HISTORY_MESSAGES
      || totalCharacters + pairCharacters > MAX_HISTORY_CHARACTERS) break;
    bounded = [userTurn, assistantTurn, ...bounded];
    totalCharacters += pairCharacters;
  }
  return bounded;
}

export function ResultInterpretationAssistant({
  experimentId,
  navigate,
}: {
  experimentId: string;
  navigate: Navigate;
}) {
  const { language, t } = useI18n();
  const [config, setConfig] = useState<LlmConfigView>();
  const [configState, setConfigState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [configError, setConfigError] = useState<string>();
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [draft, setDraft] = useState('');
  const [reasoningSummaryRequested, setReasoningSummaryRequested] = useState(false);
  const [sending, setSending] = useState(false);
  const [requestError, setRequestError] = useState<string>();
  const [failedRequest, setFailedRequest] = useState<FailedRequest>();
  const requestGeneration = useRef(0);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const latestMessageRef = useRef<HTMLLIElement | null>(null);

  const loadConfig = async () => {
    const generation = ++requestGeneration.current;
    setConfigState('loading');
    setConfigError(undefined);
    try {
      const nextConfig = await api.getLlmConfig();
      if (generation !== requestGeneration.current) return;
      setConfig(nextConfig);
      setReasoningSummaryRequested(Boolean(nextConfig.thinkingEnabled));
      setConfigState('ready');
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      setConfig(undefined);
      setConfigError(errorMessage(error));
      setConfigState('error');
    }
  };

  useEffect(() => {
    setMessages([]);
    setConversationId(undefined);
    setDraft('');
    setRequestError(undefined);
    setFailedRequest(undefined);
    setSending(false);
    void loadConfig();
    return () => {
      requestGeneration.current += 1;
    };
  }, [experimentId]);

  useEffect(() => {
    if (messages.length === 0) return;
    latestMessageRef.current?.scrollIntoView({ block: 'nearest' });
  }, [messages.length]);

  const executeRequest = async (input: ResultInterpretationChatInput) => {
    const generation = ++requestGeneration.current;
    setSending(true);
    setRequestError(undefined);
    setFailedRequest(undefined);
    try {
      const response = await api.chatAboutResults(experimentId, input);
      if (generation !== requestGeneration.current) return;
      if (response.experimentId !== experimentId) {
        throw new Error(t('results.assistantResponseMismatch'));
      }
      if (response.clientRequestId !== input.clientRequestId) {
        throw new Error(t('results.assistantRequestMismatch'));
      }
      if (response.conversationId !== input.conversationId) {
        throw new Error(t('results.assistantConversationMismatch'));
      }
      setConversationId(response.conversationId);
      setMessages((current) => [...current, response.message]);
      setDraft('');
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      setRequestError(errorMessage(error));
      setFailedRequest({ input });
    } finally {
      if (generation === requestGeneration.current) {
        setSending(false);
        window.requestAnimationFrame(() => composerRef.current?.focus());
      }
    }
  };

  const generateInitialExplanation = () => {
    const nextConversationId = crypto.randomUUID();
    const initialMessage: UserMessage = {
      id: `local-${crypto.randomUUID()}`,
      role: 'user',
      language,
      content: t('results.assistantInitialPrompt'),
      createdAt: new Date().toISOString(),
    };
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0',
      conversationId: nextConversationId,
      clientRequestId: crypto.randomUUID(),
      mode: 'INITIAL',
      language,
      reasoningSummaryRequested,
      messages: [{ role: 'user', content: initialMessage.content }],
    };
    setConversationId(nextConversationId);
    setMessages([initialMessage]);
    void executeRequest(input);
  };

  const sendFollowUp = () => {
    const content = draft.trim();
    if (!content || content.length > MAX_QUESTION_CHARACTERS || sending || !conversationId
      || messages.at(-1)?.role !== 'assistant') return;
    const userMessage: UserMessage = {
      id: `local-${crypto.randomUUID()}`,
      role: 'user',
      language,
      content,
      createdAt: new Date().toISOString(),
    };
    const nextMessages = [...messages, userMessage];
    const input: ResultInterpretationChatInput = {
      schemaVersion: '1.0.0',
      conversationId,
      clientRequestId: crypto.randomUUID(),
      mode: 'FOLLOW_UP',
      language,
      reasoningSummaryRequested,
      messages: boundedConversation(nextMessages),
    };
    setMessages(nextMessages);
    setDraft('');
    void executeRequest(input);
  };

  const clearConversation = () => {
    requestGeneration.current += 1;
    setMessages([]);
    setConversationId(undefined);
    setDraft('');
    setRequestError(undefined);
    setFailedRequest(undefined);
    setSending(false);
  };

  const handleComposerKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    sendFollowUp();
  };

  const renderHeader = () => (
    <header className="result-assistant__header">
      <div>
        <span className="eyebrow"><Brain size={18} weight="duotone" aria-hidden="true" />{t('results.assistantEyebrow')}</span>
        <h2 id="result-assistant-heading">{t('results.assistantTitle')}</h2>
        <p>{t('results.assistantSubtitle')}</p>
      </div>
      {config?.configured ? (
        <div className="result-assistant__configuration">
          <span>{t('results.assistantConfiguredAs')}</span>
          <strong>{config.provider ?? t('common.unavailable')} / {config.model ?? t('common.unavailable')}</strong>
        </div>
      ) : null}
    </header>
  );

  if (configState === 'loading') {
    return (
      <section className="result-assistant" aria-labelledby="result-assistant-heading">
        {renderHeader()}
        <LoadingPanel label={t('results.assistantCheckingConfig')} />
      </section>
    );
  }

  if (configState === 'error') {
    return (
      <section className="result-assistant" aria-labelledby="result-assistant-heading">
        {renderHeader()}
        <InlineNotification
          kind="error"
          lowContrast
          hideCloseButton
          title={t('results.assistantConfigErrorTitle')}
          subtitle={configError ?? t('results.assistantErrorFallback')}
        />
        <Button kind="tertiary" size="sm" renderIcon={ArrowClockwise} onClick={() => void loadConfig()}>
          {t('common.retry')}
        </Button>
      </section>
    );
  }

  if (!config?.configured) {
    return (
      <section className="result-assistant" aria-labelledby="result-assistant-heading">
        {renderHeader()}
        <div className="result-assistant__empty">
          <h3>{t('results.assistantNoKeyTitle')}</h3>
          <p>{t('results.assistantNoKeyBody')}</p>
          <Button kind="tertiary" onClick={() => navigate('ai')}>{t('results.assistantConfigure')}</Button>
        </div>
      </section>
    );
  }

  const draftLength = draft.length;
  const draftTooLong = draftLength > MAX_QUESTION_CHARACTERS;
  const canAskFollowUp = messages.at(-1)?.role === 'assistant';

  return (
    <section
      className="result-assistant"
      aria-labelledby="result-assistant-heading"
      aria-busy={sending}
    >
      {renderHeader()}
      <Notice>{t('results.assistantBoundary')}</Notice>
      <div className="result-assistant__controls">
        <div>
          <strong>{t('results.assistantReasoningToggle')}</strong>
          <span>{t('results.assistantReasoningHelp')}</span>
        </div>
        <Toggle
          id={`result-assistant-reasoning-${experimentId}`}
          aria-label={t('results.assistantReasoningToggle')}
          labelA={t('results.assistantOff')}
          labelB={t('results.assistantOn')}
          toggled={reasoningSummaryRequested}
          disabled={sending}
          onToggle={setReasoningSummaryRequested}
        />
      </div>

      {messages.length === 0 ? (
        <div className="result-assistant__start">
          <div>
            <h3>{t('results.assistantStartTitle')}</h3>
            <p>{t('results.assistantStartBody')}</p>
          </div>
          <Button
            renderIcon={Brain}
            disabled={sending}
            onClick={generateInitialExplanation}
          >
            {sending ? t('results.assistantGenerating') : t('results.assistantGenerate')}
          </Button>
        </div>
      ) : (
        <>
          <ol className="result-assistant__log" role="log" aria-live="polite" aria-relevant="additions">
            {messages.map((message, index) => (
              <li
                key={message.id}
                ref={index === messages.length - 1 ? latestMessageRef : undefined}
                className={`result-assistant__message result-assistant__message--${message.role}`}
              >
                <div className="result-assistant__message-meta">
                  <strong>{message.role === 'assistant' ? t('results.assistantRole') : t('results.assistantUserRole')}</strong>
                  <span>{new Intl.DateTimeFormat(messageLanguage(message), { hour: 'numeric', minute: '2-digit' }).format(new Date(message.createdAt))}</span>
                  {message.role === 'assistant' ? <Tag type="cool-gray" size="sm">{message.provider} / {message.model}</Tag> : null}
                </div>
                <p className="result-assistant__answer">{messageText(message)}</p>
                {message.role === 'assistant' && message.analysisSummary ? (
                  <details className="result-assistant__disclosure">
                    <summary>{t('results.assistantReasoningSummary')}</summary>
                    <p>{message.analysisSummary}</p>
                  </details>
                ) : null}
                {message.role === 'assistant' && message.toolActivity.length > 0 ? (
                  <details className="result-assistant__disclosure">
                    <summary><Wrench size={15} aria-hidden="true" />{t('results.assistantTools')} ({message.toolActivity.length})</summary>
                    <ul>
                      {message.toolActivity.map((activity, activityIndex) => (
                        <li key={`${activity.tool}-${activityIndex}`}>
                          <strong>{activity.label}</strong>
                          <span>{t('results.assistantToolItems', { value: activity.itemCount })}{activity.truncated ? ` · ${t('results.assistantToolTruncated')}` : ''}</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : null}
                {message.role === 'assistant' && message.groundingReferences.length > 0 ? (
                  <details className="result-assistant__disclosure">
                    <summary>{t('results.assistantReferences')} ({message.groundingReferences.length})</summary>
                    <ul className="result-assistant__references">
                      {message.groundingReferences.map((reference) => <li key={reference}><code>{reference}</code></li>)}
                    </ul>
                  </details>
                ) : null}
                {message.role === 'assistant' && message.followUpSuggestions.length > 0 ? (
                  <div className="result-assistant__suggestions" aria-label={t('results.assistantSuggestions')}>
                    <strong>{t('results.assistantSuggestions')}</strong>
                    <div>
                      {message.followUpSuggestions.map((suggestion) => (
                        <Button
                          key={suggestion}
                          kind="ghost"
                          size="sm"
                          disabled={sending}
                          onClick={() => {
                            setDraft(suggestion);
                            window.requestAnimationFrame(() => composerRef.current?.focus());
                          }}
                        >
                          {suggestion}
                        </Button>
                      ))}
                    </div>
                  </div>
                ) : null}
                {message.role === 'assistant' ? (
                  <footer className="result-assistant__usage">
                    <span>{message.totalTokens.toLocaleString(language)} {t('results.assistantTokens')}</span>
                    {message.cacheHit ? <span>{t('results.assistantCacheHit')}</span> : null}
                    {message.repairUsed ? <span>{t('results.assistantRepairUsed')}</span> : null}
                  </footer>
                ) : null}
              </li>
            ))}
            {sending ? (
              <li className="result-assistant__pending" role="status">
                <Brain size={20} weight="duotone" aria-hidden="true" />
                <span>{t('results.assistantGenerating')}</span>
              </li>
            ) : null}
          </ol>

          {canAskFollowUp ? <div className="result-assistant__composer">
            <TextArea
              ref={composerRef}
              id={`result-assistant-question-${experimentId}`}
              labelText={t('results.assistantAskLabel')}
              placeholder={t('results.assistantAskPlaceholder')}
              rows={3}
              value={draft}
              disabled={sending}
              invalid={draftTooLong}
              invalidText={t('results.assistantTooLong', { value: MAX_QUESTION_CHARACTERS })}
              helperText={t('results.assistantCharacterCount', { current: draftLength, maximum: MAX_QUESTION_CHARACTERS })}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={handleComposerKeyDown}
            />
            <Button
              renderIcon={PaperPlaneTilt}
              disabled={sending || !draft.trim() || draftTooLong}
              onClick={sendFollowUp}
            >
              {sending ? t('results.assistantSending') : t('results.assistantSend')}
            </Button>
          </div> : null}
        </>
      )}

      {requestError ? (
        <div className="result-assistant__error">
          <InlineNotification
            kind="error"
            lowContrast
            hideCloseButton
            title={t('results.assistantErrorTitle')}
            subtitle={requestError || t('results.assistantErrorFallback')}
          />
          {failedRequest ? (
            <Button
              kind="tertiary"
              size="sm"
              renderIcon={ArrowClockwise}
              disabled={sending}
              onClick={() => void executeRequest(failedRequest.input)}
            >
              {t('results.assistantRetry')}
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="result-assistant__footer-actions">
        {messages.length > 0 || requestError ? (
          <Button
            kind="ghost"
            size="sm"
            renderIcon={Trash}
            disabled={sending}
            onClick={clearConversation}
          >
            {t('results.assistantClear')}
          </Button>
        ) : null}
      </div>
    </section>
  );
}
