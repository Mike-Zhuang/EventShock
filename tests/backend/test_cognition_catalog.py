from __future__ import annotations

from decimal import Decimal

import pytest

from backend.app.cognition.catalog import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    SUPPORTED_MODELS,
    getModel,
    getProvider,
    listModels,
    listProviders,
)
from backend.app.cognition.config_store import SessionConfigStore
from backend.app.cognition.gateway import ModelPolicy, ModelUsage
from backend.app.cognition.pricing import (
    estimateReservation,
    getTokenPrice,
    usageCostUpperBoundForProviderUsd,
)
from backend.app.schemas import LlmConfigRequest

SAFE_MODEL_PAIRS = {
    ("zhipu", "glm-5.2"),
    ("zhipu", "glm-4.7-flashx"),
    ("openai", "gpt-5.6-luna"),
    ("openai", "gpt-5.6-terra"),
    ("openai", "gpt-5.6-sol"),
    ("anthropic", "claude-haiku-4-5-20251001"),
    ("anthropic", "claude-sonnet-4-6"),
    ("anthropic", "claude-sonnet-5"),
    ("google", "gemini-3.5-flash"),
    ("deepseek", "deepseek-v4-flash"),
    ("deepseek", "deepseek-v4-pro"),
    ("alibaba", "qwen3.6-flash"),
    ("moonshot", "kimi-k2.6"),
    ("moonshot", "kimi-k3"),
}


def test_provider_catalog_has_joint_keys_and_one_matching_recommendation() -> None:
    providers = listProviders()
    assert len(providers) == 7
    assert DEFAULT_PROVIDER == "zhipu"
    assert DEFAULT_MODEL == "glm-5.2"
    assert SAFE_MODEL_PAIRS <= {(item.provider, item.model_id) for item in SUPPORTED_MODELS}
    assert len(SUPPORTED_MODELS) == len(
        {(item.provider, item.model_id) for item in SUPPORTED_MODELS}
    )

    for provider in providers:
        models = listModels(provider.provider)
        recommended = [item for item in models if item.recommended]
        assert [item.model_id for item in recommended] == [provider.default_model_id]
        assert getProvider(provider.provider) == provider
        assert getModel(provider.provider, provider.default_model_id) == recommended[0]
        assert provider.official_docs_url.startswith("https://")
        assert provider.official_pricing_url.startswith("https://")


def test_legacy_zhipu_models_remain_discoverable_but_mismatches_are_rejected() -> None:
    assert getModel("zhipu", "glm-5").model_id == "glm-5"
    assert getTokenPrice("zhipu", "glm-4.6") is None

    with pytest.raises(ValueError, match="unsupported provider/model pair"):
        getModel("openai", "glm-5.2")
    with pytest.raises(ValueError, match="unsupported provider/model pair"):
        SessionConfigStore().setConfig(
            sessionId="session-provider-mismatch-001",
            apiKey="test-provider-secret-key",
            provider="openai",
            model="glm-5.2",
        )


def test_structured_output_capability_is_explicit() -> None:
    assert getModel("openai", "gpt-5.6-luna").structured_output_mode == "json_schema"
    assert getModel("zhipu", "glm-5.2").structured_output_mode == "json_object"
    assert getModel("google", "gemini-3.5-flash").supports_json_schema is True
    assert getModel("deepseek", "deepseek-v4-pro").supports_json_schema is False


def test_multi_provider_config_is_isolated_and_unverified_limits_fail_closed() -> None:
    store = SessionConfigStore()
    view = store.setConfig(
        sessionId="session-openai-config-001",
        apiKey="test-openai-secret-key",
        provider="openai",
        model="gpt-5.6-luna",
        thinkingEnabled=True,
        maxTokens=4_096,
    )
    runtime = store.getRuntimeConfig("session-openai-config-001")

    assert view.provider == "openai"
    assert view.credential_hint == "••••-key"
    assert "test-openai-secret-key" not in repr(runtime)
    assert runtime.apiKey == "test-openai-secret-key"

    with pytest.raises(ValueError, match="no verified maximum output limit"):
        store.setConfig(
            sessionId="session-kimi-unverified-001",
            apiKey="test-kimi-secret-key",
            provider="moonshot",
            model="kimi-k2.6",
        )


