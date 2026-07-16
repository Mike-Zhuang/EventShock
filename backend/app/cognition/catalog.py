"""智谱官方 Chat Completions 模型目录（2026-07-15 核验）。"""

from __future__ import annotations

from types import MappingProxyType
from typing import Literal

from pydantic import Field

from backend.app.cognition.models import StrictFrozenModel

ZHIPU_PROVIDER = "zhipu"
ZHIPU_API_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
ZHIPU_CHAT_COMPLETIONS_URL = f"{ZHIPU_API_BASE_URL}chat/completions"


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


def getZhipuModel(modelId: str) -> ZhipuModelDescriptor:
    try:
        return _MODEL_BY_ID[modelId]
    except KeyError as error:
        raise ValueError(f"unsupported Zhipu model: {modelId}") from error


def listZhipuModels(*, includeLegacy: bool = True) -> tuple[ZhipuModelDescriptor, ...]:
    if includeLegacy:
        return ZHIPU_CHAT_MODELS
    return tuple(item for item in ZHIPU_CHAT_MODELS if not item.legacy)
