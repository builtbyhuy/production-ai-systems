# P17 interview walkthrough

Lead with the current boundary: **100 tasks and 325 validated checks; zero untrusted scored runs.** Explain why this is a meaningful partial result and why claiming a 100% model score from trusted references would be false.

1. Open `build_corpus.py` and choose tasks from three different categories. Explain the observable contract, the regression and why each case matters. Discuss the limits of synthetic seeded bugs and subjective difficulty labels.
2. Follow `load_tasks` and `validate_trusted_references`. Explain the pinned byte hash, unique AST check, source split policy and why the host validator accepts only this reviewed corpus.
3. Open `validate_submission`. Show that syntax validation deliberately does not execute code and is not a security guarantee. Trace a valid malicious-looking module to a denied `SandboxRunner` call without a host fallback.
4. Explain `_candidate_harness`: only arguments enter the sandbox; expected results remain with the controller. Show strict structured comparison, exception ancestry, Boolean/numeric separation and timeout/output-limit failures.
5. Trace the no-op and mechanical repair baseline implementations. Explain their answer access, train-idiom rule selection and why neither represents an LLM benchmark.
6. Follow `build_leaderboard`. Recount raw case outcomes, inspect split coverage/digests and show rejection of corpus-QA records. Explain Wilson interval limitations, public-test contamination and self-reported generation costs.

Be able to modify these components yourself:

- Add a distinct task with an error case and show the reference passes while its seeded defect fails.
- Preserve an order-sensitive JSON argument through corpus generation and candidate input serialization.
- Break a submitted Python module and demonstrate validation before execution.
- Change a summary score without changing raw outcomes and demonstrate leaderboard rejection.
- Provision an audited P06 runtime, run both baselines on the same split twice and produce the first real leaderboard.

Be explicit about unfinished claims: secure scoring on this host, real model comparisons, broad software-engineering capability, hidden-test resistance, statistical representativeness and community adoption have not been verified.
