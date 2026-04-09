<SKILL_CLARIFICATION>
This task is likely too short, ambiguous, truncated, or uses a deictic reference.

INDICATORS — if ANY of these are true, lean toward CLARIFICATION:
- Very short request (< 4 words) with no file path or identifier
- Uses "this", "that", "these", "those" without clear antecedent
- Truncated text — ends mid-word or mid-sentence (e.g. "Archive the thread and upd")
- Vague instruction without a stable, identifiable target
- Request that names something that doesn't exist in the workspace

WORKFLOW:
1. Still orient yourself — list "/" and read AGENTS.md (the task might become clear in context)
2. Check if the request is truncated: does it end mid-word or mid-sentence?
   → If yes, ALWAYS report OUTCOME_NONE_CLARIFICATION. Do not guess.
3. If after grounding the request is still ambiguous:
   - submit_answer with OUTCOME_NONE_CLARIFICATION
   - message: explain what information is missing
   - grounding_refs: ["/AGENTS.md"]
4. If the workspace context makes the task clear, execute it normally instead.

CRITICAL: A truncated request (ending mid-word like "upd") is ALWAYS a clarification.
Do NOT guess what the user meant to type. Do NOT attempt partial execution.
</SKILL_CLARIFICATION>
