from __future__ import annotations

from pathlib import Path

_PROMPT_FILE = Path(__file__).parent / "system_prompt.md"

_PHASE1_FULL = """\
TWO MANDATORY PHASES — never skip or reorder:

PHASE 1 — GATHER ALL INSTRUCTIONS (always before touching task data):
1. list_directory "/" to see workspace structure
2. Find the workspace instruction file at root — search case-insensitively: AGENTS.md / AGENTS.MD / agents.md
3. Read it completely
4. Follow all doc references in the instruction file:
   - Unconditional ("read docs/X") → read it now
   - Conditional ("read docs/X before handling Y") → read it if the current task could involve Y, or if unsure
   - When in doubt, read it — a few extra tool calls are cheaper than missing critical context
5. Before entering any subdirectory to read or write — check if it contains an AGENTS.md (case-insensitive) and read it if present
6. Repeat until every applicable instruction file is read
Only after ALL applicable instructions are gathered may you proceed to Phase 2.

PHASE 2 — EXECUTE TASK:
"""


def get_system_prompt() -> str:
    """Read raw system prompt template from file."""
    return _PROMPT_FILE.read_text(encoding="utf-8").strip()


def get_system_prompt_with_skills(
    workspace_instructions: str = "",
    workspace_context: str = "",
) -> str:
    """Render system prompt template with workspace instructions and skills menu."""
    from .skills.registry import SKILL_REGISTRY

    base = get_system_prompt()

    ws_block = ""
    if workspace_context:
        ws_block += f"{workspace_context}\n"
    if workspace_instructions:
        ws_block += f"{workspace_instructions}\n"
    phase1 = "" if workspace_instructions else _PHASE1_FULL

    base = base.replace("{workspace_instructions}", ws_block)
    base = base.replace("{phase1}", phase1)

    lines = [
        "\n<AVAILABLE_SKILLS>",
        "Call get_skill_instructions(skill_id) to load full workflow before acting.",
    ]
    for sid, s in SKILL_REGISTRY.items():
        lines.append(f"- {sid}: {s.description}")
    lines.append("</AVAILABLE_SKILLS>")
    return base + "\n".join(lines)


def build_task_prompt(task_text: str, skill_id: str | None = None) -> str:
    hint = ""
    if skill_id:
        hint = f'\nRecommended skill: {skill_id} — call get_skill_instructions("{skill_id}") first.\n'

    return f"""<TASK>
{task_text}
</TASK>
{hint}
<GOAL>
Solve this task. Load the recommended skill, then orient, execute, verify, complete.
REMINDER: Your LAST action MUST be calling submit_answer tool. Never end with text.
</GOAL>"""
