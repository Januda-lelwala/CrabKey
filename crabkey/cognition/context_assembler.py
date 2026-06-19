from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from ..mal.message import Message, Role
from .memory_manager import MemoryEntry, MemoryManager

# Summarizes a list of older messages into a compact text note.
Summarizer = Callable[[list[Message]], Awaitable[str]]


@dataclass
class ContextBudget:
    max_tokens: int = 100_000
    system_reserve: int = 2_000
    memory_reserve: int = 8_000
    history_reserve: int = 40_000


class ContextAssembler:
    """
    Decides what enters the prompt on each turn under a token budget.
    Memory stores — ContextAssembler decides what to include this turn.
    """

    def __init__(
        self,
        memory: MemoryManager,
        budget: ContextBudget | None = None,
        summarizer: Summarizer | None = None,
    ) -> None:
        self._memory = memory
        self._budget = budget or ContextBudget()
        self._summarizer = summarizer

    def _rough_tokens(self, text: str) -> int:
        return len(text) // 4

    def _build_system(
        self,
        base_system: str | None,
        context_doc: str | None,
        memories: list[MemoryEntry],
        summary: str | None = None,
    ) -> str:
        parts: list[str] = []
        if base_system:
            parts.append(base_system)
        if context_doc:
            parts.append(f"<project_context>\n{context_doc}\n</project_context>")
        if memories:
            mem_text = "\n".join(f"- {m.text}" for m in memories)
            parts.append(f"<relevant_memories>\n{mem_text}\n</relevant_memories>")
        if summary:
            parts.append(f"<conversation_summary>\n{summary}\n</conversation_summary>")
        return "\n\n".join(parts)

    def _trim_history(self, history: list[Message], token_budget: int) -> list[Message]:
        """Keep the most recent messages that fit inside the budget."""
        kept: list[Message] = []
        used = 0
        for msg in reversed(history):
            tokens = self._rough_tokens(msg.content or "")
            if used + tokens > token_budget:
                break
            kept.append(msg)
            used += tokens
        return list(reversed(kept))

    async def build(
        self,
        history: list[Message],
        base_system: str | None = None,
        memory_query_embedding: list[float] | None = None,
    ) -> list[Message]:
        """Return the full message list to send to the model this turn."""
        context_doc = self._memory.load_context_file()
        memories: list[MemoryEntry] = []
        if memory_query_embedding:
            memories = await self._memory.search(memory_query_embedding, top_k=10)

        system_text = self._build_system(base_system, context_doc, memories)
        history_budget = self._budget.max_tokens - self._rough_tokens(system_text) - self._budget.system_reserve
        trimmed_history = self._trim_history(history, history_budget)

        # If history overflowed and a summarizer is available, compress the dropped
        # older messages into a summary rather than silently discarding them.
        dropped = history[: len(history) - len(trimmed_history)]
        if dropped and self._summarizer is not None:
            summary = await self._summarizer(dropped)
            if summary:
                system_text = self._build_system(base_system, context_doc, memories, summary)

        messages: list[Message] = []
        if system_text:
            messages.append(Message(role=Role.SYSTEM, content=system_text))
        messages.extend(trimmed_history)
        return messages
