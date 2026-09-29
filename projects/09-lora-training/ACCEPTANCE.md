# P09 acceptance and remaining prerequisites

Implementation and evidence are tracked separately. A successful pipeline smoke does not complete substantive fine-tuning acceptance.

| Requirement | Evidence/state |
|---|---|
| Validate instructions, preferences, licenses, rationale and source identities | PASS: `tests/test_training.py`; fixture demo |
| Deduplicate; keep source groups together; reject known evaluation overlap | PASS: unit/fixture validation and `artifacts/p09-smoke/dataset-manifest.json` |
| Exclude release/audit/benchmark data with explicit audit-access disclosure | PASS: five exclusion file hashes recorded in the smoke |
| Real tokenization without silent target truncation | PASS: 36 training examples; maximum total length 22 vs limit 128 |
| Genuine PEFT/Transformers/Datasets/TRL SFT optimization | PASS: three steps, changed adapter, unchanged frozen backbone |
| Genuine DPO from SFT with frozen SFT reference | PASS: three steps, changed adapter parameters |
| Checkpoint files and hashes | PASS: `checkpoint-manifest.json`; optimizer/trainer state retained |
| Adapter export/reload and evaluation | PASS: both reload checks, maximum logit difference 0 |
| Identical held-out domain/general comparison | PASS for the tiny smoke: six cases per suite at all three stages |
| Predeclared retention gate rejects insufficient evidence | PASS: twenty-case minimum rejects all six stage/suite records |
| Substantive before/after quality or capability retention | NOT VERIFIED: random model and small synthetic suites; exact match 0% throughout |
| Useful pretrained-model SFT/DPO outcome | NOT RUN: licensed immutable local model, larger reviewed data, resource budget and appropriate target modules needed |
| Automatic crash-resume drill or development-selected best checkpoint | NOT RUN: checkpoint persistence exists; the smoke uses a predetermined final step |

## Reproducible verification

```bash
.venv/bin/pytest -q tests/test_training.py
PYTHONPATH=packages .venv/bin/python -m pais.training fixture --output artifacts/p09-fixture
PYTHONPATH=packages projects/09-lora-training/.venv/bin/python -m pais.training smoke --output artifacts/p09-smoke-new
```

The original run occurred before the first repository commit and records `commit: null`, `dirty: true`; it is not attributed to a nonexistent clean commit. The retained configuration, source/exclusion hashes, model/adapter files and logs identify the measured run. Capture a new evidence envelope after a reviewed commit when comparing future changes.

The next substantive action is to provision a suitable local pretrained snapshot and independently reviewed larger dataset, populate `configs/local-snapshot.example.json`, then execute `train` into a fresh output directory. The minimum of twenty cases per suite is only an operational floor, not a statistical-power guarantee. A release needs a workload-specific evaluation design beyond this demonstration.
