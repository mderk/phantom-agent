#!/usr/bin/env python3
"""Evolution system: analyze benchmark failures, propose and apply prompt/code fixes."""
from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────

ROOT = Path(__file__).parent
EVOLUTION_DIR = ROOT / "evolution"
SKILLS_DIR = ROOT / "agent_v2" / "skills"
SYSTEM_PROMPT_PATH = ROOT / "agent_v2" / "system_prompt.md"
STATE_FILE = EVOLUTION_DIR / "state.json"

SKILL_FILES = sorted(SKILLS_DIR.glob("*.md"))
PROMPT_FILES = [("system_prompt.md", SYSTEM_PROMPT_PATH)] + [
    (f"skills/{f.name}", f) for f in SKILL_FILES
]


def _load_env() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


_load_env()


# ── State management ───────────────────────────────────────────


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"current_version": 0, "history": []}


def save_state(state: dict) -> None:
    EVOLUTION_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")


def current_version() -> int:
    return load_state()["current_version"]


def next_version() -> int:
    return current_version() + 1


def version_dir(v: int) -> Path:
    return EVOLUTION_DIR / f"v{v:03d}"


def snapshot_prompts(vdir: Path) -> None:
    """Copy all current skill .md + system_prompt.md into version directory."""
    for rel, src in PROMPT_FILES:
        dst = vdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            shutil.copy2(src, dst)


def restore_prompts(vdir: Path) -> None:
    """Restore skill .md + system_prompt.md from a version snapshot."""
    for rel, dst in PROMPT_FILES:
        src = vdir / rel
        if src.exists():
            shutil.copy2(src, dst)


# ── Failure collection from SQLite ─────────────────────────────


def collect_failures(run_id: str, include_passed: bool = False) -> list[dict]:
    """Collect failed tasks with full event data from SQLite."""
    from agent_v2 import db as store

    run = store.get_run(run_id)
    if not run:
        print(f"[ERROR] Run {run_id} not found in DB.")
        sys.exit(1)

    failures = []
    for task_id, task in sorted(run["tasks"].items()):
        score = task.get("score", -1)
        if not include_passed and (score < 0 or score >= 1.0):
            continue

        events = store.get_events(run_id, task_id)

        # Extract structured data from events
        instruction = task.get("instruction", "")
        skill_id = task.get("skill_id", "")
        skill_confidence = task.get("skill_confidence", 0.0)
        system_prompt = ""
        task_prompt = ""
        tool_trace = []
        agent_output = ""
        cost_usd = 0.0

        step_tools: dict[str, str] = {}  # step -> tool name

        for ev in events:
            et = ev.get("type", "")
            if et == "task_instruction":
                instruction = instruction or ev.get("instruction", "")
            elif et == "task_classified":
                skill_id = skill_id or ev.get("skill_id", "")
                try:
                    skill_confidence = skill_confidence or float(ev.get("skill_confidence", 0))
                except (ValueError, TypeError):
                    pass
            elif et == "prompts":
                system_prompt = ev.get("system_prompt", "")
                task_prompt = ev.get("task_prompt", "")
            elif et == "tool_start":
                step = ev.get("step", "")
                tool_name = ev.get("tool", "")
                step_tools[step] = tool_name
                tool_trace.append({
                    "step": step,
                    "tool": tool_name,
                    "args": ev.get("args", ""),
                })
            elif et == "tool_end":
                step = ev.get("step", "")
                result = ev.get("result", "")
                # Find matching tool_start entry and add result
                for t in reversed(tool_trace):
                    if t["step"] == step and "result" not in t:
                        t["result"] = str(result)[:2000]
                        break
            elif et == "agent_output":
                agent_output = ev.get("output", "")
                cost_usd = ev.get("cost_usd", 0.0)

        failures.append({
            "task_id": task_id,
            "instruction": instruction,
            "skill_id": skill_id,
            "skill_confidence": skill_confidence,
            "score": score,
            "score_detail": task.get("score_detail", []),
            "system_prompt": system_prompt,
            "task_prompt": task_prompt,
            "tool_trace": tool_trace,
            "agent_output": agent_output,
            "cost_usd": cost_usd,
        })

    return failures


# ── Claude query helper ────────────────────────────────────────


_MODEL: str | None = "claude-opus-4-6"


