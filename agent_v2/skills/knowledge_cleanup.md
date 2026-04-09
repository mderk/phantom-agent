<SKILL_KNOWLEDGE_CLEANUP>
This task asks you to remove cards, threads, or distill artifacts.

WORKFLOW:
1. Identify what to delete:
   - "Remove all captured cards and threads" → delete everything in /02_distill/cards/ and /02_distill/threads/
   - "Discard thread X" → delete specific thread file

2. For bulk delete:
   a. list_directory /02_distill/cards/ — get ALL filenames
   b. list_directory /02_distill/threads/ — get ALL filenames
   c. Delete each file INDIVIDUALLY (skip files starting with "_" and "AGENTS.md")
   d. After all deletes, list both directories again to VERIFY they are clean

3. For single delete:
   a. Delete the specific file
   b. Verify it's gone

CRITICAL: List ALL files first. Then delete EACH ONE. Then verify.
Do NOT skip any file. Templates (underscore-prefixed) and AGENTS.md are kept.

submit_answer with grounding_refs listing all deleted paths.
</SKILL_KNOWLEDGE_CLEANUP>
