from __future__ import annotations

from openai import AsyncOpenAI
from agents import (
    Agent,
    ModelSettings,
    RunConfig,
    Runner,
    set_tracing_disabled,
)
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

from .config import Config
from .context import TaskContext, Telemetry
from .prompts import get_system_prompt_with_skills, build_task_prompt
from .tools import ALL_TOOLS


# Monkey-patch: clean Harmony format garbage from tool names
# gpt-oss-120b generates corrupted names like "read_file<|channel|>commentary" or "list_directory,json"
import re as _re
import agents.run_internal.tool_execution as _tool_exec

# Known valid tool names for fast lookup
_VALID_TOOLS = {
    'get_workspace_context', 'list_directory_tree', 'list_directory', 'read_file',
    'find_files_by_name', 'search_text', 'write_file', 'delete_file',
    'create_directory', 'move_file', 'list_skills', 'get_skill_instructions', 'submit_answer',
}

def _clean_tool_name(name: str) -> str:
    """Extract valid tool name from corrupted Harmony output."""
    if name in _VALID_TOOLS:
        return name
    # Try removing everything after known corruption patterns
    clean = _re.sub(r'[<,;|].*', '', name).strip()
    if clean in _VALID_TOOLS:
        return clean
    # Try matching prefix against known tools
    for valid in _VALID_TOOLS:
        if name.startswith(valid):
            return valid
    return name

# Patch BOTH tool call types to clean names at parse time
from openai.types.chat.chat_completion_message_tool_call import Function as _OAIFunction
from openai.types.responses import ResponseFunctionToolCall as _RespFTC

def _make_patched_init(orig_init):
    def _patched_init(self, **data):
        if 'name' in data and data['name']:
            clean = _clean_tool_name(data['name'])
            if clean != data['name']:
                print(f"  [HARMONY-FIX] '{data['name']}' → '{clean}'")
                data['name'] = clean
        orig_init(self, **data)
    return _patched_init

_OAIFunction.__init__ = _make_patched_init(_OAIFunction.__init__)
_RespFTC.__init__ = _make_patched_init(_RespFTC.__init__)


_client: AsyncOpenAI | None = None
_client_key: tuple[str, str] | None = None


def _get_client(cfg: Config) -> AsyncOpenAI:
    global _client, _client_key
    key = (cfg.openai_api_key, cfg.openai_base_url)
    if _client is None or _client_key != key:
        set_tracing_disabled(True)
        _client = AsyncOpenAI(
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url or None,
            timeout=cfg.request_timeout,
        )
        _client_key = key
    return _client


def create_agent(cfg: Config, temperature: float = 1.0) -> Agent[TaskContext]:
    client = _get_client(cfg)
    model = OpenAIChatCompletionsModel(
        model=cfg.model,
        openai_client=client,
    )
    return Agent[TaskContext](
        name="PAC1-Agent",
        instructions=get_system_prompt_with_skills(),
        model=model,
        tools=ALL_TOOLS,
        model_settings=ModelSettings(
            temperature=temperature,
            max_tokens=4096,
        ),
    )


FORCE_TOOL_PROMPT = """The task was: {task_text}

The agent produced this output:
<AGENT_OUTPUT>
{output}
</AGENT_OUTPUT>

Call submit_answer now based on the output above.
- If output contains a completed answer → OUTCOME_OK
- If output is empty, shows an error, or the agent crashed before completing → OUTCOME_NONE_CLARIFICATION
- If the task involves sending email but contact was not found → OUTCOME_NONE_CLARIFICATION
- If the output mentions injection/hostile content → OUTCOME_DENIED_SECURITY
- If the workspace lacks required capabilities (no outbox, no contacts) → OUTCOME_NONE_CLARIFICATION"""


