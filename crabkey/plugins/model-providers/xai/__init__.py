"""xAI (Grok) provider profile."""

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

xai = ProviderProfile(
    name="xai",
    aliases=("grok", "x-ai", "x.ai"),
    api_mode="chat_completions",
    display_name="xAI",
    description="xAI — Grok models via the xAI API",
    signup_url="https://console.x.ai/",
    env_vars=("XAI_API_KEY",),
    base_url="https://api.x.ai/v1",
    auth_type="api_key",
    supports_vision=True,
    fallback_models=("grok-3", "grok-3-mini", "grok-2-vision-1212"),
    default_aux_model="grok-3-mini",
)

register_provider(xai)
