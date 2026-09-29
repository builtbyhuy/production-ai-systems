# fix(checkpoint-sqlite): roll back failed saver transactions

`SqliteSaver.cursor()` currently commits when its body raises, which can leave
`delete_thread()` partially applied. Commit only after successful execution, roll back
failed transaction-owning cursors, and always close the cursor; four regressions cover
statement failure, interruption, commit failure and caller-owned transactions.

Verification prepared: the unpatched regression run has three failures and one pass;
the patched regressions plus existing synchronous saver tests pass all 13 tests.

Before submission: obtain an approved assigned issue, add its real `Fixes #…` reference,
and run the complete package's required `make format`, `make lint`, and `make test` gates.
Those full gates and publication are not yet verified.
