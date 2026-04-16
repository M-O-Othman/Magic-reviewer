### USER PROMPT
Answer the Relationship Manager's question below using only the
customer data provided. Follow every rule in the system prompt.

USER_REQUEST:
<Relationship Manager question>

CUSTOMER_DATA_JSON:
<Complete customer data snapshot>

INSTRUCTIONS
1. Read CUSTOMER_DATA_JSON carefully. Field names are case-sensitive.
2. Answer using only facts present in the data. Never invent figures.
3. For computed values (sums, averages, counts), show the result clearly.
4. If no data matches the query, say so and list available values.
5. Apply the correct field for every concept:
   – "credit limit"    → credit_limit_amount_gbp (dim_account)
   – "BIB limit"       → bib_payment_limit_amount_gbp (dim_customer)
   – "CAGR"            → cagr_percentage (cite directly, do not recalculate)
6. Follow the response structure: Acknowledge → Action/Info → Next Steps → Check.
7. Keep answers concise. Use British English and active voice.
8. Add "Subject to credit risk approval" when discussing lending limits.
9. If the request is disallowed by safety policy, respond with:
   "I'm sorry, but I can't help with that."

END OF USER PROMPT
