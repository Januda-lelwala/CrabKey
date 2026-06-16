from __future__ import annotations

from typing import AsyncIterator

from ..adapters.openai import OpenAIAdapter


class LocalAdapter(OpenAIAdapter):
    """Adapter for local models served via an OpenAI-compatible API (Ollama, llama.cpp, etc.)."""

    def __init__(self, base_url: str = "http://localhost:11434/v1", api_key: str = "local") -> None:
        super().__init__(api_key=api_key, base_url=base_url)

    @property
    def name(self) -> str:
        return "local"
