<SKILL_CRM_LOOKUP>
This task asks you to find information in CRM records.

WORKFLOW:
1. Check WORKSPACE_INSTRUCTIONS above for the data model and directory structure
2. Search for the requested data using search_text and directory listings
3. Follow references between records (e.g. account → primary_contact → contact file)
4. submit_answer with the requested information

OWNERSHIP & RELATIONSHIPS (do not guess):
- Prefer stable links (IDs, explicit reference fields, exact emails) over name-only matches
- If the query mentions BOTH a PERSON and an ACCOUNT:
  - Read the person’s record (cont_* or mgr_*) AND the account record
  - Verify the person belongs to that account (e.g. account_id / referenced IDs). If mismatch → OUTCOME_NONE_CLARIFICATION
- For role-based lookups ("primary contact", "account manager/owner"):
  - Traverse account → referenced person → read the person record
  - Do NOT answer from the account file alone when the question is about a person attribute (email, name)
- If the query mentions an account manager/owner by name:
  - You MUST locate and READ their manager record in `/contacts/` (mgr_*.json), even if accounts already include the manager name
- If multiple candidates match a name:
  - Disambiguate by reading their linked accounts and matching concrete request attributes (country/industry/project keywords)
  - Clarify only if the workspace provides no stable way to pick

SEARCH STRATEGY:
- For exact names: search_text for the name across relevant directories
- For descriptions ("Dutch banking customer"): search by keywords (country, industry, etc.)
  If search_text doesn't find it, list and read ALL files in the directory
- Try BOTH "First Last" and "Last, First" orderings for name searches
- NEVER clarify until you have exhausted the search — check ALL files first

CHANNEL / POLICY LOOKUPS:
- If the request mentions a specific communication channel (e.g. Telegram/Discord) or channel policy concepts (blacklist/admin/handle),
  treat `/docs/channels/` as the source of truth.
- Read the relevant channel docs first, then count/lookup exactly as requested.
- Include those docs in grounding_refs.

COUNTING: For "how many" questions, use search_text with limit=2000 to get all matches.
Count the search results — don't read files and count mentally.

GROUNDING RULES — CRITICAL (missing ANY ref = FAIL):
- Include the EXACT path of EVERY file you read to derive the answer
- Follow the full chain: if you looked up an account, then its contact, include BOTH files
- When the query mentions a PERSON by name: search contacts/ for that person's own record
  file (mgr_*, cont_*) and READ it. Missing this file = FAIL even if you found the answer elsewhere.
  Account managers are in contacts/mgr_*.json — always search there when the query involves a manager.
- Docs are first-class evidence: if you relied on `/docs/` for your reasoning, include those doc paths too.
- Before completing, verify: "Did I include every file I read?"
</SKILL_CRM_LOOKUP>
