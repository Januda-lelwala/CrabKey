"""Local model provider profile — Ollama, LM Studio, llama.cpp, vLLM.

Reads CRABKEY_LOCAL_URL at call time via get_base_url() so the env var
is not frozen at import time.
"""

import os

from crabkey.mal.provider_registry import register_provider
from crabkey.mal.profile import ProviderProfile

_DEFAULT_LOCAL_URL = "http://localhost:11434/v1"


class LocalProfile(ProviderProfile):
    """Local server — resolves base URL from CRABKEY_LOCAL_URL at each call."""

    def get_base_url(self) -> str:
        return os.environ.get("CRABKEY_LOCAL_URL", _DEFAULT_LOCAL_URL)


local = LocalProfile(
    name="local",
    aliases=("ollama", "lmstudio", "llama-cpp", "vllm"),
    api_mode="chat_completions",
    display_name="Local",
    description="Local model server (Ollama, LM Studio, llama.cpp, vLLM)",
    env_vars=("CRABKEY_LOCAL_URL",),
    base_url=_DEFAULT_LOCAL_URL,  # fallback only; actual URL via get_base_url()
    auth_type="api_key",
    fallback_models=(),
)

register_provider(local)
