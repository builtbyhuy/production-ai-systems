# Dependency audit and production gate

Scan date: 2026-09-29. Tool: **pip-audit2.10.1** using the actual installed environments; UI uses `npm audit --omit=dev`. Raw reports are retained, including duplicate advisory records returned by the service. Counts below are affected installed package names, not an estimate of exploitable vulnerabilities.

The fresh application environment was created from the exact frozen `uv.lock`. Its audit lists 164 entries: 162 were queried, the editable project was intentionally skipped, and the CPU-specific Torch build was unmatched by the PyPI advisory lookup. Zero reported findings applies only to the 162 queried entries. An earlier experimental environment had extra packages and is not the final core environment; its scan remains `artifacts/pip-audit-core.json` for provenance.

| Environment | Listed / queried entries | Packages with reported advisories | Unqueried scope | Raw report |
|---|---:|---:|---|---|
| Core, fresh verified lock | 164 / 162 | 0 | Editable project; CPU Torch | [pip-audit-verified.json](../../artifacts/pip-audit-verified.json) |
| Evaluation worker, adopted fresh lock | 120 / 120 | 2 | None | [pip-audit-eval-final.json](../../artifacts/pip-audit-eval-final.json) |
| Evaluation worker, superseded baseline | 115 / 115 | 6 | None | [pip-audit-eval.json](../../artifacts/pip-audit-eval.json) |
| Guardrails worker | 108 / 108 | 4 | None | [pip-audit-security.json](../../artifacts/pip-audit-security.json) |
| CrewAI worker | 158 / 158 | 1 | None | [pip-audit-research.json](../../artifacts/pip-audit-research.json) |
| Training worker, after CLI dependency fix | 49 / 48 | 3 | CPU Torch | [pip-audit-training-final.json](../../artifacts/pip-audit-training-final.json) |
| CPU vLLM runtime | 153 / 148 | 1 | Five CPU wheel versions | [pip-audit-inference.json](../../artifacts/pip-audit-inference.json) |
| UI production dependencies | npm production scope | 0 reported | Development dependencies excluded from this scan | [npm-audit-production.json](../../artifacts/npm-audit-production.json) |

**The whole-repository production dependency gate is not passed.** No advisory has been suppressed or dismissed as a false positive. Functional acceptance of trusted local code remains separate from production supply-chain acceptance. These scans report known advisories at one point in time; zero findings is not a security guarantee.

The unmatched inference packages are Torch 2.13.0+cpu, Torchaudio 2.11.0+cpu, Torchcodec 0.16.0+cpu, Torchvision 0.28.0+cpu and vLLM 0.30.0+cpu. Core/training use Torch 2.8.0+cpu. These are explicit scanner coverage gaps, not cleared packages. The earlier training report listed 45 entries with 44 queried and the same three affected packages; adding the declared Pydantic dependency produced the final 49-entry environment.

## Findings and exercised paths

### Evaluation worker — superseded baseline

- `diskcache==5.6.3`: PYSEC-2026-2447. Provider-listed fixed versions: none listed.
- `langchain==0.3.27`: PYSEC-2026-2192, PYSEC-2026-2555. Provider-listed fixed versions: 0.3.30, 1.3.9.
- `langchain-core==0.3.86`: PYSEC-2026-2193, PYSEC-2026-2562. Provider-listed fixed versions: 1.2.11, 1.2.22.
- `langchain-openai==0.3.35`: PYSEC-2026-76. Provider-listed fixed versions: 1.1.14.
- `langchain-text-splitters==0.3.11`: PYSEC-2026-77. Provider-listed fixed versions: 1.1.2.
- `ragas==0.3.9`: PYSEC-2026-3046. Provider-listed fixed versions: none listed.

### Guardrails worker

