"""Agent runner using Claude Agent SDK.

Authentication: uses the standard Claude Code credential chain —
  1. ANTHROPIC_API_KEY env var (direct API key)
  2. ANTHROPIC_AUTH_TOKEN env var (Bearer token for proxies)
  3. Subscription OAuth credentials from `claude login` (Pro/Max/Team/Enterprise)

Set CLAUDE_MODEL to override the model (e.g. claude-sonnet-4-20250514).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from claude_agent_sdk import query, ClaudeAgentOptions

from .claude_tools import TOOL_NAMES, create_tool_server
from .context import TaskContext, Telemetry
from .prompts import build_task_prompt, get_system_prompt_with_skills

CLI_DIM = "\x1B[2m"
CLI_CYAN = "\x1B[36m"
CLI_GREEN = "\x1B[32m"
CLI_YELLOW = "\x1B[33m"
CLI_CLR = "\x1B[0m"


@dataclass(frozen=True)
class ClaudeConfig:
    """Configuration for the Claude Agent SDK runner."""

    model: str | None
    bitgn_api_key: str | None
    benchmark_host: str
    benchmark_id: str
    run_name: str
    max_turns: int
    concurrency: int

    @classmethod
    def from_env(cls) -> ClaudeConfig:
        return cls(
            model=os.getenv("CLAUDE_MODEL") or None,
            bitgn_api_key=os.getenv("BITGN_API_KEY"),
            benchmark_host=os.getenv("BENCHMARK_HOST", "https://api.bitgn.com"),
            benchmark_id=os.getenv("BENCHMARK_ID", "bitgn/pac1-dev"),
            run_name=os.getenv("BITGN_RUN_NAME", "claude-agent-run"),
            max_turns=int(os.getenv("AGENT_MAX_TURNS", "50")),
            concurrency=int(os.getenv("AGENT_CONCURRENCY", "10")),
        )


def _extract_fallback_answer(text: str) -> tuple[str, str, list[str]]:
    """Try to parse agent text output into (message, outcome, refs)."""
    try:
        for m in re.finditer(r"\{[^{}]*\}", text, re.DOTALL):
            obj = json.loads(m.group())
            if "message" in obj and "outcome" in obj:
                return (
                    str(obj["message"]),
                    str(obj["outcome"]),
                    list(obj.get("grounding_refs", [])),
                )
    except (json.JSONDecodeError, KeyError):
        pass
    refs = re.findall(r"/[\w._-]+(?:/[\w._-]+)+", text)
    return text[:500], "OUTCOME_OK", refs[:5]


async def run_task_claude(
    cfg: ClaudeConfig,
    runtime_url: str,
    task_text: str,
    task_id: str = "",
    on_event=None,
) -> Telemetry:
    """Run a single benchmark task using Claude Agent SDK."""

    telemetry = Telemetry()
    context = TaskContext(
        runtime_url=runtime_url,
        task_text=task_text,
        telemetry=telemetry,
    )

    # ── Classification (LLM first, regex fallback) ─────────────
    from .skills import classify_task, classify_with_claude

    # Try Claude LLM classification first
    try:
        match = await classify_with_claude(task_text, model=cfg.model)
        classifier_type = "llm"
    except Exception:
        match = classify_task(task_text)
        classifier_type = "regex"

    # Fallback to regex if LLM returned nothing or low-value "clarification"
    if not match.skill_id or match.skill_id == "clarification":
        regex_match = classify_task(task_text)
        if regex_match.skill_id and regex_match.skill_id != "clarification":
            match = regex_match
            classifier_type = "regex"
        elif not match.skill_id:
            match = regex_match
            classifier_type = "regex"

    if match.skill_id:
        print(
            f"  {task_id} skill: {match.skill_id} "
            f"({match.confidence:.0%}) [{classifier_type}]"
        )
    if on_event:
        on_event(
            "task_classified",
            {
                "task_id": task_id,
                "skill_id": match.skill_id,
                "skill_confidence": match.confidence,
                "classifier": classifier_type,
            },
        )

    # ── Prompts ────────────────────────────────────────────────
    system_prompt = get_system_prompt_with_skills()
    prompt = build_task_prompt(task_text, match.skill_id or None)

    # ── MCP tool server bound to this task ─────────────────────
    tool_server = create_tool_server(context)

    allowed = [f"mcp__pac1__{n}" for n in TOOL_NAMES]
    disallowed = [
        "Read",
        "Write",
        "Edit",
        "Bash",
        "Glob",
        "Grep",
        "WebSearch",
        "WebFetch",
        "Agent",
        "AskUserQuestion",
        "NotebookEdit",
        "TodoWrite",
    ]

    options_kw: dict = dict(
        system_prompt=system_prompt,
        mcp_servers={"pac1": tool_server},
        allowed_tools=allowed,
        disallowed_tools=disallowed,
        permission_mode="dontAsk",
        max_turns=cfg.max_turns,
        # Sandbox: restrict local filesystem/network access.
        # The agent operates on remote BitGN VMs via gRPC (MCP tools),
        # so it should not touch the local filesystem at all.
        sandbox={
            "enabled": True,
            "autoAllowBashIfSandboxed": False,
            "allowUnsandboxedCommands": False,
            "network": {
                "allowLocalBinding": False,
            },
        },
    )
    if cfg.model:
        options_kw["model"] = cfg.model

    options = ClaudeAgentOptions(**options_kw)

    # ── Run agent loop ─────────────────────────────────────────
    step = 0
    last_text = ""

    try:
        async for message in query(prompt=prompt, options=options):
            mt = type(message).__name__

            if mt == "AssistantMessage":
                for block in getattr(message, "content", []):
                    bt = getattr(block, "type", "")
                    if bt == "tool_use":
                        step += 1
                        name = getattr(block, "name", "")
                        print(
                            f"  {CLI_CYAN}{task_id} -> {name}{CLI_CLR}",
                            flush=True,
                        )
                        if on_event:
                            on_event(
                                "tool_start",
                                {"task_id": task_id, "tool": name, "step": step},
                            )
                    elif bt == "tool_result":
                        rtext = ""
                        for part in getattr(block, "content", []):
                            if hasattr(part, "text"):
                                rtext += part.text
                        preview = rtext.replace("\n", " ")[:120]
                        print(
                            f"  {CLI_DIM}=> {preview}{CLI_CLR}",
                            flush=True,
                        )
                        if on_event:
                            on_event(
                                "tool_end",
                                {
                                    "task_id": task_id,
                                    "step": step,
                                    "result": rtext[:2000],
                                },
                            )
                    elif bt == "text":
                        t = getattr(block, "text", "")
                        if t:
                            last_text = t
                            print(
                                f"  {CLI_DIM}{task_id} text: {t[:200]}{CLI_CLR}",
                                flush=True,
                            )

            elif mt == "ResultMessage":
                usage = getattr(message, "usage", None)
                if isinstance(usage, dict):
                    telemetry.input_tokens = usage.get("input_tokens", 0)
                    telemetry.output_tokens = usage.get("output_tokens", 0)
                    telemetry.total_tokens = (
                        telemetry.input_tokens + telemetry.output_tokens
                    )
                cost = getattr(message, "total_cost_usd", 0) or 0
                subtype = getattr(message, "subtype", "")
                result_val = getattr(message, "result", "") or last_text
                print(f"  {task_id} result: {subtype} (${cost:.4f})")
                if on_event:
                    on_event(
                        "agent_output",
                        {
                            "task_id": task_id,
                            "output": str(result_val)[:1000],
                            "subtype": subtype,
                            "cost_usd": cost,
                            "completion_submitted": context.completion_submitted,
                        },
                    )

        # Fallback: report_completion was never called
        if not context.completion_submitted:
            print("  [FALLBACK] report_completion not called, submitting from text")
            msg, outcome, refs = _extract_fallback_answer(last_text)
            await context.runtime.answer(msg, outcome, refs)
            if on_event:
                on_event(
                    "fallback_submit",
                    {"task_id": task_id, "message": msg, "outcome": outcome},
                )

    except Exception as exc:
        print(f"  Agent error: {exc}")
        if not context.completion_submitted:
            try:
                await context.runtime.answer(
                    message=f"Agent internal error: {exc}",
                    outcome="OUTCOME_ERR_INTERNAL",
                    refs=["/AGENTS.md"],
                )
            except Exception:
                pass
    finally:
        telemetry.finish()

    return telemetry
