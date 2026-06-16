"""Google Gemini provider profile."""

from __future__ import annotations

from typing import Any

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile


class GeminiProfile(ProviderProfile):
    """Gemini — translate reasoning_config → thinking_config in extra_body."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        model: str | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not reasoning_config:
            return {}, {}

        m = (model or "").lower()
        if m.startswith("google/"):
            m = m.split("/", 1)[1]
        if not m.startswith("gemini"):
            return {}, {}

        enabled = reasoning_config.get("enabled", True)
        if not enabled:
            return {"thinking_config": {"includeThoughts": False}}, {}

        effort = str(reasoning_config.get("effort", "medium") or "medium").lower()
        thinking_config: dict[str, Any] = {"includeThoughts": True}

        if m.startswith("gemini-2.5"):
            pass  # includeThoughts is enough for 2.5
        elif m.startswith("gemini-3"):
            level_map = {"minimal": "low", "low": "low", "medium": "medium", "high": "high", "xhigh": "high"}
            thinking_config["thinkingLevel"] = level_map.get(effort, "medium")

        return {"thinking_config": thinking_config}, {}


gemini = GeminiProfile(
    name="gemini",
    aliases=("google", "google-gemini", "google-ai-studio"),
    api_mode="chat_completions",
    display_name="Google Gemini",
    description="Google Gemini — AI Studio API (gemini-2.5-flash, gemini-3-pro, etc.)",
    signup_url="https://aistudio.google.com/app/apikey",
    env_vars=("GOOGLE_API_KEY", "GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai",
    auth_type="api_key",
    supports_vision=True,
    fallback_models=(
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.5-pro-preview-06-05",
    ),
    default_aux_model="gemini-2.5-flash-preview-05-20",
)

register_provider(gemini)
