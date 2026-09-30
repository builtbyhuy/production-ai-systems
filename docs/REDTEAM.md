# Independent redteam and portfolio scope

Reviewed 30 September 2026, after restoring the original source bundle and evidence archive.

**Verdict:** suitable to present as a local AI systems engineering lab after the fixes
below. The strongest example is the integrated PDF copilot, including failure handling,
source inspection and durable local approvals. It does not establish 18 production
systems, senior engineering experience, paid-client impact or broadly reliable model quality.

The review examined implementation, retained execution evidence, clean-checkout setup,
security boundaries and public presentation. It is a bounded source and reproduction review,
not a comprehensive penetration test or a production certification.

## Findings addressed

| Finding | Before | Correction and regression scope |
|---|---|---|
| Release evidence was too trusting | A self-labelled complete report with only 100 cases, an unregistered ID, altered source hash or zero source-support metric could be accepted. | Bind to the tested Git objects, frozen suite IDs/categories/questions, dataset hashes, thresholds, actual generation path and captured metric consistency. Malformed and tampered reports fail closed. |
| Memory and standalone vector reads missed role checks | A principal with no roles could read its tenant's memory or Qdrant search results through the library API. | Require trusted identity and a canonical reader/writer/admin role for memory and vector read entrypoints; reject empty and unrelated roles. Cross-tenant filtering remains enforced. |
| Non-admin PDF writers were rejected | API upload accepted the writer role but the retrieval layer required an editor role that was absent from the canonical identity contract. | Use writer consistently in retrieval, container credentials and API tests. A non-admin writer can upload, inspect and delete its own tenant's PDF; a reader cannot mutate it. |
| Cached validation blocked the event loop | Replaying a saved chat answer ran required synchronous validators directly inside async request handling. | Validate cached replies in tracked worker tasks. Cancellation preserves the admission lease until validation finishes; validation failure does not deliver the answer. |
| CI omitted the full evaluator path | CI installed no isolated evaluator and ran only its small contract tests. | Install the locked evaluator, require all positive fixture cases and require the degraded fixture to exit exactly 1. Exit 2 does not count as a quality rejection. The supply-chain scan remains blocking. |
| Public evidence links would break | The handoff archive contained reports that a normal Git clone did not include. | Include an explicit reviewed allowlist of historical reports, screenshots and small transitive metric/log dependencies at their original paths. New browser runs use separate destinations so historical evidence is not overwritten. Keep runtime binaries, models and large unlinked logs excluded. |

## Reproduced baseline

Before the review changes, the restored application passed **262 Python tests**. The
locked fixture evaluation passed **144/144** through the actual isolated DeepEval and
RAGAS worker; the deliberately degraded fixture produced **96 pass / 48 fail**, exit 1.
SQLite and LanceDB fixture lifecycle demos each passed **13/13**. TypeScript checking,
the Next.js production build, Ruff and the repository's declared Mypy scope also passed.

The initial browser attempt failed before all 14 cases because a partial test-browser
extraction crashed. A fresh extraction of the pinned package passed **14/14**, with
zero skips or flaky cases. This was a fixture UI run on a dirty review tree; it is not
actual-model quality evidence. Final committed-revision results are recorded below.

Focused repair checks passed **87 security/API tests** and **25 release/evaluation tests**.
The standalone Qdrant authorization follow-up passed **59 vector tests**.
The historical genuine local-model report still binds to its exact original commit,
`c7b8a793f34795f3d2de148c1c5c211845e8b222`; it cannot authorize a newer commit.

## Final publication-revision checks

All checks below ran on clean commit
`c74195a7f4f49d6ddf0e40b5262fa5d4062aac27`. A subsequent documentation/evidence-only
commit records these results; it is not a new actual-model release candidate.

| Check | Result | Evidence |
|---|---|---|
| Complete Python suite, including native Redis/Celery recovery | 335 passed; two upstream deprecation warnings | [Report](../artifacts/redteam-final/core-tests.json), [transcript](../artifacts/redteam-final/core-tests.log) |
| Complete positive fixture evaluation with real isolated metric worker | 144 passed; 0 errors/skips; deployment eligibility false | [Report](../artifacts/redteam-final/release-fixture.json) |
| Complete deliberately degraded fixture | 96 pass / 48 fail; 0 errors/skips; exit 1 | [Report](../artifacts/redteam-final/degraded-fixture.json) |
| Desktop/mobile browser fixture | 14 passed; 0 skipped/flaky; historical snapshots preserved | [Browser report](../artifacts/redteam-final/ui/browser-evidence.json) |
| TypeScript and production Next.js build | Passed | [Report](../artifacts/redteam-final/ui-build.json) |
| Ruff and declared Mypy scope | Passed | [Lint](../artifacts/redteam-final/lint.json), [types](../artifacts/redteam-final/types.json) |

The historical evidence allowlist's 139 files retain matching SHA-256 hashes. All 305 local
Markdown links checked before adding this final evidence section resolved. The current
verification is a portfolio publication gate for a scoped local application, not a
production deployment approval.

## Evidence integrity and limits

The retained final baseline reports and source-file hashes match the original tested Git
objects. The release suite's disclosed counts are consistent: 56 Qwen responses, 16
deterministic summaries and 72 contract/abstention cases. No answer-key prompt leakage was
found in the reviewed runner. This does not establish unseen generalization.

The eight audit cases reuse the development inspection template and numeric values with
renamed subjects. They are a source-separated smoke check with little distribution shift.
Audit executions are logged; direct source reads are not automatically logged. This review
inspected the audit source, so it should not be described as a blind holdout afterward.

Release binding checks the consistency of JSON from a trusted runner against committed
source and registered cases. It is **not a signed execution attestation**: a malicious
runner can manufacture a mutually consistent report. Runner integrity, credential isolation
and independent production acceptance remain separate requirements.

The [public evidence manifest](../artifacts/PUBLIC_EVIDENCE_MANIFEST.json) lists the selected
historical bytes and SHA-256 hashes. A credential-pattern screen found no real-key patterns
in this selected evidence or tracked source; the Guardrails test contains an intentional
fake private-key marker. This bounded screen is not proof that every possible secret is absent.

The [original verification report](VERIFICATION.md) keeps its date and source identities.
No historical actual-model result is relabelled as a run of the repaired code. The repaired
revision has fixture and contract verification; a new actual-model release requires its
own complete local evaluation.

## Remaining production blockers

Reported dependency advisories and scanner coverage gaps persist. Untrusted code execution
remains disabled; vLLM never became ready on the original host. External SaaS accounts,
cluster rollout/rollback, remote idempotency contracts and upstream patch submission are
unverified. Router quality/savings, large-vector recall and tiny training quality did not
meet their intended goals. These are preserved in the [criterion ledger](PROJECT_LEDGER.md).

The public portfolio should emphasize the working application, reproducible failures and
specific repairs. Test totals and framework names are evidence-navigation aids; they do not
establish commercial outcomes, expert status or production readiness.
