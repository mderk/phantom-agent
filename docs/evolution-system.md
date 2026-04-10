# Evolution System

Automated failure analysis + prompt evolution for PAC1 benchmark agent.

## Problem

Current `debug.py` does one-off analysis per task. We need a system that:
1. Batch-analyzes all failures in a run
2. Groups them into patterns
3. Proposes prompt fixes and code changes
4. Tracks versioned iterations with before/after scores
5. Supports rollback (prompts and code independently)

## Architecture

```
Run benchmark → score 83.7%
       ↓
evolve.py analyze [--run-id <id>]
  1. Collect failed tasks from SQLite
  2. Per-task Claude analysis → structured JSON
  3. Cross-task synthesis → patterns + exact changes
  4. Create evolution/vNNN/ with proposals (nothing applied yet)
       ↓
evolve.py apply [--dry-run]              # prompt changes → agent_v2/skills/
evolve.py apply-code [--dry-run]         # code patches → git apply
       ↓
Run benchmark again
       ↓
evolve.py record [--run-id <id>]         # save score for current version
```

Key: `analyze` creates the version with proposals. `apply` and `apply-code` are separate
steps that write changes. Everything is reviewable before applying.

## Data Source: SQLite Events

All analysis data comes from the local DB (`benchmark-runs/pac1.db`). No BitGN API needed.

