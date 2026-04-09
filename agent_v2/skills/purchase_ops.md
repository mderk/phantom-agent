<SKILL_PURCHASE_OPS>
This task asks you to fix a purchase processing issue (ID prefix regression).

WORKFLOW:
1. Read /docs/purchase-id-workflow.md and /processing/README.MD FIRST — these define the authoritative scope of the fix
2. List /processing/ to find all configs; read each to understand lane roles
3. Check a few historical purchase records to determine the correct established prefix
4. Apply ONLY the changes the workspace docs authorize — let the docs define the scope, not the task description's wording
5. Verify by reading the file back
6. submit_answer with grounding_refs including docs, processing, and purchase paths

Key concept: purchases flow through processing lanes. Each lane has an ID prefix
format. A "regression" means the prefix was changed incorrectly and needs to be reverted
or fixed to match the documented format.

IMPORTANT: The workspace docs (purchase-id-workflow.md, processing/README.MD) are the
authoritative source for what to change. If they say to fix only a specific lane, do exactly
that — even if the task description uses broad language like "do whatever cleanup is needed".
</SKILL_PURCHASE_OPS>
