"""FastAPI backend with SSE streaming for the PAC1 dashboard."""
from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    EndTrialRequest,
    GetBenchmarkRequest,
    RunState,
    StartPlaygroundRequest,
    StartRunRequest,
    StartTrialRequest,
    StatusRequest,
    SubmitRunRequest,
)

from agent_v2.config import Config
from agent_v2.agent import create_agent, run_task
from agent_v2.skills import classify_task, SKILL_REGISTRY
from agent_v2 import db as store

# ── State ───────────────────────────────────────────────────


class RunStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class TaskResult:
    task_id: str
    instruction: str = ""
    skill_id: str = ""
    skill_confidence: float = 0.0
    score: float = -1
    score_detail: list[str] = field(default_factory=list)
    tool_calls: int = 0
    wall_time_ms: int = 0
    status: str = "pending"
    harness_url: str = ""
    trial_id: str = ""


@dataclass
class BenchmarkRun:
    run_id: str
    concurrency: int = 5
    status: RunStatus = RunStatus.IDLE
    tasks: dict[str, TaskResult] = field(default_factory=dict)
    leaderboard_run_id: str | None = None
    final_score: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    temperature: float = 1.0
    model: str = ""


_runs: dict[str, BenchmarkRun] = {}
_event_queues: dict[str, list[asyncio.Queue]] = {}
_cfg: Config | None = None
_agent = None
_temperature: float = 1.0


def _get_cfg() -> Config:
    global _cfg
    if _cfg is None:
        _cfg = Config.from_env()
    return _cfg


def _get_agent():
    global _agent, _temperature
    # Recreate agent to pick up temperature changes
    _agent = create_agent(_get_cfg(), temperature=_temperature)
    return _agent


# ── SSE ─────────────────────────────────────────────────────


def _emit(run_id: str, event_type: str, data: dict) -> None:
    payload = {"type": event_type, "ts": time.time(), **data}
    # Persist to SQLite
    store.insert_event(run_id, event_type, payload)
    # Push to live SSE subscribers
    for q in _event_queues.get(run_id, []):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def _make_emitter(run_id: str):
    """Returns a callback compatible with on_event(type, data)."""
    def _on_event(event_type: str, data: dict) -> None:
        _emit(run_id, event_type, data)
    return _on_event


async def _sse_generator(run_id: str) -> AsyncGenerator[str, None]:
    run = _runs.get(run_id)

    # For completed runs: replay saved events from SQLite and close
    if run and run.status in (RunStatus.DONE, RunStatus.ERROR):
        yield f"event: snapshot\ndata: {json.dumps(_run_to_dict(run))}\n\n"
        saved = store.get_events(run_id)
        for ev in saved:
            yield f"event: {ev.get('type','event')}\ndata: {json.dumps(ev)}\n\n"
        yield f"event: replay_done\ndata: {{}}\n\n"
        return

    # For live runs: subscribe to queue
    q: asyncio.Queue = asyncio.Queue(maxsize=1000)
    _event_queues.setdefault(run_id, []).append(q)
    try:
        if run:
            yield f"event: snapshot\ndata: {json.dumps(_run_to_dict(run))}\n\n"
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30)
                yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                if event["type"] in ("run_done", "run_error"):
                    break
            except asyncio.TimeoutError:
                yield "event: ping\ndata: {}\n\n"
    finally:
        subs = _event_queues.get(run_id, [])
        if q in subs:
            subs.remove(q)


# ── Agent runner ────────────────────────────────────────────


