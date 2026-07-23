"""模型自由文本输出的确定性防泄漏边界。

系统提示词本身随开源代码可见，不能被当成秘密或声称“绝对不可提取”。本模块的目标
是阻止模型把控制指令、凭据形态或主动内容原样带到产品界面，并降低直接/间接提示词
注入造成的偶然复述风险。所有拒绝异常都只返回稳定原因码，不携带模型原响应。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

_ZERO_WIDTH_AND_DIRECTIONAL = frozenset(
    {
        "\u061c",
        "\u200b",
        "\u200c",
        "\u200d",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2060",
        "\u2061",
        "\u2062",
        "\u2063",
        "\u2064",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\ufeff",
    }
)
_WORD_PATTERN = re.compile(r"[a-z0-9_][a-z0-9_.:-]*|[\u3400-\u9fff]", re.IGNORECASE)
_RAW_HTML_PATTERN = re.compile(
    r"<\s*/?\s*(?:"
    r"script|iframe|object|embed|style|link|meta|form|input|button|svg|math|"
    r"[a-z][a-z0-9-]*\s+[^>]*"
    r")>",
    re.IGNORECASE,
)
_DANGEROUS_URL_PATTERN = re.compile(
    r"(?:javascript|data|file|vbscript|mailto)\s*:|http\s*://|"
    r"https\s*://[^\s/@:]+:[^\s/@]+@",
    re.IGNORECASE,
)
_CREDENTIAL_PATTERNS = (
    re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:sk|ak)-[A-Za-z0-9_.-]{16,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(
        r"(?:api[\s_-]*(?:key|密钥)|access[\s_-]*token|authorization|"
        r"password|passwd|secret|访问令牌|密码|密钥)"
        r"\s*(?:is|是|:|=)\s*(?:bearer\s+)?[\"']?"
        r"[A-Za-z0-9_./+=-]{12,}",
        re.IGNORECASE,
    ),
)
_CONTROL_DISCLOSURE_PATTERN = re.compile(
    r"(?:"
    r"security\s*(?:,|and|&)\s*authority\s*rules|"
    r"output\s+json\s+schema|"
    r"begin[_\s-]*untrusted[_\s-]*(?:evidence|data)|"
    r"end[_\s-]*untrusted[_\s-]*(?:evidence|data)|"
    r"system\s+(?:prompt|message|instruction)|"
    r"developer\s+(?:prompt|message|instruction)|"
    r"reveal\s+(?:the\s+)?(?:hidden|system|developer)\s+(?:prompt|message|instruction)|"
    r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions|"
    r"安全(?:与|和)?权限规则|系统(?:提示词|消息|指令)|开发者(?:消息|指令)|"
    r"忽略(?:之前|以上|前面).{0,12}(?:指令|提示词)"
    r")",
    re.IGNORECASE,
)
_PUBLIC_OUTPUT_PHRASES = (
    "this is scenario analysis conditional on synthetic assumptions not a prediction "
    "and not investment advice",
    "这是以合成假设为条件的情景分析不是预测也不构成投资建议",
)
_COMMON_NGRAM_WORDS = frozenset(
    {
        "about",
        "after",
        "analysis",
        "answer",
        "current",
        "data",
        "evidence",
        "eventshock",
        "experiment",
        "market",
        "model",
        "output",
        "result",
        "scenario",
        "source",
        "supplied",
        "system",
        "tools",
        "user",
    }
)
_LONG_FRAGMENT_LENGTH = 96
_RARE_NGRAM_LENGTH = 9
_MINIMUM_PROTECTED_SECRET_LENGTH = 8
_BASE64_CANDIDATE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{64,}={0,2}"
    r"(?![A-Za-z0-9+/_=-])"
)


class PromptLeakReason(StrEnum):
    """可审计但不包含原文的拒绝原因。"""

    INVISIBLE_CONTROL = "INVISIBLE_CONTROL"
    PROMPT_CONTROL_LANGUAGE = "PROMPT_CONTROL_LANGUAGE"
    PROMPT_FRAGMENT_OVERLAP = "PROMPT_FRAGMENT_OVERLAP"
    PROMPT_NGRAM_OVERLAP = "PROMPT_NGRAM_OVERLAP"
    CREDENTIAL_PATTERN = "CREDENTIAL_PATTERN"
    PROTECTED_SECRET = "PROTECTED_SECRET"
    RAW_HTML = "RAW_HTML"
    DANGEROUS_URL = "DANGEROUS_URL"


class UnsafeModelOutputError(ValueError):
    """稳定、无原文的模型输出拒绝异常。"""

    def __init__(self, reason: PromptLeakReason) -> None:
        super().__init__("model output failed deterministic disclosure safety validation")
        self.reason = reason


def _normalizeForComparison(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    withoutFormatting = "".join(
        character
        for character in normalized
        if character not in _ZERO_WIDTH_AND_DIRECTIONAL and unicodedata.category(character) != "Cf"
    )
    return " ".join(withoutFormatting.casefold().split())


def _withoutPublicPhrases(value: str) -> str:
    normalized = value
    for phrase in _PUBLIC_OUTPUT_PHRASES:
        normalized = normalized.replace(phrase, " ")
    return " ".join(normalized.split())


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _longFragmentDigests(value: str) -> frozenset[bytes]:
    if len(value) < _LONG_FRAGMENT_LENGTH:
        return frozenset()
    return frozenset(
        _digest(value[index : index + _LONG_FRAGMENT_LENGTH])
        for index in range(len(value) - _LONG_FRAGMENT_LENGTH + 1)
    )


def _isRareNgram(words: tuple[str, ...]) -> bool:
    rareWords = [
        word
        for word in words
        if word not in _COMMON_NGRAM_WORDS
        and (len(word) >= 8 or any(character.isdigit() for character in word))
    ]
    return len(rareWords) >= 2 or any(len(word) >= 14 for word in rareWords)


def _rareNgramDigests(value: str) -> frozenset[bytes]:
    words = tuple(_WORD_PATTERN.findall(value))
    if len(words) < _RARE_NGRAM_LENGTH:
        return frozenset()
    digests: set[bytes] = set()
    for index in range(len(words) - _RARE_NGRAM_LENGTH + 1):
        ngram = words[index : index + _RARE_NGRAM_LENGTH]
        if _isRareNgram(ngram):
            digests.add(_digest("\x1f".join(ngram)))
    return frozenset(digests)


def _iterTextValues(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, BaseModel):
        yield from _iterTextValues(value.model_dump(mode="python"))
        return
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _iterTextValues(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            yield from _iterTextValues(item)


def _iterDecodedBase64Texts(value: str) -> Iterable[str]:
    """只解码足够长且可严格解析的 Base64 文本，避免把普通短单词误判为载荷。"""

    decodedValues: set[bytes] = set()
    for match in _BASE64_CANDIDATE_PATTERN.finditer(value):
        token = match.group(0)
        unpadded = token.rstrip("=")
        if len(unpadded) % 4 == 1:
            continue
        padded = unpadded + ("=" * (-len(unpadded) % 4))
        for altchars in (None, b"-_"):
            try:
                decoded = base64.b64decode(
                    padded.encode("ascii"),
                    altchars=altchars,
                    validate=True,
                )
                decodedText = decoded.decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                continue
            if decoded and decoded not in decodedValues:
                decodedValues.add(decoded)
                yield decodedText


def _protectedSecretVariants(secret: str) -> frozenset[str]:
    """按请求即时生成常见编码；调用结束后不在全局校验器中保留密钥。"""

    if len(secret) < _MINIMUM_PROTECTED_SECRET_LENGTH:
        return frozenset()
    encoded = secret.encode("utf-8")
    standardBase64 = base64.b64encode(encoded).decode("ascii")
    urlSafeBase64 = base64.urlsafe_b64encode(encoded).decode("ascii")
    hexadecimal = encoded.hex()
    return frozenset(
        {
            secret,
            f"Bearer {secret}",
            standardBase64,
            standardBase64.rstrip("="),
            urlSafeBase64,
            urlSafeBase64.rstrip("="),
            hexadecimal,
            hexadecimal.upper(),
        }
    )


class PromptLeakValidator:
    """比较系统提示词与模型自由文本，并执行主动内容/凭据边界。"""

    __slots__ = ("_longFragmentDigests", "_rareNgramDigests")

    def __init__(self, systemPrompts: Iterable[str]) -> None:
        prompts = tuple(systemPrompts)
        if not prompts or any(not prompt.strip() for prompt in prompts):
            raise ValueError("systemPrompts must contain non-blank prompts")
        normalized = _withoutPublicPhrases(_normalizeForComparison("\n".join(prompts)))
        self._longFragmentDigests = _longFragmentDigests(normalized)
        self._rareNgramDigests = _rareNgramDigests(normalized)

    @staticmethod
    def normalizeForComparison(value: str) -> str:
        """供安全测试和后续工作流复用的 NFKC/零宽字符清理。"""

        return _normalizeForComparison(value)

    def validateText(self, value: str) -> None:
        self._validatePlainText(value)
        for decodedText in _iterDecodedBase64Texts(value):
            self._validatePlainText(decodedText)

    def _validatePlainText(self, value: str) -> None:
        if any(
            character in _ZERO_WIDTH_AND_DIRECTIONAL or unicodedata.category(character) == "Cf"
            for character in value
        ):
            # 即使清理后文本看似安全，也不把不可见控制字符带到 Markdown/DOM。
            raise UnsafeModelOutputError(PromptLeakReason.INVISIBLE_CONTROL)

        normalized = _normalizeForComparison(value)
        if _CONTROL_DISCLOSURE_PATTERN.search(normalized):
            raise UnsafeModelOutputError(PromptLeakReason.PROMPT_CONTROL_LANGUAGE)
        if any(pattern.search(normalized) for pattern in _CREDENTIAL_PATTERNS):
            raise UnsafeModelOutputError(PromptLeakReason.CREDENTIAL_PATTERN)
        if _RAW_HTML_PATTERN.search(normalized):
            raise UnsafeModelOutputError(PromptLeakReason.RAW_HTML)
        if _DANGEROUS_URL_PATTERN.search(normalized):
            raise UnsafeModelOutputError(PromptLeakReason.DANGEROUS_URL)

        comparisonText = _withoutPublicPhrases(normalized)
        if self._containsLongPromptFragment(comparisonText):
            raise UnsafeModelOutputError(PromptLeakReason.PROMPT_FRAGMENT_OVERLAP)
        if self._rareNgramDigests & _rareNgramDigests(comparisonText):
            raise UnsafeModelOutputError(PromptLeakReason.PROMPT_NGRAM_OVERLAP)

    def validateModelOutput(
        self,
        value: Any,
        *,
        protectedSecrets: Iterable[str] = (),
    ) -> None:
        """检查结构化结果中的全部字符串；异常绝不附带原始字段。"""

        texts = tuple(_iterTextValues(value))
        secretVariants = frozenset(
            variant
            for secret in protectedSecrets
            if secret
            for variant in _protectedSecretVariants(secret)
        )
        if secretVariants:
            # 同时检查字段拼接，避免模型把密钥拆到相邻结构化字段以绕过单字段校验。
            searchableValues = (*texts, "".join(texts))
            if any(variant in text for text in searchableValues for variant in secretVariants):
                raise UnsafeModelOutputError(PromptLeakReason.PROTECTED_SECRET)

        for text in texts:
            self.validateText(text)

    def _containsLongPromptFragment(self, value: str) -> bool:
        if len(value) < _LONG_FRAGMENT_LENGTH:
            return False
        # 提示词与输出都逐字符建立/扫描摘要，确保任意起点的连续引用都能命中；
        # 只保存摘要，避免校验器异常意外回显提示词片段。
        for index in range(len(value) - _LONG_FRAGMENT_LENGTH + 1):
            if _digest(value[index : index + _LONG_FRAGMENT_LENGTH]) in self._longFragmentDigests:
                return True
        return False
