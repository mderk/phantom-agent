<SKILL_INVOICE_CREATION>
This task asks you to create an invoice.

WORKFLOW:
1. Read /my-invoices/README.MD to understand the schema
2. Parse from task: invoice ID, line items (description + amount)
3. Compute total from line items
4. Create JSON file at /my-invoices/{invoice_id}.json following the schema
5. Verify by reading the file back
6. submit_answer with grounding_refs: ["/my-invoices/README.MD", "/my-invoices/{id}.json"]

TYPICAL SCHEMA (verify from README.MD):
{
  "id": "SR-13",
  "line_items": [
    {"description": "OpenAI Subscription", "amount": 20},
    {"description": "Claude Subscription", "amount": 20}
  ],
  "total": 40
}
</SKILL_INVOICE_CREATION>
