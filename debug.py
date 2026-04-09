#!/usr/bin/env python3
"""Debug tool: fetch BitGN trial log and analyze failures with Claude."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


def _load_env() -> None:
    env_file = Path(__file__).parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


_load_env()

from bitgn.harness_connect import HarnessServiceClientSync  # noqa: E402
from bitgn.harness_pb2 import GetTrialRequest  # noqa: E402
from agent_v2 import db as store  # noqa: E402
from agent_v2.claude_agent import ClaudeConfig  # noqa: E402


# ── BitGN log fetch ─────────────────────────────────────────


def fetch_trial(harness: HarnessServiceClientSync, trial_id: str) -> tuple[list[str], dict]:
    """Fetch full trial log via pagination. Returns (log_lines, meta)."""
    lines: list[str] = []
    meta: dict = {}
    cursor = 0

    while True:
        resp = harness.get_trial(GetTrialRequest(trial_id=trial_id, cursor=cursor))

        if not meta:
            try:
                score = resp.score if resp.HasField("score") else None
            except Exception:
                score = getattr(resp, "score", None)
            meta = {
                "trial_id": resp.trial_id,
                "task_id": resp.task_id,
                "instruction": resp.instruction,
                "score": score,
                "score_detail": list(resp.score_detail),
                "error": resp.error,
            }

        for log in resp.logs:
            lines.append(log.text if log.text else f"[{log.kind}] {log.type}")

        next_cur = resp.next_cursor
        if not next_cur or next_cur == cursor:
            break
        cursor = next_cur

    return lines, meta


# ── AI analysis ─────────────────────────────────────────────


async def analyze(
    log_lines: list[str],
    task_info: dict,
    skill_prompt: str,
    model: str | None,
) -> str:
    from claude_agent_sdk import query, ClaudeAgentOptions

    log_text = "\n".join(log_lines)

    prompt = f"""You are analyzing a failed PAC1 benchmark task for an AI agent system.

<TASK_INFO>
Task ID: {task_info.get("task_id")}
Instruction: {task_info.get("instruction")}
Skill: {task_info.get("skill_id", "(none)")} ({task_info.get("skill_confidence", 0):.0%} confidence)
Score: {task_info.get("score")}
Score detail: {json.dumps(task_info.get("score_detail", []))}
Error from scorer: {task_info.get("error", "")}
</TASK_INFO>

<SKILL_PROMPT>
{skill_prompt or "(no skill prompt for this task)"}
</SKILL_PROMPT>

<TRIAL_LOG>
{log_text[:10000]}
</TRIAL_LOG>

Analyze this failure:
1. **Root cause** — what exactly went wrong? (wrong action taken, missed check, misread doc, etc.)
2. **Where the failure originated** — skill prompt gap, agent reasoning error, or ambiguous task?
3. **Generic fix** — if the skill prompt is the cause, what specific wording change would prevent this class of error? Avoid case-specific patches; target the structural gap.
4. **Confidence** — how confident are you this fix would generalize to similar tasks?

