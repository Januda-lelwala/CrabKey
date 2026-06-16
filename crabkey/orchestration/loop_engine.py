from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable

from ..cognition.context_assembler import ContextAssembler
from ..cognition.reflector import Reflector
from ..mal.message import Message, Role, ToolCall, ToolResult
from ..mal.provider import ModelConfig, ModelProvider
from ..persistence.db import Db
from ..safety.permission_broker import PermissionBroker
from ..tools.base import ToolContext, ToolRegistry


@dataclass
class LoopConfig:
    max_iterations: int = 20
    reflect_every: int = 5      # call Reflector every N iterations
    stream: bool = True


@dataclass
class StepEvent:
    kind: str                   # "text" | "tool_call" | "tool_result" | "done" | "error"
    data: str = ""
    tool_name: str | None = None
    iteration: int = 0


class LoopEngine:
    """
    Core agentic loop: model → tool call → result → model → …
    Runs until the model emits end_turn, max_iterations is hit, or Reflector says stop.
    """

    def __init__(
        self,
        provider: ModelProvider,
        tools: ToolRegistry,
        assembler: ContextAssembler,
        db: Db,
        broker: PermissionBroker,
        reflector: Reflector | None = None,
        config: LoopConfig | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._assembler = assembler
        self._db = db
        self._broker = broker
        self._reflector = reflector
        self._config = config or LoopConfig()

    async def run(
        self,
        goal: str,
        thread_id: str,
        model_config: ModelConfig,
        working_dir: str,
        on_event: Callable[[StepEvent], None] | None = None,
    ) -> list[Message]:
        history: list[Message] = []
        history.append(Message(role=Role.USER, content=goal))
        tool_ctx = ToolContext(working_dir=working_dir)

        for iteration in range(1, self._config.max_iterations + 1):
            prompt = await self._assembler.build(history, base_system=model_config.system)
            resp = await self._provider.complete(prompt, model_config, tools=self._tools.schemas())

            await self._db.log_cost(thread_id, resp.model, resp.usage.input_tokens, resp.usage.output_tokens)

            if resp.message.content:
                if on_event:
                    on_event(StepEvent(kind="text", data=resp.message.content, iteration=iteration))

            history.append(resp.message)

            if resp.stop_reason == "end_turn" or not resp.message.tool_calls:
                if on_event:
                    on_event(StepEvent(kind="done", iteration=iteration))
                break

            tool_results = await self._dispatch_tools(resp.message.tool_calls, tool_ctx, iteration, on_event)
            tool_msg = Message(role=Role.TOOL, tool_results=tool_results)
            history.append(tool_msg)

            if self._reflector and iteration % self._config.reflect_every == 0:
                reflection = await self._reflector.reflect(history, goal)
                if not reflection.should_continue:
                    if on_event:
                        on_event(StepEvent(kind="done", data=reflection.summary, iteration=iteration))
                    break

        return history

    async def _dispatch_tools(
        self,
        tool_calls: list[ToolCall],
        ctx: ToolContext,
        iteration: int,
        on_event: Callable[[StepEvent], None] | None,
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for tc in tool_calls:
            if on_event:
                on_event(StepEvent(kind="tool_call", tool_name=tc.name, data=str(tc.arguments), iteration=iteration))
            try:
                self._broker.require(tc.name)
                tool = self._tools.get(tc.name)
                output = await tool.run(tc.arguments, ctx)
                is_error = False
            except Exception as exc:
                output = f"Error: {exc}"
                is_error = True
            if on_event:
                on_event(StepEvent(kind="tool_result", tool_name=tc.name, data=output, iteration=iteration))
            results.append(ToolResult(tool_call_id=tc.id, name=tc.name, content=output, is_error=is_error))
        return results
