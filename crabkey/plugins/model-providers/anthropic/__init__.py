"""Native Anthropic provider profile."""

from __future__ import annotations

import json
import logging
import urllib.request

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

logger = logging.getLogger(__name__)


class AnthropicProfile(ProviderProfile):
    """Anthropic — uses x-api-key header instead of Bearer auth."""

    def fetch_models(self, *, api_key: str | None = None, timeout: float = 8.0) -> list[str] | None:
        if not api_key:
            return None
        try:
            req = urllib.request.Request("https://api.anthropic.com/v1/models")
            req.add_header("x-api-key", api_key)
            req.add_header("anthropic-version", "2023-06-01")
            req.add_header("Accept", "application/json")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            return [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
        except Exception as exc:
            logger.debug("fetch_models(anthropic): %s", exc)
            return None


anthropic = AnthropicProfile(
    name="anthropic",
    aliases=("claude", "claude-code"),
    api_mode="anthropic_messages",
    display_name="Anthropic",
    description="Anthropic — native Claude API (claude-sonnet-*, claude-opus-*, etc.)",
    signup_url="https://console.anthropic.com/",
    env_vars=("ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"),
    base_url="https://api.anthropic.com",
    auth_type="api_key",
    supports_vision=True,
    fallback_models=(
        "claude-sonnet-4-6",
        "claude-opus-4-8",
        "claude-haiku-4-5-20251001",
    ),
    default_aux_model="claude-haiku-4-5-20251001",
)

register_provider(anthropic)