Be concrete. Quote the relevant log line and the relevant skill prompt section when applicable."""

    options_kw: dict = dict(max_turns=1, permission_mode="dontAsk")
    if model:
        options_kw["model"] = model

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


# ── Skill prompt loader ──────────────────────────────────────


def load_skill_prompt(skill_id: str) -> str:
    if not skill_id:
        return ""
    path = Path(__file__).parent / "agent_v2" / "skills" / f"{skill_id}.md"
    return path.read_text() if path.exists() else ""


# ── Main ─────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug PAC1 task failures")
    parser.add_argument("--run-id", help="Local run ID (from SQLite DB)")
    parser.add_argument("--task-id", help="Specific task ID within the run")
    parser.add_argument("--trial-id", help="Direct BitGN trial ID (no DB lookup)")
    parser.add_argument("--all", action="store_true", help="Include passed tasks too")
    parser.add_argument("--no-ai", action="store_true", help="Show log only, skip AI analysis")
    args = parser.parse_args()

    cfg = ClaudeConfig.from_env()
    _harness: HarnessServiceClientSync | None = None

    def get_harness() -> HarnessServiceClientSync:
        nonlocal _harness
        if _harness is None:
            _harness = HarnessServiceClientSync(cfg.benchmark_host)
        return _harness

    # ── Collect tasks to analyze ─────────────────────────────
    tasks: list[dict] = []

    if args.trial_id:
        tasks.append({
            "trial_id": args.trial_id,
            "task_id": args.task_id or "?",
            "skill_id": "",
            "skill_confidence": 0.0,
            "score": None,
            "score_detail": [],
            "instruction": "",
        })

    elif args.run_id:
        db = store.get_db()
        sql = "SELECT * FROM tasks WHERE run_id = ?"
        params: list = [args.run_id]
        if args.task_id:
            sql += " AND task_id = ?"
            params.append(args.task_id)
        elif not args.all:
            sql += " AND score >= 0 AND score < 1.0"
        rows = db.execute(sql, params).fetchall()
        for row in rows:
            r = dict(row)
            r["score_detail"] = json.loads(r.get("score_detail") or "[]")
            if r.get("trial_id"):
                tasks.append(r)
            else:
                print(f"[SKIP] {r['task_id']}: no trial_id stored")

    else:
        # List available runs
        runs = store.list_runs()
        if not runs:
            print("No runs found in DB.")
            print("Usage: uv run python debug.py --run-id <id>  [--task-id <id>]")
            print("       uv run python debug.py --trial-id <trial_id>")
            return
        print("Available runs:\n")
        for r in runs:
            tasks_all = list(r.get("tasks", {}).values())
            failed = sum(1 for t in tasks_all if 0.0 <= t.get("score", -1) < 1.0)
            passed = sum(1 for t in tasks_all if t.get("score", -1) == 1.0)
            total = len(tasks_all)
            print(
                f"  {r['run_id']}  "
                f"score={r.get('final_score', 0):.1f}%  "
                f"passed={passed}  failed={failed}  total={total}  "
                f"model={r.get('model', '?')}"
            )
        print("\nUsage: uv run python debug.py --run-id <id> [--task-id <id>] [--all] [--no-ai]")
        return

    if not tasks:
        print("No matching tasks found.")
        return

    # ── Process each task ────────────────────────────────────
    for task_info in tasks:
        trial_id = task_info["trial_id"]
        task_id = task_info.get("task_id", "?")

        print(f"\n{'=' * 64}")
        print(f"Task: {task_id}  Trial: {trial_id}")
        print(f"Skill: {task_info.get('skill_id') or '(none)'}"
              f"  Score: {task_info.get('score')}")
        if task_info.get("score_detail"):
            print(f"Detail: {task_info['score_detail']}")
        print()

        # Try local DB first (captured during run), fall back to live API
        log_lines: list[str] = []
        log_source = ""

        if args.run_id:
            events = store.get_events(args.run_id, task_id)
            for ev in events:
                if ev.get("type") == "trial_log" and ev.get("trial_id") == trial_id:
                    log_lines = ev.get("lines", [])
                    log_source = "local DB"
                    break

        if not log_lines:
            print("Fetching trial log from BitGN API…")
            try:
                log_lines, meta = fetch_trial(get_harness(), trial_id)
                if not task_info.get("instruction"):
                    task_info["instruction"] = meta.get("instruction", "")
                if meta.get("score_detail"):
                    task_info["score_detail"] = meta["score_detail"]
                if meta.get("error"):
                    task_info["error"] = meta["error"]
                log_source = "BitGN API"
            except Exception as exc:
                print(f"[ERROR] {exc}")
                continue

        print(f"[{len(log_lines)} lines, source: {log_source}]")

        if not log_lines:
            print("[INFO] No logs available — BitGN only serves logs during active trials.")
            print(f"       Next runs will capture logs automatically.")
            print(f"       Harness URL: {task_info.get('harness_url', '(not stored)')}")
            print()
            if not args.no_ai:
                print("[SKIP] Cannot analyze without log.")
            continue

        print("─── Trial Log ───")
        for line in log_lines:
            print(line)
        print("─── End Log ───\n")

        if args.no_ai:
            continue

        skill_id = task_info.get("skill_id", "")
        skill_prompt = load_skill_prompt(skill_id)

        print("Analyzing with Claude…")
        analysis = asyncio.run(analyze(log_lines, task_info, skill_prompt, cfg.model))

        print("\n─── Analysis ───")
        print(analysis)
        print("─── End Analysis ───")


if __name__ == "__main__":
    main()
