# Contributing and preparing publication

## Adding tasks

1. Write an original maintenance contract or provide a compatible source license, immutable revision and exact attribution. Do not submit private issue/customer code.
2. Define a small deterministic `solve` interface, a correct reference, one meaningful seeded regression, and at least three distinct checks including a boundary or failure case. The reference must pass every check and the starter must fail at least one.
3. Explain what distinct failure mechanism the task adds. Renaming variables or swapping constants does not create another meaningful task. Group derived or closely related examples under one source group so they cannot cross splits.
4. Add metadata, difficulty rationale and split policy. Review the task and license. Rebuild/version the corpus and pinned hash; never silently alter a scored release.
5. Run corpus QA and controller tests. Untrusted contributed reference code must itself be reviewed or executed behind P06; the built-in host reference validator is reserved for explicitly reviewed, checksum-pinned authored code.

## Submission format

The top-level JSON keys are exactly `schema_version`, `dataset_id`, `dataset_sha256`, `metadata`, and `solutions`. Export either built-in baseline to inspect a complete valid submission. `solutions` maps task id to a Python module defining one `solve`. Missing tasks score zero; unknown ids, duplicate solve definitions, oversized source and syntax errors are rejected.

`metadata` records `name`, `origin`, `version`, `configuration`, `model`, and `generation_cost_usd`. Model submissions additionally identify model id, immutable revision and provider. Cost is a nonnegative amount or null for unknown; it is self-reported, not an independently reconciled provider receipt. Declare prompt, temperature, seed, repair iterations and any exposure to public reference solutions in configuration.

## Publication checklist

- Establish the repository/account target and publication authorization before any external write.
- Review the license, data card, source/split policy, submission format and contamination statement.
- Provision and verify P06, score declared baselines, repeat them, and generate leaderboard rows only from actual raw results.
- Include immutable dataset/code versions, complete raw outcomes, hashes, command, runtime/image, resource limits, hardware, model configuration and cost basis.
- Keep trusted corpus QA separate from real baseline/model scores. Label hypothetical/controller test records so they cannot become public run evidence.
- Publish a reproducible release and contribution guide only after review. Record the actual release URL and timestamp.
- Record independent issues, contributors and real external usage only when they occur; proposed outreach and repository views are not benchmark adoption.

No public benchmark repository, release, model leaderboard or external adoption is claimed by the current implementation.
