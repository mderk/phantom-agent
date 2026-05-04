<SKILL_EMAIL_OUTBOUND>
This task asks you to send an email.

WORKFLOW:
1. Check WORKSPACE_INSTRUCTIONS above for outbox location — if none exists, OUTCOME_NONE_UNSUPPORTED
2. Read the outbox README for the exact email format and sequencing
3. Resolve the recipient:
   - Direct email given → use it
   - Name or account given → search contacts/accounts to find the email
   - Descriptive reference ("Dutch banking customer") → search by keywords across all files
   - NEVER clarify until you have exhausted the search — check ALL files first
   - RECIPIENT OWNERSHIP:
     - If the task specifies an account, only use contacts that belong to that account (account_id / explicit references)
     - If the task specifies BOTH a person and an account, require both to match; mismatch/uncertainty → OUTCOME_NONE_CLARIFICATION
     - When multiple contacts exist for an account, prefer the account’s primary_contact (or equivalent) over name guessing
   - Before writing to outbox, READ the final selected contact/account records you used to decide the recipient (for correctness + grounding)
4. Create the email file following the workspace format
5. Update the sequence file if the workspace uses one
6. Verify by reading the created file back
7. submit_answer with grounding_refs including the email file, sequence file, and all contact/account files you read

If contact/account truly cannot be resolved after checking ALL files → OUTCOME_NONE_CLARIFICATION
</SKILL_EMAIL_OUTBOUND>
