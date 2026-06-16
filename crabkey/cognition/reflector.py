from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..mal.message import Message, Role
from ..mal.provider import ModelConfig, ModelProvider


@dataclass
class Reflection:
    summary: str
    next_action: str
    confidence: float  # 0.0 – 1.0
    should_continue: bool


_REFLECT_SYSTEM = """\
You are a self-reflection module for an agentic coding assistant.
Given the conversation so far, briefly assess:
1. What was the outcome of the last step?
2. What should the next step be?
3. Should the loop continue (true) or has the goal been met (false)?

Respond in JSON: {"summary": "...", "next_action": "...", "confidence": 0.0-1.0, "should_continue": true/false}
"""


class Reflector:
    """Calls the model to reflect on progress and decide whether to continue the loop."""

    def __init__(self, provider: ModelProvider, config: ModelConfig | None = None) -> None:
        self._provider = provider
        self._config = config or ModelConfig(model="claude-haiku-4-5-20251001", max_tokens=512)

    async def reflect(self, history: list[Message], goal: str) -> Reflection:
        import json

        messages = [
            Message(role=Role.SYSTEM, content=_REFLECT_SYSTEM),
            Message(role=Role.USER, content=f"Goal: {goal}\n\nConversation so far (last 3 turns):\n" +
                    "\n".join(f"[{m.role.value}]: {m.content or ''}" for m in history[-6:])),
        ]
        resp = await self._provider.complete(messages, self._config)
        try:
            data = json.loads(resp.message.content or "{}")
        except json.JSONDecodeError:
            data = {}
        return Reflection(
            summary=data.get("summary", ""),
            next_action=data.get("next_action", ""),
            confidence=float(data.get("confidence", 0.5)),
            should_continue=bool(data.get("should_continue", True)),
        )
