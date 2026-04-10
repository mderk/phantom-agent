<SKILL_KNOWLEDGE_CLEANUP>
This task asks you to remove cards, threads, or distill artifacts.

WORKFLOW:
1. Check WORKSPACE_INSTRUCTIONS above for directory structure and preservation rules
2. Identify which directories and files the task refers to
3. List the target directories to get ALL filenames
4. Delete each file individually — preserve system files (AGENTS.md, templates, READMEs)
5. After deleting, list the directories again to VERIFY cleanup is complete
6. submit_answer with grounding_refs listing all deleted paths

CRITICAL: List ALL files first. Then delete EACH ONE. Then verify.
Do NOT skip any file. Templates (underscore-prefixed) and AGENTS.md are kept.
This is a VALID operation in knowledge_repo workspaces — do NOT clarify. Just delete and report.

submit_answer OUTCOME_OK with grounding_refs listing all deleted paths.
</SKILL_KNOWLEDGE_CLEANUP>
