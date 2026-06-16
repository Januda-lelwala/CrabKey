"""Ollama Cloud provider profile."""

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

ollama_cloud = ProviderProfile(
    name="ollama-cloud",
    aliases=("ollama-hosted",),
    api_mode="chat_completions",
    display_name="Ollama Cloud",
    description="Ollama Cloud — hosted open-source models",
    signup_url="https://ollama.com/",
    env_vars=("OLLAMA_API_KEY",),
    base_url="https://ollama.com/v1",
    auth_type="api_key",
    fallback_models=(
        "llama3.3:70b",
        "qwen2.5-coder:32b",
        "deepseek-r1:70b",
    ),
)

register_provider(ollama_cloud)
