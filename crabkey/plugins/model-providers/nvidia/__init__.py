"""NVIDIA NIM provider profile."""

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

nvidia = ProviderProfile(
    name="nvidia",
    aliases=("nim", "nvidia-nim"),
    api_mode="chat_completions",
    display_name="NVIDIA NIM",
    description="NVIDIA NIM — hosted Llama, Mistral, Nemotron and more",
    signup_url="https://build.nvidia.com/",
    env_vars=("NVIDIA_API_KEY", "NGC_API_KEY"),
    base_url="https://integrate.api.nvidia.com/v1",
    auth_type="api_key",
    fallback_models=(
        "meta/llama-3.3-70b-instruct",
        "nvidia/llama-3.1-nemotron-ultra-253b-v1",
    ),
)

register_provider(nvidia)
