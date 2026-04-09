<SKILL_EMAIL_OUTBOUND>
This task asks you to send an email.

WORKFLOW:
1. Resolve the recipient:
   - If direct email given (e.g. "alex@example.com") → use it directly
   - If name given (e.g. "Alex Meyer") → search /contacts/ JSON files for full_name match
   - If account given (e.g. "Aperture AI Labs") → search /accounts/ for the account,
     find primary_contact or contact_id, then look up their email in /contacts/
   - If descriptive (e.g. "Dutch banking customer") → iterate /accounts/, match by
     country, industry, description fields

2. Check workspace has /outbox/ — if not, OUTCOME_NONE_UNSUPPORTED

3. Read /outbox/seq.json to get the current sequence number

4. Create email JSON in /outbox/{next_seq}.json:
   {
     "id": <next_seq>,
     "to": "<resolved_email>",
     "subject": "<from task>",
     "body": "<from task>"
   }

5. Update /outbox/seq.json to {"id": next_seq + 1}

6. Verify by reading the created file back — must be valid JSON

CRITICAL: Read /outbox/README.MD first for exact format. Write EXACTLY ONCE. Filename = seq.json id value.
Email format: {"subject": "...", "to": "email", "body": "...", "sent": false}
Add "attachments": ["path"] if needed.

7. submit_answer with:
   - grounding_refs: ["/outbox/{id}.json", "/outbox/seq.json", contact_or_account_path]

CONTACT RESOLUTION STRATEGY:
- By name → search_text in /contacts/ for full_name match
- By account name → search_text in /accounts/ for name match, then find primary_contact
- By description (e.g. "Dutch banking customer", "Austrian energy") → read ALL /accounts/*.json files, match by country, industry, segment, description fields. Do NOT give up after one search — iterate all account files if needed.
- NEVER clarify if you haven't read all account files yet. Exhaust the search first.

If contact/account truly cannot be resolved after checking ALL files → OUTCOME_NONE_CLARIFICATION
</SKILL_EMAIL_OUTBOUND>
