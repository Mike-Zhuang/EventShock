import {
  Button,
  InlineNotification,
  Modal,
  Tag,
  TextArea,
  Toggle,
} from '@carbon/react';
import {
  ArrowClockwise,
  Brain,
  PaperPlaneTilt,
  Trash,
} from '@phosphor-icons/react';
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react';
import type { Navigate } from '../app';
import {
  ApiError,
  api,
  ResultInterpretationStreamError,
} from '../api/client';
import type {
  LlmConfigView,
  ResultInterpretationChatMessage,
  ResultInterpretationChatInput,
  ResultInterpretationConversationSummary,
  ResultInterpretationLanguage,
  ResultInterpretationStreamStage,
  ResultInterpretationUserMessage,
} from '../api/types';
import { LoadingPanel, Notice } from './common';
import { useI18n } from '../i18n';
import { sanitizeResultEvidencePlainText } from './result-evidence';
import {
  humanizeTechnicalText,
  TechnicalCodeDisplay,
  technicalCodeLabel,
} from './technical-code';
import { ResultInterpretationContent } from './result-interpretation-content';

const MAX_QUESTION_CHARACTERS = 2_000;
const MAX_HISTORY_MESSAGES = 11;
const MAX_HISTORY_CHARACTERS = 16_000;
const MAX_MESSAGE_CHARACTERS = 4_000;

type DisplayMessage = ResultInterpretationChatMessage;

interface FailedRequest {
  input: ResultInterpretationChatInput;
}

interface StreamState {
  stage: ResultInterpretationStreamStage | 'CONNECTING' | 'JSON_FALLBACK';
  providerChunks: number;
  receivedEventCount: number;
  elapsedMs: number;
}

interface FriendlyRequestError {
  code?: string;
  message: string;
  retryable: boolean;
  uncertainBillableAttempts: number;
  failureStage?: string;
  repairAttempted: boolean;
  repairUsed: boolean;
  billingConclusion: string;
  traceId?: string;
  needsConfiguration: boolean;
}

type HistoryState = 'loading' | 'ready' | 'error';
type HistoryDetailState = 'idle' | 'loading' | 'error';
type FollowUpSuggestionCategory = 'CURRENT_RESULT' | 'NEW_EXPERIMENT' | 'EXTERNAL_DATA';

function followUpSuggestionCategory(suggestion: string): FollowUpSuggestionCategory {
  const normalized = suggestion.toLowerCase();
  if (
    /external data|real-world data|historical data|market data|outside source|外部数据|现实数据|历史数据|市场数据|新增来源/.test(normalized)
  ) {
    return 'EXTERNAL_DATA';
  }
  if (
    /new experiment|new run|rerun|run again|matched seeds|seed pairs|larger sample|sensitivity run|ablation|change the intervention|increase.*pairs|\b(25|50|100) (pairs|seeds)\b|新实验|重新运行|再次运行|匹配种子|扩大样本|敏感性实验|消融实验|改变干预|增加到/.test(normalized)
  ) {
    return 'NEW_EXPERIMENT';
  }
  return 'CURRENT_RESULT';
}

const STREAM_STAGE_LABELS: Record<StreamState['stage'], { en: string; zh: string }> = {
  CONNECTING: { en: 'Opening a secure result stream', zh: '正在建立安全结果流' },
  PREPARING: { en: 'Preparing bounded result context', zh: '正在准备有界结果上下文' },
  PLANNING: { en: 'Selecting result sections to inspect', zh: '正在选择需要核对的结果区段' },
  READING_RESULTS: { en: 'Reading approved result sections', zh: '正在读取已允许的结果区段' },
  GENERATING: { en: 'Generating the plain-language explanation', zh: '正在生成通俗解释' },
  REASONING: { en: 'Provider processing; private reasoning stays hidden', zh: '供应商正在处理；私有推理保持隐藏' },
  VALIDATING: { en: 'Validating structure and result citations', zh: '正在校验结构与结果引用' },
  REPAIRING: { en: 'Repairing the structured response', zh: '正在修复结构化响应' },
  COMPLETED: { en: 'Final response received', zh: '已收到最终响应' },
  JSON_FALLBACK: { en: 'Using the compatible non-streaming endpoint', zh: '正在使用兼容的非流式接口' },
};

