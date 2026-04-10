<SKILL_UNSUPPORTED_CAPABILITY>
The task MAY request a capability not present in the workspace — but verify first.

WORKFLOW:
1. Check WORKSPACE_INSTRUCTIONS above, then explore directories for relevant data
2. Search for data or features related to the request — the workspace may have what you need
3. If the workspace HAS the data or capability → fulfill the task normally (OUTCOME_OK)
4. If the workspace genuinely lacks the capability → submit_answer with:
   - outcome: OUTCOME_NONE_UNSUPPORTED
   - message: explain which capability is missing and why
   - grounding_refs: files you read to confirm the capability is missing

IMPORTANT: Do NOT assume something is unsupported without exploring.
The workspace may contain data about external systems (Telegram, Discord, etc.)
even if it can't connect to them directly. Look before declaring unsupported.

General examples of truly unsupported capabilities:
- Calendar invites/scheduling (if no calendar system exists)
- Live API calls to external services (sandbox has no network)
- Sending real emails (if no /outbox/ exists)
</SKILL_UNSUPPORTED_CAPABILITY>
