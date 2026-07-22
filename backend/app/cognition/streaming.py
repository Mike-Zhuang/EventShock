"""外部模型 SSE 的有界解析与供应商中立进度事件。

结构化输出在流中只是尚未验证的文本片段；本模块只负责在内存中组装，最终仍由
网关执行完整 Pydantic、证据和动作边界校验。供应商隐藏思维链不会进入公开事件，
只累计不含正文的片段计数，以便前端展示安全的实时进度。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

MAX_PROVIDER_STREAM_BYTES = 2_000_000
MAX_PROVIDER_CONTENT_CHARACTERS = 200_000
PROVIDER_STREAM_READ_CHUNK_BYTES = 64 * 1024


class ModelStreamStage(StrEnum):
    PREPARING = "PREPARING"
    PLANNING = "PLANNING"
    READING_RESULTS = "READING_RESULTS"
    GENERATING = "GENERATING"
    REASONING = "REASONING"
    VALIDATING = "VALIDATING"
    REPAIRING = "REPAIRING"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class ModelStreamProgress:
    """可安全发送到浏览器的进度；不包含模型正文、思维链或用户输入。"""

    stage: ModelStreamStage
    elapsedMs: float = 0.0
    chunkCount: int = 0
    answerChunkCount: int = 0
    reasoningChunkCount: int = 0
    attempt: int = 1
    repair: bool = False


ModelStreamObserver = Callable[[ModelStreamProgress], Awaitable[None]]


async def emitModelStreamProgress(
    observer: ModelStreamObserver | None,
    progress: ModelStreamProgress,
) -> None:
    """进度通道失败不能让已经可能计费的模型请求失败或被重复提交。"""

    if observer is None:
        return
    try:
        await observer(progress)
    except Exception:
        # 浏览器断开、队列已关闭等仅影响实时展示；底层单飞任务继续完成，
        # 让相同 clientRequestId 可以复用结果而不是触发第二次付费调用。
        return


@dataclass(frozen=True, slots=True)
class SseEvent:
    event: str
    data: str


async def iterSseEvents(response: httpx.Response) -> AsyncIterator[SseEvent]:
    """严格、有限地解析 SSE；支持多行 ``data`` 并忽略注释心跳。"""

    eventName = "message"
    dataLines: list[str] = []
    async for line in _iterBoundedUtf8Lines(response):
        if line == "":
            if dataLines:
                yield SseEvent(event=eventName, data="\n".join(dataLines))
            eventName = "message"
            dataLines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            eventName = line[6:].strip() or "message"
        elif line.startswith("data:"):
            dataLines.append(line[5:].lstrip())
    if dataLines:
        yield SseEvent(event=eventName, data="\n".join(dataLines))


async def _iterBoundedUtf8Lines(response: httpx.Response) -> AsyncIterator[str]:
    """在换行解码前限制字节数，避免无换行响应撑大 httpx 内部行缓冲。"""

    pending = bytearray()
    receivedBytes = 0

    def decodeLine(rawLine: bytes | bytearray) -> str:
        try:
            return bytes(rawLine).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("provider stream contained invalid UTF-8") from error

    async for chunk in response.aiter_bytes(chunk_size=PROVIDER_STREAM_READ_CHUNK_BYTES):
        receivedBytes += len(chunk)
        if receivedBytes > MAX_PROVIDER_STREAM_BYTES:
            # 先检查再复制进 pending；即使供应商从不发送换行，应用层缓冲也有硬上限。
            raise ValueError("provider stream exceeded the bounded response limit")
        pending.extend(chunk)

        lineStart = 0
        index = 0
        while index < len(pending):
            delimiter = pending[index]
            if delimiter == 0x0A:  # LF
                yield decodeLine(pending[lineStart:index])
                index += 1
                lineStart = index
                continue
            if delimiter == 0x0D:  # CR 或 CRLF
                if index + 1 == len(pending):
                    # CRLF 可能恰好跨网络块；保留尾部 CR 到下一块再决定分隔符长度。
                    break
                yield decodeLine(pending[lineStart:index])
                index += 2 if pending[index + 1] == 0x0A else 1
                lineStart = index
                continue
            index += 1

        if lineStart:
            del pending[:lineStart]

    if pending:
        if pending[-1] == 0x0D:
            # EOF 时尾部 CR 本身就是合法行分隔符；空行仍需交给 SSE 事件组装器。
            yield decodeLine(pending[:-1])
        else:
            yield decodeLine(pending)


class ProviderStreamAccumulator:
    """把七家供应商的官方 SSE 事件还原成现有非流式响应形状。"""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self.contentParts: list[str] = []
        self.answerChunkCount = 0
        self.reasoningChunkCount = 0
        self.chunkCount = 0
        self.finishReason: str | None = None
        self.usage: dict[str, Any] = {}
        self.finalBody: dict[str, Any] | None = None
        self._anthropicInputUsage: dict[str, Any] = {}
        self._contentCharacterCount = 0
        self._doneReceived = False
        self._terminalEventReceived = False

    @property
    def content(self) -> str:
        return "".join(self.contentParts)

    def accept(self, event: SseEvent) -> None:
        if event.data.strip() == "[DONE]":
            self._doneReceived = True
            return
        if self._doneReceived:
            raise ValueError("provider stream emitted data after its terminal marker")
        try:
            payload = json.loads(event.data)
        except json.JSONDecodeError as error:
            raise ValueError("provider stream contained invalid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("provider stream event root must be an object")
        self.chunkCount += 1
        eventType = str(payload.get("type") or payload.get("event_type") or event.event)
        if event.event == "error" or eventType == "error":
            # 错误正文可能回显输入或供应商诊断，不把它拼入异常或日志。
            raise ValueError("provider stream reported an error")
        if self.provider == "openai":
            self._acceptOpenAi(payload, event.event)
        elif self.provider == "anthropic":
            self._acceptAnthropic(payload, event.event)
        elif self.provider == "google":
            self._acceptGoogle(payload, event.event)
        else:
            self._acceptChatCompletion(payload)

    def _appendContent(self, value: object) -> None:
        if isinstance(value, str) and value:
            nextCharacterCount = self._contentCharacterCount + len(value)
            if nextCharacterCount > MAX_PROVIDER_CONTENT_CHARACTERS:
                raise ValueError("provider structured content exceeded the bounded response limit")
            self.contentParts.append(value)
            self._contentCharacterCount = nextCharacterCount
            self.answerChunkCount += 1

    def _countReasoning(self, value: object) -> None:
        if isinstance(value, str) and value:
            # 故意不保存 value，避免隐藏思维链进入日志、审计、前端或响应哈希。
            self.reasoningChunkCount += 1

    def _acceptChatCompletion(self, payload: dict[str, Any]) -> None:
        choices = payload.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            choice = choices[0]
            delta = choice.get("delta")
            if isinstance(delta, dict):
                self._appendContent(delta.get("content"))
                self._countReasoning(
                    delta.get("reasoning_content")
                    or delta.get("reasoning")
                    or delta.get("thinking")
                )
            finishReason = choice.get("finish_reason")
            if isinstance(finishReason, str):
                self.finishReason = finishReason
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self.usage = usage

    def _acceptOpenAi(self, payload: dict[str, Any], eventName: str) -> None:
        eventType = str(payload.get("type") or eventName)
        if eventType == "response.output_text.delta":
            self._appendContent(payload.get("delta"))
        elif eventType == "response.output_text.done" and not self.contentParts:
            # 正常情况下 delta 已经包含全文；若代理只转发 done 事件，仍可安全恢复。
            self._appendContent(payload.get("text"))
        elif eventType in {
            "response.reasoning_text.delta",
            "response.reasoning_summary_text.delta",
        }:
            self._countReasoning(payload.get("delta"))
        elif eventType in {
            "response.completed",
            "response.incomplete",
            "response.failed",
        }:
            self._terminalEventReceived = True
            response = payload.get("response")
            if isinstance(response, dict):
                self.finalBody = response
                usage = response.get("usage")
                if isinstance(usage, dict):
                    self.usage = usage

    def _acceptAnthropic(self, payload: dict[str, Any], eventName: str) -> None:
        eventType = str(payload.get("type") or eventName)
        if eventType == "message_start":
            message = payload.get("message")
            if isinstance(message, dict):
                usage = message.get("usage")
                if isinstance(usage, dict):
                    self._anthropicInputUsage = usage
        elif eventType == "content_block_start":
            block = payload.get("content_block")
            if isinstance(block, dict):
                if block.get("type") == "text":
                    self._appendContent(block.get("text"))
                elif block.get("type") == "thinking":
                    self._countReasoning(block.get("thinking"))
        elif eventType == "content_block_delta":
            delta = payload.get("delta")
            if isinstance(delta, dict):
                if delta.get("type") == "text_delta":
                    self._appendContent(delta.get("text"))
                elif delta.get("type") == "thinking_delta":
                    self._countReasoning(delta.get("thinking"))
                # input_json_delta 是工具参数而非结构化回答；signature_delta 是
                # 不可展示的完整性材料。两者都不能混入答案或推理进度正文。
        elif eventType == "message_delta":
            delta = payload.get("delta")
            if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
                self.finishReason = delta["stop_reason"]
            usage = payload.get("usage")
            if isinstance(usage, dict):
                self.usage = {**self._anthropicInputUsage, **usage}
        elif eventType == "message_stop":
            self._terminalEventReceived = True

    def _acceptGoogle(self, payload: dict[str, Any], eventName: str) -> None:
        eventType = str(payload.get("event_type") or payload.get("type") or eventName)
        if eventType == "step.delta":
            delta = payload.get("delta")
            if isinstance(delta, dict):
                if delta.get("type") == "text":
                    self._appendContent(delta.get("text"))
                elif delta.get("type") in {"thought", "thinking"}:
                    self._countReasoning(delta.get("text"))
                elif delta.get("type") == "thought_summary":
                    content = delta.get("content")
                    if isinstance(content, dict):
                        self._countReasoning(content.get("text"))
        elif eventType in {"interaction.completed", "interaction.failed"}:
            self._terminalEventReceived = True
            interaction = payload.get("interaction")
            if isinstance(interaction, dict):
                self.finalBody = interaction
                usage = interaction.get("usage")
                if isinstance(usage, dict):
                    self.usage = usage
        else:
            self._acceptLegacyGoogle(payload)

    def _acceptLegacyGoogle(self, payload: dict[str, Any]) -> None:
        """兼容 ``streamGenerateContent`` 的 GenerateContentResponse 分片。"""

        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content")
                parts = content.get("parts") if isinstance(content, dict) else None
                if isinstance(parts, list):
                    for part in parts:
                        if not isinstance(part, dict):
                            continue
                        # thoughtSignature 是跨轮协议材料，既不是答案也不是可展示推理。
                        if part.get("thought") is True:
                            self._countReasoning(part.get("text"))
                        else:
                            self._appendContent(part.get("text"))
                finishReason = candidate.get("finishReason")
                if isinstance(finishReason, str) and finishReason:
                    self.finishReason = finishReason
                    self._terminalEventReceived = True

        usage = payload.get("usageMetadata")
        if isinstance(usage, dict):
            promptTokens = self._nonNegativeInt(usage.get("promptTokenCount"))
            outputTokens = self._nonNegativeInt(usage.get("candidatesTokenCount"))
            thoughtTokens = self._nonNegativeInt(usage.get("thoughtsTokenCount"))
            cachedTokens = self._nonNegativeInt(usage.get("cachedContentTokenCount"))
            normalizedUsage = {
                "total_input_tokens": promptTokens,
                "total_output_tokens": outputTokens,
                "total_thought_tokens": thoughtTokens,
                "total_cached_tokens": cachedTokens,
            }
            reportedTotal = self._nonNegativeInt(usage.get("totalTokenCount"))
            expectedTotal = promptTokens + outputTokens + thoughtTokens
            if reportedTotal == expectedTotal:
                normalizedUsage["total_tokens"] = reportedTotal
            self.usage = normalizedUsage

    @staticmethod
    def _nonNegativeInt(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    def _requireComplete(self) -> None:
        if self.provider in {"zhipu", "deepseek", "alibaba", "moonshot"}:
            if not self._doneReceived:
                raise ValueError("provider stream ended before the terminal [DONE] marker")
            if self.finishReason is None:
                raise ValueError("provider stream ended without a finish reason")
            return
        if not self._terminalEventReceived:
            raise ValueError("provider stream ended before its terminal event")
        if self.provider == "openai" and self.finalBody is None:
            raise ValueError("provider terminal event did not contain a final response")
        if self.provider == "anthropic" and self.finishReason is None:
            raise ValueError("provider terminal event did not contain a stop reason")
        if self.provider == "google" and self.finalBody is None and self.finishReason is None:
            raise ValueError("provider terminal event did not contain a final interaction")

    def buildBody(self) -> dict[str, Any]:
        # EOF 本身不是成功信号。网络中断也会产生 EOF，必须先看到供应商定义的
        # 终止标记，才能把已累计文本交给后续 JSON/Schema 校验。
        self._requireComplete()
        content = self.content.strip()
        if self.provider == "openai":
            if self.finalBody is not None:
                finalBody = dict(self.finalBody)
                if not finalBody.get("output") and content:
                    finalBody["output"] = [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": content}],
                        }
                    ]
                return finalBody
            return {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": content}],
                    }
                ],
                "usage": self.usage,
            }
        if self.provider == "anthropic":
            return {
                "stop_reason": self.finishReason or "end_turn",
                "content": [{"type": "text", "text": content}],
                "usage": self.usage or self._anthropicInputUsage,
            }
        if self.provider == "google":
            if self.finalBody is not None:
                finalBody = dict(self.finalBody)
                if not finalBody.get("steps") and content:
                    finalBody["steps"] = [
                        {"type": "model_output", "content": [{"type": "text", "text": content}]}
                    ]
                return finalBody
            return {
                "status": (
                    "completed" if self.finishReason in {None, "STOP", "stop"} else "incomplete"
                ),
                "finish_reason": self.finishReason,
                "steps": [{"type": "model_output", "content": [{"type": "text", "text": content}]}],
                "usage": self.usage,
            }
        return {
            "choices": [
                {
                    "index": 0,
                    "finish_reason": self.finishReason or "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": self.usage,
        }
