"""MCP tool server for Claude Agent SDK — PAC1 sandbox tools."""
from __future__ import annotations

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
    "list_skills",
    "get_skill_instructions",
    "submit_answer",
]


def _text(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


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
        return _text(await ctx.runtime.list_dir(args["path"]))

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
        content = await ctx.runtime.read_file(
            path, args["start_line"], args["end_line"], args["number"]
        )
        # Cache content of security-relevant files
        lower = path.lower()
        if "/inbox/" in lower or "agents.md" in lower or "/otp" in lower or "/msg_" in lower:
            ctx.file_contents[path] = content[:1000]
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
        return _text(
            await ctx.runtime.write_file(
                path, args["content"], args["start_line"], args["end_line"]
            )
        )

    @tool("delete_file", "Delete a file or directory.", {"path": str})
    async def _delete_file(args):
        ctx.telemetry.tool_calls += 1
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
        if not refs:
            last = None
            if ctx.files_written:
                last = ctx.files_written[-1]
            elif ctx.files_read:
                last = ctx.files_read[-1]
            if (
                last
                and not last.upper().endswith("README.MD")
                and "/docs/" not in last
                and last != "/AGENTS.md"
            ):
                print(f"  [AUTO-REF] injecting last file: {last}")
                refs = [last]
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
