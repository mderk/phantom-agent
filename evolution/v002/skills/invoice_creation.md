<SKILL_INVOICE_CREATION>
This task asks you to create an invoice.

WORKFLOW:
1. Check WORKSPACE_INSTRUCTIONS above for the invoices directory, then read its README for the exact schema and naming convention
2. Parse invoice details from the task (ID, line items, amounts)
3. Compute total from line items
4. Create the invoice file following the workspace schema
5. Verify by reading the file back
6. submit_answer with grounding_refs including the README and the created file
</SKILL_INVOICE_CREATION>
