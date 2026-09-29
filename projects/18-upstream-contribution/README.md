# P18 — Upstream SQLite checkpoint transaction fix

## Problem and scope

The current synchronous `SqliteSaver.cursor()` commits in `finally`. When the second
statement of `delete_thread()` raises, the first deletion can be committed even though
the public operation reports failure. A durable workflow can then retain pending writes
without their checkpoint.

The reproduction uses the MIT-licensed LangGraph checkpoint-sqlite source at commit
`07b33185eab893be2ed031eedae52f09314bf77c` and the installed checkpoint dependency family.
It creates a synthetic checkpoint and pending write through public saver methods, then
uses a local SQLite trigger to make the second deletion fail predictably. It does not
access any production database.

## Architecture and patch

[upstream.patch](upstream.patch) moves the successful commit into the `try` body, rolls
back transaction-owning cursors on an exception, re-raises the original exception, and
always closes the cursor. Nontransactional cursors continue to leave transaction control
to the caller. No dependencies, public signatures or serialization formats change.

The minimal upstream source snapshot in `vendor/` is hash-bound by
[vendor-manifest.json](vendor-manifest.json); its [license](UPSTREAM_LICENSE) is retained.
Verification copies the unchanged snapshot into separate temporary directories, applies
the patch only to one, and runs byte-identical regression tests against both.

## Setup, demo and verification

```bash
uv sync --frozen --group dev --extra vectors --extra router --extra workflows
uv run --no-sync pais demo 18 --profile local --output artifacts/p18-demo.json
```

Direct command:

```bash
uv run --no-sync python projects/18-upstream-contribution/verify_patch.py \
  --output artifacts/p18-upstream.json
```

The baseline is expected to return pytest exit 1: three regressions fail and the
caller-controlled transaction case passes. The patched run executes those four tests
plus the existing upstream synchronous saver test module: **13 tests passed** in the
observed run. The wrapper returns 0 only when that RED/GREEN contract is satisfied.
An unavailable prerequisite or a patch/source mismatch returns 2.

## Acceptance checklist

| Criterion | Status and evidence |
| --- | --- |
| Genuine current defect reproduced | PASS — original source commits a partial delete; baseline has three failures |
| Focused correction and regression tests | PASS — focused transaction change and four regression tests in the patch |
| Relevant upstream saver tests | PASS — patched four regressions plus existing module, 13 total |
| Commit/command/dataset/source provenance | PASS — `artifacts/p18-outputs/upstream-verification.json` and source/patch hashes |
| Full upstream `make format`, `make lint`, `make test` | NOT RUN — requires the complete upstream package checkout and its declared development environment |
| Maintainer-approved issue and assignment | NOT RUN — no approval or assignment requested |
| PR submitted / maintainer response / merge | NOT RUN / none / no |

The first integration run exposed a missing explicitly loaded pytest-asyncio plugin in
the isolated verification command. That failed report remains in `artifacts/p18-first`;
the runner now loads the required plugin and uses the upstream automatic async mode.

## Case study

Transaction cleanup was the failure boundary: application-level approval idempotency
does not repair a partially committed storage operation. The patch keeps rollback in the
component that owns the transaction, so callers see either the completed operation or
the prior database state after failure. It also closes the cursor if commit itself
raises. Catching `BaseException` here is deliberately limited to rollback and re-raising;
it does not convert interrupts into successful operations.

Changing `delete_thread()` alone would leave the same cursor behavior in other write
operations. Retrying blindly could erase evidence of a partial commit. The selected
change covers the shared synchronous transaction boundary while preserving
`transaction=False` ownership. The asynchronous saver and unrelated store implementation
remain outside this patch's verified scope.

## Interview walkthrough

Read `SqliteSaver.cursor`, then follow the two statements in `delete_thread`. Predict
what remains after the trigger rejects the second statement. Run the unchanged baseline,
apply the patch, and inspect all four regression cases. Explain why cursor cleanup and
transaction cleanup are separate responsibilities, why commit can also raise, and why
the nontransactional case must preserve caller control. You should be able to add a
failure-at-commit test and adapt the change to an asynchronous context manager without
claiming that the synchronous result proves it.

## Upstream rules and next action

The inspected [PR template](https://github.com/langchain-ai/langgraph/blob/main/.github/PULL_REQUEST_TEMPLATE.md)
requires a maintainer-approved issue/discussion and assignment before an external PR.
It also requires the package's format, lint and test commands. The
[title rules](https://github.com/langchain-ai/langgraph/blob/main/.github/workflows/pr_lint.yml)
allow `fix(checkpoint-sqlite): ...`.

Related [issue #8590](https://github.com/langchain-ai/langgraph/issues/8590) and
[PR #8592](https://github.com/langchain-ai/langgraph/pull/8592) concern the SQLite store;
this reproduction targets the checkpoint saver. Recheck current upstream status before
proposing an issue because another contributor may address it in the meantime.

The next external action is to obtain approval and assignment for this exact scope.
Then apply the prepared patch in a complete upstream checkout, run the required package
gates and use the [short proposed PR description](PROPOSED_PR.md). No message, issue or
PR has been submitted by this project.