async def _query_claude(prompt: str, model: str | None = None, retries: int = 2) -> str:
    """Single-turn Claude query, returns text response."""
    from claude_agent_sdk import query, ClaudeAgentOptions

    options_kw: dict = dict(max_turns=1, permission_mode="dontAsk")
    effective_model = model or _MODEL
    if effective_model:
        options_kw["model"] = effective_model

    for attempt in range(retries + 1):
        try:
            result = ""
            async for message in query(prompt=prompt, options=ClaudeAgentOptions(**options_kw)):
                mt = type(message).__name__
                if mt == "AssistantMessage":
                    for block in getattr(message, "content", []):
                        if getattr(block, "type", "") == "text":
                            result += getattr(block, "text", "")
                elif mt == "ResultMessage":
                    r = getattr(message, "result", "")
                    if r and not result:
                        result = str(r)
            return result
        except Exception as e:
            if attempt < retries:
                print(f"  [RETRY {attempt+1}/{retries}] {e}")
                await asyncio.sleep(2)
            else:
                raise


def _extract_json(text: str) -> dict | list | None:
    """Extract JSON from Claude response (possibly wrapped in ```json blocks)."""
    # Try direct parse first
    text = text.strip()
    if text.startswith(("{", "[")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Try extracting from code block
    m = re.search(r"```(?:json)?\s*\n([\s\S]*?)\n```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object/array in text
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            if text[i] == start_char:
                depth += 1
            elif text[i] == end_char:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    return None


# ── Stage 2: Per-task analysis ──────────────────────────────────


def _load_skill_prompt(skill_id: str) -> str:
    if not skill_id:
        return ""
    path = SKILLS_DIR / f"{skill_id}.md"
    return path.read_text() if path.exists() else ""


async def analyze_task(failure: dict) -> dict:
    """Analyze a single failed task. Returns structured analysis."""
    skill_prompt = _load_skill_prompt(failure["skill_id"])

    # Build tool trace summary (compact)
    trace_lines = []
    for t in failure["tool_trace"]:
        result_preview = str(t.get("result", ""))[:300]
        trace_lines.append(f"  [{t['step']}] {t['tool']}: {result_preview}")
    tool_trace_text = "\n".join(trace_lines) if trace_lines else "(no tool calls)"

    prompt = f"""You are analyzing a failed PAC1 benchmark task for an AI agent system.
Your job is to identify the root cause and propose a fix.

<TASK>
Task ID: {failure["task_id"]}
Instruction: {failure["instruction"]}
Skill: {failure["skill_id"]} ({failure["skill_confidence"]:.0%} confidence)
Score: {failure["score"]}
Score detail: {json.dumps(failure["score_detail"])}
</TASK>

<SKILL_PROMPT>
{skill_prompt or "(no skill prompt)"}
</SKILL_PROMPT>

<TOOL_TRACE>
{tool_trace_text}
</TOOL_TRACE>

<AGENT_OUTPUT>
{failure["agent_output"][:3000]}
</AGENT_OUTPUT>

<TASK_PROMPT_SENT>
{failure["task_prompt"][:2000]}
</TASK_PROMPT_SENT>

Analyze this failure and respond with ONLY a JSON object:
{{
    "root_cause": "what exactly went wrong (be specific, quote evidence)",
    "origin": "skill_prompt | system_prompt | classifier | tool_code | agent_reasoning",
    "fix_type": "skill_prompt | system_prompt | code | no_fix",
    "fix_target": "filename or skill_id to change (e.g. inbox_processing, classifier.py)",
    "proposed_change": "specific change description — what to add/modify and where",
    "confidence": 0.85
}}

Rules:
- origin: where the failure ORIGINATED, not where it manifested
- fix_type=code means a Python file needs changing (classifier, tools, agent logic)
- fix_type=no_fix means the failure is due to LLM randomness or ambiguous task
- proposed_change must be STRUCTURAL (prevent a class of errors), not case-specific
- confidence: 0.0-1.0, how likely this fix prevents similar failures"""

    raw = await _query_claude(prompt)
    parsed = _extract_json(raw)
    if isinstance(parsed, dict):
        parsed["task_id"] = failure["task_id"]
        return parsed

    # Fallback: return raw analysis
    return {
        "task_id": failure["task_id"],
        "root_cause": raw[:500],
        "origin": "unknown",
        "fix_type": "no_fix",
        "fix_target": "",
        "proposed_change": "",
        "confidence": 0.0,
        "raw": raw,
    }


# ── Stage 3: Cross-task synthesis ───────────────────────────────


async def synthesize_fixes(
    analyses: list[dict],
    current_prompts: dict[str, str],
    history: list[dict],
) -> dict:
    """Synthesize cross-task patterns and generate exact prompt changes + code proposals."""

    # Build analyses summary
    analyses_text = json.dumps(analyses, indent=2, ensure_ascii=False)

    # Build current prompts listing (skill prompts only, not system prompt — too large)
    prompts_text = ""
    for rel, src in PROMPT_FILES:
        if rel.startswith("skills/") and src.exists():
            content = src.read_text()
            prompts_text += f"\n--- {rel} ---\n{content}\n"

    # Build history summary
    history_text = ""
    for h in history[-5:]:  # last 5 versions
        history_text += f"  v{h['version']:03d}: source_score={h.get('source_score')} result_score={h.get('result_score')} note={h.get('note','')}\n"

    prompt = f"""You are the evolution engine for a PAC1 benchmark agent.
You have per-task failure analyses and the current skill prompts.
Your job: propose MINIMAL changes to fix the failures without causing regressions.

<ANALYSES>
{analyses_text[:15000]}
</ANALYSES>

<CURRENT_SKILL_PROMPTS>
{prompts_text[:20000]}
</CURRENT_SKILL_PROMPTS>

<EVOLUTION_HISTORY>
{history_text or "(no prior versions)"}
</EVOLUTION_HISTORY>

Respond with ONLY a JSON object:
{{
    "prompt_changes": [
        {{
            "file": "skills/inbox_processing.md",
            "reason": "why this change is needed (reference task IDs)",
            "new_content": "THE COMPLETE NEW FILE CONTENT — not a diff, the full text"
        }}
    ],
    "code_proposals": [
        {{
            "file": "agent_v2/skills/classifier.py",
            "reason": "why this code change is needed",
            "description": "what to change in the code",
            "diff": "unified diff format (--- a/... +++ b/...)"
        }}
    ],
    "patterns": [
        {{
            "name": "pattern_name",
            "affected_tasks": ["t20", "t29"],
            "summary": "one-line description"
        }}
    ],
    "regression_risks": ["free-text warnings about tasks that might break"]
}}

Rules:
- prompt_changes: ONLY for analyses where fix_type=skill_prompt or fix_type=system_prompt
- new_content must be the COMPLETE file content (will be written as-is)
- code_proposals: for fix_type=code — provide a unified diff
- Do NOT add case-specific patches (e.g., "if task says X, do Y")
- Target STRUCTURAL gaps that prevent a CLASS of errors
- If a skill prompt is already correct and the failure is agent randomness, skip it
- Keep changes minimal — don't rewrite entire prompts, only add/modify the relevant section
- If a fix applies to ALL skills (not just one), put it in system_prompt.md CONSTRAINTS, not in a skill prompt
- For analyses with fix_type=no_fix, do NOT propose changes"""

    raw = await _query_claude(prompt)
    parsed = _extract_json(raw)
    if isinstance(parsed, dict):
        return parsed

    return {"prompt_changes": [], "code_proposals": [], "patterns": [], "regression_risks": [], "raw": raw}


# ── Apply changes ──────────────────────────────────────────────


def create_version(synthesis: dict, run_id: str, analyses: list[dict], source_score: float) -> int:
    """Create new evolution version: snapshot current prompts, save proposals. Does NOT apply.
    Returns version number."""
    v = next_version()
    vdir = version_dir(v)
    vdir.mkdir(parents=True, exist_ok=True)

    # 1. Snapshot current prompts (before any changes)
    snapshot_prompts(vdir)

    # 2. Save proposed prompt changes as pending (in snapshot.json, not applied yet)
    prompt_changes_pending = []
    for change in synthesis.get("prompt_changes", []):
        rel = change.get("file", "")
        new_content = change.get("new_content", "")
        if not rel or not new_content:
            continue
        # Save proposed content to version dir for later apply
        proposed_path = vdir / "proposed" / rel
        proposed_path.parent.mkdir(parents=True, exist_ok=True)
        proposed_path.write_text(new_content)
        prompt_changes_pending.append({
            "file": rel,
            "reason": change.get("reason", ""),
        })

    # 3. Save code proposals as .patch + .before files
    patches_dir = vdir / "patches"
    code_proposals_saved = []
    for proposal in synthesis.get("code_proposals", []):
        src_file = proposal.get("file", "")
        diff_text = proposal.get("diff", "")
        if not src_file or not diff_text:
            continue

        patch_name = Path(src_file).name + ".patch"
        before_name = Path(src_file).name + ".before"

        patches_dir.mkdir(parents=True, exist_ok=True)

        # Save .before (original file content)
        src_path = ROOT / src_file
        if src_path.exists():
            shutil.copy2(src_path, patches_dir / before_name)

        # Save .patch
        (patches_dir / patch_name).write_text(diff_text + "\n")

        code_proposals_saved.append({
            "file": src_file,
            "reason": proposal.get("reason", ""),
            "description": proposal.get("description", ""),
            "patch": f"patches/{patch_name}",
        })

    # 4. Write snapshot.json
    snapshot = {
        "version": v,
        "parent_version": v - 1 if v > 1 else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_run_id": run_id,
        "source_run_score": source_score,
        "analysis": {
            "failed_tasks": analyses,
            "patterns": synthesis.get("patterns", []),
            "regression_risks": synthesis.get("regression_risks", []),
        },
        "prompt_changes": prompt_changes_pending,
        "code_proposals": code_proposals_saved,
        "applied": False,
        "result_run_id": None,
        "result_score": None,
    }
    (vdir / "snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")

    # 5. Update state.json
    state = load_state()
    state["current_version"] = v
    note_parts = []
    if analyses:
        note_parts.append(f"{len(analyses)} failures")
    patterns = synthesis.get("patterns", [])
    if patterns:
        note_parts.append(f"{len(patterns)} patterns")
    if prompt_changes_pending:
        note_parts.append(f"{len(prompt_changes_pending)} prompt changes")
    if code_proposals_saved:
        note_parts.append(f"{len(code_proposals_saved)} code proposals")

    state["history"].append({
        "version": v,
        "created_at": snapshot["created_at"],
        "source_run_id": run_id,
        "source_score": source_score,
        "result_run_id": None,
        "result_score": None,
        "note": " -> ".join(note_parts) if note_parts else "no changes",
    })
    save_state(state)

    return v


def apply_prompts(v: int | None = None, dry_run: bool = False) -> None:
    """Apply prompt changes from a version to agent_v2/skills/ and system_prompt.md."""
    target_v = v if v is not None else current_version()
    if target_v == 0:
        print("[ERROR] No evolution version exists yet. Run 'analyze' first.")
        sys.exit(1)

    vdir = version_dir(target_v)
    proposed_dir = vdir / "proposed"

    if not proposed_dir.exists():
        print(f"[INFO] No prompt changes in v{target_v:03d}.")
        return

    snap_path = vdir / "snapshot.json"
    snapshot = json.loads(snap_path.read_text()) if snap_path.exists() else {}

    count = 0
    for rel_file in sorted(proposed_dir.rglob("*.md")):
        rel = str(rel_file.relative_to(proposed_dir))
        target = ROOT / "agent_v2" / rel
        if dry_run:
            # Show diff
            if target.exists():
                old_lines = target.read_text().splitlines(keepends=True)
                new_lines = rel_file.read_text().splitlines(keepends=True)
                diff = list(difflib.unified_diff(old_lines, new_lines,
                                                  fromfile=f"agent_v2/{rel}", tofile=f"proposed/{rel}"))
                if diff:
                    print(f"--- {rel} ---")
                    print("".join(diff))
                    count += 1
            else:
                print(f"  [NEW] agent_v2/{rel}")
                count += 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(rel_file, target)
            print(f"  [WRITE] agent_v2/{rel}")
            count += 1

    if count == 0:
        print("No prompt changes to apply.")
        return

    if not dry_run:
        # Mark as applied in snapshot
        if snapshot:
            snapshot["applied"] = True
            snap_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
        print(f"\nApplied {count} prompt changes from v{target_v:03d}")


# ── Apply / rollback code patches ──────────────────────────────


def _get_patches(v: int | None, patch_name: str | None) -> list[tuple[Path, dict]]:
    """Get list of (patch_path, proposal_info) for a version."""
    target_v = v if v is not None else current_version()
    vdir = version_dir(target_v)

    snapshot_path = vdir / "snapshot.json"
    if not snapshot_path.exists():
        print(f"[ERROR] No snapshot.json in {vdir}")
        sys.exit(1)

    snapshot = json.loads(snapshot_path.read_text())
    results = []
    for proposal in snapshot.get("code_proposals", []):
        patch_rel = proposal.get("patch", "")
        if not patch_rel:
            continue
        if patch_name and not patch_rel.endswith(patch_name):
            continue
        patch_path = vdir / patch_rel
        if patch_path.exists():
            results.append((patch_path, proposal))

    return results


def apply_code_patches(v: int | None = None, patch_name: str | None = None, dry_run: bool = False) -> None:
    """Apply code patches via git apply, saving .before snapshots."""
    patches = _get_patches(v, patch_name)
    if not patches:
        print("[INFO] No code patches to apply.")
        return

    target_v = v if v is not None else current_version()
    vdir = version_dir(target_v)

    for patch_path, proposal in patches:
        src_file = proposal.get("file", "")
        before_path = patch_path.with_suffix(".before")

        # Save .before if not already saved and source exists
        src_path = ROOT / src_file
        if not before_path.exists() and src_path.exists():
            shutil.copy2(src_path, before_path)

        if dry_run:
            result = subprocess.run(
                ["git", "apply", "--check", str(patch_path)],
                cwd=str(ROOT), capture_output=True, text=True,
            )
            status = "OK" if result.returncode == 0 else f"FAIL: {result.stderr.strip()}"
            print(f"  [CHECK] {patch_path.name} -> {src_file}: {status}")
        else:
            result = subprocess.run(
                ["git", "apply", str(patch_path)],
                cwd=str(ROOT), capture_output=True, text=True,
            )
            if result.returncode == 0:
                print(f"  [APPLIED] {patch_path.name} -> {src_file}")
            else:
                print(f"  [FAIL] {patch_path.name}: {result.stderr.strip()}")


def rollback_code_patches(
    to_version: int | None = None,
    v: int | None = None,
    patch_name: str | None = None,
    dry_run: bool = False,
) -> None:
    """Rollback code patches by restoring .before files."""
    state = load_state()
    cur = state["current_version"]

    if to_version is not None:
        # Multi-version rollback: find earliest .before for each file after target version
        file_befores: dict[str, Path] = {}  # source_file -> earliest .before path

        for h in state["history"]:
            hv = h["version"]
            if hv <= to_version or hv > cur:
                continue
            vdir = version_dir(hv)
            snapshot_path = vdir / "snapshot.json"
            if not snapshot_path.exists():
                continue
            snapshot = json.loads(snapshot_path.read_text())
            for proposal in snapshot.get("code_proposals", []):
                src_file = proposal.get("file", "")
                patch_rel = proposal.get("patch", "")
                if not src_file or not patch_rel:
                    continue
                before_path = (vdir / patch_rel).with_suffix(".before")
                if before_path.exists() and src_file not in file_befores:
                    file_befores[src_file] = before_path

        if not file_befores:
            print(f"[INFO] No code patches to rollback between v{to_version:03d} and v{cur:03d}.")
            return

        for src_file, before_path in file_befores.items():
            dst = ROOT / src_file
            if dry_run:
                print(f"  [WOULD RESTORE] {src_file} <- {before_path}")
            else:
                shutil.copy2(before_path, dst)
                print(f"  [RESTORED] {src_file} <- {before_path}")

    else:
        # Single-version rollback
        target_v = v if v is not None else cur
        patches = _get_patches(target_v, patch_name)
        if not patches:
            print("[INFO] No code patches to rollback.")
            return

        for patch_path, proposal in patches:
            src_file = proposal.get("file", "")
            before_path = patch_path.with_suffix(".before")
            if not before_path.exists():
                print(f"  [SKIP] No .before file for {src_file}")
                continue
            dst = ROOT / src_file
            if dry_run:
                print(f"  [WOULD RESTORE] {src_file} <- {before_path}")
            else:
                shutil.copy2(before_path, dst)
                print(f"  [RESTORED] {src_file}")


# ── Record result ──────────────────────────────────────────────


def record_result(run_id: str | None) -> None:
    """Record benchmark score for the current version."""
    from agent_v2 import db as store

    run_id = resolve_run_id(run_id)
    run = store.get_run(run_id)
    if not run:
        print(f"[ERROR] Run {run_id} not found.")
        sys.exit(1)

    score = run.get("final_score", 0.0)
    passed = run.get("passed", 0)
    total = run.get("total", 0)

    state = load_state()
    v = state["current_version"]
    if v == 0:
        print("[ERROR] No evolution version exists yet.")
        sys.exit(1)

    # Update history entry
    for h in state["history"]:
        if h["version"] == v:
            h["result_run_id"] = run_id
            h["result_score"] = score
            break
    save_state(state)

    # Update snapshot.json
    vdir = version_dir(v)
    snap_path = vdir / "snapshot.json"
    if snap_path.exists():
        snapshot = json.loads(snap_path.read_text())
        snapshot["result_run_id"] = run_id
        snapshot["result_score"] = score
        snap_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")

    print(f"Recorded: v{v:03d} -> run {run_id}, score {score:.1f}% ({passed}/{total})")


# ── Rollback prompts ───────────────────────────────────────────


def rollback(to_version: int | None = None) -> None:
    """Rollback prompts to a previous version."""
    state = load_state()
    cur = state["current_version"]

    if to_version is not None:
        target = to_version
    elif cur > 1:
        target = cur - 1
    else:
        print("[ERROR] Nothing to rollback to.")
        return

    vdir = version_dir(target)
    if not vdir.exists():
        print(f"[ERROR] Version directory {vdir} does not exist.")
        return

    restore_prompts(vdir)
    state["current_version"] = target
    save_state(state)
    print(f"Rolled back prompts to v{target:03d}")


# ── Status / diff / history ────────────────────────────────────


def show_status() -> None:
    state = load_state()
    v = state["current_version"]
    if v == 0:
        print("No evolution versions yet.")
        print("Run: uv run python evolve.py analyze [--run-id <id>]")
        return

    print(f"Current version: v{v:03d}")
    print(f"Versions: {len(state['history'])}")
    print()
    show_history_table(state)


def show_history_table(state: dict | None = None) -> None:
    if state is None:
        state = load_state()

    if not state["history"]:
        print("No versions.")
        return

    print(f"{'Ver':<6} {'Source':<12} {'Score':<8} {'Result':<12} {'Score':<8} {'Note'}")
    print(f"{'---':<6} {'------':<12} {'-----':<8} {'------':<12} {'-----':<8} {'----'}")

    for h in state["history"]:
        ver = f"v{h['version']:03d}"
        src = h.get("source_run_id", "") or "-"
        src_score = f"{h['source_score']:.1f}%" if h.get("source_score") is not None else "-"
        res = h.get("result_run_id", "") or "-"
        res_score = f"{h['result_score']:.1f}%" if h.get("result_score") is not None else "-"
        note = h.get("note", "")
        print(f"{ver:<6} {src[:10]:<12} {src_score:<8} {res[:10]:<12} {res_score:<8} {note}")


def show_diff(v1_str: str, v2_str: str) -> None:
    """Show unified diff of prompt files between two versions (or a version and 'current')."""

    def _read_version(s: str) -> tuple[dict[str, list[str]], str]:
        """Returns {rel: lines} and label. s can be 'current' or version number."""
        if s.lower() == "current":
            result = {}
            for rel, src in PROMPT_FILES:
                result[rel] = src.read_text().splitlines(keepends=True) if src.exists() else []
            return result, "current"
        v = _parse_version(s)
        vdir = version_dir(v)
        if not vdir.exists():
            print(f"[ERROR] v{v:03d} does not exist.")
            sys.exit(1)
        result = {}
        for rel, _ in PROMPT_FILES:
            f = vdir / rel
            result[rel] = f.read_text().splitlines(keepends=True) if f.exists() else []
        return result, f"v{v:03d}"

    files1, label1 = _read_version(v1_str)
    files2, label2 = _read_version(v2_str)

    any_diff = False
    for rel in files1.keys() | files2.keys():
        lines1 = files1.get(rel, [])
        lines2 = files2.get(rel, [])

        diff = list(difflib.unified_diff(
            lines1, lines2,
            fromfile=f"{label1}/{rel}",
            tofile=f"{label2}/{rel}",
        ))

        if diff:
            any_diff = True
            print("".join(diff))

    # Also show code patches in v2 if it's a version
    if v2_str.lower() != "current":
        v2 = _parse_version(v2_str)
        patches_dir = version_dir(v2) / "patches"
        if patches_dir.exists():
            for patch_file in sorted(patches_dir.glob("*.patch")):
                any_diff = True
                print(f"\n--- Code patch: {patch_file.name} ---")
                print(patch_file.read_text())

    if not any_diff:
        print("No differences.")


# ── Snapshot (no analysis) ─────────────────────────────────────


def cmd_snapshot(note: str = "") -> None:
    """Snapshot current prompts into a new version without analysis."""
    v = next_version()
    vdir = version_dir(v)
    vdir.mkdir(parents=True, exist_ok=True)

    snapshot_prompts(vdir)

    snapshot = {
        "version": v,
        "parent_version": v - 1 if v > 1 else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_run_id": None,
        "source_run_score": None,
        "note": note or "manual snapshot",
        "analysis": {},
        "prompt_changes": [],
        "code_proposals": [],
        "applied": True,
        "result_run_id": None,
        "result_score": None,
    }
    (vdir / "snapshot.json").write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")

    state = load_state()
    state["current_version"] = v
    state["history"].append({
        "version": v,
        "created_at": snapshot["created_at"],
        "source_run_id": None,
        "source_score": None,
        "result_run_id": None,
        "result_score": None,
        "note": note or "manual snapshot",
    })
    save_state(state)

    print(f"Snapshot saved: v{v:03d}")
    for rel, src in PROMPT_FILES:
        if src.exists():
            print(f"  {rel}")


# ── Main pipeline ──────────────────────────────────────────────


def resolve_run_id(run_id: str | None) -> str:
    """Resolve run ID: return as-is if given, otherwise pick the latest run."""
    from agent_v2 import db as store

    if run_id:
        return run_id
    runs = store.list_runs()
    if not runs:
        print("[ERROR] No runs found in DB.")
        sys.exit(1)
    latest = runs[0]["run_id"]
    print(f"Using latest run: {latest}")
    return latest


async def run_analyze(run_id: str | None) -> None:
    """Full analysis pipeline: collect -> analyze -> synthesize -> create version."""
    from agent_v2 import db as store

    run_id = resolve_run_id(run_id)
    run = store.get_run(run_id)
    if not run:
        print(f"[ERROR] Run {run_id} not found.")
        sys.exit(1)

    source_score = run.get("final_score", 0.0)
    passed = run.get("passed", 0)
    total = run.get("total", 0)

    print(f"Run: {run_id}  Score: {source_score:.1f}%  ({passed}/{total})")
    print()

    # Stage 1: Collect failures
    print("Stage 1: Collecting failures...")
    failures = collect_failures(run_id)
    if not failures:
        print("No failures found. Nothing to evolve.")
        return

    print(f"  Found {len(failures)} failed tasks:")
    for f in failures:
        print(f"    {f['task_id']}: {f['score_detail'][:1]}  skill={f['skill_id'] or '(none)'}")
    print()

    # Stage 2: Per-task analysis
    print("Stage 2: Analyzing each failure...")
    analyses = []
    for f in failures:
        print(f"  Analyzing {f['task_id']}...", end=" ", flush=True)
        try:
            analysis = await analyze_task(f)
        except Exception as e:
            print(f"FAILED: {e}")
            analysis = {
                "task_id": f["task_id"],
                "root_cause": f"Analysis failed: {e}",
                "origin": "unknown",
                "fix_type": "no_fix",
                "fix_target": "",
                "proposed_change": "",
                "confidence": 0.0,
            }
        analyses.append(analysis)
        origin = analysis.get("origin", "?")
        fix_type = analysis.get("fix_type", "?")
        conf = analysis.get("confidence", 0)
        print(f"origin={origin} fix={fix_type} conf={conf:.0%}")
    print()

    # Stage 3: Synthesis
    print("Stage 3: Synthesizing fixes...")
    current_prompts = {}
    for rel, src in PROMPT_FILES:
        if src.exists():
            current_prompts[rel] = src.read_text()

    state = load_state()
    synthesis = await synthesize_fixes(analyses, current_prompts, state.get("history", []))
    print()

    # Display results
    prompt_changes = synthesis.get("prompt_changes", [])
    code_proposals = synthesis.get("code_proposals", [])
    patterns = synthesis.get("patterns", [])
    risks = synthesis.get("regression_risks", [])

    if patterns:
        print("Patterns:")
        for p in patterns:
            print(f"  [{p.get('name', '?')}] {p.get('summary', '')} ({p.get('affected_tasks', [])})")
        print()

    if prompt_changes:
        print(f"Prompt changes ({len(prompt_changes)}):")
        for c in prompt_changes:
            print(f"  {c['file']}: {c.get('reason', '')}")
        print()

    if code_proposals:
        print(f"Code proposals ({len(code_proposals)}):")
        for c in code_proposals:
            print(f"  {c['file']}: {c.get('description', c.get('reason', ''))}")
        print()

    if risks:
        print("Regression risks:")
        for r in risks:
            print(f"  ! {r}")
        print()

    if not prompt_changes and not code_proposals:
        print("No actionable changes proposed.")
        return

    # Create version (snapshot + proposals, no apply)
    v = create_version(synthesis, run_id, analyses, source_score)
    print(f"Created evolution v{v:03d}")
    print(f"  Prompt changes: {len(prompt_changes)} (pending)")
    print(f"  Code patches: {len(code_proposals)}")
    print()
    print("Next steps:")
    print(f"  uv run python evolve.py apply --dry-run          # preview prompt changes")
    print(f"  uv run python evolve.py apply                    # apply prompt changes")
    if code_proposals:
        print(f"  uv run python evolve.py apply-code --dry-run     # preview code patches")
        print(f"  uv run python evolve.py apply-code               # apply code patches")


# ── CLI ────────────────────────────────────────────────────────


def _parse_version(s: str) -> int:
    """Parse 'v001' or '1' or 'v1' into integer 1."""
    s = s.strip().lower().lstrip("v")
    return int(s)


def main() -> None:
    parser = argparse.ArgumentParser(description="PAC1 Evolution System")
    sub = parser.add_subparsers(dest="command")

    p_analyze = sub.add_parser("analyze", help="Analyze failures, create evolution version")
    p_analyze.add_argument("--run-id", default=None, help="Run ID (default: latest)")
    p_analyze.add_argument("--model", default=None, help="Claude model (default: claude-opus-4-6)")

    p_apply = sub.add_parser("apply", help="Apply prompt changes from a version")
    p_apply.add_argument("--version", default=None, help="Version to apply (default: current)")
    p_apply.add_argument("--dry-run", action="store_true", help="Show diff without applying")

    p_apply_code = sub.add_parser("apply-code", help="Apply code patches via git apply")
    p_apply_code.add_argument("--version", default=None)
    p_apply_code.add_argument("--patch", default=None)
    p_apply_code.add_argument("--dry-run", action="store_true")

    p_rollback_code = sub.add_parser("rollback-code", help="Rollback code patches")
    p_rollback_code.add_argument("--to", default=None, help="Target version for multi-version rollback")
    p_rollback_code.add_argument("--version", default=None, help="Specific version to rollback")
    p_rollback_code.add_argument("--patch", default=None)
    p_rollback_code.add_argument("--dry-run", action="store_true")

    p_record = sub.add_parser("record", help="Record benchmark score for current version")
    p_record.add_argument("--run-id", default=None, help="Run ID (default: latest)")

    p_rollback = sub.add_parser("rollback", help="Rollback prompts to previous version")
    p_rollback.add_argument("--to", default=None, help="Target version")

    p_snapshot = sub.add_parser("snapshot", help="Snapshot current prompts (no analysis)")
    p_snapshot.add_argument("--note", default="", help="Optional note for this snapshot")

    sub.add_parser("status", help="Show current version and history")

    p_diff = sub.add_parser("diff", help="Diff prompts between two versions (use 'current' for live files)")
    p_diff.add_argument("v1", help="First version (e.g. v001) or 'current'")
    p_diff.add_argument("v2", help="Second version (e.g. v002) or 'current'")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "analyze":
        if args.model:
            global _MODEL
            _MODEL = args.model
        asyncio.run(run_analyze(args.run_id))

    elif args.command == "apply":
        v = _parse_version(args.version) if args.version else None
        apply_prompts(v=v, dry_run=args.dry_run)

    elif args.command == "apply-code":
        v = _parse_version(args.version) if args.version else None
        apply_code_patches(v=v, patch_name=args.patch, dry_run=args.dry_run)

    elif args.command == "rollback-code":
        to_v = _parse_version(args.to) if args.to else None
        v = _parse_version(args.version) if args.version else None
        rollback_code_patches(to_version=to_v, v=v, patch_name=args.patch, dry_run=args.dry_run)

    elif args.command == "record":
        record_result(args.run_id)

    elif args.command == "rollback":
        to_v = _parse_version(args.to) if args.to else None
        rollback(to_version=to_v)

    elif args.command == "snapshot":
        cmd_snapshot(note=args.note)

    elif args.command == "status":
        show_status()

    elif args.command == "diff":
        show_diff(args.v1, args.v2)


if __name__ == "__main__":
    main()
