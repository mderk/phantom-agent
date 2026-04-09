<SKILL_CRM_LOOKUP>
This task asks you to find information in CRM records.

LOOKUP TYPES:
1. Contact email: search /contacts/*.json for full_name, return email field
2. Account info: search /accounts/*.json by name/description, return requested field
3. Account manager: find account → manager or account_manager field → look up in /contacts/
4. Primary contact email: find account → primary_contact → look up in /contacts/
5. Accounts by manager: iterate ALL /accounts/*.json, filter by manager field
6. Channel status: read /docs/channels/{channel}.md or .txt, count/extract info
7. Legal name: find account → return legal_name field

SEARCH STRATEGY:
- For exact names: search_text in /accounts/ or /contacts/ for name match
- For descriptions ("Dutch banking customer", "Austrian energy", "grid-modernization"):
  * search_text for keywords from the description (e.g. "banking", "energy", "grid")
  * If no results, list ALL /accounts/*.json and read each one to match by country, industry, segment, description
  * NEVER clarify until you have checked ALL account files
- Name matching is case-insensitive, try BOTH "First Last" and "Last First" orderings
- For "accounts managed by X": search /accounts/ for BOTH name orderings (e.g. "Engel Greta" AND "Greta Engel"), then read EVERY matching account file to verify and extract the account name
- CRITICAL: ALSO search /contacts/mgr_*.json for the manager name — you MUST include the manager's contact file in grounding_refs or the answer FAILS
- Always: find_files_by_name("mgr_*", "/contacts/") and read matching files
- NEVER guess — always verify by reading the actual file

COUNTING RULES (for "how many" questions):
- Use the search_text tool with the target pattern to find all matches
- ALWAYS set limit=2000 to get all results (files can have 1000+ lines)
- Count the number of SEARCH RESULTS returned — this is your count
- Do NOT try to count by reading the whole file and counting mentally
- Do NOT read the file with read_file and count lines — use search_text with limit=2000
- Example: search_text(pattern="blacklist", root="/docs/channels/Telegram.txt", limit=2000)
  → count the returned matches = your answer
- Double-check: the search_text tool tells you how many lines matched
- If results are truncated, increase limit or search_text more specifically

FORMAT RULES:
- "Return only the email" → message = ONLY the email address, nothing else
- "Answer only with the number" → message = ONLY the digit(s)
- "Return account names sorted alphabetically" → one name per line, sorted, nothing else

GROUNDING RULES — CRITICAL (missing ANY ref = FAIL):
grounding_refs MUST include the EXACT path of EVERY file you read to derive the answer:
- Account lookup → include "/accounts/acct_XXX.json"
- Contact lookup → include "/contacts/c_XXX.json" or "/contacts/cont_XXX.json"
- Manager lookup → include "/contacts/mgr_XXX.json" (manager contacts have "mgr_" prefix)
- Channel file → include "/docs/channels/Telegram.txt"
- For "managed by X" queries: include EVERY account file you checked AND the manager's contact file
- Ask yourself before completing: "Did I include the path of every file I read?" If not, add them.
</SKILL_CRM_LOOKUP>