const FRIENDLY_ERROR_COPY: Record<string, { en: string; zh: string; configuration?: boolean }> = {
  LLM_CREDENTIAL_NOT_CONFIGURED: {
    en: 'No usable API credential is available. Reconnect the provider in AI Configuration.',
    zh: '当前没有可用的 API 凭据，请到“AI 配置”重新连接供应商。',
    configuration: true,
  },
  MODEL_AUTHENTICATION_ERROR: {
    en: 'The provider rejected this API key. Check or replace it in AI Configuration.',
    zh: '供应商拒绝了当前 API Key，请到“AI 配置”检查或更换。',
    configuration: true,
  },
  MODEL_PERMISSION_ERROR: {
    en: 'This API key cannot use the selected model. Choose an allowed model or key in AI Configuration.',
    zh: '当前 API Key 无权使用所选模型，请在“AI 配置”中更换模型或 Key。',
    configuration: true,
  },
  MODEL_QUOTA_EXHAUSTED: {
    en: 'The provider account has no remaining quota. Check provider billing before trying again.',
    zh: '供应商账户额度已用尽，请先检查供应商账单或余额。',
    configuration: true,
  },
  MODEL_RATE_LIMITED: {
    en: 'The provider is rate-limiting requests. Wait briefly before reviewing a retry.',
    zh: '供应商正在限流，请稍等片刻后再决定是否重试。',
  },
  RATE_LIMIT_EXCEEDED: {
    en: 'This session reached the interpretation request limit. Wait before trying again.',
    zh: '当前会话已达到解释请求限额，请稍后再试。',
  },
  MODEL_TIMEOUT: {
    en: 'The provider did not finish in time. The billing outcome may be uncertain; review the retry warning first.',
    zh: '供应商未在时限内完成；本次是否计费可能无法确定，重试前请先阅读费用提示。',
  },
  RESULT_INTERPRETATION_STREAM_TIMEOUT: {
    en: 'The result stream timed out before the final response arrived. Resume the same request ID first.',
    zh: '结果流在最终响应到达前超时；请先使用同一个请求标识恢复。',
  },
  RESULT_INTERPRETATION_STREAM_INTERRUPTED: {
    en: 'The connection was interrupted before a final response arrived. Resume with the same request ID first.',
    zh: '连接在最终响应到达前中断；请先使用同一个请求标识恢复。',
  },
  MODEL_OVERLOADED: {
    en: 'The selected provider is temporarily overloaded. Wait briefly before trying again.',
    zh: '所选供应商暂时过载，请稍后再试。',
  },
  RESULT_INTERPRETATION_BUSY: {
    en: 'Another interpretation request is still active for this session. Wait for it to finish.',
    zh: '当前会话仍有解释请求在执行，请等待其完成。',
  },
  CONTENT_FILTERED: {
    en: 'The provider content filter blocked this answer. Rephrase the question without sensitive content.',
    zh: '供应商内容过滤器阻止了本次回答，请移除敏感内容后重新提问。',
  },
  REFUSAL: {
    en: 'The provider declined this request. Rephrase it as a question about the experiment evidence.',
    zh: '供应商拒绝了本次请求，请改写为针对实验证据的问题。',
  },
  RESULT_INTERPRETATION_CONTEXT_INVALID: {
    en: 'The saved experiment context cannot support this question. Reload the result before trying again.',
    zh: '已保存的实验上下文无法支持本次问题，请重新加载结果后再试。',
  },
  RESULT_INTERPRETATION_PRIVATE_INPUT: {
    en: 'This message may contain an API key, password, email address, phone, payment or identity information, or another secret. It was blocked before any content was sent to the model provider. Remove the private data and submit a safer question.',
    zh: '本次消息可能包含 API Key、密码、邮箱、电话、支付或身份信息或其他秘密。系统已在发送给模型供应商之前拦截，相关内容未发送给模型。请删除私密数据后再提交。',
  },
  RESULT_INTERPRETATION_CONVERSATION_CONFLICT: {
    en: 'This conversation already has saved server history, so the new-conversation request was not sent to the model. Refresh saved conversations and reopen the correct one, or start a separate conversation.',
    zh: '这段对话已经存在服务器历史，因此本次“新对话”请求未发送给模型。请刷新已保存对话并重新打开正确记录，或开始一段独立的新对话。',
  },
  RESULT_INTERPRETATION_CONVERSATION_NOT_FOUND: {
    en: 'This saved conversation no longer exists or has expired, so the follow-up was not sent to the model. Refresh saved conversations, then reopen an available conversation or start a new one.',
    zh: '这段已保存对话已不存在或已过期，因此追问未发送给模型。请刷新已保存对话，然后重新打开可用记录或开始新对话。',
  },
  RESULT_INTERPRETATION_CONVERSATION_MISMATCH: {
    en: 'This browser copy does not match the validated conversation saved on the server, so the follow-up was not sent to the model. Refresh saved conversations and reopen this conversation before asking again.',
    zh: '当前浏览器中的对话与服务器保存的已校验记录不一致，因此追问未发送给模型。请刷新已保存对话并重新打开本对话后再问。',
  },
  RESULT_INTERPRETATION_CONVERSATION_DELETED: {
    en: 'This conversation was deleted, so its old request was blocked before reaching the model. Start a new conversation to ask again; deleted server history cannot be restored.',
    zh: '这段对话已经删除，旧请求已在发送给模型前被拦截。若需继续，请开始新对话；已删除的服务器历史无法恢复。',
  },
  CLIENT_REQUEST_ID_REUSED: {
    en: 'This request identifier was already used for different content. A fresh retry identifier is required.',
    zh: '本次请求标识已绑定到不同内容；重试必须使用新的请求标识。',
  },
  RESULT_INTERPRETATION_STREAM_ENDED_EARLY: {
    en: 'The connection ended before the final answer arrived. The provider may already have processed the request.',
    zh: '连接在最终回答到达前中断；供应商可能已经处理过本次请求。',
  },
  RESULT_INTERPRETATION_STREAM_CONTRACT_INVALID: {
    en: 'The server returned an invalid stream event, so no partial model text was shown.',
    zh: '服务器返回了无效流事件，因此界面没有展示任何不完整的模型文本。',
  },
  RESULT_INTERPRETATION_STREAM_BUFFER_LIMIT_EXCEEDED: {
    en: 'The result stream exceeded its safe buffer limit, so the response was rejected.',
    zh: '结果流超过安全缓冲区上限，本次响应已被拒绝。',
  },
  RESULT_INTERPRETATION_STREAM_FRAME_LIMIT_EXCEEDED: {
    en: 'A result stream event was too large, so the response was rejected.',
    zh: '结果流中的单个事件过大，本次响应已被拒绝。',
  },
  RESULT_INTERPRETATION_WAIT_CANCELLED: {
    en: 'You stopped waiting for this response. Provider processing may continue, and a charge may still occur.',
    zh: '你已停止等待本次响应；供应商仍可能继续处理，也仍可能产生费用。',
  },
};

const SAME_REQUEST_RECOVERY_CODES = new Set([
  'RESULT_INTERPRETATION_STREAM_INTERRUPTED',
  'RESULT_INTERPRETATION_STREAM_TIMEOUT',
  'RESULT_INTERPRETATION_STREAM_ENDED_EARLY',
  'RESULT_INTERPRETATION_WAIT_CANCELLED',
]);

function messageText(message: DisplayMessage): string {
  return message.role === 'user' ? message.content : message.answer;
}

