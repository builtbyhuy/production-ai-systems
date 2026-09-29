# Integration contracts — v1

Python namespace: `pais`, source under `packages/pais/`. Core schema: `contracts.py`.
Durable state: `Database(path)` from `db.py`; use `transaction()` for atomic decisions.
Each module owns tables with its prefix. Do not migrate another module's tables.
SQLite application state is authoritative; vectors/caches are derived. Models live outside Git.

Identity is `Principal(subject, tenant_id, roles)` resolved by the API from a bearer credential.
No request-supplied tenant ID grants access. Pass Principal to every resource operation.
Fixture tokens must be opt-in at server startup; production authentication fails closed.

Module ownership:
- `rag.py`, `models.py`, `retrieval.py`: P01/P07 retrieval team.
- `reliability.py`, `security.py`, `observability.py`, `sandbox.py`: P02/P05/P06 reliability team.
- `workflows.py`, `jobs.py`, `research.py`, `tenancy.py`, `vectors.py`, `memory.py`: workflow team.
- `training.py`, `benchmark.py`: advanced team, isolated ML dependencies.
- `services/api/`, `apps/copilot/`: API/UI team.
- `cli.py`, `evidence.py`, evals, root tooling/docs: root; ops team owns infra and P11/P14/P18.

RAG service public methods agreed before integration:
`RAGService(db_path, profile='fixture', backend='sqlite')`,
`ingest(principal, pdf_bytes, filename, document_id=None) -> DocumentVersion`,
`answer(principal, question, request_id=None) -> Answer`,
`search(principal, query, mode='hybrid-rerank', limit=5) -> list[SearchHit]`,
`validate_citation(principal, citation) -> dict` (exists/span/support boolean fields),
`list_documents(principal)`, `get_pdf(principal, document_id, version_id) -> bytes`,
`delete(principal, document_id)`.

UI/API baseline endpoints under `/api`: `GET /health`, `POST /documents` multipart,
`GET /documents`, `GET /documents/{id}/versions/{version}/pdf`, `POST /chat`,
`POST /chat/stream`, `GET /approvals`, `POST /approvals/{id}/decision`.
`POST /chat` accepts question and optional message_id; principals come from bearer auth.
AI SDK UI message SSE stream: `x-vercel-ai-ui-message-stream: v1` header, `start`,
`text-start`, `text-delta`, `text-end`, custom `data-citations`, `finish`, `[DONE]`.
Stable IDs and cancellation are required. Validate/redact complete protected text before
streaming; disclose buffering and measure first display separately from provider TTFT.

All `demo` entrypoints accept explicit profile, return measured JSON, and fail with exit 2
for missing prerequisites. Optional imports must fail clearly when that project is invoked.
Pytest must not skip required dependencies silently. Contract fixtures label model outputs.

No external account, cloud cost, public push or upstream PR is authorized solely by a key.
GitHub account found: builtbyhuy; no existing production-ai-systems repository was returned.
