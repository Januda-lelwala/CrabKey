"""DeepSeek provider profile.

DeepSeek V4+ defaults to thinking-mode ON when extra_body.thinking is unset.
This profile explicitly controls thinking/reasoning to avoid the HTTP 400
'reasoning_content must be passed back' error on subsequent turns.
"""

from __future__ import annotations

from typing import Any

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile


def _supports_thinking(model: str | None) -> bool:
    m = (model or "").strip().lower()
    if m.startswith("deepseek-v") and not m.startswith("deepseek-v3"):
        return True
    return m == "deepseek-reasoner"


class DeepSeekProfile(ProviderProfile):
    """DeepSeek — extra_body.thinking + top-level reasoning_effort."""

    def build_api_kwargs_extras(
        self,
        *,
        reasoning_config: dict | None = None,
        model: str | None = None,
        **context: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not _supports_thinking(model):
            return {}, {}

        enabled = not (
            isinstance(reasoning_config, dict)
            and reasoning_config.get("enabled") is False
        )
        extra_body = {"thinking": {"type": "enabled" if enabled else "disabled"}}
        top_level: dict[str, Any] = {}

        if enabled and isinstance(reasoning_config, dict):
            effort = (reasoning_config.get("effort") or "").strip().lower()
            if effort in {"xhigh", "max"}:
                top_level["reasoning_effort"] = "max"
            elif effort in {"low", "medium", "high"}:
                top_level["reasoning_effort"] = effort

        return extra_body, top_level


deepseek = DeepSeekProfile(
    name="deepseek",
    aliases=("deepseek-chat",),
    api_mode="chat_completions",
    display_name="DeepSeek",
    description="DeepSeek — DeepSeek-V3, DeepSeek-V4, DeepSeek-R1",
    signup_url="https://platform.deepseek.com/",
    env_vars=("DEEPSEEK_API_KEY",),
    base_url="https://api.deepseek.com/v1",
    auth_type="api_key",
    fallback_models=("deepseek-chat", "deepseek-reasoner"),
    default_aux_model="deepseek-chat",
)

register_provider(deepseek)