async def _run_single(
    cfg: Config, agent, harness, run_id: str,
    task_id: str, trial_id: str | None, benchmark_id: str,
    task_result: TaskResult,
) -> None:
    task_result.status = "running"
    emitter = _make_emitter(run_id)
    emitter("task_start", {"task_id": task_id})

    try:
        if trial_id:
            trial = await asyncio.to_thread(
                harness.start_trial, StartTrialRequest(trial_id=trial_id)
            )
        else:
            trial = await asyncio.to_thread(
                harness.start_playground,
                StartPlaygroundRequest(benchmark_id=benchmark_id, task_id=task_id),
            )

        task_result.instruction = trial.instruction
        task_result.harness_url = trial.harness_url
        task_result.trial_id = trial.trial_id
        store.upsert_task(run_id, task_id,
                          trial_id=trial.trial_id,
                          harness_url=trial.harness_url,
                          instruction=trial.instruction,
                          status="running")
        emitter("task_instruction", {
            "task_id": task_id,
            "instruction": trial.instruction,
            "trial_id": trial.trial_id,
            "harness_url": trial.harness_url,
        })

        # Run agent — hooks emit events via on_event callback
        telemetry = await run_task(
            cfg, agent, trial.harness_url, trial.instruction,
            task_id=task_id, on_event=emitter,
        )

        # Update skill from classification (done inside run_task)
        task_result.skill_id = task_result.skill_id  # already set via events

        # Score
        result = await asyncio.to_thread(
            harness.end_trial, EndTrialRequest(trial_id=trial.trial_id)
        )
        task_result.score = result.score if result.score >= 0 else 0.0
        task_result.score_detail = list(result.score_detail)
        task_result.tool_calls = telemetry.tool_calls
        task_result.wall_time_ms = telemetry.wall_time_ms
        task_result.status = "done"

        store.upsert_task(run_id, task_id,
                          score=task_result.score,
                          score_detail=task_result.score_detail,
                          tool_calls=task_result.tool_calls,
                          wall_time_ms=task_result.wall_time_ms,
                          skill_id=task_result.skill_id,
                          status="done")

        emitter("task_done", {
            "task_id": task_id,
            "score": task_result.score,
            "score_detail": task_result.score_detail,
            "tool_calls": task_result.tool_calls,
            "wall_time_ms": task_result.wall_time_ms,
            "skill_id": task_result.skill_id,
            "input_tokens": telemetry.input_tokens,
            "output_tokens": telemetry.output_tokens,
            "total_tokens": telemetry.total_tokens,
        })

    except Exception as exc:
        task_result.status = "error"
        task_result.score = 0.0
        store.upsert_task(run_id, task_id, status="error", score=0.0)
        emitter("task_error", {"task_id": task_id, "error": str(exc)[:500]})


async def _run_benchmark_async(run_id: str, task_filter: list[str] | None = None) -> None:
    cfg = _get_cfg()
    agent = _get_agent()
    harness = HarnessServiceClientSync(cfg.benchmark_host)
    run = _runs[run_id]
    run.status = RunStatus.RUNNING
    run.started_at = time.time()
    concurrency = run.concurrency
    emitter = _make_emitter(run_id)

    try:
        res = await asyncio.to_thread(
            harness.get_benchmark, GetBenchmarkRequest(benchmark_id=cfg.benchmark_id)
        )
        emitter("benchmark_info", {
            "benchmark_id": res.benchmark_id,
            "total_tasks": len(res.tasks),
            "description": res.description[:300],
        })

        trial_ids = None
        if task_filter:
            tasks = [(t.task_id, None) for t in res.tasks if t.task_id in set(task_filter)]
        else:
            run_response = await asyncio.to_thread(
                harness.start_run,
                StartRunRequest(
                    benchmark_id=cfg.benchmark_id,
                    name=cfg.run_name,
                    api_key=cfg.bitgn_api_key,
                ),
            )
            run.leaderboard_run_id = run_response.run_id
            trial_ids = list(run_response.trial_ids)
            all_tasks = list(res.tasks)
            tasks = [(all_tasks[i].task_id, trial_ids[i]) for i in range(len(all_tasks))]

        for task_id, _ in tasks:
            run.tasks[task_id] = TaskResult(task_id=task_id)
            store.upsert_task(run_id, task_id)

        emitter("run_start", {
            "task_count": len(tasks),
            "concurrency": concurrency,
            "model": cfg.model,
        })

        # Sliding window: semaphore limits concurrency, all tasks launched at once.
        # As soon as one finishes, the next one starts immediately.
        semaphore = asyncio.Semaphore(concurrency)

        async def _guarded(tid: str, trid: str | None) -> None:
            async with semaphore:
                await _run_single(
                    cfg, agent, harness, run_id, tid, trid,
                    cfg.benchmark_id, run.tasks[tid],
                )

        await asyncio.gather(*[_guarded(tid, trid) for tid, trid in tasks])

        scored = [t for t in run.tasks.values() if t.score >= 0]
        run.final_score = sum(t.score for t in scored) / len(scored) * 100 if scored else 0
        run.finished_at = time.time()
        run.status = RunStatus.DONE

        if run.leaderboard_run_id:
            await asyncio.to_thread(
                harness.submit_run, SubmitRunRequest(run_id=run.leaderboard_run_id)
            )

        store.update_run(run_id, status="done", final_score=run.final_score, finished_at=run.finished_at)

        emitter("run_done", {
            "final_score": run.final_score,
            "passed": sum(1 for t in scored if t.score == 1.0),
            "total": len(scored),
            "wall_time_ms": int((run.finished_at - run.started_at) * 1000),
        })

    except Exception as exc:
        run.status = RunStatus.ERROR
        run.finished_at = time.time()
        store.update_run(run_id, status="error", finished_at=run.finished_at)
        emitter("run_error", {"error": str(exc)[:500]})


