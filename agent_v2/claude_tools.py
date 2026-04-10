"""MCP tool server for Claude Agent SDK — PAC1 sandbox tools."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from claude_agent_sdk import tool, create_sdk_mcp_server

from .context import TaskContext


# Tool names exposed via the pac1 MCP server.
# Full MCP name: mcp__pac1__{name}
TOOL_NAMES = [
    "get_workspace_context",
    "list_directory_tree",
    "list_directory",
    "read_file",
    "find_files_by_name",
    "search_text",
    "write_file",
    "delete_file",
    "create_directory",
    "move_file",
    "calculate",
    "list_skills",
    "get_skill_instructions",
    "submit_answer",
]


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


def find_file_in_listing(listing: str, target: str) -> str | None:
    """Find a file in a directory listing (case-insensitive). Returns bare filename or None."""
    target_lower = target.lower()
    for line in listing.splitlines():
        name = line.strip().rstrip("/")
        if name.lower() == target_lower:
            return name
    return None


def create_tool_server(ctx: TaskContext):
    """Build an in-process MCP server with all PAC1 tools bound to *ctx*."""

    # ── Sandbox tools ──────────────────────────────────────────

    @tool(
        "get_workspace_context",
        "Get current sandbox date/time (JSON with unixTime and ISO). Call this first.",
        {},
    )
    async def _get_workspace_context(args):
        ctx.telemetry.tool_calls += 1
        return _text(await ctx.runtime.get_context())

    @tool(
        "calculate",
        "Evaluate a Python expression and return the result. Use for date math, counting, sums, etc. "
        "Available: datetime, timedelta, math, sum, len, sorted, min, max. "
        "Examples: 'datetime(2026,3,10) - timedelta(days=45)', '2280 + 285', 'len([x for x in range(10) if x > 5])'",
        {"expression": str},
    )
    async def _calculate(args):
        import math

        ctx.telemetry.tool_calls += 1
        allowed = {
            "datetime": datetime, "timedelta": timedelta,
            "abs": abs, "round": round, "sum": sum, "len": len,
            "min": min, "max": max, "sorted": sorted,
            "int": int, "float": float, "str": str,
            "range": range, "list": list,
            "True": True, "False": False, "math": math,
        }
        def _eval():
            return eval(args["expression"], {"__builtins__": {}}, allowed)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_eval), timeout=5
            )
            if isinstance(result, datetime):
                return _text(result.strftime("%Y-%m-%d"))
            if isinstance(result, timedelta):
                return _text(str(result.days))
            return _text(str(result))
        except asyncio.TimeoutError:
            return _text("Error: expression timed out (5s limit)")
        except Exception as e:
            return _text(f"Error: {e}")

    @tool(
        "list_directory_tree",
        "List directory tree structure recursively. root: start dir (default '/'), level: max depth (default 2, 0=unlimited).",
        {"root": str, "level": int},
    )
    async def _list_directory_tree(args):
        ctx.telemetry.tool_calls += 1
        return _text(await ctx.runtime.tree(args["root"], args["level"]))

    @tool(
        "list_directory",
        "List directory contents. path: directory to list (default '/').",
        {"path": str},
    )
    async def _list_directory(args):
        ctx.telemetry.tool_calls += 1
        path = args.get("path", "/")
        result = await ctx.runtime.list_dir(path)
        norm_path = path.rstrip("/") or "/"
        if norm_path not in ctx.agents_dirs_read:
            from .preflight import gather_workspace_instructions, format_instructions
            collected = await gather_workspace_instructions(ctx, norm_path, listing=result)
            if collected:
                block = format_instructions(collected)
                return _text(
                    f"[Workspace instructions for {norm_path}]\n{block}"
                    f"\n\n[Directory listing for {norm_path}]\n{result}"
                )
        return _text(result)

    @tool(
        "read_file",
        "Read file. start_line/end_line: 1-based line range, pass 0 for full file. number: show line numbers (false).",
        {"path": str, "start_line": int, "end_line": int, "number": bool},
    )
    async def _read_file(args):
        ctx.telemetry.tool_calls += 1
        path = args["path"]
        if path not in ctx.files_read:
            ctx.files_read.append(path)
        # Cache only full-file reads without line numbers
        is_full_read = args["start_line"] == 0 and args["end_line"] == 0 and not args["number"]
        if is_full_read and path in ctx.file_contents:
            return _text(ctx.file_contents[path])
        content = await ctx.runtime.read_file(
            path, args["start_line"], args["end_line"], args["number"]
        )
        if is_full_read:
            ctx.file_contents[path] = content
        return _text(content)

    @tool(
        "find_files_by_name",
        "Find files or directories by name pattern. kind: 'all'|'files'|'dirs'. limit: 1-100.",
        {"name": str, "root": str, "kind": str, "limit": int},
    )
    async def _find_files_by_name(args):
        ctx.telemetry.tool_calls += 1
        return _text(
            await ctx.runtime.find_files(
                args["name"], args["root"], args["kind"], min(args["limit"], 100)
            )
        )

    @tool(
        "search_text",
        "Full-text regex search across files. For counting queries set limit=1000+. Max 2000.",
        {"pattern": str, "root": str, "limit": int},
    )
    async def _search_text(args):
        ctx.telemetry.tool_calls += 1
        return _text(
            await ctx.runtime.search(
                args["pattern"], args["root"], min(args["limit"], 2000)
            )
        )

    @tool(
        "write_file",
        "Write/create file. start_line/end_line for partial writes (0 = overwrite entire file).",
        {"path": str, "content": str, "start_line": int, "end_line": int},
    )
    async def _write_file(args):
        ctx.telemetry.tool_calls += 1
        path = args["path"]
        if path not in ctx.files_written:
            ctx.files_written.append(path)
        ctx.file_contents.pop(path, None)
        return _text(
            await ctx.runtime.write_file(
                path, args["content"], args["start_line"], args["end_line"]
            )
        )

    @tool("delete_file", "Delete a file or directory.", {"path": str})
    async def _delete_file(args):
        ctx.telemetry.tool_calls += 1
        ctx.file_contents.pop(args["path"], None)
        return _text(await ctx.runtime.delete(args["path"]))

    @tool("create_directory", "Create a new directory.", {"path": str})
    async def _create_directory(args):
        ctx.telemetry.tool_calls += 1
        return _text(await ctx.runtime.mkdir(args["path"]))

    @tool(
        "move_file",
        "Move or rename a file/directory.",
        {"from_path": str, "to_path": str},
    )
    async def _move_file(args):
        ctx.telemetry.tool_calls += 1
        ctx.file_contents.pop(args["from_path"], None)
        ctx.file_contents.pop(args["to_path"], None)
        return _text(await ctx.runtime.move(args["from_path"], args["to_path"]))

    # ── Skill tools ────────────────────────────────────────────

    @tool(
        "list_skills",
        "List available skill workflows. Use if unsure which workflow to follow.",
        {},
    )
    async def _list_skills(args):
        from .skills.registry import SKILL_REGISTRY
        lines = [f"- {sid}: {s.description}" for sid, s in SKILL_REGISTRY.items()]
        return _text("\n".join(lines))

    @tool(
        "get_skill_instructions",
        "Get detailed workflow instructions for a skill. Call this before acting on any task.",
        {"skill_id": str},
    )
    async def _get_skill_instructions(args):
        from .skills.registry import SKILL_REGISTRY
        skill = SKILL_REGISTRY.get(args["skill_id"])
        if not skill:
            return _text(f"Unknown skill_id '{args['skill_id']}'. Call list_skills.")
        return _text(skill.prompt or f"No instructions for {args['skill_id']}.")

    # ── Completion ─────────────────────────────────────────────

    @tool(
        "submit_answer",
        "Submit the final answer. MUST be the last action in every task. "
        "outcome: OUTCOME_OK | OUTCOME_DENIED_SECURITY | OUTCOME_NONE_CLARIFICATION | "
        "OUTCOME_NONE_UNSUPPORTED | OUTCOME_ERR_INTERNAL. "
        "grounding_refs: list of exact file paths that support the answer.",
        {"message": str, "outcome": str, "grounding_refs": list},
    )
    async def _submit_answer(args):
        ctx.telemetry.tool_calls += 1
        ctx.completion_submitted = True
        refs = args.get("grounding_refs", [])

        # Auto-merge: add files the model read/wrote but forgot to include
        skip_names = {"readme.md", "agents.md"}
        skip_prefixes = ("/docs/",)
        all_files = set(refs)
        for f in ctx.files_read + ctx.files_written:
            basename = (f.rsplit("/", 1)[-1] if "/" in f else f).lower()
            if basename in skip_names or any(f.lower().startswith(p) for p in skip_prefixes):
                continue
            if f not in all_files:
                print(f"  [AUTO-REF] adding missing ref: {f}")
                all_files.add(f)
        refs = list(all_files)

        return _text(await ctx.runtime.answer(args["message"], args["outcome"], refs))

    # ── Server ─────────────────────────────────────────────────

    return create_sdk_mcp_server(
        name="pac1",
        tools=[
            _get_workspace_context,
            _list_directory_tree,
            _list_directory,
            _read_file,
            _find_files_by_name,
            _search_text,
            _write_file,
            _delete_file,
            _create_directory,
            _move_file,
            _list_skills,
            _get_skill_instructions,
            _submit_answer,
        ],
    )
