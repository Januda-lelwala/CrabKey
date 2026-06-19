"""Lightweight, dependency-free tracing for the agent loop, with optional OTel.

Telemetry attaches to the HookDispatcher (the same lifecycle hooks the loop
fires) and records structured events. It always keeps events in memory; if a
trace file is given it also appends JSONL; if `otel=True` and OpenTelemetry is
installed it emits properly nested spans. Nothing here is required for the loop
to run — it degrades to a no-op.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..orchestration.hook_dispatcher import HookEvent

# Which lifecycle events open vs. close a span, and the span name to use.
_SPAN_OPEN = {
    HookEvent.LOOP_START: "crabkey.loop",
    HookEvent.PRE_TURN: "crabkey.turn",
    HookEvent.PRE_TOOL: "crabkey.tool",
}
_SPAN_CLOSE = {HookEvent.LOOP_END, HookEvent.POST_TURN, HookEvent.POST_TOOL}

# Only small, safe fields are recorded as attributes (never full tool output).
_ATTR_KEYS = ("tool", "iteration", "is_error", "thread_id")


def _safe_attrs(payload: dict[str, Any]) -> dict[str, Any]:
    attrs = {k: payload[k] for k in _ATTR_KEYS if k in payload}
    if "goal" in payload and isinstance(payload["goal"], str):
        attrs["goal"] = payload["goal"][:120]
    return attrs


class Telemetry:
    def __init__(self, trace_file: str | Path | None = None, otel: bool = False) -> None:
        self.trace_file = Path(trace_file) if trace_file else None
        self.events: list[dict[str, Any]] = []
        self._tracer = _try_otel_tracer() if otel else None
        self._span_stack: list[Any] = []

    def register(self, dispatcher) -> None:
        for event in HookEvent:
            dispatcher.on(event, self._handle)

    async def _handle(self, event: HookEvent, payload: dict[str, Any]) -> None:
        attrs = _safe_attrs(payload)
        record = {"event": event.value, "ts": time.time(), "attrs": attrs}
        self.events.append(record)

        if self.trace_file is not None:
            with self.trace_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")

        if self._tracer is not None:
            self._handle_span(event, attrs)

    def _handle_span(self, event: HookEvent, attrs: dict[str, Any]) -> None:
        if event in _SPAN_OPEN:
            span = self._tracer.start_span(_SPAN_OPEN[event])
            for k, v in attrs.items():
                span.set_attribute(k, v)
            self._span_stack.append(span)
        elif event in _SPAN_CLOSE and self._span_stack:
            self._span_stack.pop().end()

    # Convenience for tests / summaries.
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self.events:
            counts[e["event"]] = counts.get(e["event"], 0) + 1
        return counts


def _try_otel_tracer():
    """Return an OpenTelemetry tracer if the package is importable, else None."""
    try:
        from opentelemetry import trace  # type: ignore
    except ImportError:
        return None
    return trace.get_tracer("crabkey")
