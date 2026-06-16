"""OpenAI provider profile."""

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

openai_provider = ProviderProfile(
    name="openai",
    aliases=("gpt", "openai-api"),
    api_mode="chat_completions",
    display_name="OpenAI",
    description="OpenAI — GPT-4o, GPT-5, o3, o4-mini and more",
    signup_url="https://platform.openai.com/api-keys",
    env_vars=("OPENAI_API_KEY",),
    base_url="https://api.openai.com/v1",
    auth_type="api_key",
    supports_vision=True,
    fallback_models=(
        "gpt-4o",
        "gpt-4o-mini",
        "o3",
        "o4-mini",
    ),
    default_aux_model="gpt-4o-mini",
)

register_provider(openai_provider)
