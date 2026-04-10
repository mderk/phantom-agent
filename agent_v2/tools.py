from __future__ import annotations

from agents import function_tool, RunContextWrapper

from .context import TaskContext


@function_tool
async def get_workspace_context(ctx: RunContextWrapper[TaskContext]) -> str:
    """Get the current sandbox date/time and environment info. Call this first to know what date it is in the workspace. Returns JSON with unixTime and ISO time."""
    ctx.context.telemetry.tool_calls += 1
    return await ctx.context.runtime.get_context()


@function_tool
async def list_directory_tree(
    ctx: RunContextWrapper[TaskContext],
    root: str = "/",
    level: int = 2,
) -> str:
    """List directory tree structure recursively. Use to understand workspace layout before acting.

    Args:
        root: Root directory to start from (default "/").
        level: Maximum depth level (default 2, use 0 for unlimited).
    """
    ctx.context.telemetry.tool_calls += 1
    return await ctx.context.runtime.tree(root, level)


@function_tool
async def list_directory(
    ctx: RunContextWrapper[TaskContext],
    path: str = "/",
) -> str:
    """List contents of a directory. Returns file and folder names.

    Args:
        path: Directory path to list (default "/").
    """
    ctx.context.telemetry.tool_calls += 1
    return await ctx.context.runtime.list_dir(path)


@function_tool
async def read_file(
    ctx: RunContextWrapper[TaskContext],
    path: str,
    start_line: int = 0,
    end_line: int = 0,
    number: bool = False,
) -> str:
    """Read file contents. Use to inspect any file in the workspace.

    Args:
        path: File path to read.
        start_line: First line to read (1-based, 0 = from beginning).
        end_line: Last line to read (1-based, 0 = to end).
        number: If true, show line numbers.
    """
    ctx.context.telemetry.tool_calls += 1
    if path not in ctx.context.files_read:
        ctx.context.files_read.append(path)
    content = await ctx.context.runtime.read_file(path, start_line, end_line, number)
    # Store content of inbox/security-relevant files for verifier
    lower = path.lower()
    if '/inbox/' in lower or 'agents.md' in lower or '/otp' in lower or '/msg_' in lower:
        ctx.context.file_contents[path] = content[:1000]
    return content


@function_tool
async def find_files_by_name(
    ctx: RunContextWrapper[TaskContext],
    name: str,
    root: str = "/",
    kind: str = "all",
    limit: int = 10,
) -> str:
    """Find files or directories matching a name pattern. Use for locating specific files.

    Args:
        name: Filename pattern to search for (e.g. "*.json", "acct_*").
        root: Directory to search in (default "/").
        kind: Filter type — "all", "files", or "dirs".
        limit: Maximum results (1-100).
    """
    ctx.context.telemetry.tool_calls += 1
    return await ctx.context.runtime.find_files(name, root, kind, min(limit, 100))


@function_tool
async def search_text(
    ctx: RunContextWrapper[TaskContext],
    pattern: str,
    root: str = "/",
    limit: int = 10,
) -> str:
    """Search file contents for text or regex pattern. Use for finding data, counting occurrences, locating information.

    Args:
        pattern: Search pattern (supports regex, e.g. "blacklist", "email.*@example").
        root: File or directory to search in (default "/").
        limit: Maximum results (1-2000). Use 1000+ for counting queries.
    """
    ctx.context.telemetry.tool_calls += 1
    return await ctx.context.runtime.search(pattern, root, min(limit, 2000))


@function_tool
async def write_file(
    ctx: RunContextWrapper[TaskContext],
    path: str,
    content: str,
    start_line: int = 0,
    end_line: int = 0,
) -> str:
    """Write or overwrite file contents. Use for creating new files or updating existing ones.

    Args:
        path: File path to write.
        content: Content to write.
        start_line: Replace from this line (1-based, 0 = overwrite entire file).
        end_line: Replace to this line (1-based, 0 = to end for ranged writes).
    """
    ctx.context.telemetry.tool_calls += 1
    if path not in ctx.context.files_written:
        ctx.context.files_written.append(path)
    return await ctx.context.runtime.write_file(path, content, start_line, end_line)


