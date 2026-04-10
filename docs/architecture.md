# Architecture

## C4 — System Context

```
┌─────────────┐         ┌──────────────────┐         ┌──────────────┐
│  Developer  │────────▶│  Phantom Agent   │────────▶│  BitGN       │
│  (Browser)  │◀────────│  System          │◀────────│  Platform    │
└─────────────┘  HTTP   └──────────────────┘  gRPC   └──────────────┘
                 SSE      │                            │
                          │  Runs tasks in             │  Provides sandboxed
                          │  isolated VMs              │  file-system VMs
                          │                            │  Scores results
                          ▼                            │
                 ┌──────────────────┐                  │
                 │  LLM Provider    │                  │
                 │  (vLLM + patches)│◀─────────────────┘
                 └──────────────────┘
                   Chat Completions API
```

**Phantom Agent** is an autonomous system that:
1. Receives 43 tasks from the BitGN benchmark platform
2. Runs each task inside an isolated sandbox VM via gRPC
3. Uses an LLM (gpt-oss-120b via patched vLLM) to reason and execute
4. Reports results back to the platform for scoring
5. Achieves ~93% average, 100% best

## C4 — Container Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│  Phantom Agent System                                           │
│                                                                 │
│  ┌──────────────┐    SSE    ┌──────────────────────────────┐    │
│  │  Dashboard   │◀─────────▶│  FastAPI Server              │    │
│  │  (React/Vite)│           │  server.py                   │    │
│  │              │    HTTP   │                              │    │
│  │  - Run tab   │──────────▶│  - /api/runs (CRUD+SSE)      │    │
│  │  - Compare   │           │  - /api/config/llm (GET/PUT) │    │
│  │  - Skills    │           │  - /api/config/temperature    │    │
│  │  - Settings  │           │  - /api/runs/:id/stop         │    │
│  │  - Repeat N  │           │  - /api/skills, /api/prompt   │    │
│  │  - Fail→Next │           │  - stop_on_fail support       │    │
│  └──────────────┘           └──────────┬───────────────────┘    │
│                                         │                       │
│                              ┌──────────▼───────────────────┐   │
│                              │  Agent Runner                │   │
│                              │  agent_v2/agent.py           │   │
│                              │                              │   │
│                              │  ┌──────────┐ ┌───────────┐  │   │
│                              │  │Classifier│ │Skills Menu│  │   │
│                              │  │LLM+Regex │ │12x in sys │  │   │
│                              │  └──────────┘ └───────────┘  │   │
│                              │  ┌──────────┐ ┌───────────┐  │   │
│                              │  │Tools 13x │ │Resilience │  │   │
│                              │  │Action+Obj│ │Retry+Force│  │   │
│                              │  └──────────┘ └───────────┘  │   │
│                              │  ┌──────────┐ ┌───────────┐  │   │
│                              │  │Harmony   │ │Auto-merge │  │   │
│                              │  │Fix Patch │ │Refs       │  │   │
│                              │  └──────────┘ └───────────┘  │   │
│                              └──────────┬───────────────────┘   │
│                                         │                       │
│                              ┌──────────▼───────────────────┐   │
│                              │  SQLite (db.py)              │   │
│                              │  runs, tasks, events         │   │
│                              └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
         │                              │
         │ gRPC (protobuf)              │ OpenAI Chat Completions
         ▼                              ▼
┌──────────────────┐          ┌──────────────────────────────┐
│  BitGN Harness   │          │  vLLM v0.14.1 (patched)     │
│  - Sandbox VMs   │          │  gpt-oss-120b               │
│  - Scoring       │          │  x2 4090 (48GB), mxfp4 quant│
│  - Leaderboard   │          │  + PR#34454 multi-turn fix   │
└──────────────────┘          │  + Harmony name cleanup      │
                              │  HF_HUB_OFFLINE=1            │
                              └──────────────────────────────┘