async def run_task(
    cfg: Config,
    agent: Agent[TaskContext],
    runtime_url: str,
    task_text: str,
    task_id: str = "",
    on_event=None,
) -> Telemetry:
    """Run a single benchmark task. Returns telemetry.

    Args:
        on_event: Optional callback (event_type, data_dict) for SSE streaming.
    """
    from .hooks import LiveHooks

    telemetry = Telemetry()
    context = TaskContext(
        runtime_url=runtime_url,
        task_text=task_text,
        telemetry=telemetry,
    )
    hooks = LiveHooks(task_id=task_id, on_event=on_event)

    # Classify task — LLM first, regex fallback
    from .skills import classify_task
    from .skills.llm_classifier import classify_with_llm

    # Try LLM classification
    client = _get_client(cfg)
    try:
        match = await classify_with_llm(client, cfg.model, task_text)
        classifier_type = "llm"
    except Exception:
        match = classify_task(task_text)
        classifier_type = "regex"

    # Fallback to regex if LLM returned nothing or low-value "clarification"
    # LLM often misclassifies terse/ALL-CAPS requests as clarification
    if not match.skill_id or match.skill_id == "clarification":
        regex_match = classify_task(task_text)
        if regex_match.skill_id and regex_match.skill_id != "clarification":
            match = regex_match
            classifier_type = "regex"
        elif not match.skill_id:
            match = regex_match
            classifier_type = "regex"

    recommended_skill = match.skill_id
    if match.skill_id:
        print(f"  {task_id} skill: {match.skill_id} ({match.confidence:.0%}) [{classifier_type}]")
    if on_event:
        on_event("task_classified", {
            "task_id": task_id,
            "skill_id": match.skill_id,
            "skill_confidence": match.confidence,
            "classifier": classifier_type,
        })

    try:
        # Retry on ModelBehaviorError (Harmony corruption) or 0 tool calls
        from agents.exceptions import ModelBehaviorError
        max_retries = 3
        result = None
        for attempt in range(max_retries):
            try:
                result = await Runner.run(
                    agent,
                    input=build_task_prompt(task_text, recommended_skill),
                    context=context,
                    max_turns=cfg.max_turns,
                    hooks=hooks,
                    run_config=RunConfig(
                        model_settings=ModelSettings(
                            temperature=agent.model_settings.temperature if agent.model_settings else 1.0,
                            max_tokens=4096,
                        ),
                    ),
                )
                if context.completion_submitted or telemetry.tool_calls >= 5:
                    break
            except ModelBehaviorError as mbe:
                print(f"  {task_id} [RETRY {attempt+1}/{max_retries}] ModelBehaviorError: {mbe}")
                if on_event:
                    on_event("fallback_submit", {
                        "task_id": task_id,
                        "message": f"Retry {attempt+1}: {str(mbe)[:100]}",
                        "outcome": "RETRY",
                    })
                hooks.step = 0
                if attempt == max_retries - 1:
                    raise
                continue
            if attempt < max_retries - 1:
                print(f"  {task_id} [RETRY {attempt+1}/{max_retries}] 0 tool calls, retrying...")
                if on_event:
                    on_event("fallback_submit", {
                        "task_id": task_id,
                        "message": f"Retry {attempt+1}/{max_retries}: model returned text without tool calls",
                        "outcome": "RETRY",
                    })
                hooks.step = 0
        output = str(result.final_output) if result else ""

        print(f"  {task_id} output: {output[:200]}")
        if on_event:
            on_event("agent_output", {
                "task_id": task_id,
                "output": output[:1000],
                "completion_submitted": context.completion_submitted,
            })

        # If agent finished without calling submit_answer, re-run with ONLY submit_answer tool
        if not context.completion_submitted:
            print(f"  {task_id} [FORCE_TOOL] re-running with only submit_answer")
            if on_event:
                on_event("fallback_submit", {
                    "task_id": task_id,
                    "message": "Re-running agent to force tool call",
                    "outcome": "FORCE_TOOL",
                })
            from .tools import submit_answer
            force_agent = Agent[TaskContext](
                name="ForceSubmit",
                instructions="You must call submit_answer with the provided answer. Nothing else.",
                model=agent.model,
                tools=[submit_answer],
                model_settings=ModelSettings(temperature=0.0, max_tokens=4096, tool_choice="required"),
            )
            await Runner.run(
                force_agent,
                input=FORCE_TOOL_PROMPT.format(task_text=task_text[:500], output=output[:2000]),
                context=context,
                max_turns=1,
                hooks=hooks,
            )
            if not context.completion_submitted:
                print(f"  {task_id} [FORCE_TOOL] still no tool call, giving up")

    except Exception as exc:
        print(f"  {task_id} Agent error: {exc}")
        if on_event:
            on_event("fallback_submit", {
                "task_id": task_id,
                "message": f"Agent error: {str(exc)[:200]}",
                "outcome": "ERROR_RECOVERY",
            })
        # Try force-tool even on error
        if not context.completion_submitted:
            try:
                from .tools import submit_answer
                force_agent = Agent[TaskContext](
                    name="ForceSubmit",
                    instructions="Call submit_answer based on the task. Use OUTCOME_OK for normal tasks.",
                    model=agent.model,
                    tools=[submit_answer],
                    model_settings=ModelSettings(temperature=0.0, max_tokens=4096, tool_choice="required"),
                )
                await Runner.run(
                    force_agent,
                    input=FORCE_TOOL_PROMPT.format(task_text=task_text[:500], output=f"Error: {str(exc)[:200]}"),
                    context=context,
                    max_turns=1,
                )
            except Exception as exc2:
                print(f"  {task_id} Force-tool also failed: {exc2}")
    finally:
        telemetry.finish()

    return telemetry