# ── Serialization ───────────────────────────────────────────


def _run_to_dict(run: BenchmarkRun) -> dict:
    scored = [t for t in run.tasks.values() if t.score >= 0]
    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "concurrency": run.concurrency,
        "final_score": run.final_score,
        "tasks": {
            tid: {
                "task_id": t.task_id,
                "instruction": t.instruction,
                "skill_id": t.skill_id,
                "skill_confidence": t.skill_confidence,
                "score": t.score,
                "score_detail": t.score_detail,
                "tool_calls": t.tool_calls,
                "wall_time_ms": t.wall_time_ms,
                "status": t.status,
                "harness_url": getattr(t, 'harness_url', ''),
                "trial_id": getattr(t, 'trial_id', ''),
            }
            for tid, t in run.tasks.items()
        },
        "passed": sum(1 for t in scored if t.score == 1.0),
        "total": len(run.tasks),
        "wall_time_ms": int((run.finished_at - run.started_at) * 1000) if run.finished_at and run.started_at else 0,
        "started_at": run.started_at,
        "temperature": getattr(run, 'temperature', 1.0),
        "model": getattr(run, 'model', ''),
    }


# ── FastAPI ─────────────────────────────────────────────────

app = FastAPI(title="PAC1 Agent Dashboard API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def _startup():
    # Load completed runs from SQLite into memory
    for rd in store.list_runs():
        run_id = rd["run_id"]
        if run_id in _runs:
            continue
        run = BenchmarkRun(run_id=run_id, concurrency=rd.get("concurrency", 5))
        run.status = RunStatus(rd.get("status", "done"))
        run.final_score = rd.get("final_score", 0)
        run.started_at = rd.get("started_at", 0)
        run.finished_at = rd.get("finished_at", 0) or time.time()
        run.temperature = rd.get("temperature", 1.0)
        run.model = rd.get("model", "")
        for tid, td in rd.get("tasks", {}).items():
            run.tasks[tid] = TaskResult(
                task_id=td["task_id"],
                instruction=td.get("instruction", ""),
                skill_id=td.get("skill_id", ""),
                score=td.get("score", -1),
                score_detail=td.get("score_detail", []),
                tool_calls=td.get("tool_calls", 0),
                wall_time_ms=td.get("wall_time_ms", 0),
                status=td.get("status", "done"),
                harness_url=td.get("harness_url", ""),
                trial_id=td.get("trial_id", ""),
            )
        _runs[run_id] = run


class RunRequest(BaseModel):
    task_filter: list[str] | None = None
    concurrency: int = 5


@app.get("/api/config")
async def get_config():
    cfg = _get_cfg()
    return {"model": cfg.model, "concurrency": cfg.concurrency, "max_turns": cfg.max_turns, "benchmark_id": cfg.benchmark_id, "temperature": _temperature, "openai_base_url": cfg.openai_base_url, "openai_api_key": cfg.openai_api_key}


@app.put("/api/config/temperature")
async def set_temperature(body: dict):
    global _temperature
    t = float(body.get("temperature", 1.0))
    if t < 0 or t > 2:
        return {"error": "temperature must be between 0 and 2"}
    _temperature = t
    return {"temperature": _temperature}


@app.get("/api/config/llm")
async def get_llm_config():
    cfg = _get_cfg()
    return {
        "model": cfg.model,
        "openai_base_url": cfg.openai_base_url,
        "openai_api_key": cfg.openai_api_key,
        "bitgn_api_key": cfg.bitgn_api_key or "",
    }


@app.put("/api/config/llm")
async def set_llm_config(body: dict):
    global _cfg, _agent
    old = _get_cfg()
    _cfg = Config(
        model=body.get("model", old.model),
        openai_api_key=body.get("openai_api_key", old.openai_api_key),
        openai_base_url=body.get("openai_base_url", old.openai_base_url),
        bitgn_api_key=body.get("bitgn_api_key", old.bitgn_api_key),
        benchmark_host=old.benchmark_host,
        benchmark_id=old.benchmark_id,
        run_name=old.run_name,
        max_turns=old.max_turns,
        concurrency=old.concurrency,
        request_timeout=old.request_timeout,
    )
    _agent = None  # force re-creation on next run
    return {
        "model": _cfg.model,
        "openai_base_url": _cfg.openai_base_url,
        "openai_api_key": _cfg.openai_api_key,
        "bitgn_api_key": _cfg.bitgn_api_key or "",
    }


@app.get("/api/skills")
async def list_skills():
    return {sid: {"id": s.id, "name": s.name, "description": s.description, "prompt": s.prompt} for sid, s in SKILL_REGISTRY.items()}


@app.get("/api/prompt")
async def get_prompt():
    """Return the full system prompt as markdown."""
    from agent_v2.prompts import get_system_prompt_with_skills
    return {"prompt": get_system_prompt_with_skills()}


@app.post("/api/runs")
async def start_run(req: RunRequest):
    run_id = str(uuid.uuid4())[:8]
    _runs[run_id] = BenchmarkRun(run_id=run_id, concurrency=req.concurrency, temperature=_temperature, model=_get_cfg().model)
    store.create_run(run_id, req.concurrency, model=_get_cfg().model, temperature=_temperature)
    asyncio.create_task(_run_benchmark_async(run_id, req.task_filter))
    return {"run_id": run_id}


@app.get("/api/runs")
async def list_runs():
    return [_run_to_dict(r) for r in _runs.values()]


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    run = _runs.get(run_id)
    if not run:
        return {"error": "not found"}
    return _run_to_dict(run)


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str):
    if run_id not in _runs:
        return {"error": "not found"}
    return StreamingResponse(
        _sse_generator(run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/events")
async def get_run_events(run_id: str, task_id: str | None = None):
    """Get all events for a run, optionally filtered by task_id."""
    return store.get_events(run_id, task_id)


@app.get("/api/runs/{run_id}/tasks/{task_id}/log")
async def get_task_log(run_id: str, task_id: str):
    """Get a plain-text log for a specific task — easy to copy-paste."""
    run = _runs.get(run_id)
    if not run:
        return {"error": "run not found"}
    task = run.tasks.get(task_id)
    if not task:
        return {"error": "task not found"}

    events = store.get_events(run_id, task_id)
    lines = [
        f"=== Task {task_id} ===",
        f"Instruction: {task.instruction}",
        f"Skill: {task.skill_id}",
        f"Score: {task.score}",
        f"Tools: {task.tool_calls}",
        f"Wall time: {task.wall_time_ms}ms",
        "",
    ]
    if task.score_detail:
        lines.append("Score detail:")
        for d in task.score_detail:
            lines.append(f"  {d}")
        lines.append("")

    lines.append("Event log:")
    for ev in events:
        t = ev.get("type", "")
        if t == "llm_start":
            lines.append(f"  [{t}] step {ev.get('step')}")
        elif t == "llm_end":
            lines.append(f"  [{t}] step {ev.get('step')} ({ev.get('elapsed_ms')}ms)")
            if ev.get("output_preview"):
                lines.append(f"    LLM: {ev['output_preview'][:500]}")
        elif t == "tool_start":
            lines.append(f"  [{t}] {ev.get('tool')}")
        elif t == "tool_end":
            lines.append(f"  [{t}] {ev.get('tool')} ({ev.get('result_lines', 0)} lines)")
            if ev.get("result"):
                for rl in ev["result"].split("\n")[:30]:
                    lines.append(f"    | {rl}")
        elif t == "task_classified":
            lines.append(f"  [classified] {ev.get('skill_id')} ({ev.get('skill_confidence', 0):.0%})")
        elif t == "agent_output":
            lines.append(f"  [output] {ev.get('output', '')[:500]}")
        elif t == "fallback_submit":
            lines.append(f"  [fallback] {ev.get('outcome')} — {ev.get('message', '')[:200]}")
        elif t == "task_done":
            lines.append(f"  [DONE] score={ev.get('score')} tools={ev.get('tool_calls')} time={ev.get('wall_time_ms')}ms")
        elif t == "task_error":
            lines.append(f"  [ERROR] {ev.get('error')}")

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse("\n".join(lines))


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str):
    run = _runs.get(run_id)
    if not run:
        return {"error": "not found"}
    if run.status != RunStatus.RUNNING:
        return {"error": "not running"}
    run.status = RunStatus.ERROR
    run.finished_at = time.time()
    store.update_run(run_id, status="error", finished_at=run.finished_at)
    _emit(run_id, "run_error", {"error": "Stopped by user"})
    return {"stopped": run_id}


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    _runs.pop(run_id, None)
    db = store.get_db()
    db.execute("DELETE FROM events WHERE run_id=?", (run_id,))
    db.execute("DELETE FROM tasks WHERE run_id=?", (run_id,))
    db.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
    db.commit()
    return {"deleted": run_id}


@app.get("/api/compare")
async def compare_runs(run_ids: str):
    """Compare multiple runs. Returns heatmap data.
    Usage: /api/compare?run_ids=abc,def,ghi
    """
    ids = [r.strip() for r in run_ids.split(",") if r.strip()]
    all_task_ids = set()
    run_data = {}

    for rid in ids:
        run = _runs.get(rid)
        if not run:
            continue
        run_data[rid] = {}
        for tid, task in run.tasks.items():
            all_task_ids.add(tid)
            run_data[rid][tid] = {
                "score": task.score,
                "tool_calls": task.tool_calls,
                "wall_time_ms": task.wall_time_ms,
                "skill_id": task.skill_id,
                "status": task.status,
            }

    sorted_tasks = sorted(all_task_ids, key=lambda x: (int(x[1:]) if x[1:].isdigit() else 999))

    # Build heatmap: rows = tasks, cols = runs
    heatmap = []
    for tid in sorted_tasks:
        row = {"task_id": tid, "runs": {}}
        for rid in ids:
            if rid in run_data and tid in run_data[rid]:
                row["runs"][rid] = run_data[rid][tid]
            else:
                row["runs"][rid] = {"score": -1, "tool_calls": 0, "wall_time_ms": 0, "skill_id": "", "status": "missing"}
        # Stability: same result across all runs?
        scores = [row["runs"][rid]["score"] for rid in ids if rid in row["runs"] and row["runs"][rid]["score"] >= 0]
        row["stable"] = len(set(scores)) <= 1 if scores else True
        row["always_pass"] = all(s == 1.0 for s in scores) if scores else False
        row["always_fail"] = all(s == 0.0 for s in scores) if scores else False
        heatmap.append(row)

    return {
        "run_ids": ids,
        "task_ids": sorted_tasks,
        "heatmap": heatmap,
        "run_scores": {rid: _runs[rid].final_score for rid in ids if rid in _runs},
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