```

## C4 — Component Diagram (Agent Runner)

```
┌──────────────────────────────────────────────────────────────────┐
│  Agent Runner (agent_v2/)                                        │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  Prompt Architecture (Progressive Disclosure)               │ │
│  │                                                             │ │
│  │  System Prompt (5.2K, cached):                              │ │
│  │  ├── MAIN_ROLE + APPROACH + SECURITY + CONSTRAINTS          │ │
│  │  ├── COMPLETION (outcome rules)                             │ │
│  │  └── AVAILABLE_SKILLS (12x name+description)                │ │
│  │                                                             │ │
│  │  User Prompt (~300 chars):                                  │ │
│  │  ├── <TASK> instruction                                     │ │
│  │  ├── Recommended skill: X (from classifier)                 │ │
│  │  └── <GOAL> load skill, execute, submit                     │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────────────────┐ │
│  │  Task Classification                                        │ │
│  │  1. LLM Classifier → skill_id + confidence                  │ │
│  │  2. Regex fallback if LLM returns "clarification"           │ │
│  └────────────────────────┬────────────────────────────────────┘ │
│                           │                                      │
│  ┌────────────────────────▼────────────────────────────────────┐ │
│  │  OpenAI Agents SDK Runner + Resilience Stack                │ │
│  │                                                             │ │
│  │  ReAct Loop:                                                │ │
│  │    LLM → tool call → result → LLM → ... → submit_answer    │ │
│  │                                                             │ │
│  │  Retry Layer:                                               │ │
│  │  ├── Text-only output (no tools) → retry 3x                │ │
│  │  ├── ModelBehaviorError (corruption) → retry 3x             │ │
│  │  └── <5 tool calls without submit → retry                  │ │
│  │                                                             │ │
│  │  Force-Tool Layer:                                          │ │
│  │  └── No submit_answer → minimal agent with ONLY submit     │ │
│  │      tool_choice="required", gets task context              │ │
│  │                                                             │ │
│  │  Harmony Fix Layer:                                         │ │
│  │  └── Function.__init__ + ResponseFunctionToolCall.__init__  │ │
│  │      patched to clean corrupted names at parse time         │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──────────────┐ ┌──────────────────┐ ┌───────────────────────┐ │
│  │ Tools (13)   │ │ Skills (12)      │ │ Context               │ │
│  │              │ │                  │ │                       │ │
│  │ workspace_ctx│ │ Loaded on-demand │ │ runtime_url           │ │
│  │ dir_tree     │ │ via get_skill_*  │ │ task_text             │ │
│  │ list_dir     │ │ tool call        │ │ telemetry             │ │
│  │ read_file    │ │                  │ │ files_read[]          │ │
│  │ find_files   │ │ inbox_processing │ │ files_written[]       │ │
│  │ search_text  │ │ email_outbound   │ │ file_contents{}       │ │
│  │ write_file   │ │ crm_lookup       │ │ completion_submitted  │ │
│  │ delete_file  │ │ security_denial  │ │                       │ │
│  │ create_dir   │ │ knowledge_*      │ │ Auto-merge refs:      │ │
│  │ move_file    │ │ invoice_creation │ │ submit_answer adds    │ │
│  │ list_skills  │ │ followup_resched │ │ all read/written files│ │
│  │ get_skill_*  │ │ purchase_ops     │ │ to grounding_refs     │ │
│  │ submit_answer│ │ clarification    │ │                       │ │
│  └──────────────┘ └──────────────────┘ └───────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **LLM** | OpenAI Agents SDK (`openai-agents>=0.0.7`) | ReAct agent loop, tool execution, hooks |
| **LLM Client** | OpenAI Python SDK (`openai>=2.26.0`) | Chat completions via `OpenAIChatCompletionsModel` |
| **LLM Server** | vLLM v0.14.1 (patched) | gpt-oss-120b serving, 2x 4090 GPU, mxfp4 quant |
| **Backend** | FastAPI (`fastapi>=0.115.0`) + Uvicorn | REST API, SSE streaming, run management |
| **Frontend** | React 19 + Vite 8 + Tailwind CSS 4 | Live dashboard, heatmap, repeat runs |
| **Persistence** | SQLite (stdlib `sqlite3`) | Runs, tasks, events — WAL mode |
| **Platform SDK** | `bitgn-local-sdk` + `connectrpc` | gRPC client for BitGN sandbox VMs |
| **Serialization** | Protobuf (`protobuf>=6.33.0`) | BitGN harness protocol |
| **Config** | python-dotenv + os.getenv | Credentials via .env file |

## Data Flow — Single Task Execution

```
1. Server receives POST /api/runs {concurrency, stop_on_fail}
   └─ Creates BenchmarkRun, starts async _run_benchmark_async()

2. Harness connection
   └─ start_run() → get trial_ids for leaderboard
   └─ For each task: start_trial() → get instruction + runtime_url

3. Classification (agent.py)
   ├─ LLM classifier: sends task text → gets skill_id + confidence
   ├─ If "clarification" → regex classifier overrides
   └─ Skill hint passed in user prompt (model loads full skill on demand)

4. Agent execution with resilience
   ├─ Runner.run(agent, task_prompt, context, hooks, max_turns=50)
   ├─ Harmony fix: corrupted tool names cleaned at SDK parse level
   ├─ ReAct loop: LLM → tool call → runtime gRPC → result → LLM
   ├─ Hooks emit SSE events in real-time
   ├─ If text-only/error → retry up to 3x
   └─ If no submit_answer → force-tool agent (tool_choice=required)

5. Completion
   ├─ submit_answer(message, outcome, grounding_refs)
   ├─ Auto-merge: all files_read + files_written added to refs
   ├─ end_trial() → score from harness
   └─ SSE: task_done event with score, tokens, timing

6. Early stop (if stop_on_fail enabled)
   └─ First task with score=0 → skip remaining tasks → finalize run

7. Run finish
   ├─ submit_run() → leaderboard (skipped if early-stopped)
   └─ SQLite: persist final scores
```

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **Progressive skill disclosure** | System prompt only has skills menu (~100 tok/skill). Full skill loaded on-demand via tool call. Reduces initial context from 14K to 6.5K chars. |
| **OpenAI Agents SDK** over raw completions | Built-in ReAct loop, tool management, hooks. Avoids reimplementing orchestration. |
| **Dual classifier** (LLM + regex) | LLM handles nuance, regex catches patterns LLM misclassifies (e.g. ALL CAPS requests) |
| **Action+Object tool naming** | `search_text` not `search`, `submit_answer` not `report_completion`. Improves model tool selection accuracy. |
| **Harmony monkey-patch at SDK level** | Patches `Function.__init__` to clean corrupted names. Earliest possible interception — before any SDK logic. |
| **Auto-merge grounding_refs** | Model forgets refs 50%+ of the time. Auto-adding all read/written files eliminates this failure class. |
| **Force-tool with single tool** | When model outputs text, force agent with ONLY `submit_answer` + `tool_choice=required` guarantees tool call. |
| **Stop-on-fail** | For iteration: abort run on first failure, start next. 10x faster when tuning. |
| **SQLite WAL mode** | Concurrent reads during benchmark runs without locking |
| **SSE streaming** (not WebSocket) | Simpler, works with EventSource API, auto-reconnect |
| **Hot-reload skill prompts** from `.md` files | Edit file → next run picks it up. No restart needed. |
| **vLLM patches mounted as volumes** | Survive container restarts. PR #34454 + Harmony cleanup. |
