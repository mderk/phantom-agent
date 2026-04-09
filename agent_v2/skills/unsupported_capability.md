<SKILL_UNSUPPORTED_CAPABILITY>
This task requests a capability that does not exist in the workspace.

UNSUPPORTED CAPABILITIES:
- Calendar invites/scheduling → no calendar system in sandbox
- External uploads (to URLs, APIs) → no network access from sandbox
- Salesforce/HubSpot/Zendesk sync → no external CRM integration
- Email sending from knowledge_repo (no /outbox/) → workspace lacks email

WORKFLOW:
1. Orient yourself — list "/" and identify workspace type
2. Confirm the capability is indeed missing (no outbox, no calendar, etc.)
3. submit_answer with:
   - outcome: OUTCOME_NONE_UNSUPPORTED
   - message: explain which capability is missing and why
   - grounding_refs: ["/AGENTS.md"]

Do NOT try to work around it. Do NOT create fake files.
Simply report that the capability is not available.
</SKILL_UNSUPPORTED_CAPABILITY>
