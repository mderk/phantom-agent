from __future__ import annotations

from pathlib import Path

_PROMPT_FILE = Path(__file__).parent / "system_prompt.md"


def get_system_prompt() -> str:
    """Read system prompt from file — hot-reloadable."""
    return _PROMPT_FILE.read_text(encoding="utf-8").strip()


# Keep SYSTEM_PROMPT as a property-like for backwards compat
# But anyone importing it gets the current value at import time
# Use get_system_prompt() for dynamic reads
SYSTEM_PROMPT = get_system_prompt()


def get_system_prompt_with_skills() -> str:
    """System prompt + available skills menu."""
    from .skills.registry import SKILL_REGISTRY
    base = get_system_prompt()
    lines = ["\n<AVAILABLE_SKILLS>",
             "Call get_skill_instructions(skill_id) to load full workflow before acting."]
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
