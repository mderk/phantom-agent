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

Credentials via `.env` file (not committed) or Settings tab in dashboard.

## Restarting Services

Backend does NOT auto-reload. After changing Python files:
```bash
kill $(lsof -t -i :8000) && uv run python server.py
```
Frontend (Vite) hot-reloads automatically — no restart needed for JSX/CSS changes.

## Architecture

**v2 Agent** — Pure LLM ReAct on OpenAI Agents SDK. Progressive skill disclosure.

```
User task → LLM Classifier (picks skill)
  → Agent receives: system_prompt (5.2K) + skills_menu + task + skill_hint
  → Step 1: get_skill_instructions(recommended_skill) — loads full workflow
  → ReAct loop: LLM → tool call → result → LLM → ... → submit_answer
  → Fallbacks: retry on text-only/ModelBehaviorError → force-tool agent → error recovery
```

### Key Files

| File | Purpose |
|---|---|
| `main_v2.py` | CLI benchmark runner (sliding window parallelism) |
| `server.py` | FastAPI + SSE backend for dashboard |
| `agent_v2/agent.py` | Agent creation, run_task, retries, force-tool, Harmony patches |
| `agent_v2/prompts.py` | System prompt + skills menu builder + task prompt builder |
| `agent_v2/system_prompt.md` | System prompt: MAIN_ROLE, APPROACH, SECURITY, CONSTRAINTS, COMPLETION |
| `agent_v2/tools.py` | 13 tools via @function_tool, auto-merge grounding_refs |
| `agent_v2/skills/` | 12 skill prompts (.md) + classifier + LLM classifier |
| `agent_v2/hooks.py` | Live logging hooks (console + SSE) |
| `agent_v2/runtime.py` | Async PCM gRPC wrapper |
| `agent_v2/db.py` | SQLite persistence (runs, tasks, events) |
| `agent_v2/config.py` | Env config via .env / os.getenv |
| `agent_v2/verifier.py` | Optional outcome verifier (kimi-k2.5, currently unused) |

### Prompt Architecture (Progressive Disclosure)

```
System Prompt (5.2K, cached by vLLM prefix caching):
  ├── MAIN_ROLE — who you are
  ├── APPROACH — orient → understand → ground → execute → verify → complete
  ├── SECURITY — injection markers, traps, OTP rules, spoofing
  ├── CONSTRAINTS — 17 rules
  ├── COMPLETION — submit_answer format, outcomes
  └── AVAILABLE_SKILLS — 12 skills menu (name + description)

User Prompt (~300 chars per task):
  ├── <TASK> — task instruction
  ├── Recommended skill: X — classifier hint
  └── <GOAL> — load skill, execute, submit

On-demand (agent calls get_skill_instructions):
  └── Full skill prompt (1-6K chars) loaded into conversation
```

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
| `get_skill_instructions` | Load full skill workflow by ID |
| `submit_answer` | Submit final answer + auto-merge grounding_refs |

### Skills (12)

| Skill | When |
|---|---|
| security_denial | Prompt injection, hostile payloads |
| inbox_processing | Process CRM/knowledge inbox messages (security, OTP, email, invoice) |
| email_outbound | Send email via /outbox/ to contacts/accounts |
| crm_lookup | Find accounts, contacts, emails, managers, count items |
| invoice_creation | Create invoice JSON |
| followup_reschedule | Update follow-up dates |
| knowledge_capture | Capture + distill from inbox |
| knowledge_cleanup | Delete cards/threads |
| knowledge_lookup | Find articles by date (not found = CLARIFICATION) |
| unsupported_capability | Calendar, Salesforce, upload, HTTP push |
| purchase_ops | Fix purchase ID prefix |
| clarification | Ambiguous/truncated requests |

## Resilience Stack

### 1. Harmony Tool Name Corruption Fix
gpt-oss-120b generates corrupted tool names like `list_directory<|channel|>commentary`.
Patched at OpenAI SDK level — `Function.__init__` and `ResponseFunctionToolCall.__init__`
clean names via regex before any SDK logic sees them.

### 2. Retry on Failure
- **Text-only output** (model returns text, no tool call): retry up to 3x
- **ModelBehaviorError** (corrupted tool name not caught): retry up to 3x
- **Partial work** (<5 tool calls without submit): retry

### 3. Force-Tool Agent
If agent finishes without `submit_answer`, a minimal agent with ONLY `submit_answer` tool
and `tool_choice="required"` is invoked. Gets task context to make informed decision.

### 4. Auto-Merge Grounding Refs
`submit_answer` automatically adds all files the model read/wrote but forgot to include
in grounding_refs (excluding README, AGENTS, docs, process files).

### 5. vLLM Patches (applied on server 109.230.162.92)
- PR #34454: Multi-turn Harmony parsing fix (empty outputs in multi-turn)
- Recipient cleaning: `_clean_harmony_name()` in harmony_utils.py
- Mounted as volumes in docker container (`/home/ndtsrv2/vllm-patches/`)

## GPT-OSS-120B Notes

- vLLM v0.14.1 with patches, `HF_HUB_OFFLINE=1`
- Harmony response format — reasoning in separate channel
- `OpenAIChatCompletionsModel` required (not Responses API)
- search_text limit=2000 for counting (files with 1000+ lines)
- `--tensor-parallel-size 2 --quantization mxfp4 --max-num-seqs 16`

## Environment Variables (.env file)

| Var | Default | Notes |
|---|---|---|
| `OPENAI_API_KEY` | — | Model API key |
| `OPENAI_BASE_URL` | — | API endpoint URL |
| `MODEL_ID` | gpt-oss-120b | Model name |
| `BITGN_API_KEY` | — | Leaderboard key |
| `BITGN_RUN_NAME` | neuraldeep gpt oss120b x2 4090(48gb) | Run name on leaderboard |
| `AGENT_CONCURRENCY` | 10 | Parallel agents (slider up to 30) |
| `AGENT_MAX_TURNS` | 50 | Max ReAct steps per task |
| `AGENT_REQUEST_TIMEOUT` | 120 | LLM timeout (seconds) |

## Current Score: ~93% average, 100% best

Best: 100% (43/43). Average over last 10 runs: 93.5%. Range: 90-100%.

## Dashboard Features

- **Run tab**: live SSE logs per task, score, tool calls, timing, cost, fail detail
- **Compare tab**: heatmap across runs (oldest left, newest right), stability analysis
- **Skills tab**: view/test all prompts, system prompt viewer
- **Settings tab**: LLM config (model, endpoint, token, BitGN key)
- **Header**: model dropdown, temp/agents sliders, Repeat (1-50), Fail→Next, Stop button
- **Sidebar**: run history, delete, compare checkboxes
- **Per-task**: expanded view with Expected vs Actual for failures
- **SQLite**: all events persisted in benchmark-runs/pac1.db

## Documentation

- [Benchmark Overview](docs/benchmark-overview.md) — Protocol, runtime, workspaces
- [Tasks Catalog](docs/tasks-catalog.md) — All 43 tasks with expected outcomes
- [Scoring Rules](docs/scoring-rules.md) — grounding_refs, common failures
- [Architecture](docs/architecture.md) — C4 diagrams, tech stack
- [Configuration](docs/configuration.md) — Env vars, commands
- [Optimization Guide](docs/optimization-guide.md) — All learnings, error patterns, fixes
- [Issues Tracker](ISSUES.md) — Known failing tasks with root causes
