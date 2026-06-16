from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Any


class HookEvent(str, Enum):
    PRE_TOOL = "pre_tool"
    POST_TOOL = "post_tool"
    PRE_TURN = "pre_turn"
    POST_TURN = "post_turn"
    LOOP_START = "loop_start"
    LOOP_END = "loop_end"


HookHandler = Callable[[HookEvent, dict[str, Any]], Awaitable[None]]


class HookDispatcher:
    """
    Fires named lifecycle hooks so external code (tests, logging, UI) can observe
    or intercept the loop without coupling to loop internals.
    """

    def __init__(self) -> None:
        self._handlers: dict[HookEvent, list[HookHandler]] = {e: [] for e in HookEvent}

    def on(self, event: HookEvent, handler: HookHandler) -> None:
        self._handlers[event].append(handler)

    def off(self, event: HookEvent, handler: HookHandler) -> None:
        self._handlers[event].remove(handler)

    async def fire(self, event: HookEvent, payload: dict[str, Any] | None = None) -> None:
        payload = payload or {}
        for handler in self._handlers[event]:
            await handler(event, payload)
