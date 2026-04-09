<SKILL_FOLLOWUP_RESCHEDULE>
This task asks you to reschedule a follow-up date.

WORKFLOW:
1. Identify the account (by name or description)
2. Search /accounts/ — read each account JSON to find the match
3. Read /docs/ for any follow-up audit context if mentioned in the task
4. Also check /docs/follow-up-audit.json if it exists
5. Read the account JSON — find the next_follow_up or follow_up_date field
6. Compute the new date:
   - "in two weeks" → get current date from get_context, add 14 days
   - "move to 2026-12-15" → use that exact date
7. Update the account JSON with new follow-up date (keep all other fields!)
8. List /reminders/ and find the reminder matching the account_id
9. Update the reminder JSON with the same new date
10. Verify BOTH files by reading them back
11. submit_answer with grounding_refs including BOTH file paths

CRITICAL: You must update BOTH the account AND the reminder. Missing one = fail.

ERROR HANDLING:
- If account not found → OUTCOME_NONE_CLARIFICATION
- If reminder not found → still update account, note missing reminder
- If follow_up_date field doesn't exist → check for next_follow_up, followup_date, etc.
- Read the FULL JSON before writing — preserve all existing fields, only change the date field
</SKILL_FOLLOWUP_RESCHEDULE>
