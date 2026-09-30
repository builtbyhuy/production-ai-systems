"""Strict, versioned regression harness over actual RAG/storage contracts."""

from __future__ import annotations

import io
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

from pais.contracts import Citation, Principal, utcnow
from pais.evidence import ROOT, manifest, sha256, write_report


class EvaluationPrerequisite(RuntimeError):
    pass


def load_suite(suite: str = "release") -> tuple[list[dict], dict]:
    if suite not in {"release", "development", "audit"}:
        raise ValueError("suite must be release, development, or audit")
    cases = json.loads((ROOT / "evals" / f"{suite}.json").read_text())
    corpus = json.loads((ROOT / "evals/corpus.json").read_text())
    registered = json.loads((ROOT / "evals/manifest.json").read_text())
    for name in (f"{suite}.json", "corpus.json"):
        if registered["files"].get(name) != sha256(ROOT / "evals" / name):
            raise ValueError(f"Frozen dataset hash mismatch: {name}")
    if len(cases) != registered["counts"].get(suite):
        raise ValueError("Frozen suite count does not match its registration")
    if any(case.get("split") != suite for case in cases):
        raise ValueError("Case split does not match its registered suite")
    if suite == "release" and dict(Counter(case["category"] for case in cases)) != registered["release_categories"]:
        raise ValueError("Frozen release category counts do not match their registration")
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate case IDs")
    for case in cases:
        if case["source_id"] not in corpus:
            raise ValueError(f"Missing source for {case['id']}")
    return cases, corpus


def _pdf(pages: list[str]) -> bytes:
    from pais.rag import create_demo_pdf

    return create_demo_pdf(pages)


def _valid(validation: dict) -> bool:
    return all(validation.get(key) is True for key in ["exists", "span", "support"])


def _citation(service, principal, document, query: str) -> Citation:
    from pais.models import sentences_with_spans

    hits = service.search(principal, query, mode="lexical", limit=8)
    hit = next(
        h for h in hits if h.chunk.document_id == document.document_id and h.chunk.page_number == 1
    )
    chunk = hit.chunk
    spans = sentences_with_spans(chunk.text)
    start, end, quote = spans[0]
    return Citation(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        version_id=chunk.version_id,
        page_number=chunk.page_number,
        page_label=chunk.page_label,
        start=chunk.start + start,
        end=chunk.start + end,
        quote=quote,
        claim=quote,
    )


def _denied(callable_) -> bool:
    try:
        callable_()
    except (PermissionError, FileNotFoundError):
        return True
    return False