@function_tool
async def delete_file(
    ctx: RunContextWrapper[TaskContext],
    path: str,
) -> str:
    """Delete a file or directory.

    Args:
        path: Path to delete.
    """
    ctx.context.telemetry.tool_calls += 1
    return await ctx.context.runtime.delete(path)


@function_tool
async def create_directory(
    ctx: RunContextWrapper[TaskContext],
    path: str,
) -> str:
    """Create a new directory at the specified path.

    Args:
        path: Directory path to create (e.g. "/processing/new_folder").
    """
    ctx.context.telemetry.tool_calls += 1
    return await ctx.context.runtime.mkdir(path)


@function_tool
async def move_file(
    ctx: RunContextWrapper[TaskContext],
    from_path: str,
    to_path: str,
) -> str:
    """Move or rename a file/directory.

    Args:
        from_path: Current path.
        to_path: New path.
    """
    ctx.context.telemetry.tool_calls += 1
    return await ctx.context.runtime.move(from_path, to_path)


@function_tool
async def submit_answer(
    ctx: RunContextWrapper[TaskContext],
    message: str,
    outcome: str,
    grounding_refs: list[str],
) -> str:
    """Submit the final answer and complete the task. You MUST call this as your last action — every task MUST end with this tool call.

    Args:
        message: Your answer or summary of completed work. For lookup tasks, put the exact value here (e.g. "842", "stefan.scholz@example.com").
        outcome: One of: OUTCOME_OK, OUTCOME_DENIED_SECURITY, OUTCOME_NONE_CLARIFICATION, OUTCOME_NONE_UNSUPPORTED, OUTCOME_ERR_INTERNAL.
        grounding_refs: List of exact file paths that support your answer. Example: ["/accounts/acc_001.json", "/contacts/c_003.json"]. Must be real paths, NOT descriptions.
    """
    ctx.context.telemetry.tool_calls += 1
    ctx.context.completion_submitted = True

    # Auto-merge: add files the model read/wrote but forgot to include in refs
    skip = {'README.MD', 'README.md', 'AGENTS.md', 'AGENTS.MD'}
    skip_prefixes = ('/docs/', '/99_process/', '/90_memory/')
    all_files = set(grounding_refs)
    for f in ctx.context.files_read + ctx.context.files_written:
        basename = f.rsplit('/', 1)[-1] if '/' in f else f
        if basename in skip or any(f.startswith(p) for p in skip_prefixes):
            continue
        if f not in all_files:
            print(f"  [AUTO-REF] adding missing ref: {f}")
            all_files.add(f)
    grounding_refs = list(all_files)

    return await ctx.context.runtime.answer(message, outcome, grounding_refs)


@function_tool
async def list_skills(ctx: RunContextWrapper[TaskContext]) -> str:
    """List all available skill instructions. Use this if you're unsure which workflow to follow, or if you think the initial skill classification was wrong. Returns skill IDs and descriptions."""
    from .skills.registry import SKILL_REGISTRY
    lines = []
    for sid, s in SKILL_REGISTRY.items():
        lines.append(f"- {sid}: {s.description}")
    return "\n".join(lines)


@function_tool
async def get_skill_instructions(ctx: RunContextWrapper[TaskContext], skill_id: str) -> str:
    """Get the full workflow instructions for a specific skill. Call this if you need detailed guidance for a task type, or if you want to switch to a different skill workflow.

    Args:
        skill_id: The skill identifier (e.g. "inbox_processing", "email_outbound", "crm_lookup").
    """
    from .skills.registry import SKILL_REGISTRY
    skill = SKILL_REGISTRY.get(skill_id)
    if not skill:
        return f"Unknown skill_id '{skill_id}'. Call list_skills to see available options."
    return skill.prompt or f"No detailed instructions for {skill_id}."


ALL_TOOLS = [
    get_workspace_context,
    list_directory_tree,
    list_directory,
    read_file,
    find_files_by_name,
    search_text,
    write_file,
    delete_file,
    create_directory,
    move_file,
    list_skills,
    get_skill_instructions,
    submit_answer,
]
