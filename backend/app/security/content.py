"""Event Pack 上传内容的无状态、确定性安全扫描。

扫描器故意不调用网络或模型，也不把命中的原文放进返回对象。这样即使上层把扫描结果
写入日志，API Key、凭据和个人信息也不会通过 ``redactedExcerpt`` 二次泄漏。
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

SupportedLocale = Literal["en", "zh", "zh-CN", "zh-cn"]

DEFAULT_OFFICIAL_HOST_ALLOWLIST = (
    "federalreserve.gov",
    "nasdaq.com",
    "sec.gov",
    "spacex.com",
)

MAX_SCAN_CHARACTERS = 100_000
MAX_RETURNED_FINDINGS = 256
MAX_METADATA_FIELDS = 1_024

_SAFE_METADATA_FIELD_NAMES = {
    "authors",
    "description",
    "isOfficial",
    "knownAt",
    "language",
    "name",
    "publishedAt",
    "publisher",
    "sourceId",
    "sourceType",
    "sourceUrl",
    "source_url",
    "summary",
    "tags",
    "title",
    "titleZh",
    "url",
    "value",
}


class FindingSeverity(StrEnum):
    """发现项的严重度；HIGH 及以上必须阻断。"""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ContentPolicyDecision(StrEnum):
    """上传策略结果。"""

    BLOCK = "BLOCK"
    REVIEW = "REVIEW"
    ALLOW = "ALLOW"


class SourceReviewLabel(StrEnum):
    """URL 来源审查标签；该标签永远不会降低正文扫描的策略结果。"""

    OFFICIAL_HOST_ALLOWLIST_MATCH = "OFFICIAL_HOST_ALLOWLIST_MATCH"
    HOST_NOT_ALLOWLISTED = "HOST_NOT_ALLOWLISTED"
    INVALID_OR_INSECURE_URL = "INVALID_OR_INSECURE_URL"
    URL_MISSING = "URL_MISSING"


@dataclass(frozen=True, slots=True)
class ContentFinding:
    """可安全记录的单个发现项。"""

    code: str
    severity: FindingSeverity
    field: str
    offset: int
    redactedExcerpt: str
    recommendedAction: str

    def toDict(self) -> dict[str, str | int]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "field": self.field,
            "offset": self.offset,
            "redactedExcerpt": self.redactedExcerpt,
            "recommendedAction": self.recommendedAction,
        }


@dataclass(frozen=True, slots=True)
class ContentScanResult:
    """一次 Event Pack 内容扫描的完整结果。"""

    decision: ContentPolicyDecision
    findings: tuple[ContentFinding, ...]
    sourceReviewLabel: SourceReviewLabel
    officialHost: str | None

    @property
    def isAllowed(self) -> bool:
        return self.decision is ContentPolicyDecision.ALLOW

    def toDict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "findings": [finding.toDict() for finding in self.findings],
            "sourceReviewLabel": self.sourceReviewLabel.value,
            "officialHost": self.officialHost,
        }


@dataclass(frozen=True, slots=True)
class _TextView:
    original: str
    normalized: str
    normalizedOffsets: tuple[int, ...]
    compact: str
    compactOffsets: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _RawFinding:
    code: str
    severity: FindingSeverity
    field: str
    start: int
    end: int
    actionKey: str


@dataclass(frozen=True, slots=True)
class _PatternSpec:
    code: str
    severity: FindingSeverity
    pattern: re.Pattern[str]
    actionKey: str
    viewName: Literal["original", "normalized", "compact"] = "normalized"
    captureGroup: int = 0


_ACTION_TEXT: dict[str, dict[str, str]] = {
    "binary": {
        "en": "Reject the upload and provide valid UTF-8 plain text only.",
        "zh": "拒绝该上传；仅提交有效 UTF-8 纯文本。",
    },
    "control": {
        "en": "Remove control, bidirectional, and invisible formatting characters, then rescan.",
        "zh": "删除控制字符、双向控制字符和不可见格式字符后重新扫描。",
    },
    "script": {
        "en": (
            "Reject executable or active script content; retain a plain-text factual summary only."
        ),
        "zh": "拒绝可执行或活动脚本内容；仅保留纯文本事实摘要。",
    },
    "codeReview": {
        "en": "Quarantine the code-like text and require a human security review before use.",
        "zh": "隔离疑似代码文本，并在使用前进行人工安全审查。",
    },
    "promptInjection": {
        "en": "Reject or remove instruction-like text before sending any source to an LLM.",
        "zh": "在把来源交给任何 LLM 前，拒绝或删除指令式文本。",
    },
    "privilege": {
        "en": "Reject the privilege-escalation request and review the source provenance.",
        "zh": "拒绝权限提升请求，并复核来源链。",
    },
    "secret": {
        "en": "Remove the credential, rotate it immediately, and upload a sanitized copy.",
        "zh": "删除凭据、立即轮换，并上传经过清理的副本。",
    },
    "highRiskPii": {
        "en": (
            "Reject the upload, remove high-risk personal data, and obtain approval "
            "before retrying."
        ),
        "zh": "拒绝上传，删除高风险个人信息，并在获批后重试。",
    },
    "contactPii": {
        "en": "Redact the contact information and require human review before processing.",
        "zh": "遮盖联系信息，并在处理前进行人工审查。",
    },
    "size": {
        "en": "Reject the oversized field and submit a bounded plain-text excerpt.",
        "zh": "拒绝超长字段，并提交长度受限的纯文本摘录。",
    },
    "findingLimit": {
        "en": (
            "Reject the upload because the finding limit was exceeded; sanitize it offline first."
        ),
        "zh": "发现项数量超限，拒绝上传；请先离线清理内容。",
    },
    "type": {
        "en": "Reject the unsupported value and submit a string or UTF-8 byte sequence.",
        "zh": "拒绝不支持的值；请提交字符串或 UTF-8 字节序列。",
    },
}


_CONFUSABLE_TRANSLATION = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "і": "i",
        "ј": "j",
        "ο": "o",
        "р": "p",
        "с": "c",
        "х": "x",
        "у": "y",
        "Α": "a",
        "Β": "b",
        "Ε": "e",
        "Ι": "i",
        "Κ": "k",
        "Μ": "m",
        "Ν": "n",
        "Ο": "o",
        "Ρ": "p",
        "Τ": "t",
        "Χ": "x",
    }
)


_SENSITIVE_PATTERNS = (
    _PatternSpec(
        "PRIVATE_KEY_MATERIAL",
        FindingSeverity.CRITICAL,
        re.compile(r"-----BEGIN(?: [A-Z0-9]+)? PRIVATE KEY-----", re.IGNORECASE),
        "secret",
        "original",
    ),
    _PatternSpec(
        "API_KEY_OR_TOKEN",
        FindingSeverity.CRITICAL,
        re.compile(
            r"(?:api[\s_-]*(?:key|密钥)|access[\s_-]*token|auth[\s_-]*token|"
            r"authorization|访问令牌|鉴权令牌|密钥)"
            r"\s*(?:(?:is|是)\s*[:=]?|[:=])\s*"
            r"(?:bearer\s+)?[\"']?([a-z0-9_./+=-]{8,256})",
            re.IGNORECASE,
        ),
        "secret",
        captureGroup=1,
    ),
    _PatternSpec(
        "API_KEY_OR_TOKEN",
        FindingSeverity.CRITICAL,
        re.compile(
            r"(?<![a-z0-9])(?:sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|"
            r"akia[0-9a-z]{16}|aiza[0-9a-z_-]{30,}|xox[baprs]-[a-z0-9-]{16,}|"
            r"eyj[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}\.[a-z0-9_-]{8,}|"
            r"[a-z0-9_-]{16,64}\.[a-z0-9_-]{20,128})(?![a-z0-9])",
            re.IGNORECASE,
        ),
        "secret",
    ),
    _PatternSpec(
        "PASSWORD_VALUE",
        FindingSeverity.CRITICAL,
        re.compile(
            r"(?:password|passwd|pwd|密码|口令)\s*"
            r"(?:(?:is|是)\s*[:=]?|[:=])\s*[\"']?([^\s\"';&]{4,128})",
            re.IGNORECASE,
        ),
        "secret",
        captureGroup=1,
    ),
    _PatternSpec(
        "URL_EMBEDDED_CREDENTIAL",
        FindingSeverity.CRITICAL,
        re.compile(r"https?://[^/@\s:]+:([^/@\s]+)@", re.IGNORECASE),
        "secret",
        "original",
        1,
    ),
    _PatternSpec(
        "EMAIL_ADDRESS",
        FindingSeverity.MEDIUM,
        re.compile(
            r"(?<![a-z0-9._%+-])[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,63}(?![a-z0-9-])", re.IGNORECASE
        ),
        "contactPii",
    ),
    _PatternSpec(
        "US_SOCIAL_SECURITY_NUMBER",
        FindingSeverity.HIGH,
        # 无上下文的连续九位数字常见于 UUID、工件 ID 和财经数据，不能一概
        # 视为 SSN。这里要求规范分隔符，并排除 SSA 明确不会分配的段值。
        re.compile(
            r"(?<![0-9])(?!(?:000|666|9[0-9]{2})(?:[- ]))"
            r"[0-8][0-9]{2}(?P<ssn_sep>[- ])"
            r"(?!00)[0-9]{2}(?P=ssn_sep)(?!0000)[0-9]{4}(?![0-9])"
        ),
        "highRiskPii",
    ),
    _PatternSpec(
        "US_SOCIAL_SECURITY_NUMBER",
        FindingSeverity.HIGH,
        # 紧凑九位形式只在明确的 SSN 上下文后识别，兼顾保护与误报控制。
        re.compile(
            r"(?:\bssn\b|\bsocial\s+security(?:\s+number)?\b)"
            r"\s*(?:is\s*)?[:#=]?\s*"
            r"((?!(?:000|666|9[0-9]{2}))[0-8][0-9]{2}"
            r"(?!00)[0-9]{2}(?!0000)[0-9]{4})(?![0-9])",
            re.IGNORECASE,
        ),
        "highRiskPii",
        captureGroup=1,
    ),
    _PatternSpec(
        "PHONE_NUMBER",
        FindingSeverity.MEDIUM,
        re.compile(
            r"(?<![0-9])(?:\+?1[ .-]?)?(?:\([2-9][0-9]{2}\)|[2-9][0-9]{2})"
            r"[ .-]?[0-9]{3}[ .-]?[0-9]{4}(?![0-9])|"
            r"(?<![0-9])(?:\+?86[ .-]?)?1[3-9][0-9][ .-]?[0-9]{4}[ .-]?[0-9]{4}(?![0-9])"
        ),
        "contactPii",
    ),
)


_ACTIVE_CONTENT_PATTERNS = (
    _PatternSpec(
        "ACTIVE_SCRIPT_CONTENT",
        FindingSeverity.CRITICAL,
        re.compile(
            r"<\s*/?\s*(?:script|iframe|object|embed)\b|"
            r"(?:javascript|vbscript)\s*:|"
            r"\bon(?:error|load|click|focus|mouseover)\s*=|<\?php\b",
            re.IGNORECASE,
        ),
        "script",
    ),
    _PatternSpec(
        "SHELL_OR_COMMAND_PAYLOAD",
        FindingSeverity.HIGH,
        re.compile(
            r"^\s*#!\s*/(?:usr/)?bin/(?:sh|bash|zsh|python)|"
            r"\bpowershell(?:\.exe)?\s+(?:-[a-z]+\s+)*(?:-enc|-encodedcommand)\b|"
            r"\bcmd(?:\.exe)?\s*/c\b|\brm\s+-rf\s+(?:/|~)|"
            r"\b(?:curl|wget)\b[^\n|]{0,200}\|\s*(?:sh|bash)\b",
            re.IGNORECASE | re.MULTILINE,
        ),
        "script",
        "original",
    ),
    _PatternSpec(
        "EXECUTABLE_CODE_LIKE_CONTENT",
        FindingSeverity.MEDIUM,
        re.compile(
            r"\b(?:eval|exec|compile)\s*\(|\b(?:os\.system|subprocess\.(?:run|call|popen))\s*\(",
            re.IGNORECASE,
        ),
        "codeReview",
    ),
)


_PROMPT_INJECTION_PATTERNS = (
    _PatternSpec(
        "PROMPT_INJECTION_INSTRUCTION_OVERRIDE",
        FindingSeverity.HIGH,
        re.compile(
            r"(?:ignore|disregard|forget|override)(?:all|any|the)?"
            r"(?:previous|prior|above|earlier|existing)(?:instructions?|rules?|prompts?|directives?)|"
            r"(?:donot|never)(?:follow|obey)(?:the)?(?:previous|prior|above)"
            r"(?:instructions?|rules?|prompts?)|"
            r"(?:忽略|无视|忘记|覆盖)(?:你|模型|助手)?"
            r"(?:(?:所有)?(?:之前|以上|上面|此前|先前|前面)|所有)?"
            r"(?:收到|获得)?(?:的)?(?:所有)?(?:指令|提示词|提示|规则|要求)",
            re.IGNORECASE,
        ),
        "promptInjection",
        "compact",
    ),
    _PatternSpec(
        "PROMPT_INJECTION_SECRET_EXFILTRATION",
        FindingSeverity.HIGH,
        re.compile(
            r"(?:reveal|print|show|expose|return)(?:the)?"
            r"(?:systemprompt|developerprompt|developermessage|hiddeninstructions?|apikey|secrets?)|"
            r"(?:泄露|显示|输出|返回)(?:系统提示词|开发者消息|隐藏指令|密钥|秘密)",
            re.IGNORECASE,
        ),
        "promptInjection",
        "compact",
    ),
    _PatternSpec(
        "PROMPT_INJECTION_SAFETY_BYPASS",
        FindingSeverity.HIGH,
        re.compile(
            r"(?:bypass|disable|evade|circumvent)(?:the)?"
            r"(?:safety|guardrails?|permissions?|authorization|accesscontrol|contentfilters?)|"
            r"(?:jailbreak|danmode)|"
            r"(?:绕过|关闭|规避)(?:安全|权限|授权|审核|限制|内容过滤)",
            re.IGNORECASE,
        ),
        "promptInjection",
        "compact",
    ),
    _PatternSpec(
        "PRIVILEGE_ESCALATION_REQUEST",
        FindingSeverity.HIGH,
        re.compile(
            r"(?:actas|pretendtobe|youarenow)(?:the)?(?:system|developer|root|administrator|admin)|"
            r"(?:grant|give)(?:me|us)?(?:root|admin|administrator)(?:access|permissions?|privileges?)|"
            r"(?:elevate|escalate)(?:my|our)?privileges?|runasadministrator|enablerootaccess|"
            r"(?:你现在是|扮演|假装是)(?:系统|开发者|根用户|管理员)|"
            r"(?:授予|提升|获取)(?:我的|我们的)?(?:管理员|根用户|系统)?(?:权限|特权)|"
            r"给(?:我|我们)(?:管理员|根用户|系统)?权限|越权",
            re.IGNORECASE,
        ),
        "privilege",
        "compact",
    ),
)


_CARD_CANDIDATE_PATTERN = re.compile(r"(?<![0-9])(?:[0-9][ -]?){12,18}[0-9](?![0-9])")
_BIDI_CONTROL_CODEPOINTS = {
    0x061C,
    0x200E,
    0x200F,
    0x202A,
    0x202B,
    0x202C,
    0x202D,
    0x202E,
    0x2066,
    0x2067,
    0x2068,
    0x2069,
}
_SEVERITY_RANK = {
    FindingSeverity.CRITICAL: 0,
    FindingSeverity.HIGH: 1,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.LOW: 3,
}


def scanEventPackContent(
    rawText: str | bytes,
    sourceMetadata: Mapping[str, object] | None = None,
    *,
    officialHostAllowlist: Iterable[str] = DEFAULT_OFFICIAL_HOST_ALLOWLIST,
    locale: SupportedLocale = "en",
) -> ContentScanResult:
    """扫描正文和所有字符串来源元数据，并返回 fail-closed 策略结果。

    allowlist 只决定 ``sourceReviewLabel``，不会过滤发现项，也不会把 BLOCK 降级。
    """

    language = _normalizeLocale(locale)
    rawFindings = _scanValue(rawText, "rawText")
    metadata = {} if sourceMetadata is None else sourceMetadata
    if not isinstance(metadata, Mapping):
        rawFindings.append(
            _RawFinding(
                code="UNSUPPORTED_METADATA_TYPE",
                severity=FindingSeverity.CRITICAL,
                field="sourceMetadata",
                start=0,
                end=0,
                actionKey="type",
            )
        )
        metadata = {}
    else:
        flattenedMetadata, metadataFindings = _flattenMetadata(metadata)
        rawFindings.extend(metadataFindings)
        for field, value in flattenedMetadata:
            rawFindings.extend(_scanValue(value, field))

    sourceReviewLabel, officialHost = _reviewSourceUrl(metadata, officialHostAllowlist)
    findings = _materializeFindings(rawFindings, language)
    return ContentScanResult(
        decision=evaluateContentPolicy(findings),
        findings=findings,
        sourceReviewLabel=sourceReviewLabel,
        officialHost=officialHost,
    )


def scanTextContent(
    text: str | bytes,
    *,
    field: str = "rawText",
    locale: SupportedLocale = "en",
) -> ContentScanResult:
    """扫描单一文本字段；适合在模型调用前复用相同安全策略。"""

    language = _normalizeLocale(locale)
    rawFindings = _scanValue(text, _safeFieldName(field))
    findings = _materializeFindings(rawFindings, language)
    return ContentScanResult(
        decision=evaluateContentPolicy(findings),
        findings=findings,
        sourceReviewLabel=SourceReviewLabel.URL_MISSING,
        officialHost=None,
    )


def redactReviewableText(text: str) -> str:
    """遮盖 MEDIUM/LOW 命中；HIGH/CRITICAL 内容必须由调用方拒绝。"""

    rawFindings = _deduplicateRawFindings(_scanValue(text, "rawText"))
    if evaluateContentPolicy(rawFindings) is ContentPolicyDecision.BLOCK:
        raise ValueError("Blocked content cannot be sanitized through acknowledgement.")
    ordered = sorted(
        (
            finding
            for finding in rawFindings
            if finding.severity in {FindingSeverity.MEDIUM, FindingSeverity.LOW}
        ),
        key=lambda finding: (finding.start, finding.end),
        reverse=True,
    )
    sanitized = text
    replacedStart = len(text) + 1
    for finding in ordered:
        if finding.end > replacedStart:
            continue
        start = max(0, min(finding.start, len(sanitized)))
        end = max(start, min(finding.end, len(sanitized)))
        sanitized = sanitized[:start] + f"[REDACTED:{finding.code}]" + sanitized[end:]
        replacedStart = finding.start
    return sanitized


def evaluateContentPolicy(
    findings: Iterable[ContentFinding | _RawFinding],
) -> ContentPolicyDecision:
    """按最严重发现项计算策略；未知严重度无法进入类型化 API。"""

    severities = {finding.severity for finding in findings}
    if severities & {FindingSeverity.CRITICAL, FindingSeverity.HIGH}:
        return ContentPolicyDecision.BLOCK
    if severities:
        return ContentPolicyDecision.REVIEW
    return ContentPolicyDecision.ALLOW


def _scanValue(value: object, field: str) -> list[_RawFinding]:
    findings: list[_RawFinding] = []
    if isinstance(value, bytes):
        findings.extend(_scanBinarySignatures(value, field))
        try:
            text = value.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            findings.append(
                _RawFinding(
                    code="BINARY_OR_INVALID_UTF8",
                    severity=FindingSeverity.CRITICAL,
                    field=field,
                    start=error.start,
                    end=max(error.end, error.start + 1),
                    actionKey="binary",
                )
            )
            text = value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        text = value
    else:
        return [
            _RawFinding(
                code="UNSUPPORTED_CONTENT_TYPE",
                severity=FindingSeverity.CRITICAL,
                field=field,
                start=0,
                end=0,
                actionKey="type",
            )
        ]

    if len(text) > MAX_SCAN_CHARACTERS:
        findings.append(
            _RawFinding(
                code="CONTENT_SIZE_LIMIT_EXCEEDED",
                severity=FindingSeverity.CRITICAL,
                field=field,
                start=MAX_SCAN_CHARACTERS,
                end=len(text),
                actionKey="size",
            )
        )
        text = text[:MAX_SCAN_CHARACTERS]

    view = _buildTextView(text)
    findings.extend(_scanUnicodeControls(text, field))
    for spec in (*_SENSITIVE_PATTERNS, *_ACTIVE_CONTENT_PATTERNS, *_PROMPT_INJECTION_PATTERNS):
        findings.extend(_findPattern(spec, view, field))
    findings.extend(_findPaymentCards(view, field))
    return _deduplicateRawFindings(findings)


def _scanBinarySignatures(value: bytes, field: str) -> list[_RawFinding]:
    signatures = (
        (b"\x7fELF", "ELF"),
        (b"MZ", "PE"),
        (b"\xfe\xed\xfa\xce", "MACH_O"),
        (b"\xfe\xed\xfa\xcf", "MACH_O"),
        (b"\xcf\xfa\xed\xfe", "MACH_O"),
        (b"\xca\xfe\xba\xbe", "MACH_O_FAT"),
    )
    for signature, _name in signatures:
        if value.startswith(signature):
            return [
                _RawFinding(
                    code="EXECUTABLE_BINARY_SIGNATURE",
                    severity=FindingSeverity.CRITICAL,
                    field=field,
                    start=0,
                    end=len(signature),
                    actionKey="binary",
                )
            ]
    return []


def _scanUnicodeControls(text: str, field: str) -> list[_RawFinding]:
    findings: list[_RawFinding] = []
    index = 0
    while index < len(text):
        char = text[index]
        codepoint = ord(char)
        category = unicodedata.category(char)
        if char == "\x00":
            code = "NUL_BYTE"
            severity = FindingSeverity.CRITICAL
            actionKey = "binary"
        elif codepoint in _BIDI_CONTROL_CODEPOINTS:
            code = "BIDIRECTIONAL_UNICODE_CONTROL"
            severity = FindingSeverity.HIGH
            actionKey = "control"
        elif category == "Cc" and char not in {"\t", "\n", "\r"}:
            code = "CONTROL_CHARACTER"
            severity = FindingSeverity.MEDIUM
            actionKey = "control"
        elif category == "Cf":
            code = "INVISIBLE_UNICODE_FORMATTING"
            severity = FindingSeverity.MEDIUM
            actionKey = "control"
        else:
            index += 1
            continue

        end = index + 1
        while end < len(text):
            nextChar = text[end]
            nextCodepoint = ord(nextChar)
            nextCategory = unicodedata.category(nextChar)
            sameCategory = (
                code == "NUL_BYTE"
                and nextChar == "\x00"
                or code == "BIDIRECTIONAL_UNICODE_CONTROL"
                and nextCodepoint in _BIDI_CONTROL_CODEPOINTS
                or code == "CONTROL_CHARACTER"
                and nextCategory == "Cc"
                and nextChar not in {"\t", "\n", "\r", "\x00"}
                or code == "INVISIBLE_UNICODE_FORMATTING"
                and nextCategory == "Cf"
                and nextCodepoint not in _BIDI_CONTROL_CODEPOINTS
            )
            if not sameCategory:
                break
            end += 1
        findings.append(_RawFinding(code, severity, field, index, end, actionKey))
        index = end
    return findings


def _buildTextView(text: str) -> _TextView:
    normalizedCharacters: list[str] = []
    normalizedOffsets: list[int] = []
    for offset, char in enumerate(text):
        expanded = unicodedata.normalize("NFKC", char).casefold().translate(_CONFUSABLE_TRANSLATION)
        for normalizedChar in expanded:
            if normalizedChar.isdigit():
                try:
                    normalizedChar = str(unicodedata.digit(normalizedChar))
                except (TypeError, ValueError):
                    pass
            normalizedCharacters.append(normalizedChar)
            normalizedOffsets.append(offset)

    normalized = "".join(normalizedCharacters)
    compactCharacters: list[str] = []
    compactOffsets: list[int] = []
    for char, offset in zip(normalized, normalizedOffsets, strict=True):
        category = unicodedata.category(char)
        if char.isalnum() and category not in {"Cf", "Cc"}:
            compactCharacters.append(char)
            compactOffsets.append(offset)
    return _TextView(
        original=text,
        normalized=normalized,
        normalizedOffsets=tuple(normalizedOffsets),
        compact="".join(compactCharacters),
        compactOffsets=tuple(compactOffsets),
    )


def _findPattern(spec: _PatternSpec, view: _TextView, field: str) -> list[_RawFinding]:
    if spec.viewName == "original":
        searchable = view.original
        offsets: tuple[int, ...] | None = None
    elif spec.viewName == "compact":
        searchable = view.compact
        offsets = view.compactOffsets
    else:
        searchable = view.normalized
        offsets = view.normalizedOffsets

    findings: list[_RawFinding] = []
    for match in spec.pattern.finditer(searchable):
        start, end = match.span(spec.captureGroup)
        originalStart, originalEnd = _mapSpanToOriginal(start, end, offsets)
        findings.append(
            _RawFinding(
                code=spec.code,
                severity=spec.severity,
                field=field,
                start=originalStart,
                end=originalEnd,
                actionKey=spec.actionKey,
            )
        )
    return findings


def _findPaymentCards(view: _TextView, field: str) -> list[_RawFinding]:
    findings: list[_RawFinding] = []
    for match in _CARD_CANDIDATE_PATTERN.finditer(view.normalized):
        digits = "".join(char for char in match.group(0) if char.isdigit())
        if 13 <= len(digits) <= 19 and _passesLuhn(digits):
            start, end = _mapSpanToOriginal(match.start(), match.end(), view.normalizedOffsets)
            findings.append(
                _RawFinding(
                    code="PAYMENT_CARD_NUMBER",
                    severity=FindingSeverity.HIGH,
                    field=field,
                    start=start,
                    end=end,
                    actionKey="highRiskPii",
                )
            )
    return findings


def _passesLuhn(digits: str) -> bool:
    checksum = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        value = int(character)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        checksum += value
    return checksum % 10 == 0


def _mapSpanToOriginal(
    start: int,
    end: int,
    offsets: tuple[int, ...] | None,
) -> tuple[int, int]:
    if offsets is None:
        return start, end
    if start >= len(offsets):
        return (offsets[-1] + 1, offsets[-1] + 1) if offsets else (0, 0)
    if end <= start:
        return offsets[start], offsets[start]
    return offsets[start], offsets[min(end - 1, len(offsets) - 1)] + 1


def _deduplicateRawFindings(findings: Iterable[_RawFinding]) -> list[_RawFinding]:
    unique: dict[tuple[str, str, int, int], _RawFinding] = {}
    for finding in findings:
        key = (finding.field, finding.code, finding.start, finding.end)
        unique.setdefault(key, finding)
    return list(unique.values())


def _materializeFindings(
    rawFindings: Sequence[_RawFinding],
    language: Literal["en", "zh"],
) -> tuple[ContentFinding, ...]:
    ordered = sorted(
        rawFindings,
        key=lambda finding: (
            0 if finding.field == "rawText" else 1,
            finding.field,
            finding.start,
            _SEVERITY_RANK[finding.severity],
            finding.code,
            finding.end,
        ),
    )
    if len(ordered) > MAX_RETURNED_FINDINGS:
        firstOmitted = ordered[MAX_RETURNED_FINDINGS - 1]
        ordered = [
            *ordered[: MAX_RETURNED_FINDINGS - 1],
            _RawFinding(
                code="FINDING_LIMIT_EXCEEDED",
                severity=FindingSeverity.CRITICAL,
                field=firstOmitted.field,
                start=firstOmitted.start,
                end=firstOmitted.end,
                actionKey="findingLimit",
            ),
        ]

    return tuple(
        ContentFinding(
            code=finding.code,
            severity=finding.severity,
            field=finding.field,
            offset=max(0, finding.start),
            # 返回值只说明发现项类型和位置，从根本上避免任何原文、凭据或 PII 回显。
            redactedExcerpt=f"[REDACTED:{finding.code}@{max(0, finding.start)}]",
            recommendedAction=_ACTION_TEXT[finding.actionKey][language],
        )
        for finding in ordered
    )


def _flattenMetadata(
    metadata: Mapping[str, object],
) -> tuple[list[tuple[str, str | bytes]], list[_RawFinding]]:
    flattened: list[tuple[str, str | bytes]] = []
    findings: list[_RawFinding] = []
    seenContainers: set[int] = set()

    def addStructureFinding(code: str, path: str) -> None:
        if any(finding.code == code and finding.field == path for finding in findings):
            return
        findings.append(
            _RawFinding(
                code=code,
                severity=FindingSeverity.HIGH,
                field=path,
                start=0,
                end=0,
                actionKey="size",
            )
        )

    def visit(value: object, path: str, depth: int) -> None:
        if isinstance(value, (str, bytes)):
            if len(flattened) >= MAX_METADATA_FIELDS:
                addStructureFinding("METADATA_FIELD_LIMIT_EXCEEDED", "sourceMetadata")
                return
            flattened.append((path, value))
            return
        if depth >= 8:
            if isinstance(value, (Mapping, Sequence)):
                addStructureFinding("METADATA_DEPTH_LIMIT_EXCEEDED", path)
            return
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in seenContainers:
                addStructureFinding("METADATA_CYCLE_DETECTED", path)
                return
            seenContainers.add(identity)
            entries = sorted(value.items(), key=lambda entry: _stableMetadataKey(entry[0]))
            if len(entries) > 256:
                addStructureFinding("METADATA_ENTRY_LIMIT_EXCEEDED", path)
            for key, nestedValue in entries[:256]:
                segment = _safeFieldSegment(key)
                visit(nestedValue, f"{path}.{segment}", depth + 1)
            return
        if isinstance(value, Sequence):
            identity = id(value)
            if identity in seenContainers:
                addStructureFinding("METADATA_CYCLE_DETECTED", path)
                return
            seenContainers.add(identity)
            if len(value) > 256:
                addStructureFinding("METADATA_ENTRY_LIMIT_EXCEEDED", path)
            for index, nestedValue in enumerate(value[:256]):
                visit(nestedValue, f"{path}[{index}]", depth + 1)

    visit(metadata, "sourceMetadata", 0)
    return flattened, findings


def _stableMetadataKey(key: object) -> tuple[str, str]:
    if isinstance(key, str):
        return ("str", key)
    digest = hashlib.sha256(f"{type(key).__name__}:{key!r}".encode()).hexdigest()
    return (type(key).__name__, digest)


def _safeFieldSegment(key: object) -> str:
    if isinstance(key, str) and key in _SAFE_METADATA_FIELD_NAMES:
        return key
    digest = hashlib.sha256(f"{type(key).__name__}:{key!s}".encode()).hexdigest()[:12]
    return f"field-{digest}"


def _safeFieldName(field: str) -> str:
    if field == "rawText":
        return field
    return f"field-{hashlib.sha256(field.encode()).hexdigest()[:12]}"


def _reviewSourceUrl(
    metadata: Mapping[str, object],
    officialHostAllowlist: Iterable[str],
) -> tuple[SourceReviewLabel, str | None]:
    sourceUrl = _findSourceUrl(metadata)
    if sourceUrl is None:
        return SourceReviewLabel.URL_MISSING, None
    try:
        parsed = urlsplit(sourceUrl)
        host = parsed.hostname
        if (
            parsed.scheme.lower() != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
        ):
            return SourceReviewLabel.INVALID_OR_INSECURE_URL, None
        normalizedHost = host.rstrip(".").encode("idna").decode("ascii").lower()
    except (UnicodeError, ValueError):
        return SourceReviewLabel.INVALID_OR_INSECURE_URL, None

    allowedHosts = {
        normalized
        for entry in officialHostAllowlist
        if (normalized := _normalizeAllowlistHost(entry)) is not None
    }
    if any(
        normalizedHost == allowedHost or normalizedHost.endswith(f".{allowedHost}")
        for allowedHost in allowedHosts
    ):
        return SourceReviewLabel.OFFICIAL_HOST_ALLOWLIST_MATCH, normalizedHost
    # 非 allowlist 主机不回显，避免让攻击者控制的 hostname 进入审计日志。
    return SourceReviewLabel.HOST_NOT_ALLOWLISTED, None


def _findSourceUrl(metadata: Mapping[str, object]) -> str | None:
    candidates = {"url", "sourceurl", "source_url"}
    for key, value in sorted(metadata.items(), key=lambda entry: _stableMetadataKey(entry[0])):
        if isinstance(key, str) and key.casefold() in candidates and isinstance(value, str):
            return value.strip() or None
    return None


def _normalizeAllowlistHost(entry: object) -> str | None:
    if not isinstance(entry, str):
        return None
    candidate = entry.strip().lower().lstrip("*.")
    if not candidate:
        return None
    try:
        if "://" in candidate:
            candidate = urlsplit(candidate).hostname or ""
        candidate = candidate.rstrip(".").encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", candidate):
        return None
    return candidate


def _normalizeLocale(locale: SupportedLocale) -> Literal["en", "zh"]:
    return "zh" if str(locale).casefold().startswith("zh") else "en"