def run_case(
    service, case: dict, source: dict, db_path: Path, profile: str, degraded: bool = False
) -> dict:
    from pais.rag import ExtractionError, PDFInputError, RAGService, ScannedPDFError

    principal = Principal(
        subject="evaluation-runner", tenant_id="eval-" + case["id"], roles=["admin", "reviewer"]
    )
    other = Principal(subject="unrelated-reader", tenant_id="other-" + case["id"], roles=["admin"])
    reader = Principal(subject="read-only", tenant_id=principal.tenant_id, roles=["reader"])
    original = _pdf(source["pages"])
    scenario = case["scenario"]
    question = case.get("question", source["pages"][0])
    started = time.perf_counter()
    result = {
        "id": case["id"],
        "category": case["category"],
        "scenario": scenario,
        "question": question,
        "profile": profile,
        "passed": False,
        "source_checks": [True],
        "expected_reference": "",
        "actual_reference": "",
        "actual_text": "",
        "details": {},
    }
    try:
        document = service.ingest(principal, original, source["id"] + ".pdf")
        if scenario in {"answer", "abstain", "conflict", "injection"}:
            if scenario == "conflict":
                service.ingest(principal, _pdf([case["alternate_text"]]), "alternate-current.pdf")
            if scenario == "injection":
                service.ingest(
                    principal, _pdf([case["payload"], *source["pages"]]), "untrusted-attachment.pdf"
                )
            answer = service.answer(principal, question)
            if degraded and scenario == "answer":
                answer = answer.model_copy(
                    update={
                        "text": "Unsupported answer: 999999.",
                        "citations": [],
                        "abstained": False,
                    }
                )
            result["actual_text"] = answer.text
            result["details"] = {
                "answer": answer.model_dump(mode="json"),
                "document": document.model_dump(),
            }
            validations = [service.validate_citation(principal, c) for c in answer.citations]
            result["source_checks"] = (
                [_valid(v) for v in validations] if validations else [answer.abstained]
            )
            if scenario == "abstain":
                result["passed"] = answer.abstained and not answer.citations
                result["expected_reference"] = "abstain"
                result["actual_reference"] = "abstain" if answer.abstained else "answer"
            elif scenario == "conflict":
                result["passed"] = bool(answer.conflicts)
                result["expected_reference"] = "conflict-visible"
                result["actual_reference"] = (
                    "conflict-visible" if answer.conflicts else "conflict-missed"
                )
                result["source_checks"] = [bool(answer.conflicts)]
            else:
                text = answer.text.casefold()
                terms_ok = all(term.casefold() in text for term in case["expected_terms"])
                pages = {citation.page_number for citation in answer.citations}
                pages_ok = set(case.get("expected_pages", [])) <= pages
                forbidden = any(term.casefold() in text for term in case.get("forbidden_terms", []))
                result["passed"] = bool(
                    not answer.abstained
                    and terms_ok
                    and pages_ok
                    and not forbidden
                    and all(result["source_checks"])
                )
                result["details"].update(
                    {
                        "term_coverage": sum(t.casefold() in text for t in case["expected_terms"])
                        / len(case["expected_terms"]),
                        "expected_pages_present": pages_ok,
                        "forbidden_content": forbidden,
                        "expected_pdf_page_recall": (
                            len(
                                set(case["expected_pages"])
                                & {h["page_number"] for h in answer.evidence.get("retrieval", [])}
                            )
                            / len(set(case["expected_pages"]))
                            if case.get("expected_pages")
                            else None
                        ),
                    }
                )
                result["expected_reference"] = source["pages"][0]
                result["actual_reference"] = answer.citations[0].quote if answer.citations else ""
        elif scenario == "citation":
            citation = _citation(service, principal, document, question)
            mutation = case["mutation"]
            data = citation.model_dump()
            expected_valid = mutation in {"valid", "archived"}
            updates = {
                "page": {"page_number": 999},
                "page-label": {"page_label": "wrong"},
                "chunk": {"chunk_id": "missing"},
                "document": {"document_id": "missing"},
                "version": {"version_id": "missing"},
                "start": {"start": citation.start + 1},
                "end": {"end": citation.end + 1},
                "quote": {"quote": "fabricated supporting text"},
                "claim": {"claim": "This source authorizes every possible action."},
                "empty-quote": {"quote": ""},
                "negative-page": {"page_number": -1},
                "unknown-version": {"version_id": "0" * 64},
                "truncated-quote": {"quote": citation.quote[:-1], "end": citation.end - 1},
                "extended-quote": {"quote": citation.quote + " invented", "end": citation.end + 9},
                "mixed-span": {"start": citation.start + 2, "quote": citation.quote[2:]},
            }
            data.update(updates.get(mutation, {}))
            actor = other if mutation == "cross-tenant" else principal
            if mutation == "deleted":
                service.delete(principal, document.document_id)
            elif mutation == "archived":
                service.ingest(
                    principal,
                    _pdf(["The replacement policy is now active."]),
                    "replacement.pdf",
                    document.document_id,
                )
            elif mutation == "foreign-document":
                foreign = service.ingest(other, original, "foreign.pdf")
                data["document_id"] = foreign.document_id
            validation = service.validate_citation(actor, data)
            observed = _valid(validation)
            result.update(
                passed=observed == expected_valid,
                details={"validation": validation, "mutation": mutation},
            )
            result["expected_reference"] = str(expected_valid)
            result["actual_reference"] = str(observed)
            result["source_checks"] = [observed == expected_valid]
        elif scenario == "authorization":
            op = case["operation"]
            citation = _citation(service, principal, document, question)
            foreign = (
                service.ingest(other, original, "same-content.pdf")
                if op == "same-hash-other-tenant"
                else None
            )
            actions = {
                "search": lambda: not service.search(other, question),
                "list": lambda: not service.list_documents(other),
                "get-pdf": lambda: _denied(
                    lambda: service.get_pdf(other, document.document_id, document.version_id)
                ),
                "citation": lambda: not _valid(service.validate_citation(other, citation)),
                "delete": lambda: _denied(lambda: service.delete(other, document.document_id)),
                "replace": lambda: _denied(
                    lambda: service.ingest(other, original, "replacement.pdf", document.document_id)
                ),
                "foreign-version": lambda: _denied(
                    lambda: service.get_pdf(other, document.document_id, document.version_id)
                ),
                "read-only-ingest": lambda: _denied(
                    lambda: service.ingest(reader, original, "denied.pdf")
                ),
                "read-only-delete": lambda: _denied(
                    lambda: service.delete(reader, document.document_id)
                ),
                "unknown-doc": lambda: _denied(
                    lambda: service.get_pdf(principal, "missing", document.version_id)
                ),
                "unknown-citation": lambda: (
                    not _valid(
                        service.validate_citation(
                            principal, citation.model_copy(update={"chunk_id": "missing"})
                        )
                    )
                ),
                "same-hash-other-tenant": lambda: (
                    foreign.document_id != document.document_id
                    and _denied(
                        lambda: service.get_pdf(principal, foreign.document_id, foreign.version_id)
                    )
                ),
            }
            observed = bool(actions[op]())
            result.update(
                passed=observed,
                source_checks=[observed],
                expected_reference="denied-or-isolated",
                actual_reference="denied-or-isolated" if observed else "access-leak",
                details={"operation": op},
            )
        elif scenario == "malformed":
            variant = case["variant"]
            payloads = {
                "empty": b"",
                "not-pdf": b"a normal text file",
                "truncated": original[:24],
                "corrupt-header": b"%PDF-1.7\ncorrupt data",
                "json": b'{"input":"pdf"}',
                "html": b"<html>not a PDF</html>",
                "zip": b"PK\x03\x04not a PDF",
                "nul": b"\0" * 200,
                "random-bytes": bytes(range(256)),
            }
            if variant in {"empty-page", "encrypted", "image-only"}:
                from pypdf import PdfWriter

                writer = PdfWriter()
                writer.add_blank_page(width=200, height=200)
                if variant == "encrypted":
                    writer.encrypt("synthetic-test-password")
                if variant == "image-only":
                    from PIL import Image
                    from reportlab.lib.utils import ImageReader
                    from reportlab.pdfgen.canvas import Canvas

                    buf = io.BytesIO()
                    canvas = Canvas(buf, invariant=1)
                    canvas.drawImage(
                        ImageReader(Image.new("RGB", (10, 10), "black")), 0, 0, 100, 100
                    )
                    canvas.save()
                    payload = buf.getvalue()
                else:
                    buf = io.BytesIO()
                    writer.write(buf)
                    payload = buf.getvalue()
            else:
                payload = payloads[variant]
            try:
                service.ingest(principal, payload, f"malformed-{variant}.pdf")
                rejected = False
            except (PDFInputError, ExtractionError, ScannedPDFError) as exc:
                rejected = True
                result["details"]["rejection"] = type(exc).__name__
            result.update(
                passed=rejected,
                source_checks=[rejected],
                expected_reference="rejected",
                actual_reference="rejected" if rejected else "accepted",
            )
        elif scenario == "recovery":
            op = case["operation"]
            citation = _citation(service, principal, document, question)
            replacement = _pdf(["The replacement verification marker is RESTORED-42."])
            if op in {"duplicate-upload", "duplicate-after-restart"}:
                active = RAGService(db_path, profile=profile) if op.endswith("restart") else service
                duplicate = active.ingest(principal, original, "duplicate.pdf")
                ok = (
                    duplicate.version_id == document.version_id
                    and len(active.list_documents(principal)) == 1
                )
            elif op == "restart-search":
                active = RAGService(db_path, profile=profile)
                ok = bool(active.search(principal, question))
            elif op in {"replacement-active", "replacement-old-citation"}:
                new = service.ingest(
                    principal, replacement, "replacement.pdf", document.document_id
                )
                if op == "replacement-active":
                    ok = new.version_id != document.version_id and all(
                        h.chunk.version_id == new.version_id
                        for h in service.search(principal, "replacement verification marker")
                    )
                else:
                    ok = _valid(service.validate_citation(principal, citation))
            elif op.startswith("deletion-"):
                service.delete(principal, document.document_id)
                ok = {
                    "deletion-search": lambda: not service.search(principal, question),
                    "deletion-pdf": lambda: _denied(
                        lambda: service.get_pdf(
                            principal, document.document_id, document.version_id
                        )
                    ),
                    "deletion-citation": lambda: (
                        not _valid(service.validate_citation(principal, citation))
                    ),
                }[op]()
            elif op == "reingest-after-delete":
                service.delete(principal, document.document_id)
                restored = service.ingest(principal, original, "restored.pdf")
                ok = bool(service.search(principal, question)) and bool(restored.version_id)
            elif op == "invalid-replacement":
                try:
                    service.ingest(principal, b"invalid", "replacement.pdf", document.document_id)
                    ok = False
                except (PDFInputError, ExtractionError):
                    ok = _valid(service.validate_citation(principal, citation))
            elif op == "foreign-replacement":
                ok = _denied(
                    lambda: service.ingest(
                        other, replacement, "replacement.pdf", document.document_id
                    )
                ) and _valid(service.validate_citation(principal, citation))
            elif op == "restart-citation":
                ok = _valid(
                    RAGService(db_path, profile=profile).validate_citation(principal, citation)
                )
            else:
                raise ValueError(f"Unknown recovery operation: {op}")
            result.update(
                passed=bool(ok),
                source_checks=[bool(ok)],
                expected_reference="recovered",
                actual_reference="recovered" if ok else "inconsistent",
                details={"operation": op},
            )
        else:
            raise ValueError(f"Unknown scenario: {scenario}")
    except Exception as exc:  # noqa: BLE001 -- every dependency failure is recorded as a failed required case
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["source_checks"] = [False]
    result["latency_ms"] = (time.perf_counter() - started) * 1000
    return result


