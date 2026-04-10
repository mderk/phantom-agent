<SKILL_CRM_LOOKUP>
This task asks you to find information in CRM records.

WORKFLOW:
1. Check WORKSPACE_INSTRUCTIONS above for the data model and directory structure
2. Search for the requested data using search_text and directory listings
3. Follow references between records (e.g. account → primary_contact → contact file)
4. submit_answer with the requested information

SEARCH STRATEGY:
- For exact names: search_text for the name across relevant directories
- For descriptions ("Dutch banking customer"): search by keywords (country, industry, etc.)
  If search_text doesn't find it, list and read ALL files in the directory
- Try BOTH "First Last" and "Last, First" orderings for name searches
- NEVER clarify until you have exhausted the search — check ALL files first

COUNTING: For "how many" questions, use search_text with limit=2000 to get all matches.
Count the search results — don't read files and count mentally.

GROUNDING RULES — CRITICAL (missing ANY ref = FAIL):
- Include the EXACT path of EVERY file you read to derive the answer
- Follow the full chain: if you looked up an account, then its contact, include BOTH files
- When the query mentions a PERSON by name: search contacts/ for that person's own record
  file (mgr_*, cont_*) and READ it. Missing this file = FAIL even if you found the answer elsewhere.
- Before completing, verify: "Did I include every file I read?"
</SKILL_CRM_LOOKUP>