def test_generic_prices_and_reservations_use_conservative_upper_bounds() -> None:
    for provider, model in SAFE_MODEL_PAIRS:
        assert getTokenPrice(provider, model) is not None

    usage = ModelUsage(promptTokens=1_000_000, completionTokens=100_000)
    assert usageCostUpperBoundForProviderUsd("openai", "gpt-5.6-luna", usage) == Decimal(
        "2.900000000"
    )

    reservation = estimateReservation(
        provider="anthropic",
        modelId="claude-sonnet-4-6",
        maxOutputTokens=2_048,
        policy=ModelPolicy(),
    )
    assert reservation.provider == "anthropic"
    assert reservation.maximumUsd > Decimal("36")


def test_catalog_distinguishes_application_and_official_output_limits() -> None:
    deepSeek = getModel("deepseek", "deepseek-v4-flash")
    kimi = getModel("moonshot", "kimi-k3")

    assert deepSeek.max_output_tokens == 131_072
    assert deepSeek.official_max_output_tokens == 384_000
    assert kimi.max_output_tokens == 131_072
    assert kimi.official_max_output_tokens == 1_048_576
    assert kimi.thinking_behavior == "always"
    assert "always reasons" in (kimi.capability_note or "")

    with pytest.raises(ValueError, match="application limit"):
        SessionConfigStore().setConfig(
            sessionId="session-kimi-application-cap-001",
            apiKey="test-kimi-secret-key",
            provider="moonshot",
            model="kimi-k3",
            maxTokens=131_073,
        )
    with pytest.raises(ValueError):
        LlmConfigRequest(
            provider="moonshot",
            model="kimi-k3",
            apiKey="test-kimi-secret-key",
            maxTokens=131_073,
        )


def test_current_anthropic_qwen_and_kimi_metadata_are_explicit() -> None:
    assert getProvider("anthropic").default_model_id == "claude-sonnet-5"
    assert getModel("anthropic", "claude-sonnet-5").recommended is True
    assert getModel("anthropic", "claude-sonnet-4-6").legacy is False
    assert getModel("anthropic", "claude-sonnet-4-6").deprecation_note is None
    assert getModel("anthropic", "claude-sonnet-4-6").recommended is False
    sonnetPrice = getTokenPrice("anthropic", "claude-sonnet-5")
    assert sonnetPrice is not None
    assert sonnetPrice.listInputPerMillion == Decimal("2")
    assert sonnetPrice.listOutputPerMillion == Decimal("10")
    assert sonnetPrice.budgetInputUpperBoundPerMillion == Decimal("6")
    assert sonnetPrice.budgetOutputUpperBoundPerMillion == Decimal("15")
    assert "2026-09-01" in sonnetPrice.pricingNote

    qwen = getModel("alibaba", "qwen3.6-flash")
    qwenPrice = getTokenPrice("alibaba", "qwen3.6-flash")
    assert getProvider("alibaba").region == "CN_BEIJING"
    assert qwen.region == "CN_BEIJING"
    assert qwenPrice is not None
    assert qwenPrice.listInputPerMillion == Decimal("4.8")
    assert qwenPrice.listOutputPerMillion == Decimal("28.8")
    assert qwenPrice.budgetInputUpperBoundPerMillion == Decimal("6")

    assert getTokenPrice("moonshot", "kimi-k2.6").sourceUrl.endswith("/chat-k26")  # type: ignore[union-attr]
    assert getTokenPrice("moonshot", "kimi-k3").sourceUrl.endswith("/chat-k3")  # type: ignore[union-attr]
