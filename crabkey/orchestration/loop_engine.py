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
from ..safety.checkpoint import Checkpoint
from ..safety.permission_broker import Approver, PermissionBroker
from ..tools.base import ToolContext, ToolRegistry
from .hook_dispatcher import HookDispatcher, HookEvent


# Tools that mutate the workspace and therefore warrant a checkpoint before they run.
DESTRUCTIVE_TOOLS = frozenset({"file.write", "file.edit", "shell.run"})


def representative_arg(tool_name: str, arguments: dict) -> str | None:
    """Pick the most meaningful argument for permission prompts / logging."""
    for key in ("command", "path", "url", "file_path"):
        if key in arguments and isinstance(arguments[key], str):
            return arguments[key]
    return None


@dataclass
class LoopConfig:
    max_iterations: int = 20
    reflect_every: int = 5      # call Reflector every N iterations
    stream: bool = True


@dataclass
class StepEvent:
    kind: str                   # "text" | "text_delta" | "tool_call" | "tool_result" | "done" | "error"
    data: str = ""
    tool_name: str | None = None
    iteration: int = 0
    is_error: bool = False      # set on "tool_result" events when the tool failed


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
        hooks: HookDispatcher | None = None,
        checkpoint: Checkpoint | None = None,
        approver: Approver | None = None,
    ) -> None:
        self._provider = provider
        self._tools = tools
        self._assembler = assembler
        self._db = db
        self._broker = broker
        self._reflector = reflector
        self._config = config or LoopConfig()
        self._hooks = hooks
        self._checkpoint = checkpoint
        self._approver = approver

    async def run(
        self,
        goal: str,
        thread_id: str,
        model_config: ModelConfig,
        working_dir: str,
        on_event: Callable[[StepEvent], None] | None = None,
        history: list[Message] | None = None,
    ) -> list[Message]:
        # When a history list is passed in it is reused and mutated, so the caller
        # can carry a multi-turn conversation across run() calls (e.g. the TUI).
        history = history if history is not None else []
        history.append(Message(role=Role.USER, content=goal))
        tool_ctx = ToolContext(working_dir=working_dir)

        await self._fire(HookEvent.LOOP_START, {"goal": goal, "thread_id": thread_id})
        try:
            for iteration in range(1, self._config.max_iterations + 1):
                await self._fire(HookEvent.PRE_TURN, {"iteration": iteration, "history": history})

                prompt = await self._assembler.build(history, base_system=model_config.system)

                streaming = self._config.stream and hasattr(self._provider, "stream_complete")
                if streaming:
                    def on_text(delta: str, _it: int = iteration) -> None:
                        if on_event:
                            on_event(StepEvent(kind="text_delta", data=delta, iteration=_it))
                    resp = await self._provider.stream_complete(
                        prompt, model_config, tools=self._tools.schemas(), on_text=on_text
                    )
                else:
                    resp = await self._provider.complete(prompt, model_config, tools=self._tools.schemas())

                await self._db.log_cost(thread_id, resp.model, resp.usage.input_tokens, resp.usage.output_tokens)

                # In streaming mode the text was already emitted via text_delta events.
                if resp.message.content and not streaming:
                    if on_event:
                        on_event(StepEvent(kind="text", data=resp.message.content, iteration=iteration))

                history.append(resp.message)
                await self._fire(HookEvent.POST_TURN, {"iteration": iteration, "response": resp})

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
        finally:
            await self._fire(HookEvent.LOOP_END, {"thread_id": thread_id, "history": history})

        return history

    async def _fire(self, event: HookEvent, payload: dict) -> None:
        if self._hooks is not None:
            await self._hooks.fire(event, payload)

    async def _dispatch_tools(
        self,
        tool_calls: list[ToolCall],
        ctx: ToolContext,
        iteration: int,
        on_event: Callable[[StepEvent], None] | None,
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        checkpointed = False
        for tc in tool_calls:
            arg = representative_arg(tc.name, tc.arguments)
            if on_event:
                on_event(StepEvent(kind="tool_call", tool_name=tc.name, data=str(tc.arguments), iteration=iteration))
            await self._fire(HookEvent.PRE_TOOL, {"tool": tc.name, "arguments": tc.arguments})
            try:
                self._broker.require(tc.name, arg, on_ask=self._approver)
                # Snapshot the workspace once per turn before the first mutating call,
                # so a single `crabkey restore` can undo everything this turn did.
                if not checkpointed and tc.name in DESTRUCTIVE_TOOLS and self._checkpoint is not None:
                    await self._checkpoint.create(f"before {tc.name} (iter {iteration})")
                    checkpointed = True
                tool = self._tools.get(tc.name)
                output = await tool.run(tc.arguments, ctx)
                is_error = False
            except Exception as exc:
                output = f"Error: {exc}"
                is_error = True
            if on_event:
                on_event(StepEvent(kind="tool_result", tool_name=tc.name, data=output, iteration=iteration, is_error=is_error))
            await self._fire(HookEvent.POST_TOOL, {"tool": tc.name, "output": output, "is_error": is_error})
            results.append(ToolResult(tool_call_id=tc.id, name=tc.name, content=output, is_error=is_error))
        return results
