# Data card — pais-python-maintenance-v1

## Identity and provenance

- Release: **1.0.0**, authored **2026-09-29**.
- File: `data/tasks-v1.jsonl`.
- SHA-256: `c76215ca42e8d33254ceff5146a2f1c92833c9156ccbe5ec9b57b63ebf25a8bd`.
- Size/coverage: **100 tasks, 100 source identities, 100 unique reference ASTs, 325 executable checks**.
- License: [MIT](data/LICENSE) for original corpus and generator.
- Provenance: original, synthetic Python/API maintenance contracts and seeded regressions; no external issue, copied code solution, customer data, or mined benchmark was used.

Each task records a stable id, task/source revision, source id, license, provenance statement, category, difficulty, split, behavioral prompt, entrypoint, defective starter, trusted reference and JSON test cases. Cases specify positional arguments and either expected output or expected exception ancestry. The generated programs are standard-library, bounded, in-memory operations.

## Categories and difficulty

| Category | Tasks | Examples of distinct failure mechanisms |
|---|---:|---|
| Collections | 10 | Stable order, dropped tails, missing values, last-write behavior |
| Text | 10 | Unicode case folding, literal prefix/suffix, quoted CSV, regex escaping |
| Numeric | 10 | Weighted means, decimal rounding, percentile rank, reservation rounding |
| Time | 10 | Offset conversion, half-open intervals, lease equality, midnight wrapping |
| Validation | 10 | Boolean/integer confusion, empty JSON object, nonfinite values, IPv4 |
| HTTP/API | 10 | Retry policy, repeated parameters, opaque path segments, header parsing |
| State | 10 | LRU access, atomic rollback, reversal deduplication, revision conflicts |
| Serialization | 10 | Decimal precision, timezone preservation, BOM handling, strict UTF-8 |
| Algorithms | 10 | Cycles, bounded traversal, duplicate ranges, stable ranking |
| Security logic | 10 | Exact host matching, nested redaction, tenant keys, stale approval |

Difficulty labels are authored estimates: **31 easy, 53 medium, 16 hard**. Easy tasks isolate a direct type/boundary/transformation; medium tasks combine API semantics or multiple cases; hard tasks involve state transitions, graph traversal, nested structure or interacting authorization conditions. Labels have not been calibrated against independent human completion time or model performance.

## Splits

Each category contributes six train, two development and two test tasks, yielding **60/20/20**. Source groups do not cross splits. Task reference programs are structurally distinct, but this does not prove conceptual independence: several share Python constructs or related boundary patterns. Split assignment is deliberately transparent and reproducible rather than hidden.

Train tasks may inform the supplied mechanical rule baseline. Development is for future configuration choices. Test is for a declared evaluation. P09 excludes the **entire** release, including train tasks, so this benchmark is not a training source for the portfolio's adapter smoke.

## Rubric and limitations

Every task requires all of its checks to pass for binary credit. Tests include typical behavior, boundaries and exceptions. Public examples do not exhaust every permitted input, and code can overfit them. This release has no secret tests and no claim of zero contamination. Seeds and immutable hashes make reruns identifiable, but do not remove bias from authorship, public solutions, hand-engineered rules or model pretraining.

The current host verified that **all 100 trusted references pass and all 100 seeded defects fail at least one check**. This is dataset-authoring QA, not baseline accuracy. No available secure boundary was verified, so no untrusted submission execution, model pass@1 or external community usage has been measured.
