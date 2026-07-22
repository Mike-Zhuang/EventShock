"""官方模型能力目录。

通用目录只收录项目实际支持并在 2026-07-20 从供应商官方文档核验过的
模型。旧的智谱完整目录继续保留，避免破坏现有调用方。
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal

from pydantic import Field, computed_field

from backend.app.cognition.models import StrictFrozenModel

ZHIPU_PROVIDER = "zhipu"
ZHIPU_API_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
ZHIPU_CHAT_COMPLETIONS_URL = f"{ZHIPU_API_BASE_URL}chat/completions"

ProviderId = Literal[
    "zhipu",
    "openai",
    "anthropic",
    "google",
    "deepseek",
    "alibaba",
    "moonshot",
]
StructuredOutputMode = Literal["json_schema", "json_object"]
IntegrationValidationStatus = Literal[
    "REAL_PROJECT_KEY_VERIFIED",
    "CONTRACT_TESTED_COMMUNITY_PREVIEW",
]
DEFAULT_PROVIDER: ProviderId = "zhipu"
DEFAULT_MODEL = "glm-5.2"
CATALOG_VERIFIED_AT = "2026-07-20"
APPLICATION_MAX_OUTPUT_TOKENS = 131_072
PROVIDER_FEEDBACK_ISSUE_URL = (
    "https://github.com/Mike-Zhuang/EventShock/issues/new"
    "?template=llm-provider-feedback.yml"
)


class ProviderDescriptor(StrictFrozenModel):
    provider: ProviderId
    display_name: str = Field(min_length=2, max_length=80)
    api_endpoint: str = Field(pattern=r"^https://")
    api_style: Literal["chat_completions", "responses", "messages", "interactions"]
    auth_mode: Literal["bearer", "x-api-key", "x-goog-api-key"]
    region: str = Field(min_length=2, max_length=80)
    official_docs_url: str = Field(pattern=r"^https://")
    official_pricing_url: str = Field(pattern=r"^https://")
    verified_at: str = CATALOG_VERIFIED_AT
    default_model_id: str = Field(min_length=3, max_length=128)
    # 能力目录核验与真实凭据端到端核验是两件事，前端必须据此明确提示风险。
    integration_validation_status: IntegrationValidationStatus = (
        "CONTRACT_TESTED_COMMUNITY_PREVIEW"
    )
    feedback_issue_url: str = Field(
        default=PROVIDER_FEEDBACK_ISSUE_URL,
        pattern=r"^https://github\.com/",
    )


class ModelDescriptor(StrictFrozenModel):
    provider: ProviderId
    model_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
    display_name: str = Field(min_length=3, max_length=80)
    context_tokens: int = Field(ge=16_000)
    # max_output_tokens 是应用实际可执行上限，必须与 SamplingConfig 保持一致。
    # None 表示官方资料未给出可独立核验的最大输出上限，配置须 fail-closed。
    max_output_tokens: int | None = Field(
        default=None,
        ge=1_024,
        le=APPLICATION_MAX_OUTPUT_TOKENS,
    )
    official_output_limit_tokens: int | None = Field(
        default=None,
        ge=1_024,
        exclude=True,
        repr=False,
    )
    quality_tier: Literal["economy", "balanced", "premium"] = "balanced"
    structured_output_mode: StructuredOutputMode
    supports_thinking: bool
    supports_function_calling: bool
    thinking_behavior: Literal["optional", "always"] = "optional"
    recommended: bool = False
    free_tier: bool = False
    legacy: bool = False
    deprecation_note: str | None = Field(default=None, max_length=200)
    region: str = Field(min_length=2, max_length=80)
    official_model_url: str = Field(pattern=r"^https://")
    verified_at: str = CATALOG_VERIFIED_AT
    capability_note: str | None = Field(default=None, max_length=500)

    @property
    def supports_json_schema(self) -> bool:
        return self.structured_output_mode == "json_schema"

    @property
    def supports_json_object(self) -> bool:
        return True

    @computed_field(return_type=int | None)
    @property
    def official_max_output_tokens(self) -> int | None:
        """供前端明确区分“官方上限”与用户本次请求的 maxTokens。"""

        return self.official_output_limit_tokens or self.max_output_tokens


PROVIDERS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        provider="zhipu",
        display_name="Zhipu AI / 智谱",
        api_endpoint=ZHIPU_CHAT_COMPLETIONS_URL,
        api_style="chat_completions",
        auth_mode="bearer",
        region="CN",
        official_docs_url="https://docs.bigmodel.cn/cn/guide/start/model-overview",
        official_pricing_url="https://bigmodel.cn/pricing",
        default_model_id="glm-5.2",
        integration_validation_status="REAL_PROJECT_KEY_VERIFIED",
    ),
    ProviderDescriptor(
        provider="openai",
        display_name="OpenAI",
        api_endpoint="https://api.openai.com/v1/responses",
        api_style="responses",
        auth_mode="bearer",
        region="GLOBAL",
        official_docs_url="https://developers.openai.com/api/docs/models",
        official_pricing_url="https://openai.com/api/pricing/",
        default_model_id="gpt-5.6-terra",
    ),
    ProviderDescriptor(
        provider="anthropic",
        display_name="Anthropic",
        api_endpoint="https://api.anthropic.com/v1/messages",
        api_style="messages",
        auth_mode="x-api-key",
        region="GLOBAL",
        official_docs_url="https://platform.claude.com/docs/en/about-claude/models/overview",
        official_pricing_url="https://platform.claude.com/docs/en/about-claude/pricing",
        default_model_id="claude-sonnet-5",
    ),
    ProviderDescriptor(
        provider="google",
        display_name="Google Gemini",
        api_endpoint="https://generativelanguage.googleapis.com/v1beta/interactions",
        api_style="interactions",
        auth_mode="x-goog-api-key",
        region="GLOBAL",
        official_docs_url="https://ai.google.dev/gemini-api/docs/models",
        official_pricing_url="https://ai.google.dev/gemini-api/docs/pricing",
        default_model_id="gemini-3.5-flash",
    ),
    ProviderDescriptor(
        provider="deepseek",
        display_name="DeepSeek",
        api_endpoint="https://api.deepseek.com/chat/completions",
        api_style="chat_completions",
        auth_mode="bearer",
        region="GLOBAL",
        official_docs_url="https://api-docs.deepseek.com/",
        official_pricing_url="https://api-docs.deepseek.com/quick_start/pricing",
        default_model_id="deepseek-v4-flash",
    ),
    ProviderDescriptor(
        provider="alibaba",
        display_name="Alibaba Cloud Qwen / 通义千问",
        api_endpoint="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        api_style="chat_completions",
        auth_mode="bearer",
        region="CN_BEIJING",
        official_docs_url="https://www.alibabacloud.com/help/en/model-studio/models",
        official_pricing_url=("https://www.alibabacloud.com/help/en/model-studio/model-pricing"),
        default_model_id="qwen3.6-flash",
    ),
    ProviderDescriptor(
        provider="moonshot",
        display_name="Moonshot AI / Kimi",
        api_endpoint="https://api.moonshot.cn/v1/chat/completions",
        api_style="chat_completions",
        auth_mode="bearer",
        region="CN",
        official_docs_url="https://platform.kimi.com/docs/guide/start-using-kimi-api",
        official_pricing_url="https://platform.kimi.com/docs/pricing/chat",
        default_model_id="kimi-k3",
    ),
)


SUPPORTED_MODELS: tuple[ModelDescriptor, ...] = (
    ModelDescriptor(
        provider="zhipu",
        model_id="glm-5.2",
        display_name="GLM-5.2",
        context_tokens=1_000_000,
        max_output_tokens=131_072,
        structured_output_mode="json_object",
        supports_thinking=True,
        supports_function_calling=True,
        recommended=True,
        quality_tier="premium",
        region="CN",
        official_model_url="https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2",
        capability_note="JSON mode returns an object; validate it against the application schema.",
    ),
    ModelDescriptor(
        provider="zhipu",
        model_id="glm-4.7-flashx",
        display_name="GLM-4.7-FlashX",
        context_tokens=200_000,
        max_output_tokens=131_072,
        structured_output_mode="json_object",
        supports_thinking=True,
        supports_function_calling=True,
        quality_tier="economy",
        region="CN",
        official_model_url="https://docs.bigmodel.cn/cn/guide/models/text/glm-4.7",
        capability_note="JSON mode returns an object; validate it against the application schema.",
    ),
    ModelDescriptor(
        provider="openai",
        model_id="gpt-5.6-luna",
        display_name="GPT-5.6 Luna",
        context_tokens=1_050_000,
        max_output_tokens=128_000,
        structured_output_mode="json_schema",
        supports_thinking=True,
        supports_function_calling=True,
        quality_tier="economy",
        region="GLOBAL",
        official_model_url="https://developers.openai.com/api/docs/models/gpt-5.6-luna",
    ),
    ModelDescriptor(
        provider="openai",
        model_id="gpt-5.6-terra",
        display_name="GPT-5.6 Terra",
        context_tokens=1_050_000,
        max_output_tokens=128_000,
        structured_output_mode="json_schema",
        supports_thinking=True,
        supports_function_calling=True,
        recommended=True,
        quality_tier="balanced",
        region="GLOBAL",
        official_model_url="https://developers.openai.com/api/docs/models/gpt-5.6-terra",
    ),
    ModelDescriptor(
        provider="openai",
        model_id="gpt-5.6-sol",
        display_name="GPT-5.6 Sol",
        context_tokens=1_050_000,
        max_output_tokens=128_000,
        structured_output_mode="json_schema",
        supports_thinking=True,
        supports_function_calling=True,
        quality_tier="premium",
        region="GLOBAL",
        official_model_url="https://developers.openai.com/api/docs/models/gpt-5.6-sol",
    ),
    ModelDescriptor(
        provider="anthropic",
        model_id="claude-haiku-4-5-20251001",
        display_name="Claude Haiku 4.5",
        context_tokens=200_000,
        max_output_tokens=64_000,
        structured_output_mode="json_schema",
        supports_thinking=True,
        supports_function_calling=True,
        quality_tier="economy",
        region="GLOBAL",
        official_model_url="https://platform.claude.com/docs/en/about-claude/models/overview",
    ),
    ModelDescriptor(
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6",
        context_tokens=1_000_000,
        max_output_tokens=128_000,
        structured_output_mode="json_schema",
        supports_thinking=True,
        supports_function_calling=True,
        quality_tier="premium",
        region="GLOBAL",
        official_model_url="https://platform.claude.com/docs/en/about-claude/models/overview",
    ),
    ModelDescriptor(
        provider="anthropic",
        model_id="claude-sonnet-5",
        display_name="Claude Sonnet 5",
        context_tokens=1_000_000,
        max_output_tokens=128_000,
        structured_output_mode="json_schema",
        supports_thinking=True,
        supports_function_calling=True,
        recommended=True,
        quality_tier="premium",
        region="GLOBAL",
        official_model_url="https://platform.claude.com/docs/en/about-claude/models/overview",
        capability_note="Current Sonnet model with adaptive thinking support.",
    ),
    ModelDescriptor(
        provider="google",
        model_id="gemini-3.5-flash",
        display_name="Gemini 3.5 Flash",
        context_tokens=1_000_000,
        max_output_tokens=65_536,
        structured_output_mode="json_schema",
        supports_thinking=True,
        supports_function_calling=True,
        recommended=True,
        quality_tier="economy",
        region="GLOBAL",
        official_model_url="https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash",
        capability_note="Structured output supports a documented subset of JSON Schema.",
    ),
    ModelDescriptor(
        provider="deepseek",
        model_id="deepseek-v4-flash",
        display_name="DeepSeek V4 Flash",
        context_tokens=1_000_000,
        max_output_tokens=APPLICATION_MAX_OUTPUT_TOKENS,
        official_output_limit_tokens=384_000,
        structured_output_mode="json_object",
        supports_thinking=True,
        supports_function_calling=True,
        recommended=True,
        quality_tier="economy",
        region="GLOBAL",
        official_model_url="https://api-docs.deepseek.com/quick_start/pricing",
        capability_note="JSON mode requires downstream application-schema validation.",
    ),
    ModelDescriptor(
        provider="deepseek",
        model_id="deepseek-v4-pro",
        display_name="DeepSeek V4 Pro",
        context_tokens=1_000_000,
        max_output_tokens=APPLICATION_MAX_OUTPUT_TOKENS,
        official_output_limit_tokens=384_000,
        structured_output_mode="json_object",
        supports_thinking=True,
        supports_function_calling=True,
        quality_tier="premium",
        region="GLOBAL",
        official_model_url="https://api-docs.deepseek.com/quick_start/pricing",
        capability_note="JSON mode requires downstream application-schema validation.",
    ),
    ModelDescriptor(
        provider="alibaba",
        model_id="qwen3.6-flash",
        display_name="Qwen3.6 Flash",
        context_tokens=1_000_000,
        max_output_tokens=65_536,
        structured_output_mode="json_object",
        supports_thinking=True,
        supports_function_calling=True,
        recommended=True,
        quality_tier="economy",
        region="CN_BEIJING",
        official_model_url=("https://www.alibabacloud.com/help/en/model-studio/models"),
        capability_note=(
            "JSON object mode requires the prompt to mention JSON and downstream validation."
        ),
    ),
    ModelDescriptor(
        provider="moonshot",
        model_id="kimi-k2.6",
        display_name="Kimi K2.6",
        context_tokens=262_144,
        max_output_tokens=None,
        structured_output_mode="json_schema",
        supports_thinking=True,
        supports_function_calling=True,
        quality_tier="balanced",
        region="CN",
        official_model_url="https://platform.kimi.com/docs/guide/kimi-k2-6-quickstart",
        capability_note=(
            "Official material does not publish a separately verifiable maximum output limit; "
            "session configuration therefore fails closed."
        ),
    ),
    ModelDescriptor(
        provider="moonshot",
        model_id="kimi-k3",
        display_name="Kimi K3",
        context_tokens=1_048_576,
        max_output_tokens=APPLICATION_MAX_OUTPUT_TOKENS,
        official_output_limit_tokens=1_048_576,
        structured_output_mode="json_schema",
        supports_thinking=True,
        supports_function_calling=True,
        thinking_behavior="always",
        recommended=True,
        quality_tier="premium",
        region="CN",
        official_model_url="https://platform.kimi.com/docs/guide/kimi-k3-quickstart",
        capability_note=(
            "Kimi K3 always reasons: disabling the UI switch maps to the official low effort "
            "instead of disabling reasoning. The application caps output at 131072 tokens; "
            "requested input and output together must fit the context window."
        ),
    ),
)

_PROVIDER_BY_ID = MappingProxyType({item.provider: item for item in PROVIDERS})
_SUPPORTED_MODEL_BY_KEY = MappingProxyType(
    {(item.provider, item.model_id): item for item in SUPPORTED_MODELS}
)


def getProvider(provider: ProviderId | str) -> ProviderDescriptor:
    try:
        return _PROVIDER_BY_ID[provider]  # type: ignore[index]
    except KeyError as error:
        raise ValueError(f"unsupported model provider: {provider}") from error


def getModel(provider: ProviderId | str, modelId: str) -> ModelDescriptor:
    getProvider(provider)
    try:
        return _SUPPORTED_MODEL_BY_KEY[(provider, modelId)]  # type: ignore[index]
    except KeyError as error:
        raise ValueError(f"unsupported provider/model pair: {provider}/{modelId}") from error


def listProviders() -> tuple[ProviderDescriptor, ...]:
    return PROVIDERS


def listModels(provider: ProviderId | str | None = None) -> tuple[ModelDescriptor, ...]:
    if provider is None:
        return SUPPORTED_MODELS
    getProvider(provider)
    return tuple(item for item in SUPPORTED_MODELS if item.provider == provider)


class ZhipuModelDescriptor(StrictFrozenModel):
    provider: Literal["zhipu"] = "zhipu"
    model_id: str = Field(pattern=r"^glm-[a-z0-9.-]+$")
    display_name: str = Field(min_length=3, max_length=80)
    context_tokens: int = Field(ge=16_000)
    max_output_tokens: int = Field(ge=1_024)
    supports_json_object: Literal[True] = True
    supports_function_calling: bool
    supports_thinking: bool
    supports_tool_stream: bool
    recommended: bool = False
    free_tier: bool = False
    legacy: bool = False
    deprecation_note: str | None = Field(default=None, max_length=200)


ZHIPU_CHAT_MODELS: tuple[ZhipuModelDescriptor, ...] = (
    ZhipuModelDescriptor(
        model_id="glm-5.2",
        display_name="GLM-5.2",
        context_tokens=1_000_000,
        max_output_tokens=131_072,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=True,
        recommended=True,
    ),
    ZhipuModelDescriptor(
        model_id="glm-5.1",
        display_name="GLM-5.1",
        context_tokens=200_000,
        max_output_tokens=131_072,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=True,
    ),
    ZhipuModelDescriptor(
        model_id="glm-5-turbo",
        display_name="GLM-5-Turbo",
        context_tokens=200_000,
        max_output_tokens=131_072,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=True,
    ),
    ZhipuModelDescriptor(
        model_id="glm-5",
        display_name="GLM-5",
        context_tokens=200_000,
        max_output_tokens=131_072,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=True,
    ),
    ZhipuModelDescriptor(
        model_id="glm-4.7",
        display_name="GLM-4.7",
        context_tokens=200_000,
        max_output_tokens=131_072,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=True,
    ),
    ZhipuModelDescriptor(
        model_id="glm-4.7-flashx",
        display_name="GLM-4.7-FlashX",
        context_tokens=200_000,
        max_output_tokens=131_072,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=False,
    ),
    ZhipuModelDescriptor(
        model_id="glm-4.7-flash",
        display_name="GLM-4.7-Flash",
        context_tokens=200_000,
        max_output_tokens=131_072,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=False,
        free_tier=True,
    ),
    ZhipuModelDescriptor(
        model_id="glm-4.6",
        display_name="GLM-4.6",
        context_tokens=200_000,
        max_output_tokens=131_072,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=True,
    ),
    ZhipuModelDescriptor(
        model_id="glm-4.5-air",
        display_name="GLM-4.5-Air",
        context_tokens=128_000,
        max_output_tokens=98_304,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=False,
    ),
    ZhipuModelDescriptor(
        model_id="glm-4.5-airx",
        display_name="GLM-4.5-AirX",
        context_tokens=128_000,
        max_output_tokens=98_304,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=False,
    ),
    ZhipuModelDescriptor(
        model_id="glm-4.5-flash",
        display_name="GLM-4.5-Flash",
        context_tokens=128_000,
        max_output_tokens=98_304,
        supports_function_calling=True,
        supports_thinking=True,
        supports_tool_stream=False,
        free_tier=True,
        legacy=True,
        deprecation_note="智谱官方模型概览已标记为即将下线。",
    ),
    ZhipuModelDescriptor(
        model_id="glm-4-flash-250414",
        display_name="GLM-4-Flash-250414",
        context_tokens=128_000,
        max_output_tokens=16_384,
        supports_function_calling=True,
        supports_thinking=False,
        supports_tool_stream=False,
        free_tier=True,
        legacy=True,
    ),
    ZhipuModelDescriptor(
        model_id="glm-4-flashx-250414",
        display_name="GLM-4-FlashX-250414",
        context_tokens=128_000,
        max_output_tokens=16_384,
        supports_function_calling=True,
        supports_thinking=False,
        supports_tool_stream=False,
        legacy=True,
    ),
)

_MODEL_BY_ID = MappingProxyType({item.model_id: item for item in ZHIPU_CHAT_MODELS})

# 把既有智谱型号映射进通用目录。安全集合中的两个型号保留更精确的元数据，
# 其余型号继续可被联合键发现；没有公开价格的型号仍会在配置阶段 fail-closed。
_SAFE_ZHIPU_MODEL_IDS = {item.model_id for item in SUPPORTED_MODELS if item.provider == "zhipu"}
_ZHIPU_COMPAT_MODELS = tuple(
    ModelDescriptor(
        provider="zhipu",
        model_id=item.model_id,
        display_name=item.display_name,
        context_tokens=item.context_tokens,
        max_output_tokens=item.max_output_tokens,
        quality_tier="economy" if item.free_tier else "balanced",
        structured_output_mode="json_object",
        supports_thinking=item.supports_thinking,
        supports_function_calling=item.supports_function_calling,
        recommended=False,
        free_tier=item.free_tier,
        legacy=item.legacy,
        deprecation_note=item.deprecation_note,
        region="CN",
        official_model_url="https://docs.bigmodel.cn/cn/guide/start/model-overview",
        capability_note=(
            "Legacy compatibility entry; JSON output requires downstream schema validation."
            if item.legacy
            else "Compatibility entry; JSON output requires downstream schema validation."
        ),
    )
    for item in ZHIPU_CHAT_MODELS
    if item.model_id not in _SAFE_ZHIPU_MODEL_IDS
)
SUPPORTED_MODELS = SUPPORTED_MODELS + _ZHIPU_COMPAT_MODELS
_SUPPORTED_MODEL_BY_KEY = MappingProxyType(
    {(item.provider, item.model_id): item for item in SUPPORTED_MODELS}
)


def getZhipuModel(modelId: str) -> ZhipuModelDescriptor:
    try:
        return _MODEL_BY_ID[modelId]
    except KeyError as error:
        raise ValueError(f"unsupported Zhipu model: {modelId}") from error


def listZhipuModels(*, includeLegacy: bool = True) -> tuple[ZhipuModelDescriptor, ...]:
    if includeLegacy:
        return ZHIPU_CHAT_MODELS
    return tuple(item for item in ZHIPU_CHAT_MODELS if not item.legacy)
