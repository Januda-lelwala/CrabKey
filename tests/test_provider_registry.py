"""Tests for provider plugin discovery and registry."""

import pytest

import crabkey.mal.provider_registry as reg
from crabkey.mal.provider_registry import (
    get_provider_profile,
    list_providers,
    register_provider,
)
from crabkey.mal.profile import ProviderProfile


EXPECTED_PROVIDERS = {
    "anthropic", "openrouter", "openai", "gemini",
    "deepseek", "xai", "mistral", "groq",
    "nvidia", "huggingface", "ollama-cloud", "local",
}

EXPECTED_ALIASES = {
    "claude": "anthropic",
    "or": "openrouter",
    "ollama": "local",
}


def test_all_bundled_providers_discovered():
    providers = list_providers()
    names = {p.name for p in providers}
    assert EXPECTED_PROVIDERS.issubset(names), f"Missing providers: {EXPECTED_PROVIDERS - names}"


def test_provider_count_matches_bundled_plugins():
    providers = list_providers()
    assert len(providers) >= len(EXPECTED_PROVIDERS)


def test_get_provider_by_name():
    profile = get_provider_profile("anthropic")
    assert profile is not None
    assert profile.name == "anthropic"


def test_get_provider_returns_none_for_unknown():
    profile = get_provider_profile("totally_unknown_xyz")
    assert profile is None


def test_alias_resolution():
    for alias, canonical in EXPECTED_ALIASES.items():
        profile = get_provider_profile(alias)
        assert profile is not None, f"Alias {alias!r} not found"
        assert profile.name == canonical, f"{alias!r} → {profile.name!r} (expected {canonical!r})"


def test_anthropic_uses_anthropic_messages_api_mode():
    profile = get_provider_profile("anthropic")
    assert profile.api_mode == "anthropic_messages"


def test_openrouter_uses_chat_completions_api_mode():
    profile = get_provider_profile("openrouter")
    assert profile.api_mode == "chat_completions"


def test_local_uses_chat_completions_api_mode():
    profile = get_provider_profile("local")
    assert profile.api_mode == "chat_completions"


def test_local_env_vars_declared():
    profile = get_provider_profile("local")
    assert "CRABKEY_LOCAL_URL" in profile.env_vars


def test_anthropic_has_fallback_models():
    profile = get_provider_profile("anthropic")
    assert len(profile.fallback_models) > 0
    assert any("claude" in m for m in profile.fallback_models)


def test_register_custom_provider():
    custom = ProviderProfile(name="custom_test_xyz", aliases=("ctz",))
    register_provider(custom)
    assert get_provider_profile("custom_test_xyz") is custom
    assert get_provider_profile("ctz") is custom


def test_user_provider_overrides_bundled():
    list_providers()  # trigger discovery first so bundled openai is already registered
    override = ProviderProfile(name="openai", base_url="https://override.example.com/v1")
    register_provider(override)
    profile = get_provider_profile("openai")
    assert profile.base_url == "https://override.example.com/v1"


def test_list_providers_no_duplicates():
    providers = list_providers()
    names = [p.name for p in providers]
    assert len(names) == len(set(names))
