"""Groq provider profile — ultra-fast LLM inference."""

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

groq = ProviderProfile(
    name="groq",
    aliases=("groq-cloud",),
    api_mode="chat_completions",
    display_name="Groq",
    description="Groq — ultra-fast inference for Llama, Gemma, Qwen, etc.",
    signup_url="https://console.groq.com/keys",
    env_vars=("GROQ_API_KEY",),
    base_url="https://api.groq.com/openai/v1",
    auth_type="api_key",
    fallback_models=(
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "qwen-qwq-32b",
    ),
    default_aux_model="llama-3.1-8b-instant",
)

register_provider(groq)