- `click==8.2.0`: PYSEC-2026-2132. Provider-listed fixed versions: 8.3.3.
- `guardrails-ai==0.6.8`: PYSEC-2026-206. Provider-listed fixed versions: none listed.
- `langchain-core==0.3.86`: PYSEC-2026-2193, PYSEC-2026-2562. Provider-listed fixed versions: 1.2.11, 1.2.22.
- `litellm==1.80.0`: CVE-2026-12771, CVE-2026-12772, CVE-2026-12773, CVE-2026-12795, CVE-2026-12796, CVE-2026-12797, CVE-2026-12798, CVE-2026-12799, CVE-2026-59823, GHSA-69x8-hrgq-fjj8, PYSEC-2026-2597, PYSEC-2026-2598, PYSEC-2026-2599, PYSEC-2026-2600, PYSEC-2026-3476, PYSEC-2026-3477, PYSEC-2026-3478, PYSEC-2026-3479, PYSEC-2026-3861, PYSEC-2026-388, PYSEC-2026-390. Provider-listed fixed versions: 1.82.0, 1.83.0, 1.83.10, 1.83.14, 1.83.7, 1.83.9, 1.84.0.

### CrewAI worker

- `chromadb==1.1.1`: PYSEC-2026-311, PYSEC-2026-3813, PYSEC-2026-3814, PYSEC-2026-3815. Provider-listed fixed versions: none listed.

### Training worker

- `accelerate==1.10.1`: PYSEC-2026-3804. Provider-listed fixed versions: none listed.
- `datasets==4.1.1`: PYSEC-2026-3716. Provider-listed fixed versions: 5.0.1.
- `transformers==4.56.2`: PYSEC-2025-214, PYSEC-2025-215, PYSEC-2025-216, PYSEC-2025-217, PYSEC-2025-218, PYSEC-2026-2288, PYSEC-2026-2289, PYSEC-2026-2290, PYSEC-2026-3929. Provider-listed fixed versions: 5.0.0, 5.0.0rc3, 5.10.0, 5.3.0, 5.5.0.

## Reachability is separate from package status

The evaluation worker executes fixed source-support and string/reference metrics over trusted synthetic observations. It does not use multimodal URL/file metrics, public prompt loading or a DiskCacheBackend. The Guardrails bridge accepts the fixed schema/text validation operation; it does not expose the bundled LiteLLM proxy/server/administrative surface. CrewAI memory is disabled for its controlled evidence workflow; Chroma is not the selected memory store. Training uses repository-authored synthetic records and original tiny weights rather than untrusted pickle checkpoints. These facts describe the executed paths. They do not remove installed advisories or turn process isolation into a sandbox.

## Compatibility and remediation

RAGAS0.3.9 and0.4.3 both encountered a missing VertexAI module under current LangChain Community0.4.2. The evaluator remains isolated from the application environment. A disposable candidate and a fresh adopted environment both reproduced all432 numerical metrics across144 preserved release observations exactly. The adopted versions are DeepEval4.2.6, RAGAS0.4.3, Community0.3.31, LangChain1.4.3/Core1.6.5/OpenAI1.6.6. The fresh scan now reports only DiskCache5.6.3/PYSEC-2026-2447 and RAGAS0.4.3/PYSEC-2026-3046, with no listed fixes. The previous LangChain-family findings above remain as historical baseline evidence. See [adoption.json](../../artifacts/eval-upgrade/adoption.json) and [the experiment](../../artifacts/eval-upgrade/report.json). The latest RAGAS and DiskCache releases still have advisories with no fixed version listed by the audit service; upgrading other transitives alone cannot establish an advisory-free runtime.

Guardrails and training also have version-family constraints. Replace their locks only after supported dependency resolution and the meaningful existing validation/training/export/reload tests pass. Do not use `--no-deps`, hand-written import shims or ignore rules to manufacture a pass. Before any production deployment, either upgrade to corrected compatible packages or adopt a reviewed alternative implementation that preserves the required acceptance contracts, then rescan and rerun the affected end-to-end paths.

## Reproduction

```bash
uvx --from pip-audit==2.10.1 pip-audit --path .venv/lib/python3.12/site-packages --skip-editable --format json --output artifacts/pip-audit-core-current.json
uvx --from pip-audit==2.10.1 pip-audit --path projects/04-eval-harness/.venv/lib/python3.12/site-packages --skip-editable --format json --output artifacts/pip-audit-eval-current.json
cd apps/copilot
npm audit --omit=dev --json
```

Run the same isolated-environment scan for P03, P06 and P09; their `.venv` paths are listed in each README. Exit1 means reported findings, not a successful production gate. The CPU vLLM runtime scan found setuptools77.0.3 with PYSEC-2025-49 and PYSEC-2026-3447. Its dependency consistency check passed, but that is distinct from advisory clearance. Serving remains blocked by the host IPC prerequisite regardless of this finding.
