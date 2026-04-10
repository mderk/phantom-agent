---
name: debug-benchmark
description: Query PAC1 benchmark database to analyze task failures — list runs, find failed tasks, read trial logs, and inspect agent behavior. Use this skill whenever analyzing benchmark results, investigating why a task scored 0, reviewing agent logs, or when the user mentions a task ID like "t31" or a run. Also use when the user pastes a trial log and wants to compare with stored data.
---

# Debug Benchmark

Query the SQLite database at `benchmark-runs/pac1.db` to analyze benchmark runs and task failures.

## Database schema

Three tables: `runs`, `tasks`, `events`.

```sql
-- runs: one row per benchmark run
runs(run_id TEXT PK, status TEXT, concurrency INT, model TEXT, temperature REAL,
     final_score REAL, started_at REAL, finished_at REAL, leaderboard_run_id TEXT)

-- tasks: one row per task within a run
tasks(run_id TEXT, task_id TEXT, trial_id TEXT, harness_url TEXT, instruction TEXT,
      skill_id TEXT, skill_confidence REAL, score REAL, score_detail TEXT JSON,
      tool_calls INT, wall_time_ms INT, status TEXT)

-- events: tool calls, logs, results per task
events(run_id TEXT, task_id TEXT, event_type TEXT, data TEXT JSON, ts REAL)
```

## Common queries

Run these with `sqlite3 benchmark-runs/pac1.db`.

### List runs with scores

```bash
sqlite3 -header -column benchmark-runs/pac1.db "
  SELECT run_id, model, final_score, temperature,
         datetime(started_at, 'unixepoch', 'localtime') as started
  FROM runs ORDER BY created_at DESC LIMIT 10"
```

### Failed tasks in a run

```bash
sqlite3 -header -column benchmark-runs/pac1.db "
  SELECT task_id, skill_id, score, score_detail, tool_calls, wall_time_ms
  FROM tasks WHERE run_id = '<RUN_ID>' AND score >= 0 AND score < 1.0
  ORDER BY task_id"
```

### All tasks in a run (with pass/fail)

```bash
sqlite3 -header -column benchmark-runs/pac1.db "
  SELECT task_id, skill_id, score, tool_calls
  FROM tasks WHERE run_id = '<RUN_ID>'
  ORDER BY task_id"
```

### Task details

```bash
sqlite3 -header -column benchmark-runs/pac1.db "
  SELECT task_id, instruction, skill_id, skill_confidence, score, score_detail,
         trial_id, harness_url, tool_calls, wall_time_ms
  FROM tasks WHERE run_id = '<RUN_ID>' AND task_id = '<TASK_ID>'"
```

### Prompts sent to agent

System prompt and task prompt are stored as a `prompts` event:

```bash
sqlite3 benchmark-runs/pac1.db "
  SELECT json_extract(data, '$.system_prompt') FROM events
  WHERE run_id = '<RUN_ID>' AND task_id = '<TASK_ID>' AND event_type = 'prompts'"
```

```bash
sqlite3 benchmark-runs/pac1.db "
  SELECT json_extract(data, '$.task_prompt') FROM events
  WHERE run_id = '<RUN_ID>' AND task_id = '<TASK_ID>' AND event_type = 'prompts'"
```

### Agent log for a task

The full agent interaction is in `tool_start` and `tool_end` events:

```bash
sqlite3 benchmark-runs/pac1.db "
  SELECT data FROM events
  WHERE run_id = '<RUN_ID>' AND task_id = '<TASK_ID>'
    AND event_type IN ('tool_start', 'tool_end', 'agent_output')
  ORDER BY ts"
```

To see tool names and results in readable form:

```bash
sqlite3 benchmark-runs/pac1.db "
  SELECT event_type,
         coalesce(json_extract(data, '$.tool'), '') as tool,
         substr(coalesce(json_extract(data, '$.result'), json_extract(data, '$.output'), ''), 1, 300) as detail
  FROM events
  WHERE run_id = '<RUN_ID>' AND task_id = '<TASK_ID>'
    AND event_type IN ('tool_start', 'tool_end', 'agent_output')
  ORDER BY ts"
```

### Cross-run comparison for a specific task

```bash
sqlite3 -header -column benchmark-runs/pac1.db "
  SELECT r.run_id, r.model, t.score, t.skill_id, t.tool_calls
  FROM tasks t JOIN runs r ON t.run_id = r.run_id
  WHERE t.task_id = '<TASK_ID>'
  ORDER BY r.created_at DESC"
```

### Stability: tasks that sometimes fail

```bash
sqlite3 -header -column benchmark-runs/pac1.db "
  SELECT task_id,
         COUNT(*) as runs,
         SUM(CASE WHEN score = 1.0 THEN 1 ELSE 0 END) as passes,
         SUM(CASE WHEN score >= 0 AND score < 1.0 THEN 1 ELSE 0 END) as fails
  FROM tasks WHERE score >= 0
  GROUP BY task_id HAVING fails > 0
  ORDER BY fails DESC"
```

## Fetching live trial logs from BitGN

If the log isn't in the database (older runs), use the debug script:

```bash
uv run python debug.py --run-id <RUN_ID> --task-id <TASK_ID> --no-ai
```

This fetches the trial log from the BitGN API and prints it. The `--no-ai` flag skips the AI analysis step.

## Workflow

1. Start by listing recent runs to find the relevant run_id
2. Query failed tasks to see what went wrong
3. For each failure, check `score_detail` — it usually contains the specific error (e.g., "unexpected file write", "missing required reference")
4. Pull the trial log to see the agent's step-by-step actions
5. Cross-reference with the skill prompt in `agent_v2/skills/<skill_id>.md`
6. Identify whether the failure is a skill prompt issue, agent reasoning error, or workspace ambiguity