function messageLanguage(message: DisplayMessage): ResultInterpretationLanguage {
  return message.language;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function friendlyRequestError(
  error: unknown,
  language: ResultInterpretationLanguage,
): FriendlyRequestError {
  const code = error instanceof ApiError ? error.code : undefined;
  const knownCopy = code ? FRIENDLY_ERROR_COPY[code] : undefined;
  const isZh = language === 'zh-CN';
  const streamError = error instanceof ResultInterpretationStreamError ? error : undefined;
  const status = error instanceof ApiError ? error.status : undefined;
  const retryable = streamError?.retryable
    ?? (status === undefined || status === 408 || status === 429 || status >= 500);
  const fallbackMessage = isZh
    ? '本次解释未能完成。界面不会展示不完整输出；请检查配置或稍后再试。'
    : 'The explanation could not be completed. No partial output was shown; check the configuration or try later.';
  return {
    code,
    message: knownCopy ? (isZh ? knownCopy.zh : knownCopy.en) : fallbackMessage,
    retryable,
    uncertainBillableAttempts: error instanceof ApiError
      ? error.uncertainBillableAttempts ?? 0
      : 0,
    failureStage: error instanceof ApiError ? error.failureStage : undefined,
    repairAttempted: error instanceof ApiError
      ? Boolean(error.repairAttempted ?? error.repairUsed)
      : false,
    repairUsed: error instanceof ApiError ? Boolean(error.repairUsed) : false,
    billingConclusion: error instanceof ApiError
      ? error.billingConclusion
        ?? ((error.uncertainBillableAttempts ?? 0) > 0
          ? 'BILLING_UNCERTAIN'
          : 'NO_UNCERTAIN_BILLING_EVIDENCE')
      : 'NO_BILLING_METADATA',
    traceId: error instanceof ApiError ? error.traceId : undefined,
    needsConfiguration: Boolean(knownCopy?.configuration),
  };
}

function formatElapsed(elapsedMs: number, language: ResultInterpretationLanguage): string {
  return new Intl.NumberFormat(language, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(Math.max(0, elapsedMs) / 1_000);
}

function billingConclusionLabel(value: string, isZh: boolean): string {
  const labels: Record<string, [string, string]> = {
    BILLING_UNCERTAIN: ['Billing is uncertain', '计费状态不确定'],
    NO_PROVIDER_ATTEMPT_RECORDED: [
      'No provider attempt was recorded',
      '未记录到供应商调用',
    ],
    PROVIDER_ATTEMPT_RECORDED_NO_UNCERTAIN_BILLING: [
      'A provider attempt was recorded; no uncertain-billing attempt was reported',
      '已记录供应商调用；未报告计费不确定调用',
    ],
    NO_UNCERTAIN_BILLING_EVIDENCE: [
      'No uncertain-billing evidence was reported',
      '未报告计费不确定证据',
    ],
    NO_BILLING_METADATA: ['Billing metadata is unavailable', '无可用计费元数据'],
  };
  return labels[value]?.[isZh ? 1 : 0] ?? value.replaceAll('_', ' ');
}

function formatHistoryDate(value: string, language: ResultInterpretationLanguage): string {
  return new Intl.DateTimeFormat(language, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value));
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
  onCreateExperimentDraft,
}: {
  experimentId: string;
  navigate: Navigate;
  onCreateExperimentDraft?: (suggestion: string) => void;
}) {
  const { language, t } = useI18n();
  const [config, setConfig] = useState<LlmConfigView>();
  const [configState, setConfigState] = useState<'loading' | 'ready' | 'error'>('loading');
  const [configError, setConfigError] = useState<string>();
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [conversationId, setConversationId] = useState<string>();
  const [historyItems, setHistoryItems] = useState<ResultInterpretationConversationSummary[]>([]);
  const [historyState, setHistoryState] = useState<HistoryState>('loading');
  const [historyError, setHistoryError] = useState<string>();
  const [historyDetailState, setHistoryDetailState] = useState<HistoryDetailState>('idle');
  const [historyDetailError, setHistoryDetailError] = useState<string>();
  const [deleteTarget, setDeleteTarget] = useState<ResultInterpretationConversationSummary>();
  const [deletingHistory, setDeletingHistory] = useState(false);
  const [historyPersistedWarning, setHistoryPersistedWarning] = useState(false);
  const [draft, setDraft] = useState('');
  const [revisionDraft, setRevisionDraft] = useState('');
  const [reasoningSummaryRequested, setReasoningSummaryRequested] = useState(false);
  const [sending, setSending] = useState(false);
  const [requestError, setRequestError] = useState<FriendlyRequestError>();
  const [failedRequest, setFailedRequest] = useState<FailedRequest>();
  const [retryReviewOpen, setRetryReviewOpen] = useState(false);
  const [streamState, setStreamState] = useState<StreamState>();
  const requestGeneration = useRef(0);
  const configGeneration = useRef(0);
  const historyGeneration = useRef(0);
  const historyDetailGeneration = useRef(0);
  const streamAbortController = useRef<AbortController | undefined>(undefined);
  const activeRequestInput = useRef<ResultInterpretationChatInput | undefined>(undefined);
  const composerRef = useRef<HTMLTextAreaElement | null>(null);
  const latestMessageRef = useRef<HTMLLIElement | null>(null);

  const loadConfig = async () => {
    const generation = ++configGeneration.current;
    setConfigState('loading');
    setConfigError(undefined);
    try {
      const nextConfig = await api.getLlmConfig();
      if (generation !== configGeneration.current) return;
      setConfig(nextConfig);
      setConfigState('ready');
    } catch (error) {
      if (generation !== configGeneration.current) return;
      setConfig(undefined);
      setConfigError(errorMessage(error));
      setConfigState('error');
    }
  };

  const loadHistory = async (silent = false) => {
    const generation = ++historyGeneration.current;
    if (!silent) setHistoryState('loading');
    setHistoryError(undefined);
    try {
      const history = await api.getResultInterpretationConversations(experimentId);
      if (generation !== historyGeneration.current) return;
      if (history.items.some((item) => item.experimentId !== experimentId)) {
        throw new TypeError('Interpretation history belongs to a different experiment.');
      }
      setHistoryItems(history.items);
      setHistoryState('ready');
    } catch (error) {
      if (generation !== historyGeneration.current) return;
      setHistoryError(errorMessage(error));
      setHistoryState('error');
    }
  };

  useEffect(() => {
    setMessages([]);
    setConversationId(undefined);
    setHistoryItems([]);
    setHistoryState('loading');
    setHistoryError(undefined);
    setHistoryDetailState('idle');
    setHistoryDetailError(undefined);
    setDeleteTarget(undefined);
    setDeletingHistory(false);
    setHistoryPersistedWarning(false);
    setDraft('');
    setRevisionDraft('');
    setRequestError(undefined);
    setFailedRequest(undefined);
    setRetryReviewOpen(false);
    setStreamState(undefined);
    setReasoningSummaryRequested(false);
    setSending(false);
    void loadConfig();
    void loadHistory();
    return () => {
      requestGeneration.current += 1;
      configGeneration.current += 1;
      historyGeneration.current += 1;
      historyDetailGeneration.current += 1;
      streamAbortController.current?.abort();
      streamAbortController.current = undefined;
      activeRequestInput.current = undefined;
    };
  }, [experimentId]);

  useEffect(() => {
    if (!sending || !streamState) return;
    const startedAt = performance.now() - streamState.elapsedMs;
    const timer = window.setInterval(() => {
      setStreamState((current) => current ? {
        ...current,
        elapsedMs: Math.max(current.elapsedMs, performance.now() - startedAt),
      } : current);
    }, 1_000);
    return () => window.clearInterval(timer);
  }, [sending, Boolean(streamState)]);

  useEffect(() => {
    if (messages.length === 0) return;
    latestMessageRef.current?.scrollIntoView({ block: 'nearest' });
  }, [messages.length]);

  const executeRequest = async (input: ResultInterpretationChatInput) => {
    const generation = ++requestGeneration.current;
    const controller = new AbortController();
    streamAbortController.current?.abort();
    streamAbortController.current = controller;
    activeRequestInput.current = input;
    setSending(true);
    setRequestError(undefined);
    setFailedRequest(undefined);
    setRetryReviewOpen(false);
    setStreamState({
      stage: 'CONNECTING',
      providerChunks: 0,
      receivedEventCount: 0,
      elapsedMs: 0,
    });
    try {
      const result = await api.streamChatAboutResults(
        experimentId,
        input,
        (update) => {
          if (generation !== requestGeneration.current) return;
          if (update.kind === 'fallback') {
            setStreamState({
              stage: 'JSON_FALLBACK',
              providerChunks: 0,
              receivedEventCount: update.receivedEventCount,
              elapsedMs: update.elapsedMs,
            });
            return;
          }
          setStreamState((current) => ({
            stage: update.progress.stage,
            providerChunks: Math.max(
              current?.providerChunks ?? 0,
              update.progress.chunkCount ?? update.progress.answerChunkCount ?? 0,
            ),
            receivedEventCount: Math.max(
              current?.receivedEventCount ?? 0,
              update.receivedEventCount,
            ),
            elapsedMs: Math.max(current?.elapsedMs ?? 0, update.progress.elapsedMs),
          }));
        },
        controller.signal,
      );
      if (generation !== requestGeneration.current) return;
      const response = result.response;
      if (result.transport === 'json-fallback') {
        setStreamState({
          stage: 'JSON_FALLBACK',
          providerChunks: 0,
          receivedEventCount: result.receivedEventCount,
          elapsedMs: result.elapsedMs,
        });
      }
      if (response.experimentId !== experimentId) {
        throw new Error(t('results.assistantResponseMismatch'));
      }
      if (response.clientRequestId !== input.clientRequestId) {
        throw new Error(t('results.assistantRequestMismatch'));
      }
      if (response.conversationId !== input.conversationId) {
        throw new Error(t('results.assistantConversationMismatch'));
      }
      if (response.message.language !== input.language) {
        throw new Error(t('results.assistantLanguageMismatch'));
      }
      setConversationId(response.conversationId);
      setMessages((current) => [...current, response.message]);
      setHistoryPersistedWarning(!response.historyPersisted);
      if (response.historyPersisted) void loadHistory(true);
      setDraft('');
      setRevisionDraft('');
    } catch (error) {
      if (generation !== requestGeneration.current) return;
      setRequestError(friendlyRequestError(error, language));
      setFailedRequest({ input });
      setRevisionDraft(input.messages.at(-1)?.content ?? '');
    } finally {
      if (generation === requestGeneration.current) {
        setSending(false);
        setStreamState(undefined);
        streamAbortController.current = undefined;
        activeRequestInput.current = undefined;
        window.requestAnimationFrame(() => composerRef.current?.focus());
      }
    }
  };

  const generateInitialExplanation = () => {
    const nextConversationId = crypto.randomUUID();
    const initialMessage: ResultInterpretationUserMessage = {
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
      || historyPersistedWarning || messages.at(-1)?.role !== 'assistant') return;
    const userMessage: ResultInterpretationUserMessage = {
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

  const startNewConversation = () => {
    requestGeneration.current += 1;
    historyDetailGeneration.current += 1;
    streamAbortController.current?.abort();
    streamAbortController.current = undefined;
    activeRequestInput.current = undefined;
    setMessages([]);
    setConversationId(undefined);
    setDraft('');
    setRevisionDraft('');
    setRequestError(undefined);
    setFailedRequest(undefined);
    setRetryReviewOpen(false);
    setStreamState(undefined);
    setHistoryDetailState('idle');
    setHistoryDetailError(undefined);
    setHistoryPersistedWarning(false);
    setSending(false);
  };

  const openSavedConversation = async (savedConversationId: string) => {
    if (sending) return;
    const generation = ++historyDetailGeneration.current;
    setHistoryDetailState('loading');
    setHistoryDetailError(undefined);
    try {
      const history = await api.getResultInterpretationConversation(
        experimentId,
        savedConversationId,
      );
      if (generation !== historyDetailGeneration.current) return;
      if (history.experimentId !== experimentId
        || history.conversationId !== savedConversationId) {
        throw new TypeError('Interpretation history does not match the selected conversation.');
      }
      requestGeneration.current += 1;
      setConversationId(history.conversationId);
      setMessages(history.messages);
      setDraft('');
      setRevisionDraft('');
      setRequestError(undefined);
      setFailedRequest(undefined);
      setRetryReviewOpen(false);
      setHistoryPersistedWarning(false);
      setHistoryDetailState('idle');
    } catch (error) {
      if (generation !== historyDetailGeneration.current) return;
      setHistoryDetailError(errorMessage(error));
      setHistoryDetailState('error');
    }
  };

  const deleteSavedConversation = async () => {
    if (!deleteTarget || deletingHistory || sending) return;
    const target = deleteTarget;
    const generation = historyGeneration.current;
    setDeletingHistory(true);
    setHistoryDetailError(undefined);
    try {
      const result = await api.deleteResultInterpretationConversation(
        experimentId,
        target.conversationId,
      );
      if (generation !== historyGeneration.current) return;
      if (result.conversationId !== target.conversationId) {
        throw new TypeError('Deleted conversation did not match the selected history item.');
      }
      setHistoryItems((current) => current.filter(
        (item) => item.conversationId !== target.conversationId,
      ));
      if (conversationId === target.conversationId) startNewConversation();
      setDeleteTarget(undefined);
      setHistoryState('ready');
    } catch (error) {
      if (generation !== historyGeneration.current) return;
      setHistoryDetailError(errorMessage(error));
      setHistoryDetailState('error');
      setDeleteTarget(undefined);
    } finally {
      setDeletingHistory(false);
    }
  };

  const cancelActiveRequest = () => {
    const input = activeRequestInput.current;
    if (!sending || !input) return;
    requestGeneration.current += 1;
    streamAbortController.current?.abort();
    streamAbortController.current = undefined;
    activeRequestInput.current = undefined;
    setSending(false);
    setStreamState(undefined);
    setRetryReviewOpen(false);
    setFailedRequest({ input });
    setRequestError({
      code: 'RESULT_INTERPRETATION_WAIT_CANCELLED',
      message: language === 'zh-CN'
        ? FRIENDLY_ERROR_COPY.RESULT_INTERPRETATION_WAIT_CANCELLED.zh
        : FRIENDLY_ERROR_COPY.RESULT_INTERPRETATION_WAIT_CANCELLED.en,
      retryable: true,
      // 浏览器停止等待后无法确认上游是否已经开始或完成计费调用。
      uncertainBillableAttempts: 1,
      failureStage: streamState?.stage,
      repairAttempted: streamState?.stage === 'REPAIRING',
      repairUsed: false,
      billingConclusion: 'BILLING_UNCERTAIN',
      needsConfiguration: false,
    });
  };

  const retryFailedRequest = () => {
    if (!failedRequest || sending) return;
    // 重试是新的潜在计费调用，不能复用上一请求的幂等键掩盖计费不确定性。
    const nextInput: ResultInterpretationChatInput = {
      ...failedRequest.input,
      clientRequestId: crypto.randomUUID(),
      language,
      reasoningSummaryRequested,
    };
    setRetryReviewOpen(false);
    void executeRequest(nextInput);
  };

  const resumeFailedRequest = () => {
    if (!failedRequest || sending || !requestError?.code
      || !SAME_REQUEST_RECOVERY_CODES.has(requestError.code)) return;
    setRetryReviewOpen(false);
    // 传输状态不明时必须保持请求体和幂等键完全一致，让服务器恢复或合并旧调用。
    void executeRequest(failedRequest.input);
  };

  const submitRevisedRequest = () => {
    const content = revisionDraft.trim();
    if (!failedRequest || !requestError || requestError.retryable
      || requestError.needsConfiguration || sending || !content
      || content.length > MAX_QUESTION_CHARACTERS) return;
    const previousInputMessages = failedRequest.input.messages.slice(0, -1);
    const revisedUserMessage: ResultInterpretationUserMessage = {
      id: `local-${crypto.randomUUID()}`,
      role: 'user',
      language,
      content,
      createdAt: new Date().toISOString(),
    };
    const revisedInput: ResultInterpretationChatInput = {
      ...failedRequest.input,
      clientRequestId: crypto.randomUUID(),
      language,
      reasoningSummaryRequested,
      messages: [...previousInputMessages, { role: 'user', content }],
    };
    // 失败的用户轮次尚未产生助手回答，因此替换它而不是追加，继续保持严格交替。
    setMessages((current) => current.at(-1)?.role === 'user'
      ? [...current.slice(0, -1), revisedUserMessage]
      : [...current, revisedUserMessage]);
    void executeRequest(revisedInput);
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

  const canUseModel = configState === 'ready' && Boolean(config?.configured);
  const draftLength = draft.length;
  const draftTooLong = draftLength > MAX_QUESTION_CHARACTERS;
  const revisionTooLong = revisionDraft.length > MAX_QUESTION_CHARACTERS;
  const canResumeSameRequest = Boolean(
    failedRequest
    && requestError?.code
    && SAME_REQUEST_RECOVERY_CODES.has(requestError.code),
  );
  // 后端未持久化时不能只依赖当前页面的对话副本追问，否则刷新后
  // 服务器无法重建相同上下文，也无法对后续记录做完整性校验。
  const canAskFollowUp = !historyPersistedWarning
    && messages.at(-1)?.role === 'assistant';
  const isZh = language === 'zh-CN';
  const analysisSummaryLabel = isZh ? '包含分析摘要' : 'Include an analysis summary';
  const providerThinkingLabel = config?.thinkingEnabled
    ? isZh ? '供应商思考模式：已开启' : 'Provider thinking: on'
    : isZh ? '供应商思考模式：已关闭' : 'Provider thinking: off';
  const streamStageLabel = streamState
    ? (isZh ? STREAM_STAGE_LABELS[streamState.stage].zh : STREAM_STAGE_LABELS[streamState.stage].en)
    : undefined;

  return (
    <section
      className="result-assistant"
      aria-labelledby="result-assistant-heading"
      aria-busy={sending}
    >
      {renderHeader()}
      <Notice>{t('results.assistantBoundary')}</Notice>
      <div className="result-assistant__storage-boundary" role="note">
        <strong>{t('results.assistantStorageTitle')}</strong>
        <span>{t('results.assistantStorageBody')}</span>
      </div>

      <section
        className="result-assistant__history"
        aria-labelledby={`result-assistant-history-${experimentId}`}
      >
        <header>
          <div>
            <h3 id={`result-assistant-history-${experimentId}`}>
              {t('results.assistantHistoryTitle')}
            </h3>
            <p>{t('results.assistantHistoryBody')}</p>
          </div>
          <div>
            {messages.length > 0 || conversationId ? (
              <Button
                kind="ghost"
                size="sm"
                disabled={sending}
                onClick={startNewConversation}
              >
                {t('results.assistantNewConversation')}
              </Button>
            ) : null}
            <Button
              kind="ghost"
              size="sm"
              renderIcon={ArrowClockwise}
              disabled={sending || historyState === 'loading'}
              onClick={() => void loadHistory()}
            >
              {t('results.assistantHistoryRefresh')}
            </Button>
          </div>
        </header>

        {historyState === 'loading' ? (
          <LoadingPanel label={t('results.assistantHistoryLoading')} />
        ) : null}
        {historyState === 'error' ? (
          <InlineNotification
            kind="error"
            lowContrast
            hideCloseButton
            title={t('results.assistantHistoryErrorTitle')}
            subtitle={historyError ?? t('results.assistantHistoryErrorBody')}
          />
        ) : null}
        {historyState === 'ready' && historyItems.length === 0 ? (
          <p className="result-assistant__history-empty">
            {t('results.assistantHistoryEmpty')}
          </p>
        ) : null}
        {historyItems.length > 0 ? (
          <ul className="result-assistant__history-list">
            {historyItems.map((item) => {
              const isActive = item.conversationId === conversationId;
              return (
                <li key={item.conversationId} className={isActive ? 'is-active' : undefined}>
                  <button
                    type="button"
                    className="result-assistant__history-open"
                    aria-current={isActive ? 'true' : undefined}
                    disabled={sending || historyDetailState === 'loading'}
                    onClick={() => void openSavedConversation(item.conversationId)}
                  >
                    <strong>{item.lastUserMessage}</strong>
                    <span>
                      {t('results.assistantHistoryExchanges', { value: item.exchangeCount })}
                      {' · '}
                      {formatHistoryDate(item.updatedAt, language)}
                    </span>
                  </button>
                  <Tag type="cool-gray" size="sm">{item.language === 'zh-CN' ? '中文' : 'EN'}</Tag>
                  <Button
                    kind="ghost"
                    size="sm"
                    hasIconOnly
                    renderIcon={Trash}
                    iconDescription={t('results.assistantHistoryDeleteNamed', {
                      value: item.lastUserMessage,
                    })}
                    disabled={sending || deletingHistory}
                    onClick={() => setDeleteTarget(item)}
                  />
                </li>
              );
            })}
          </ul>
        ) : null}
        {historyDetailState === 'loading' ? (
          <p className="result-assistant__history-status" role="status">
            {t('results.assistantHistoryOpening')}
          </p>
        ) : null}
        {historyDetailState === 'error' ? (
          <InlineNotification
            kind="error"
            lowContrast
            hideCloseButton
            title={t('results.assistantHistoryActionErrorTitle')}
            subtitle={historyDetailError ?? t('results.assistantHistoryErrorBody')}
          />
        ) : null}
      </section>

      {configState === 'loading' ? (
        <div className="result-assistant__config-state">
          <LoadingPanel label={t('results.assistantCheckingConfig')} />
        </div>
      ) : null}
      {configState === 'error' ? (
        <div className="result-assistant__config-state">
          <InlineNotification
            kind="error"
            lowContrast
            hideCloseButton
            title={t('results.assistantConfigErrorTitle')}
            subtitle={configError ?? t('results.assistantErrorFallback')}
          />
          <Button
            kind="tertiary"
            size="sm"
            renderIcon={ArrowClockwise}
            onClick={() => void loadConfig()}
          >
            {t('common.retry')}
          </Button>
        </div>
      ) : null}
      {configState === 'ready' && !config?.configured ? (
        <div className="result-assistant__empty">
          <div>
            <h3>{t('results.assistantNoKeyTitle')}</h3>
            <p>{t('results.assistantNoKeyBody')}</p>
          </div>
          <Button kind="tertiary" onClick={() => navigate('ai')}>
            {t('results.assistantConfigure')}
          </Button>
        </div>
      ) : null}

      {historyPersistedWarning ? (
        <InlineNotification
          kind="warning"
          lowContrast
          hideCloseButton
          title={t('results.assistantHistoryNotSavedTitle')}
          subtitle={t('results.assistantHistoryNotSavedBody')}
        />
      ) : null}

      {canUseModel ? <div className="result-assistant__controls">
        <div>
          <strong>{analysisSummaryLabel}</strong>
          <span>{isZh
            ? `这里仅请求最终回答附带一段可核验的证据检查摘要，和“${providerThinkingLabel}”相互独立。供应商的私有思维链不会返回，也不会显示。`
            : `This only asks the final answer to include a reviewable evidence-check summary. It is independent of “${providerThinkingLabel}.” Private chain-of-thought is never returned or displayed.`}</span>
        </div>
        <Toggle
          id={`result-assistant-reasoning-${experimentId}`}
          aria-label={analysisSummaryLabel}
          labelA={t('results.assistantOff')}
          labelB={t('results.assistantOn')}
          toggled={reasoningSummaryRequested}
          disabled={sending}
          onToggle={setReasoningSummaryRequested}
        />
      </div> : null}

      {messages.length === 0 ? (
        canUseModel ? <div className="result-assistant__start">
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
        </div> : null
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
                {message.role === 'assistant' ? (
                  <ResultInterpretationContent
                    experimentId={experimentId}
                    message={message}
                    navigate={navigate}
                  />
                ) : (
                  <p className="result-assistant__answer result-assistant__answer--user">
                    {message.content}
                  </p>
                )}
                {message.role === 'assistant' && message.followUpSuggestions.length > 0 ? (
                  <div className="result-assistant__suggestions" aria-label={t('results.assistantSuggestions')}>
                    <strong>{t('results.assistantSuggestions')}</strong>
                    <div>
                      {message.followUpSuggestions.map((suggestion, suggestionIndex) => {
                        const visibleSuggestion = humanizeTechnicalText(
                          sanitizeResultEvidencePlainText(suggestion, language),
                          language,
                        );
                        const category = followUpSuggestionCategory(visibleSuggestion);
                        if (category === 'NEW_EXPERIMENT') {
                          return (
                            <div
                              key={`${message.id}-${suggestionIndex}`}
                              className="result-assistant__suggestion-item"
                            >
                              <p>{visibleSuggestion}</p>
                              <span>
                                <Tag type="blue" size="sm">
                                  {isZh ? '需要新实验' : 'New experiment required'}
                                </Tag>
                                <Tag type="warm-gray" size="sm">
                                  {isZh ? '尚未运行' : 'Not run'}
                                </Tag>
                              </span>
                              {onCreateExperimentDraft ? (
                                <Button
                                  kind="tertiary"
                                  size="sm"
                                  disabled={sending || historyPersistedWarning}
                                  onClick={() => onCreateExperimentDraft(visibleSuggestion)}
                                >
                                  {isZh ? '创建预填场景草稿' : 'Create prefilled scenario draft'}
                                </Button>
                              ) : null}
                            </div>
                          );
                        }
                        if (category === 'EXTERNAL_DATA') {
                          return (
                            <div
                              key={`${message.id}-${suggestionIndex}`}
                              className="result-assistant__suggestion-item"
                            >
                              <p>{visibleSuggestion}</p>
                              <Tag type="gray" size="sm">
                                {isZh ? '需要外部数据' : 'External data required'}
                              </Tag>
                            </div>
                          );
                        }
                        return (
                          <div
                            key={`${message.id}-${suggestionIndex}`}
                            className="result-assistant__suggestion-item"
                          >
                            <Tag type="gray" size="sm">
                              {isZh ? '当前结果可回答' : 'Answerable from current result'}
                            </Tag>
                            <Button
                              kind="ghost"
                              size="sm"
                              disabled={sending || !canUseModel || historyPersistedWarning}
                              onClick={() => {
                                setDraft(visibleSuggestion);
                                window.requestAnimationFrame(() => composerRef.current?.focus());
                              }}
                            >
                              {visibleSuggestion}
                            </Button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ) : null}
                {message.role === 'assistant' ? (
                  <footer className="result-assistant__usage">
                    <span>{message.totalTokens.toLocaleString(language)} {t('results.assistantTokens')}</span>
                    <span>{formatElapsed(message.latencyMs, language)} {isZh ? '秒模型耗时' : 's model latency'}</span>
                    {message.cacheHit ? <span>{t('results.assistantCacheHit')}</span> : null}
                    {message.repairUsed ? <span>{t('results.assistantRepairUsed')}</span> : null}
                  </footer>
                ) : null}
              </li>
            ))}
            {sending ? (
              <li className="result-assistant__pending">
                <Brain size={20} weight="duotone" aria-hidden="true" />
                <div>
                  <div className="result-assistant__pending-status" role="status" aria-live="polite" aria-atomic="true">
                    <strong>{streamStageLabel ?? t('results.assistantGenerating')}</strong>
                  </div>
                  <span aria-hidden="true">
                    {isZh
                      ? `模型数据块 ${streamState?.providerChunks ?? 0} · 状态事件 ${streamState?.receivedEventCount ?? 0} · ${formatElapsed(streamState?.elapsedMs ?? 0, language)} 秒`
                      : `${streamState?.providerChunks ?? 0} provider chunks · ${streamState?.receivedEventCount ?? 0} status events · ${formatElapsed(streamState?.elapsedMs ?? 0, language)} s`}
                  </span>
                  <small>{isZh
                    ? '这里只显示安全阶段和计数；不会流式展示回答草稿或私有思维链。'
                    : 'Only safe stages and counters appear here; answer drafts and private chain-of-thought are never streamed to the UI.'}</small>
                  <Button kind="ghost" size="sm" onClick={cancelActiveRequest}>
                    {isZh ? '停止等待' : 'Stop waiting'}
                  </Button>
                </div>
              </li>
            ) : null}
          </ol>

          {canAskFollowUp && canUseModel ? <div className="result-assistant__composer">
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
          {canAskFollowUp && !canUseModel ? (
            <div className="result-assistant__history-readonly">
              <div>
                <strong>{t('results.assistantHistoryReadOnlyTitle')}</strong>
                <span>{t('results.assistantHistoryReadOnlyBody')}</span>
              </div>
              <Button kind="tertiary" size="sm" onClick={() => navigate('ai')}>
                {t('results.assistantConfigure')}
              </Button>
            </div>
          ) : null}
        </>
      )}

      {requestError ? (
        <div className="result-assistant__error">
          <InlineNotification
            kind="error"
            lowContrast
            hideCloseButton
            title={t('results.assistantErrorTitle')}
            subtitle={requestError.message}
          />
          {requestError.code || requestError.failureStage ? (
            <TechnicalCodeDisplay
              codes={[requestError.code, requestError.failureStage]}
              language={language}
            />
          ) : null}
          {requestError.traceId ? (
            <details className="result-assistant__error-meta">
              <summary>{isZh ? '支持诊断信息' : 'Support diagnostic'}</summary>
              <span>{isZh ? '追踪号' : 'Trace'}: <code>{requestError.traceId}</code></span>
            </details>
          ) : null}
          <dl className="definition-list definition-list--compact">
            <div>
              <dt>{isZh ? '失败阶段' : 'Failure stage'}</dt>
              <dd>{requestError.failureStage
                ? technicalCodeLabel(requestError.failureStage, language)
                : isZh ? '未记录' : 'Not recorded'}</dd>
            </div>
            <div>
              <dt>{isZh ? '修复尝试' : 'Repair attempt'}</dt>
              <dd>{requestError.repairAttempted
                ? requestError.repairUsed
                  ? isZh ? '已尝试并记录修复' : 'Attempted; repair recorded'
                  : isZh ? '已尝试，未采用修复结果' : 'Attempted; repair result not used'
                : isZh ? '未尝试' : 'Not attempted'}</dd>
            </div>
            <div>
              <dt>{isZh ? '计费结论' : 'Billing conclusion'}</dt>
              <dd>{billingConclusionLabel(requestError.billingConclusion, isZh)}</dd>
            </div>
          </dl>
          {requestError.needsConfiguration ? (
            <Button
              kind="tertiary"
              size="sm"
              disabled={sending}
              onClick={() => navigate('ai')}
            >
              {t('results.assistantConfigure')}
            </Button>
          ) : null}
          {canResumeSameRequest ? (
            <div className="result-assistant__recovery">
              <p>{isZh
                ? '本次先用同一请求标识尝试合并正在处理的调用或恢复已保存终态。若服务在终态写入前重启，结果与计费状态仍可能未知；明确发起新请求仍需再次确认费用。'
                : 'This first reuses the same request ID to join an active call or recover a saved final response. If the service restarted before saving the final state, outcome and billing may remain unknown; an explicit new request still requires cost confirmation.'}</p>
              <Button
                kind="tertiary"
                size="sm"
                renderIcon={ArrowClockwise}
                disabled={sending}
                onClick={resumeFailedRequest}
              >
                {isZh ? '使用原请求标识恢复' : 'Resume the same request'}
              </Button>
            </div>
          ) : null}
          {failedRequest && requestError.retryable && !canResumeSameRequest && !retryReviewOpen ? (
            <Button
              kind="tertiary"
              size="sm"
              renderIcon={ArrowClockwise}
              disabled={sending}
              onClick={() => setRetryReviewOpen(true)}
            >
              {isZh ? '查看重试与费用提示' : 'Review retry and cost warning'}
            </Button>
          ) : null}
          {failedRequest && requestError.retryable && !canResumeSameRequest && retryReviewOpen ? (
            <div className="result-assistant__retry-review">
              <InlineNotification
                kind="warning"
                lowContrast
                hideCloseButton
                title={isZh ? '重试可能再次产生费用' : 'A retry may create another provider charge'}
                subtitle={requestError.uncertainBillableAttempts > 0
                  ? isZh
                    ? `上一次请求有 ${requestError.uncertainBillableAttempts} 次供应商调用无法确认是否已计费。确认后系统会使用新的请求标识发起一次独立调用。`
                    : `The previous request has ${requestError.uncertainBillableAttempts} provider attempt(s) with uncertain billing. Confirming starts an independent call with a new request ID.`
                  : isZh
                    ? '即使上一次没有确认计费，重试仍是一次新的供应商请求，可能产生费用；系统会生成新的请求标识。'
                    : 'Even when no prior charge was confirmed, retrying is a new provider request and may incur a charge. A new request ID will be generated.'}
              />
              <div>
                <Button kind="secondary" size="sm" onClick={() => setRetryReviewOpen(false)}>
                  {isZh ? '取消' : 'Cancel'}
                </Button>
                <Button size="sm" renderIcon={ArrowClockwise} onClick={retryFailedRequest}>
                  {isZh ? '确认并发起新重试' : 'Confirm new retry'}
                </Button>
              </div>
            </div>
          ) : null}
          {failedRequest && !requestError.retryable && !requestError.needsConfiguration ? (
            <div className="result-assistant__revision">
              <TextArea
                id={`result-assistant-revision-${experimentId}`}
                labelText={isZh ? '修改后重新提交' : 'Revise and submit again'}
                helperText={isZh
                  ? `保留此前已有回答，只替换失败的最后一个问题。${revisionDraft.length}/${MAX_QUESTION_CHARACTERS}`
                  : `Prior completed turns are preserved; only the failed final question is replaced. ${revisionDraft.length}/${MAX_QUESTION_CHARACTERS}`}
                invalid={revisionTooLong}
                invalidText={t('results.assistantTooLong', { value: MAX_QUESTION_CHARACTERS })}
                rows={3}
                value={revisionDraft}
                disabled={sending}
                onChange={(event) => setRevisionDraft(event.target.value)}
              />
              <Button
                size="sm"
                renderIcon={PaperPlaneTilt}
                disabled={sending || !revisionDraft.trim() || revisionTooLong}
                onClick={submitRevisedRequest}
              >
                {isZh ? '使用新请求提交修改' : 'Submit revision as a new request'}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}

      {deleteTarget ? <Modal
        open
        danger
        modalHeading={t('results.assistantHistoryDeleteTitle')}
        primaryButtonText={deletingHistory
          ? t('results.assistantHistoryDeleting')
          : t('results.assistantHistoryDeleteConfirm')}
        secondaryButtonText={t('results.assistantHistoryDeleteCancel')}
        primaryButtonDisabled={deletingHistory || sending}
        onRequestClose={() => {
          if (!deletingHistory) setDeleteTarget(undefined);
        }}
        onRequestSubmit={() => void deleteSavedConversation()}
      >
        <p>{t('results.assistantHistoryDeleteBody')}</p>
        <blockquote className="result-assistant__delete-preview">
          {deleteTarget.lastUserMessage}
        </blockquote>
      </Modal> : null}
    </section>
  );
}
