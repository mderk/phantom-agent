"""Realtime logging hooks for the agent run."""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from agents import RunHooks
from agents.tool import FunctionTool

from .context import TaskContext

CLI_DIM = "\x1B[2m"
CLI_CYAN = "\x1B[36m"
CLI_GREEN = "\x1B[32m"
CLI_YELLOW = "\x1B[33m"
CLI_CLR = "\x1B[0m"


class LiveHooks(RunHooks[TaskContext]):
    """Prints every action and optionally emits SSE events."""

    def __init__(
        self,
        task_id: str,
        on_event: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.task_id = task_id
        self.step = 0
        self.llm_start_time: float = 0
        self._on_event = on_event

    def _emit(self, event_type: str, data: dict) -> None:
        if self._on_event:
            self._on_event(event_type, {"task_id": self.task_id, **data})

    async def on_llm_start(self, context, agent, system_prompt, input_items) -> None:
        self.step += 1
        self.llm_start_time = time.time()
        print(f"  {CLI_DIM}{self.task_id} step {self.step}: thinking...{CLI_CLR}", flush=True)
        self._emit("llm_start", {"step": self.step})

    async def on_llm_end(self, context, agent, response) -> None:
        elapsed = int((time.time() - self.llm_start_time) * 1000)
        # Extract full response text and tool calls
        output_text = ""
        tool_calls = []
        try:
            if hasattr(response, "output"):
                for item in response.output:
                    if hasattr(item, "content"):
                        for part in item.content:
                            if hasattr(part, "text"):
                                output_text += part.text
                    # Capture tool call names
                    item_type = getattr(item, "type", "")
                    if item_type == "function_call" or hasattr(item, "call_id"):
                        name = getattr(item, "name", "") or getattr(item, "function", {}).get("name", "")
                        if name:
                            tool_calls.append(name)
        except Exception:
            pass

        # Track token usage
        usage_info = ""
        try:
            if hasattr(response, "usage") and response.usage:
                u = response.usage
                ctx = context.context
                ctx.telemetry.input_tokens += u.input_tokens or 0
                ctx.telemetry.output_tokens += u.output_tokens or 0
                ctx.telemetry.total_tokens += u.total_tokens or 0
                usage_info = f" [{u.input_tokens}+{u.output_tokens}={u.total_tokens}tok]"
        except Exception:
            pass

        has_tools = "+" + ",".join(tool_calls) if tool_calls else ""
        print(
            f"  {CLI_DIM}{self.task_id} step {self.step}: "
            f"LLM responded ({elapsed}ms){has_tools}{usage_info}{CLI_CLR}",
            flush=True,
        )
        if output_text:
            print(f"  {CLI_DIM}{self.task_id} LLM text: {output_text[:500]}{CLI_CLR}", flush=True)

        self._emit("llm_end", {
            "step": self.step,
            "elapsed_ms": elapsed,
            "output_preview": output_text[:2000] if output_text else "",
            "tool_calls": tool_calls,
        })

    async def on_tool_start(self, context, agent, tool) -> None:
        name = tool.name if isinstance(tool, FunctionTool) else str(tool)
        print(f"  {CLI_CYAN}{self.task_id} -> {name}{CLI_CLR}", end="", flush=True)
        self._emit("tool_start", {"tool": name, "step": self.step})

    async def on_tool_end(self, context, agent, tool, result) -> None:
        name = tool.name if isinstance(tool, FunctionTool) else str(tool)
        result_text = result or ""
        preview = result_text.replace("\n", " ")[:120]
        if name == "submit_answer":
            print(f" {CLI_GREEN}[DONE]{CLI_CLR} {preview}")
        else:
            print(f" {CLI_DIM}=> {preview}{CLI_CLR}")

        self._emit("tool_end", {
            "tool": name,
            "step": self.step,
            "result": result_text[:2000],
            "result_lines": len(result_text.split("\n")) if result_text else 0,
        })
