# Data card — ops-instructions-v1

## Origin, license and purpose

This is **60 original synthetic instruction/preference records**, authored for this repository on 2026-09-29. Thirty concern narrow technical-operations decisions and thirty cover elementary arithmetic, language, sequence and evidence-reading tasks. The dataset, generator and original labels use the [MIT license](data/LICENSE). No customer content, public benchmark solution, user conversation, mined issue or pretrained-model output was imported.

`build_data.py` is the reproducible source. Its generated file is `data/ops-instructions-v1.jsonl`, SHA-256 `6652a2bc386a68c9feb5a8dc5613cb8c75a30ab743da47dcb44c7b29cde56f9c`. The prepared logical dataset manifest has a separate hash because it represents normalized records rather than JSONL bytes.

These examples are appropriate for pipeline smoke tests. They are too small and elementary to substantiate general assistant quality or production technical-operations competence. The authoring process did not include independent expert review or population sampling.

## Record schema and preference rationale

Each record contains `id`, `source_id`, `source_revision`, `license`, `provenance`, `suite`, `prompt`, `completion`, `chosen`, `rejected`, `rationale`, and `criterion`. The instruction completion equals the preferred answer. Preference pairs use a concise, observable justification tied to a stated contract or directly checkable fact: for example, retrying after the configured attempt limit violates that limit; a changed action revision requires a new approval.

The preference rationale is not model chain of thought and is never trained as an answer. The validator requires substantive text and an allowed criterion, but it cannot prove that a human-authored rationale is correct. Data review remains necessary for new sources. Identical alternatives, conflicting labels for an instruction, incomplete metadata, and unreviewed licenses are rejected. CC-BY additions require an explicit attribution entry.

## Splits and contamination policy

Seed `20260929` sorts source-group hashes independently within domain and general suites. Entire sources remain together: 60% train, 20% development, 20% test. The built-in dataset contains one independent instruction per source, resulting in **36/12/12 records**, with equal domain/general counts in each split. Changing order does not change source membership.

The tokenizer sees only training prompts and training chosen/rejected alternatives. Held-out vocabulary can therefore become `[UNK]`; this is disclosed and is another reason the random word-tokenizer smoke cannot establish capability quality. Exact normalized duplicates are removed only within the same source with consistent labels. Cross-source duplicate instructions and cross-split high-overlap trigram pairs are rejected.

The pipeline fingerprints **all text fields and source identities** in `evals/release.json`, `evals/development.json`, `evals/audit.json`, `evals/corpus.json`, and `projects/17-domain-benchmark/data/tasks-v1.jsonl`. Missing exclusion files block training. The recorded smoke manifest counted 1,516 unique exclusion fingerprints and 148 source identities. Audit data was accessed only by hash/overlap traversal; it was not used for training, checkpoint selection or threshold adjustment. No audit answers are printed by this traversal.

Exact hashes do not detect every paraphrase, semantic overlap or pretraining exposure. Shared elementary labels such as `yes`, `0`, and `deny` are not treated as contaminated examples by themselves; full prompts, prompt/answer identities and substantive answer text are checked. No contamination-free claim is made.

## Versioning

Review every proposed source, rationale and license. Rebuild the JSONL, update its version and pinned hash deliberately, rerun source/overlap validation and capture a new manifest. Never silently replace the current held-out suite or relax retention thresholds after viewing its score. Keep dataset version, model revision, tokenizer, seed, hyperparameters and exclusion manifest together in every run.
