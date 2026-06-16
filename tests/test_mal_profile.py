"""Tests for ProviderProfile, OMIT_TEMPERATURE, and LocalProfile."""

import os

from crabkey.mal.profile import OMIT_TEMPERATURE, ProviderProfile


def test_omit_temperature_is_singleton():
    assert OMIT_TEMPERATURE is OMIT_TEMPERATURE


def test_profile_defaults():
    p = ProviderProfile(name="test")
    assert p.api_mode == "chat_completions"
    assert p.aliases == ()
    assert p.auth_type == "api_key"
    assert p.fallback_models == ()
    assert p.default_headers == {}


def test_get_hostname_from_base_url():
    p = ProviderProfile(name="test", base_url="https://api.example.com/v1")
    assert p.get_hostname() == "api.example.com"


def test_get_hostname_explicit_overrides_base_url():
    p = ProviderProfile(name="test", base_url="https://api.example.com", hostname="override.example.com")
    assert p.get_hostname() == "override.example.com"


def test_get_hostname_empty_when_no_url():
    p = ProviderProfile(name="test")
    assert p.get_hostname() == ""


def test_get_base_url_default():
    p = ProviderProfile(name="test", base_url="https://api.example.com/v1")
    assert p.get_base_url() == "https://api.example.com/v1"


def test_prepare_messages_passthrough():
    p = ProviderProfile(name="test")
    msgs = [{"role": "user", "content": "hi"}]
    assert p.prepare_messages(msgs) is msgs


def test_build_extra_body_default_empty():
    p = ProviderProfile(name="test")
    assert p.build_extra_body() == {}


def test_build_api_kwargs_extras_default_empty():
    p = ProviderProfile(name="test")
    extra_body, top_level = p.build_api_kwargs_extras()
    assert extra_body == {}
    assert top_level == {}


def test_get_max_tokens_returns_default():
    p = ProviderProfile(name="test", default_max_tokens=4096)
    assert p.get_max_tokens("any-model") == 4096


def test_get_max_tokens_none_by_default():
    p = ProviderProfile(name="test")
    assert p.get_max_tokens("any-model") is None


# ── LocalProfile — dynamic base_url ──────────────────────────────────────────
# The local plugin lives in model-providers/local/ (hyphen in dir name), which
# is not a valid Python package path. Load it via the registry instead.

def _get_local_profile():
    import crabkey.mal.provider_registry as reg
    reg._discover_providers()
    return reg.get_provider_profile("local")


def test_local_profile_get_base_url_reads_env(monkeypatch):
    profile = _get_local_profile()
    monkeypatch.setenv("CRABKEY_LOCAL_URL", "http://192.168.1.5:8080/v1")
    assert profile.get_base_url() == "http://192.168.1.5:8080/v1"


def test_local_profile_falls_back_to_default(monkeypatch):
    profile = _get_local_profile()
    monkeypatch.delenv("CRABKEY_LOCAL_URL", raising=False)
    assert profile.get_base_url() == "http://localhost:11434/v1"


def test_local_profile_base_url_field_not_frozen(monkeypatch):
    """The .base_url dataclass field stays at default; get_base_url() reads env dynamically."""
    profile = _get_local_profile()
    default_url = "http://localhost:11434/v1"
    monkeypatch.setenv("CRABKEY_LOCAL_URL", "http://10.0.0.1:9999/v1")
    assert profile.base_url == default_url                       # frozen field unchanged
    assert profile.get_base_url() == "http://10.0.0.1:9999/v1"  # hook reads env
