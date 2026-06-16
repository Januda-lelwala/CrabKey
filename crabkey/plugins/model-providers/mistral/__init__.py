"""Mistral AI provider profile."""

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

mistral = ProviderProfile(
    name="mistral",
    aliases=("mistral-ai",),
    api_mode="chat_completions",
    display_name="Mistral AI",
    description="Mistral AI — Mistral Large, Codestral, Devstral, etc.",
    signup_url="https://console.mistral.ai/api-keys/",
    env_vars=("MISTRAL_API_KEY",),
    base_url="https://api.mistral.ai/v1",
    auth_type="api_key",
    fallback_models=("mistral-large-latest", "codestral-latest", "devstral-small-2505"),
    default_aux_model="mistral-small-latest",
)

register_provider(mistral)
