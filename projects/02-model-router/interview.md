# Interview walkthrough

1. Open `ModelRouter.complete`. Follow a request from policy selection to each attempt. Explain
   why the attempt count and model alias belong in traces while request IDs do not become metric labels.
2. Open `BudgetLedger.reserve`. Identify the transaction boundary and the two constraints:
   cumulative tenant commitment and cumulative parent-request commitment. Change the configured
   cap and rerun the concurrent reservation test; three admissions should become the corresponding
   whole number of calls, without races.
3. Walk through `unknown`, `settle`, and `reconcile`. Explain the distinction between reported
   tokens priced locally and an invoice-reconciled charge. Demonstrate the append-only triggers.
4. Modify the routing policy to add a new capability. Add it to a model configuration and show
   that ineligible fallbacks remain excluded. Do not give the model permission to edit the policy.
5. Cancel an in-flight task. Explain why cooperative cancellation is observable but a provider's
   final bill may remain unknown. Show the retained hold after restarting the ledger.
6. Inspect `LiteLLMProvider`: both `max_retries=0` and `num_retries=0` are deliberate. Explain why
   replacing this with an SDK default can break accounting even if application tests still pass.

Be able to defend the limitations: conservative byte-based input bounds are not universal
tokenizers; circuit state is local shared SQLite state; response caching requires up-to-date
source context; the public synthetic comparison is too small for broad model-quality claims.

Use the actual local result when defending the routing decision: cheap 4/12, expensive 6/12,
routed 4/12, with means of 0.801, 2.084 and 1.054 seconds. Explain why lower routing overhead
alone does not establish better quality or economics, and how you would develop a new policy
without tuning against the same held-out scoring cases.
