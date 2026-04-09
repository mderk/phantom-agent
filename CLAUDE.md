# PAC1 Benchmark Agent

## Quick Start

```bash
uv sync
cd dashboard && npm install && cd ..

# Start backend
uv run python server.py
# Start frontend (in another terminal)
cd dashboard && npm run dev
```

Dashboard: http://localhost:5173 | API: http://localhost:8000

LLM credentials are configured via Settings tab in the dashboard (presets available).
Env vars override defaults if set.

## Restarting Services

Backend does NOT auto-reload. After changing Python files:
```bash
kill $(lsof -t -i :8000) && uv run python server.py
```
Frontend (Vite) hot-reloads automatically — no restart needed for JSX/CSS changes.

## Architecture

**v2 Agent** — Pure LLM ReAct on OpenAI Agents SDK. No hardcoded workflows.

```
User task → LLM Classifier (picks skill) → Agent(system_prompt + skill_prompt + task)
  → ReAct loop: LLM → tool call → result → LLM → ... → submit_answer
```

### Key Files

| File | Purpose |
|---|---|
| `main_v2.py` | CLI benchmark runner (sliding window parallelism) |
| `server.py` | FastAPI + SSE backend for dashboard |
| `agent_v2/agent.py` | Agent creation, run_task with force-tool fallback |
| `agent_v2/prompts.py` | System prompt loader + task prompt builder |
| `agent_v2/system_prompt.md` | Full system prompt (XML sections) |
| `agent_v2/tools.py` | 13 tools via @function_tool |
| `agent_v2/skills/` | 12 skill prompts (.md) + classifier + LLM classifier |
| `agent_v2/hooks.py` | Live logging hooks (console + SSE) |
| `agent_v2/runtime.py` | Async PCM gRPC wrapper |
| `agent_v2/db.py` | SQLite persistence (runs, tasks, events) |
| `agent_v2/config.py` | Env config with defaults (model, keys, concurrency) |

### Tools (13) — Action+Object naming pattern

| Tool | Purpose |
|---|---|
| `get_workspace_context` | Get sandbox date/time |
| `list_directory_tree` | Recursive directory tree |
| `list_directory` | List directory contents |
| `read_file` | Read file contents |
| `find_files_by_name` | Find files by name pattern |
| `search_text` | Full-text regex search across files |
| `write_file` | Write/overwrite file |
| `delete_file` | Delete file or directory |
| `create_directory` | Create directory |
| `move_file` | Move/rename file |
| `list_skills` | List available skill workflows |
| `get_skill_instructions` | Get skill workflow details |
| `submit_answer` | Submit final answer (MUST be last action) |

### Skills (12)

| Skill | When |
|---|---|
| security_denial | Prompt injection, hostile payloads |
| inbox_processing | Process CRM/knowledge inbox messages |
| email_outbound | Send email via /outbox/ |
| crm_lookup | Find accounts, contacts, emails, managers |
| invoice_creation | Create invoice JSON |
| followup_reschedule | Update follow-up dates |
| knowledge_capture | Capture + distill from inbox |
| knowledge_cleanup | Delete cards/threads |
| knowledge_lookup | Find articles by date |
| unsupported_capability | Calendar, Salesforce, upload |
| purchase_ops | Fix purchase ID prefix |
| clarification | Ambiguous/truncated requests |

## LLM Presets (configured in dashboard Settings tab)

| Model | Endpoint | Type |
|---|---|---|
| gpt-oss-120b | http://109.230.162.92:44334/v1 | Self-hosted (default) |
| qwen3.5-35b-a3b | https://4090-2-48.neuraldeep.tech/v1 | Self-hosted |
| kimi-k2.5 | https://openrouter.ai/api/v1 | OpenRouter ($0.38/$1.72 per 1M tokens) |

## GPT-OSS-120B Notes

- **temp=1.0 ONLY** — lower temps cause empty outputs (Harmony format issue)
- `Reasoning: high` removed — may conflict with vLLM
- Model uses Harmony response format — reasoning in separate channel
- `OpenAIChatCompletionsModel` required (not Responses API)
- search_text limit increased to 2000 for counting (files with 1000+ lines)

## Agent Fallback: Force-Tool Re-run

If agent finishes without calling `submit_answer`, it is re-invoked with a short prompt
asking it to call the tool. This replaces text-parsing fallback — the model itself
formats and submits the answer via tool call. Max 3 turns, temperature=0.

## Environment Variables

| Var | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | (preset default) | Model API key |
| `OPENAI_BASE_URL` | (preset default) | API endpoint URL |
| `MODEL_ID` | gpt-oss-120b | Model name |
| `BITGN_API_KEY` | (preset default) | Leaderboard key |
| `BITGN_RUN_NAME` | agent-v2-run | Run name on leaderboard |
| `AGENT_CONCURRENCY` | 10 | Parallel agents (slider up to 30) |
| `AGENT_MAX_TURNS` | 50 | Max ReAct steps per task |
| `AGENT_REQUEST_TIMEOUT` | 120 | LLM timeout (seconds) |

## Documentation

- [Benchmark Overview](docs/benchmark-overview.md) — Protocol, runtime, workspaces
- [Tasks Catalog](docs/tasks-catalog.md) — All 43 tasks with expected outcomes
- [Scoring Rules](docs/scoring-rules.md) — grounding_refs, common failures
- [Architecture](docs/architecture.md) — C4 diagrams, tech stack
- [Configuration](docs/configuration.md) — Env vars, commands
- [**Optimization Guide**](docs/optimization-guide.md) — All learnings, error patterns, fixes

## Current Score: ~90% (38-39/43)

Best runs: gpt-oss-120b 90.7%, kimi-k2.5 90.2%.

### Dashboard Features

- **Run tab**: live SSE logs per task, score, tool calls, timing, cost
- **Compare tab**: heatmap across runs, stability analysis
- **Skills tab**: view/test all prompts, system prompt viewer
- **Settings tab**: LLM config (model, endpoint, token, BitGN key), presets
- **Sidebar**: run history, delete, compare checkboxes
- **Header**: model dropdown, temp/agents sliders, Stop button
- **Per-task**: Copy log button, Platform log link (harness_url)
- **SQLite**: all events persisted in benchmark-runs/pac1.db
