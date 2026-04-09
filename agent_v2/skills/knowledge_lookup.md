<SKILL_KNOWLEDGE_LOOKUP>
This task asks about captured articles or knowledge repo content.

WORKFLOW:
1. Call get_workspace_context to determine current sandbox date
2. list_directory /01_capture/ to find capture buckets
3. list_directory /01_capture/influential/ (or other bucket) to see all files
4. Files are named with dates: YYYY-MM-DD__slug.md
5. Compute the target date from the task:
   - "12 days ago" → current_date - 12 days
   - "the day after tomorrow" → current_date + 2 days
6. Look for a filename matching the computed date EXACTLY
7. If found → submit_answer OUTCOME_OK with the filename
   - grounding_refs MUST include the FULL path: /01_capture/influential/YYYY-MM-DD__slug.md
   - message should reference the filename
8. If NOT found → submit_answer OUTCOME_NONE_CLARIFICATION
   - EXACT date match required — do NOT return a "closest" or "nearest" article
   - Even one day off is still not the requested article
   - Explain that no file matches the computed date, list what dates ARE available

DATE COMPUTATION:
- Be precise. 2026-03-29 minus 12 days = 2026-03-17
- Double-check your arithmetic

CRITICAL: grounding_refs must contain the EXACT full file path, not descriptions.
</SKILL_KNOWLEDGE_LOOKUP>
