"""Pre-flight workspace instruction gathering.

Programmatically reads AGENTS.md (and referenced docs) before the main agent starts,
so workspace instructions are available in the system prompt before security rules run.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from .context import TaskContext

_PREFLIGHT_PROMPT_FILE = Path(__file__).parent / "preflight_prompt.md"
_PREFLIGHT_MODEL = "claude-haiku-4-5-20251001"
_MAX_FILE_CHARS = 4000  # skip instruction files larger than this

# Directories that contain data files — skip these in regex extraction
_DATA_DIRS = {"inbox", "accounts", "contacts", "opportunities", "reminders",
              "my-invoices", "outbox", "01_notes", "00_inbox", "01_capture",
              "02_distill", "04_projects", "07_rfcs"}


def _regex_extract_refs(agents_content: str) -> list[str]:
    """Extract explicit file/dir paths from AGENTS.md using regex.

    Handles:
    - Markdown links: [text](/docs/file.md), [text](../docs)
    - Backtick paths: `docs/`, `/99_process/document_capture.md`
    - Bare absolute paths: /docs/inbox-task-processing.md
    """
    paths: list[str] = []
    seen: set[str] = set()

    # Markdown links: [text](path)
    for m in re.finditer(r"\[.*?\]\(([^)]+)\)", agents_content):
        paths.append(m.group(1))

    # Backtick paths: `/docs/file.md` or `docs/` or `99_process/`
    for m in re.finditer(r"`(/?[\w._-]+(?:/[\w._-]*)*)`", agents_content):
        paths.append(m.group(1))

    # Bare absolute paths (not inside markdown/backticks): /docs/something.md
    for m in re.finditer(r"(?<![(`\w])(/(?:[\w._-]+/)*[\w._-]+\.(?:md|txt|json|yaml|yml))", agents_content):
        paths.append(m.group(1))

    result: list[str] = []
    for p in paths:
        # Normalize: strip trailing slashes, resolve ../
        p = p.strip().rstrip("/")
        if p.startswith(".."):
            p = "/" + p.lstrip("./")
        if not p.startswith("/"):
            p = "/" + p

        # Skip data directories
        top_dir = p.strip("/").split("/")[0]
        if top_dir in _DATA_DIRS:
            continue

        # Skip AGENTS.md itself
        if p.lower().endswith("agents.md"):
            continue

        if p not in seen:
            seen.add(p)
            result.append(p)

    return result


def _get_preflight_prompt() -> str:
    return _PREFLIGHT_PROMPT_FILE.read_text(encoding="utf-8").strip()


async def _llm_extract_refs(
    agents_content: str,
    task_text: str,
    skill_id: str,
    model: str | None = None,
) -> list[str]:
    """LLM call: given AGENTS.md content + task, return list of file paths to read."""
    from claude_agent_sdk import query, ClaudeAgentOptions
    from claude_agent_sdk.types import TextBlock

    prompt = f"AGENTS.md:\n{agents_content}\n\nTask: {task_text}\nSkill: {skill_id or 'unknown'}"

    options_kw: dict = dict(
        system_prompt=_get_preflight_prompt(),
        allowed_tools=[],
        permission_mode="dontAsk",
        max_turns=1,
    )
    options_kw["model"] = model or _PREFLIGHT_MODEL

    options = ClaudeAgentOptions(**options_kw)

    async def _run():
        t = ""
        async for message in query(prompt=prompt, options=options):
            if type(message).__name__ == "AssistantMessage":
                for block in getattr(message, "content", []):
                    if isinstance(block, TextBlock):
                        t += block.text
        return t

    try:
        text = await asyncio.wait_for(_run(), timeout=30)
    except asyncio.TimeoutError:
        print("  [preflight] LLM extract timed out")
        return []
    except Exception as e:
        print(f"  [preflight] LLM extract failed: {e}")
        return []

    for m in re.finditer(r"\[.*?\]", text, re.DOTALL):
        try:
            paths = json.loads(m.group())
            if isinstance(paths, list):
                return [p for p in paths if isinstance(p, str) and p.startswith("/")]
        except (json.JSONDecodeError, ValueError):
            continue
    return []


def format_instructions(collected: dict[str, str]) -> str:
    """Format {path: content} dict as readable block for system prompt or listing prepend."""
    parts = []
    for path, content in collected.items():
        # Strip runtime command header (e.g. "cat /path") — redundant with [/path] label
        if content.startswith(("cat ", "sed ")):
            nl = content.find("\n")
            if nl >= 0:
                content = content[nl + 1:]
        parts.append(f"### {path}\n{content}")
    return "\n\n".join(parts)


async def gather_workspace_instructions(
    ctx: TaskContext,
    path: str = "/",
    listing: str | None = None,
) -> dict[str, str]:
    """Gather AGENTS.md + referenced docs from `path`.

    Returns {filepath: content}. Empty dict if no AGENTS.md found.
    Reads all files into ctx.file_contents cache.
    Marks `path` in ctx.agents_dirs_read to prevent re-processing.
    """
    from .claude_tools import find_agents_file

    norm_path = path.rstrip("/") or "/"

    # Mark as processed so list_directory hook won't repeat
    ctx.agents_dirs_read.add(norm_path)

    # Step 1: get listing
    if listing is None:
        try:
            listing = await ctx.runtime.list_dir(path)
        except Exception:
            return {}

    # Step 2: find and read AGENTS.md
    agents_name = find_agents_file(listing)
    if not agents_name:
        return {}

    agents_path = f"{norm_path}/{agents_name}".replace("//", "/")

    if agents_path in ctx.file_contents:
        agents_content = ctx.file_contents[agents_path]
    else:
        try:
            agents_content = await ctx.runtime.read_file(agents_path, 0, 0, False)
            ctx.file_contents[agents_path] = agents_content
        except Exception:
            return {}

    collected: dict[str, str] = {agents_path: agents_content}

    # Step 3: regex extracts explicit links (instant, always works)
    regex_paths = _regex_extract_refs(agents_content)

    # Step 4: LLM extracts additional refs in parallel with regex file reads
    llm_task = asyncio.create_task(_llm_extract_refs(
        agents_content, ctx.task_text, ctx.skill_id
    ))

    # Step 5: read files; if path is a directory, list it and read .md files inside

    async def _read_or_expand(ref_path: str) -> None:
        if ref_path in ctx.file_contents:
            collected[ref_path] = ctx.file_contents[ref_path]
            return
        # Try reading as a file first
        try:
            content = await ctx.runtime.read_file(ref_path, 0, 0, False)
            if len(content) > _MAX_FILE_CHARS:
                content = content[:_MAX_FILE_CHARS] + f"\n\n[TRUNCATED ({len(content)} chars) — read full file at {ref_path} if needed]"
            ctx.file_contents[ref_path] = content
            collected[ref_path] = content
            return
        except Exception:
            pass
        # If read_file failed, try as a directory — list and read .md files
        try:
            dir_listing = await ctx.runtime.list_dir(ref_path)
            for line in dir_listing.splitlines():
                fname = line.strip()
                if not fname or not fname.lower().endswith(".md"):
                    continue
                fpath = f"{ref_path}/{fname}".replace("//", "/")
                if fpath in ctx.file_contents or fpath in collected:
                    collected[fpath] = ctx.file_contents.get(fpath, collected.get(fpath, ""))
                    continue
                try:
                    content = await ctx.runtime.read_file(fpath, 0, 0, False)
                    if len(content) > _MAX_FILE_CHARS:
                        content = content[:_MAX_FILE_CHARS] + f"\n\n[TRUNCATED ({len(content)} chars) — read full file at {fpath} if needed]"
                    ctx.file_contents[fpath] = content
                    collected[fpath] = content
                except Exception:
                    pass
        except Exception:
            pass

    # Read regex-extracted paths immediately
    seen: set[str] = set()
    for ref_path in regex_paths[:15]:
        if len(collected) >= 20:
            break
        seen.add(ref_path)
        await _read_or_expand(ref_path)

    # Merge LLM results (may already be done by now)
    llm_paths = await llm_task
    for ref_path in llm_paths:
        if len(collected) >= 20:
            break
        if ref_path not in seen:
            seen.add(ref_path)
            await _read_or_expand(ref_path)

    return collected
