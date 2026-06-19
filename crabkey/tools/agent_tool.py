from __future__ import annotations

from typing import Any, Awaitable, Callable

from .base import Tool, ToolContext

# Runs a named sub-agent on a task and returns its final textual result.
DispatchFn = Callable[[str, str], Awaitable[str]]


class AgentDispatchTool(Tool):
    """Delegate a focused subtask to a named sub-agent with an isolated context.

    Sub-agents run their own LoopEngine over a fresh history, so their work does
    not pollute the parent's context window. Useful for parallelizable or
    self-contained subtasks (e.g. "investigate why test X fails").
    """

    name = "agent.dispatch"

    def __init__(self, dispatch: DispatchFn, available_agents: list[str]) -> None:
        self._dispatch = dispatch
        self._agents = list(available_agents)

    @property
    def description(self) -> str:
        agents = ", ".join(self._agents) if self._agents else "(none configured)"
        return (
            "Delegate a focused subtask to a sub-agent with an isolated context "
            f"and return its result. Available agents: {agents}."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        agent_schema: dict[str, Any] = {"type": "string", "description": "Name of the sub-agent to run."}
        if self._agents:
            agent_schema["enum"] = self._agents
        return {
            "type": "object",
            "properties": {
                "agent": agent_schema,
                "task": {"type": "string", "description": "The task/instructions for the sub-agent."},
            },
            "required": ["agent", "task"],
        }

    async def run(self, arguments: dict[str, Any], ctx: ToolContext) -> str:
        agent = arguments["agent"]
        task = arguments["task"]
        if self._agents and agent not in self._agents:
            return f"Error: unknown agent {agent!r}. Available: {', '.join(self._agents)}"
        return await self._dispatch(agent, task)
