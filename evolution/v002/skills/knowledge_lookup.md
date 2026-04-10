<SKILL_KNOWLEDGE_LOOKUP>
This task asks about captured articles or knowledge repo content.

WORKFLOW:
1. Use the sandbox date from WORKSPACE_CONTEXT above — do NOT assume today's real date
2. Explore the workspace to find where captured content lives (check directories, READMEs)
3. List the files and identify ones with dates in their names
4. If the task uses a relative date ("45 days ago", "last week"), compute the target date
   from the SANDBOX date, not from your own clock
5. Match the computed date against available files
6. If found → submit_answer OUTCOME_OK with full file path in grounding_refs
7. If NOT found → submit_answer OUTCOME_NONE_CLARIFICATION
   - EXACT date match required — do NOT return a "closest" or "nearest" article
   - List what dates ARE available

DATE COMPUTATION: Use calculate tool — do NOT compute dates mentally.
Example: calculate("datetime(2026,3,10) - timedelta(days=45)") → "2026-01-24"
</SKILL_KNOWLEDGE_LOOKUP>