Per failed task, we have:
- `task_instruction` event: instruction text, trial_id
- `task_classified` event: skill_id, confidence, classifier type
- `prompts` event: full system_prompt + task_prompt sent to LLM
- `tool_start/tool_end` events: tool name, step number, result text
- `agent_output` event: final output, cost_usd, completion_submitted flag
- `tasks` row: score, score_detail (scorer's failure reason)

## Directory Structure

```
evolution/
  state.json              # current version + history
  v001/
    snapshot.json          # analysis, proposals, scores
    skills/                # full copy of all 12 skill .md files (before changes)
    system_prompt.md       # copy of system_prompt.md (before changes)
    proposed/              # proposed prompt changes (new file content)
      skills/inbox_processing.md
      skills/security_denial.md
    patches/               # code change proposals
      classifier.py.patch  # unified diff
      classifier.py.before # original file content (for rollback)
  v002/
    ...
evolve.py                  # CLI entry point
```

## CLI

```
evolve.py analyze       [--run-id <id>] [--model <model>]  # analyze failures, create version with proposals
evolve.py apply         [--version vNNN] [--dry-run]  # apply prompt changes from version
evolve.py apply-code    [--version vNNN] [--dry-run] [--patch <name>]  # apply code patches
evolve.py rollback      [--to vNNN]           # restore prompts from snapshot
evolve.py rollback-code [--to vNNN] [--version vNNN] [--patch <name>] [--dry-run]
evolve.py record        [--run-id <id>]       # record benchmark score for current version
evolve.py status                              # current version + history table
evolve.py diff          <v1> <v2>             # unified diff between versions
```

All `--run-id` and `--version` default to latest/current if omitted.

`--model` defaults to `claude-opus-4-6`. Example: `--model claude-sonnet-4-6`.

## Analysis Pipeline (3 stages)

### Stage 1: Collect Failures

Query `tasks` table for `score >= 0 AND score < 1.0`. For each, gather all events from `events` table. Build a structured failure record:

```python
{
    "task_id": "t20",
    "instruction": "TAKE CARE OF THE INBOX!",
    "skill_id": "inbox_processing",
    "skill_confidence": 0.95,
    "score_detail": ["expected outcome OUTCOME_NONE_CLARIFICATION, got OUTCOME_OK"],
    "system_prompt": "...",      # from prompts event
    "task_prompt": "...",        # from prompts event
    "tool_trace": [              # from tool_start/tool_end pairs
        {"step": 1, "tool": "get_skill_instructions", "result": "..."},
        {"step": 2, "tool": "list_directory", "result": "..."},
    ],
    "agent_output": "...",       # from agent_output event
    "cost_usd": 0.12
}
```

### Stage 2: Per-Task Root Cause Analysis

For each failed task, call Claude with structured prompt. Returns JSON:

```json
{
    "root_cause": "Agent processed cross-account data request without clarifying",
    "origin": "skill_prompt",
    "fix_type": "skill_prompt",
    "fix_target": "inbox_processing",
    "proposed_change": "Add rule: when sender requests data about a different account, CLARIFICATION",
    "confidence": 0.85
}
```

`origin` values: `skill_prompt | system_prompt | classifier | tool_code | agent_reasoning`
`fix_type` values: `skill_prompt | system_prompt | code | no_fix`

### Stage 3: Cross-Task Synthesis

Feed ALL per-task analyses + current skill prompt texts to Claude. It:
1. Groups failures by pattern
2. Generates exact new `.md` content for prompt changes
3. Generates code change proposals as unified diffs
4. Flags regression risks

## Change Application

### Prompt changes (`apply`)

`analyze` saves proposed prompt content to `evolution/vNNN/proposed/skills/*.md`.
`apply` copies them to `agent_v2/skills/`. Hot-reload picks up changes immediately.

```bash
uv run python evolve.py apply --dry-run    # show diff without writing
uv run python evolve.py apply              # write prompt changes
uv run python evolve.py apply --version v002  # from specific version
```

### Code patches (`apply-code`)

Each code proposal is stored as `.patch` + `.before`:
```
evolution/v002/patches/
  classifier.py.patch     # standard unified diff
  classifier.py.before    # original file content BEFORE patch
```

`.before` = snapshot of the original file before patching. Enables reliable rollback
regardless of how many versions have passed.

```bash
uv run python evolve.py apply-code --dry-run             # validate
uv run python evolve.py apply-code                       # apply all
uv run python evolve.py apply-code --patch classifier.py.patch  # apply one
uv run python evolve.py apply-code --version v002        # from specific version
```

Or directly: `git apply evolution/v002/patches/classifier.py.patch`

### Rollback prompts (`rollback`)

Restores `.md` files from the version's snapshot (copies taken before changes):
```bash
uv run python evolve.py rollback           # to previous version
uv run python evolve.py rollback --to v001 # to specific version
```

### Rollback code (`rollback-code`)

Restores `.before` files — works reliably across multiple versions:

```bash
uv run python evolve.py rollback-code                    # current version
uv run python evolve.py rollback-code --to v001          # multi-version
uv run python evolve.py rollback-code --patch classifier.py.patch  # one file
uv run python evolve.py rollback-code --dry-run          # preview
```

**Multi-version rollback logic:**

For each patched file, finds the earliest `.before` snapshot after target version:

```
v002 patches classifier.py  → v002/patches/classifier.py.before = v001 state
v003 patches classifier.py  → v003/patches/classifier.py.before = v002 state
v003 patches tools.py       → v003/patches/tools.py.before = v001 state

Rollback --to v001:
  classifier.py ← v002/patches/classifier.py.before  (earliest after v001)
  tools.py      ← v003/patches/tools.py.before        (earliest after v001)
```

## State Schema

### `state.json`
```json
{
    "current_version": 2,
    "history": [
        {
            "version": 1,
            "created_at": "2026-04-10T14:30:00Z",
            "source_run_id": "c398e271",
            "source_score": 83.7,
            "result_run_id": null,
            "result_score": null,
            "note": "7 failures -> 3 patterns -> 2 prompt changes"
        }
    ]
}
```

### `snapshot.json`
```json
{
    "version": 1,
    "parent_version": null,
    "created_at": "2026-04-10T14:30:00Z",
    "source_run_id": "c398e271",
    "source_run_score": 83.7,
    "analysis": {
        "failed_tasks": [{ "task_id": "t20", "root_cause": "...", "..." : "..." }],
        "patterns": [{ "name": "...", "affected_tasks": ["..."] }],
        "regression_risks": ["..."]
    },
    "prompt_changes": [
        { "file": "skills/inbox_processing.md", "reason": "..." }
    ],
    "code_proposals": [
        { "file": "agent_v2/skills/classifier.py", "description": "...", "patch": "patches/classifier.py.patch" }
    ],
    "applied": false,
    "result_run_id": null,
    "result_score": null
}
```

## Typical Workflow

```bash
# 1. Run benchmark
uv run python main_claude.py

# 2. Analyze failures → creates evolution version
uv run python evolve.py analyze
# Creates evolution/v001/ with analysis + proposals

# 3. Review proposed prompt changes
uv run python evolve.py apply --dry-run

# 4. Apply prompt changes
uv run python evolve.py apply

# 5. (Optional) Review and apply code patches
uv run python evolve.py apply-code --dry-run
uv run python evolve.py apply-code

# 6. Run benchmark again
uv run python main_claude.py

# 7. Record result
uv run python evolve.py record

# 8. Check progress
uv run python evolve.py status
# v001: 83.7% → 90.7%

# 9. If regression — rollback
uv run python evolve.py rollback
uv run python evolve.py rollback-code
```
