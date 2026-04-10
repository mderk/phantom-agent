<SKILL_KNOWLEDGE_LOOKUP>
This task asks about captured articles or knowledge repo content.

WORKFLOW:
1. Call get_context to determine current sandbox date
2. list_directory /01_capture/ to find capture buckets
3. list_directory /01_capture/influential/ (or other bucket) to see all files
4. Files are named with dates: YYYY-MM-DD__slug.md
5. Compute the target date from the task:
   - "12 days ago" → current_date - 12 days
   - "the day after tomorrow" → current_date + 2 days
6. Look for a filename matching the computed date
7. If found → submit_answer OUTCOME_OK with the filename
   - grounding_refs MUST include the FULL path: /01_capture/influential/YYYY-MM-DD__slug.md
   - message should reference the filename
8. If NOT found → submit_answer OUTCOME_NONE_CLARIFICATION (NOT OUTCOME_OK!)
   - CRITICAL: "no article found" = CLARIFICATION, never OK
   - Explain that no file matches the date
   - List what dates ARE available

DATE COMPUTATION: Use calculate tool — do NOT compute dates mentally.
Example: calculate("datetime(2026,3,10) - timedelta(days=45)") → "2026-01-24"
</SKILL_KNOWLEDGE_LOOKUP>
