<SKILL_FOLLOWUP_RESCHEDULE>
This task asks you to reschedule a follow-up date.

WORKFLOW:
1. Check WORKSPACE_INSTRUCTIONS above — they define which records carry follow-up dates
   and whether multiple records need to stay in sync
2. Find the target account by searching the workspace
3. If the task uses a relative date ("in two weeks"), use the calculate tool
   with the sandbox date from WORKSPACE_CONTEXT above
   Example: calculate("datetime(2026,3,10) + timedelta(days=14)") → "2026-03-24"
4. Update ALL records that carry the follow-up date — workspace rules define which ones
   (e.g. both the account and its reminder). Missing one = fail
5. Preserve all existing fields — only change the date
6. Verify ALL modified files by reading them back
7. submit_answer with grounding_refs including ALL modified files

If account not found → OUTCOME_NONE_CLARIFICATION
</SKILL_FOLLOWUP_RESCHEDULE>
