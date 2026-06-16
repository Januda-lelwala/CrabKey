"""OpenRouter provider profile — aggregator for 200+ models."""

from __future__ import annotations

import logging
from typing import Any

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

logger = logging.getLogger(__name__)

_MODEL_CACHE: list[str] | None = None

# Claude 4.6+ uses adaptive thinking and rejects any explicit reasoning toggle.
_ANTHROPIC_REASONING_OPTIONAL = (
    "claude-3",
    "claude-opus-4-0", "claude-opus-4.0",
    "claude-sonnet-4-0", "claude-sonnet-4.0",
    "claude-haiku-4-5", "claude-haiku-4.5",
)


def _anthropic_reasoning_mandatory(model: str | None) -> bool:
    m = (model or "").lower()
    if not ("anthropic/" in m or m.startswith("claude")):
        return False
    return not any(s in m for s in _ANTHROPIC_REASONING_OPTIONAL)


class OpenRouterProfile(ProviderProfile):
    """OpenRouter — provider preferences + reasoning config passthrough."""

    def fetch_models(self, *, api_key: str | None = None, timeout: float = 8.0) -> list[str] | None:
        global _MODEL_CACHE
        if _MODEL_CACHE is not None:
            return _MODEL_CACHE
        result = super().fetch_models(api_key=None, timeout=timeout)
        if result:
            _MODEL_CACHE = result
        return result

    def build_extra_body(self, *, session_id: str | None = None, **context: Any) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if session_id:
            body["session_id"] = session_id
        if prefs := context.get("provider_preferences"):
            body["provider"] = prefs
        return body

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        supports_reasoning: bool = False,
        model: str | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        extra_body: dict[str, Any] = {}
        top_level: dict[str, Any] = {}

        if supports_reasoning:
            if _anthropic_reasoning_mandatory(model):
                # Adaptive thinking models: route effort to `verbosity`, omit `reasoning`
                cfg = reasoning_config or {}
                effort = cfg.get("effort")
                if cfg.get("enabled", True) is not False and effort and effort != "none":
                    top_level["verbosity"] = effort
            elif reasoning_config is not None:
                extra_body["reasoning"] = dict(reasoning_config)
            else:
                extra_body["reasoning"] = {"enabled": True, "effort": "medium"}

        return extra_body, top_level


openrouter = OpenRouterProfile(
    name="openrouter",
    aliases=("or",),
    api_mode="chat_completions",
    display_name="OpenRouter",
    description="OpenRouter — unified API for 200+ models from every provider",
    signup_url="https://openrouter.ai/keys",
    env_vars=("OPENROUTER_API_KEY",),
    base_url="https://openrouter.ai/api/v1",
    models_url="https://openrouter.ai/api/v1/models",
    auth_type="api_key",
    supports_vision=True,
    fallback_models=(
        "anthropic/claude-sonnet-4-6",
        "openai/gpt-4o",
        "deepseek/deepseek-chat",
        "google/gemini-2.5-flash-preview",
        "qwen/qwen3-235b-a22b",
    ),
)

register_provider(openrouter)
