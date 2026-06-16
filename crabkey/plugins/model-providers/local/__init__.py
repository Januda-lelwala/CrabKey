"""Local model provider profile — Ollama, LM Studio, llama.cpp, vLLM.

Reads base URL from the CRABKEY_LOCAL_URL env var (default: http://localhost:11434/v1).
No API key required for most local servers.
"""

import os

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

_base_url = os.environ.get("CRABKEY_LOCAL_URL", "http://localhost:11434/v1")

local = ProviderProfile(
    name="local",
    aliases=("ollama", "lmstudio", "llama-cpp", "vllm"),
    api_mode="chat_completions",
    display_name="Local",
    description="Local model server (Ollama, LM Studio, llama.cpp, vLLM)",
    env_vars=("CRABKEY_LOCAL_URL",),
    base_url=_base_url,
    auth_type="api_key",
    fallback_models=(),
)

register_provider(local)