def _framework_metrics(results: list[dict], output: Path) -> dict:
    worker = ROOT / "projects/04-eval-harness"
    configured_python = os.environ.get("PAIS_EVAL_PYTHON")
    python = Path(configured_python) if configured_python else worker / ".venv/bin/python"
    if not configured_python and sys.platform == "win32":
        python = worker / ".venv/Scripts/python.exe"
    if not python.exists():
        raise EvaluationPrerequisite("Run: uv sync --project projects/04-eval-harness")
    inputs = output.with_suffix(".metric-inputs.json")
    outputs = output.with_suffix(".metrics.json")
    write_report(inputs, results)
    p = subprocess.run(
        [str(python), str(worker / "worker.py"), str(inputs), str(outputs)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if p.returncode:
        raise EvaluationPrerequisite("Required DeepEval/RAGAS metrics failed: " + p.stderr[-1500:])
    report = json.loads(outputs.read_text())
    if not isinstance(report.get("results"), dict) or set(report["results"]) != {row["id"] for row in results}:
        raise EvaluationPrerequisite("Incomplete required framework metric evidence")
    versions = report.get("versions", {})
    if any(not isinstance(versions.get(name), str) or not versions[name] for name in ("deepeval", "ragas")):
        raise EvaluationPrerequisite("Required evaluator version evidence is missing")
    for row in results:
        row["metrics"] = report["results"][row["id"]]
        for name in ("deepeval_source_support", "ragas_reference_exact_match", "ragas_reference_similarity"):
            value = row["metrics"].get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
                raise EvaluationPrerequisite("Missing or invalid required framework metric")
        checks = row["source_checks"]
        expected_support = sum(check is True for check in checks) / len(checks) if checks else None
        if row["metrics"]["deepeval_source_support"] != expected_support:
            raise EvaluationPrerequisite("Source-support metric contradicts captured source checks")
        row["passed"] = row["passed"] and row["metrics"]["deepeval_source_support"] == 1.0
    return {k: v for k, v in report.items() if k != "results"}


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def _summarize_category(rows: list[dict], profile: str) -> dict:
    latencies = [r["latency_ms"] for r in rows]
    retrieval = [
        r["details"]["expected_pdf_page_recall"]
        for r in rows
        if r["details"].get("expected_pdf_page_recall") is not None
    ]
    metrics = {}
    for key in [
        "deepeval_source_support",
        "ragas_reference_exact_match",
        "ragas_reference_similarity",
    ]:
        values = [r["metrics"][key] for r in rows if key in r.get("metrics", {})]
        metrics[key] = {"mean": statistics.fmean(values) if values else None, "cases": len(values)}
    generated = [
        r["details"].get("answer", {}).get("evidence", {}).get("generation", {}) for r in rows
    ]
    provider_usage = [g for g in generated if g.get("real_inference") is True]
    return {
        "total": len(rows),
        "passed": sum(bool(r["passed"]) for r in rows),
        "errors": sum(bool(r.get("error")) for r in rows),
        "pass_rate": sum(bool(r["passed"]) for r in rows) / len(rows) if rows else None,
        "latency_ms": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "p99": _percentile(latencies, 0.99),
        },
        "metrics": metrics,
        "retrieval": {
            "expected_pdf_page_recall_mean": statistics.fmean(retrieval) if retrieval else None,
            "cases": len(retrieval),
            "scope": "Physical page coverage in retrieved candidates; no broad semantic recall claim",
        },
        "usage": {
            "actual_inference_responses": len(provider_usage),
            "reported_input_tokens": sum(g.get("input_tokens", 0) for g in provider_usage)
            if provider_usage
            else None,
            "reported_output_tokens": sum(g.get("output_tokens", 0) for g in provider_usage)
            if provider_usage
            else None,
            "api_charges_usd": 0 if profile == "local" else None,
        },
    }


def run_suite(
    profile: str, suite: str, output: str | Path, degraded: bool = False, limit: int | None = None
) -> tuple[dict, int]:
    if profile not in {"fixture", "local"}:
        raise EvaluationPrerequisite(
            "Only explicitly implemented fixture/local profiles can execute this release suite"
        )
    from pais.rag import RAGService

    cases, corpus = load_suite(suite)
    full_count = len(cases)
    if limit is not None:
        cases = cases[:limit]
    thresholds = json.loads((ROOT / "evals/thresholds.json").read_text())["release"]
    output = Path(output).resolve()
    report = {
        "manifest": manifest(
            profile, sys.argv, {"suite": suite, "thresholds": thresholds, "degraded": degraded}
        ),
        "profile": profile,
        "suite": suite,
        "results": [],
        "required_cases": full_count,
    }
    if suite == "audit":
        path = ROOT / "artifacts/evals/audit-exposures.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as file:
            file.write(
                json.dumps(
                    {
                        "timestamp": utcnow(),
                        "commit": report["manifest"]["git_commit"],
                        "source_snapshot": report["manifest"]["source_snapshot_sha256"],
                    }
                )
                + "\n"
            )
    framework_error = None
    try:
        with tempfile.TemporaryDirectory(prefix="pais-eval-") as tmp:
            db_path = Path(tmp) / "eval.db"
            service = RAGService(db_path, profile=profile)
            for index, case in enumerate(cases, 1):
                row = run_case(service, case, corpus[case["source_id"]], db_path, profile, degraded)
                report["results"].append(row)
                print(
                    json.dumps(
                        {
                            "case": row["id"],
                            "n": index,
                            "total": len(cases),
                            "passed": row["passed"],
                            "latency_ms": round(row["latency_ms"], 2),
                            "error": row.get("error"),
                        }
                    ),
                    flush=True,
                )
            report["framework_metrics"] = _framework_metrics(report["results"], output)
    except Exception as exc:  # noqa: BLE001 -- unknown infrastructure errors must block the release
        framework_error = f"{type(exc).__name__}: {exc}"
        report["prerequisite_error"] = framework_error
    rows = report["results"]
    passed = sum(bool(r["passed"]) for r in rows)
    errors = sum(bool(r.get("error")) for r in rows) + bool(framework_error)
    skipped = full_count - len(rows)
    categories = {
        key: _summarize_category([r for r in rows if r["category"] == key], profile)
        for key in sorted({c["category"] for c in cases})
    }
    latencies = [r["latency_ms"] for r in rows]
    p95 = _percentile(latencies, 0.95)
    complete = skipped == 0 and errors == 0
    if suite == "release":
        complete = (
            complete
            and len(rows) >= thresholds["minimum_cases"]
            and set(thresholds["required_categories"]) <= categories.keys()
        )
    gate = bool(
        complete
        and passed == len(rows)
        and p95 is not None
        and p95 <= thresholds["operational_p95_ms_target"]
    )
    summary = {
        "total": len(rows),
        "passed": passed,
        "failed": len(rows) - passed,
        "errors": int(errors),
        "skipped": skipped,
        "gate_passed": gate,
        "deployment_eligible": bool(
            gate
            and profile == "local"
            and suite == "release"
            and report["manifest"]["git_commit"]
            and not report["manifest"]["dirty_tree"]
        ),
        "deployment_eligibility_scope": "Local synthetic regression and source provenance only; P11 cluster acceptance remains separate",
        "p50_latency_ms": _percentile(latencies, 0.5),
        "p95_latency_ms": p95,
        "p99_latency_ms": _percentile(latencies, 0.99),
        "per_category": categories,
        "model_quality_claim": "none"
        if profile == "fixture"
        else "Measured narrow synthetic extractive corpus only",
        "cost": {
            "api_charges": 0 if profile == "local" else None,
            "billing_mode": "local-native"
            if profile == "local"
            else "fixture; no provider costs measured",
        },
    }
    report["summary"] = summary
    status = 2 if framework_error else (0 if gate else 1)
    report["exit_status"] = status
    write_report(output, report)
    trends = output.parent / "trends.jsonl"
    with trends.open("a") as file:
        file.write(
            json.dumps(
                {
                    "timestamp": utcnow(),
                    "profile": profile,
                    "suite": suite,
                    "git_commit": report["manifest"]["git_commit"],
                    "dataset": sha256(ROOT / "evals" / f"{suite}.json"),
                    "summary": summary,
                }
            )
            + "\n"
        )
    return report, status


def langsmith_upload(report_path: str | Path, dataset_name: str, *, enabled: bool = False) -> dict:
    """Explicit external write; caller must establish account/authorization. Never automatic."""
    if not enabled or not os.environ.get("LANGSMITH_API_KEY"):
        raise EvaluationPrerequisite(
            "LangSmith upload requires explicit enablement and a configured key"
        )
    from uuid import uuid4

    from langsmith import Client

    report = json.loads(Path(report_path).read_text())
    client = Client()
    dataset = client.create_dataset(
        dataset_name=dataset_name, description="Versioned synthetic operations regression results"
    )
    run_ids = []
    for row in report["results"]:
        example = client.create_example(
            inputs={"question": row["question"]},
            outputs={"reference": row["expected_reference"]},
            dataset_id=dataset.id,
            metadata={"case_id": row["id"], "category": row["category"], "profile": row["profile"]},
        )
        run_id = uuid4()
        client.create_run(
            id=run_id,
            name="pais-regression",
            run_type="chain",
            inputs={"question": row["question"]},
            outputs={"answer": row["actual_text"]},
            reference_example_id=example.id,
            extra={"metadata": report["manifest"]},
        )
        client.create_feedback(run_id=run_id, key="required_case_passed", score=int(row["passed"]))
        run_ids.append(str(run_id))
    return {"dataset_id": str(dataset.id), "run_ids": run_ids, "status": "submitted"}
