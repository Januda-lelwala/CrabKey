from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..mal.message import Message, Role
from ..mal.provider import ModelConfig, ModelProvider


@dataclass
class PlanStep:
    index: int
    description: str
    tool_hint: str | None = None


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep] = field(default_factory=list)


_PLAN_SYSTEM = """\
You are a planning module for an agentic coding assistant.
Given a goal, produce a concise numbered plan of steps.
Each step should reference the most likely tool to use.
Available tools: file.read, file.write, file.edit, file.list, shell.run, web.fetch.

Respond with JSON:
{"steps": [{"description": "...", "tool_hint": "file.read"}, ...]}
"""


class Planner:
    """Generates a structured plan for a goal before the loop starts."""

    def __init__(self, provider: ModelProvider, config: ModelConfig | None = None) -> None:
        self._provider = provider
        self._config = config or ModelConfig(model="claude-haiku-4-5-20251001", max_tokens=1024)

    async def plan(self, goal: str) -> Plan:
        messages = [
            Message(role=Role.SYSTEM, content=_PLAN_SYSTEM),
            Message(role=Role.USER, content=f"Goal: {goal}"),
        ]
        resp = await self._provider.complete(messages, self._config)
        try:
            data = json.loads(resp.message.content or "{}")
        except json.JSONDecodeError:
            data = {}
        steps = [
            PlanStep(index=i + 1, description=s["description"], tool_hint=s.get("tool_hint"))
            for i, s in enumerate(data.get("steps", []))
        ]
        return Plan(goal=goal, steps=steps)
