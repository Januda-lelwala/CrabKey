"""Hugging Face Inference API provider profile."""

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

huggingface = ProviderProfile(
    name="huggingface",
    aliases=("hf", "hugging-face"),
    api_mode="chat_completions",
    display_name="Hugging Face",
    description="Hugging Face Inference API — open-source models",
    signup_url="https://huggingface.co/settings/tokens",
    env_vars=("HF_TOKEN", "HUGGINGFACE_API_KEY"),
    base_url="https://api-inference.huggingface.co/v1",
    auth_type="api_key",
    fallback_models=(
        "meta-llama/Llama-3.3-70B-Instruct",
        "Qwen/Qwen2.5-72B-Instruct",
    ),
)

register_provider(huggingface)
