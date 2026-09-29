from __future__ import annotations

import io
from concurrent.futures import ThreadPoolExecutor

import pytest
from pais.contracts import Citation, Principal
from pais.models import GeneratedClaims, Generation, ModelFailure, ProposedClaim
from pais.rag import (
    ExtractionError,
    PDFInputError,
    RAGService,
    ScannedPDFError,
    create_demo_pdf,
    demo,
)
from pypdf import PdfReader, PdfWriter


@pytest.fixture
def principal():
    return Principal(subject="operator", tenant_id="alpha", roles=["admin"])


@pytest.fixture(params=["sqlite", "lancedb"])
def service(request, tmp_path):
    return RAGService(tmp_path / "rag.sqlite", profile="fixture", backend=request.param)


def test_acceptance_demo_all_required_behaviors(service):
    result = demo(profile="fixture", backend=service.backend)
    assert all(result["checks"].values()), result["checks"]
    assert result["models"]["real_inference"] is False
    assert result["answer"]["evidence"]["graph_nodes"] == ["retrieve", "generate", "validate", "finalize"]


def test_page_offsets_and_printed_page_labels(service, principal):
    source = create_demo_pdf(["Recovery target is 30 minutes.", "Backup retention is 30 days."])
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(source)))
    writer.set_page_label(0, 1, style="/r")
    stream = io.BytesIO()
    writer.write(stream)
    version = service.ingest(principal, stream.getvalue(), "labeled.pdf")
    answer = service.answer(principal, "What is the backup retention?", request_id="request-123")
    assert not answer.abstained
    assert answer.request_id == "request-123"
    assert answer.citations[0].page_number == 2
    assert answer.citations[0].page_label == "ii"
    citation = answer.citations[0]
    text = PdfReader(io.BytesIO(service.get_pdf(principal, version.document_id, version.version_id))).pages[1].extract_text()
    assert text[citation.start:citation.end] == citation.quote
    assert service.validate_citation(principal, citation)["support"]


def test_same_version_duplicate_and_archival_citations(service, principal):
    original = create_demo_pdf(["Backup retention is 30 days."])
    first = service.ingest(principal, original, "one.pdf")
    assert service.ingest(principal, original, "duplicate.pdf").version_id == first.version_id
    old = service.answer(principal, "What is the backup retention?").citations[0]
    second = service.ingest(principal, create_demo_pdf(["Backup retention is 14 days."]), "two.pdf", first.document_id)
    assert len(service.list_documents(principal)) == 1
    assert second.version_id != first.version_id
    assert service.get_pdf(principal, first.document_id, first.version_id) == original
    assert service.validate_citation(principal, old) == {
        "exists": True, "span": True, "support": True, "active": False,
        "reason": "Validated complete extractive assertion", "policy": "extractive-v1",
    }
    for mode in ("lexical", "dense", "hybrid", "hybrid-rerank"):
        assert {hit.chunk.version_id for hit in service.search(principal, "backup retention", mode)} == {second.version_id}
    service.delete(principal, first.document_id)
    assert not service.validate_citation(principal, old)["exists"]
    with pytest.raises(FileNotFoundError):
        service.get_pdf(principal, first.document_id, first.version_id)


def test_all_document_routes_are_tenant_scoped(service, principal):
    version = service.ingest(principal, create_demo_pdf(["Special calibration constant is 17 units."]), "private.pdf")
    citation = service.answer(principal, "What is the calibration constant?").citations[0]
    other = Principal(subject="other", tenant_id="beta", roles=["admin"])
    assert service.list_documents(other) == []
    for mode in ("lexical", "dense", "hybrid", "hybrid-rerank"):
        assert service.search(other, "calibration constant", mode) == []
    assert not service.validate_citation(other, citation)["exists"]
    with pytest.raises(FileNotFoundError):
        service.get_pdf(other, version.document_id, version.version_id)
    with pytest.raises(FileNotFoundError):
        service.delete(other, version.document_id)
    with pytest.raises(FileNotFoundError):
        service.ingest(other, create_demo_pdf(["Hostile replacement."]), "replacement.pdf", version.document_id)
    assert service.list_documents(principal)[0].version_id == version.version_id


def test_reader_is_read_only(service, principal):
    version = service.ingest(principal, create_demo_pdf(["Retention is 30 days."]), "policy.pdf")
    reader = principal.model_copy(update={"roles": ["reader"]})
    assert service.list_documents(reader)
    assert service.search(reader, "retention")
    with pytest.raises(PermissionError):
        service.ingest(reader, create_demo_pdf(["Retention is 7 days."]), "new.pdf")
    with pytest.raises(PermissionError):
        service.delete(reader, version.document_id)


@pytest.mark.parametrize("mutation,exists,span", [
    ({"page_number": 90}, True, False),
    ({"start": 1}, True, False),
    ({"quote": "Backup retention is 300 days."}, True, False),
    ({"version_id": "foreign-version"}, False, False),
    ({"claim": "Backup retention is 300 days."}, True, True),
])
def test_forged_citations_are_caught_at_correct_level(service, principal, mutation, exists, span):
    service.ingest(principal, create_demo_pdf(["Backup retention is 30 days."]), "policy.pdf")
    original = service.answer(principal, "What is the backup retention?").citations[0]
    forged = Citation.model_validate({**original.model_dump(), **mutation})
    result = service.validate_citation(principal, forged)
    assert result["exists"] is exists
    assert result["span"] is span
    assert result["support"] is False


def test_substring_is_not_entailment_and_negation_cannot_be_dropped(service, principal):
    service.ingest(principal, create_demo_pdf(["Unapproved production access is not allowed."]), "access.pdf")
    original = service.answer(principal, "What production access is allowed?").citations[0]
    start = original.start + original.quote.index("allowed")
    forged = original.model_copy(update={"quote": "allowed.", "claim": "allowed.", "start": start, "end": start + 8})
    validation = service.validate_citation(principal, forged)
    assert validation["exists"] and validation["span"] and not validation["support"]


def test_wrong_model_claim_abstains_entire_answer(service, principal, monkeypatch):
    service.ingest(principal, create_demo_pdf(["Backup retention is 30 days."]), "policy.pdf")
    chunk = service.search(principal, "backup retention")[0].chunk
    monkeypatch.setattr(service.models, "generate", lambda *_: Generation(GeneratedClaims(claims=[
        ProposedClaim(chunk_id=chunk.chunk_id, quote="Backup retention is 30 days.", claim="Backup retention is 30 days."),
        ProposedClaim(chunk_id=chunk.chunk_id, quote="Backup retention is 30 days.", claim="Backup retention is 300 days."),
    ])))
    answer = service.answer(principal, "What is the backup retention?")
    assert answer.abstained and not answer.citations
    assert "failed validation" in answer.evidence["abstention_reason"]


def test_conflicts_surface_even_if_generator_selects_one_side(service, principal, monkeypatch):
    service.ingest(principal, create_demo_pdf(["Backup retention is 30 days."]), "thirty.pdf")
    service.ingest(principal, create_demo_pdf(["Backup retention is 7 days."]), "seven.pdf")
    chunk = service.search(principal, "backup retention")[0].chunk
    quote = chunk.text.strip()
    monkeypatch.setattr(service.models, "generate", lambda *_: Generation(GeneratedClaims(claims=[
        ProposedClaim(chunk_id=chunk.chunk_id, quote=quote, claim=quote),
    ])))
    answer = service.answer(principal, "What is the backup retention?")
    assert answer.conflicts and len(answer.citations) == 2
    assert answer.evidence["conflict_source_assertions_added"] == 1


def test_document_summary_can_cover_pages_without_question_keyword_overlap(service, principal):
    service.ingest(principal, create_demo_pdf([
        "Mercury queues retain completed tasks for 4 days.",
        "Jupiter exports require approval from a supervisor.",
    ]), "space-named-services.pdf")
    answer = service.answer(principal, "Summarize both documented operating rules.")
    assert not answer.abstained
    assert {citation.page_number for citation in answer.citations} == {1, 2}
    assert answer.text.startswith("Summary of the retrieved document excerpts:")
    # An unrelated requested topic must still abstain, even when phrased as a summary.
    assert service.answer(principal, "Summarize uploaded documents about polar bears.").abstained


def test_explicit_summary_can_use_filename_scope_without_keyword_in_body(service, principal):
    service.ingest(principal, create_demo_pdf([
        "The receiving clerk checks each package for damage.",
        "A supervisor signs the count sheet before the goods enter stock.",
    ]), "warehouse-intake.pdf")
    answer = service.answer(principal, "Summarize both documented warehouse intake operating rules.")
    assert not answer.abstained
    assert {citation.page_number for citation in answer.citations} == {1, 2}
    assert answer.evidence["summary_filename_scoped_documents"]
    assert service.answer(principal, "What is the warehouse annual revenue?").abstained


def test_summary_covers_retrieved_pages_without_claiming_model_generation(service, principal, monkeypatch):
    service.ingest(principal, create_demo_pdf([
        "First response objective is 12 minutes. Escalation requires an on-call supervisor.",
        "Archive retention is 120 days. Archives require access logging.",
    ]), "operations.pdf")
    def unwanted_model_call(*_):
        raise AssertionError("Deterministic excerpt summaries must not pretend to call a model")
    monkeypatch.setattr(service.models, "generate", unwanted_model_call)
    answer = service.answer(principal, "Summarize both documented operations rules.")
    assert not answer.abstained and len(answer.citations) == 4
    assert {citation.page_number for citation in answer.citations} == {1, 2}
    assert answer.model == "extractive:page-balanced-v1"
    assert answer.evidence["generation"]["real_inference"] is False
    assert answer.evidence["generation"]["represented_pages"] == 2
    assert answer.evidence["graph_nodes"] == ["retrieve", "assemble_summary", "validate", "finalize"]


@pytest.mark.parametrize("first,second,expected", [
    ("Gateway timeout is 90 seconds.", "Gateway timeout is 999 units.", True),
    ("Gateway timeout is 60 seconds.", "Gateway timeout is 1 minute.", False),
    ("Gateway timeout is 1 minute.", "Gateway timeout is 2 minutes.", True),
])
def test_numeric_disagreements_cross_units_and_equivalent_units(service, principal, first, second, expected):
    service.ingest(principal, create_demo_pdf([first]), "one.pdf")
    service.ingest(principal, create_demo_pdf([second]), "two.pdf")
    answer = service.answer(principal, "What is the gateway timeout?")
    assert bool(answer.conflicts) is expected
    assert len(answer.citations) == 2


def test_malformed_encrypted_blank_and_scanned_pdf_fail_atomically(service, principal):
    for source in (b"not PDF", b"%PDF-1.7\nbroken"):
        with pytest.raises(PDFInputError):
            service.ingest(principal, source, "bad.pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    blank = io.BytesIO()
    writer.write(blank)
    with pytest.raises(ExtractionError, match="no extractable text"):
        service.ingest(principal, blank.getvalue(), "blank.pdf")
    writer.encrypt("secret")
    encrypted = io.BytesIO()
    writer.write(encrypted)
    with pytest.raises(PDFInputError, match="Encrypted"):
        service.ingest(principal, encrypted.getvalue(), "encrypted.pdf")
    from PIL import Image
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    scanned = io.BytesIO()
    canvas_pdf = canvas.Canvas(scanned)
    canvas_pdf.drawImage(ImageReader(Image.new("RGB", (10, 10), "black")), 0, 0, width=100, height=100)
    canvas_pdf.save()
    with pytest.raises(ScannedPDFError, match="OCR"):
        service.ingest(principal, scanned.getvalue(), "scan.pdf")
    assert not service.list_documents(principal)


def test_embedding_failure_does_not_replace_active_document(service, principal, monkeypatch):
    version = service.ingest(principal, create_demo_pdf(["Backup retention is 30 days."]), "original.pdf")
    def fail(*_):
        raise ModelFailure("Embedding service unavailable")
    monkeypatch.setattr(service.models, "embed", fail)
    with pytest.raises(ModelFailure):
        service.ingest(principal, create_demo_pdf(["Backup retention is 14 days."]), "changed.pdf", version.document_id)
    assert service.list_documents(principal)[0].version_id == version.version_id


def test_derived_index_failure_is_repaired_from_committed_source(service, principal, monkeypatch):
    version = service.ingest(principal, create_demo_pdf(["Backup retention is 30 days."]), "original.pdf")
    original_replace = service.adapter.replace
    def interrupted(*args, **kwargs):
        original_replace(*args, **kwargs)
        raise RuntimeError("Crash after derived-index side effect, before sync checkpoint")
    monkeypatch.setattr(service.adapter, "replace", interrupted)
    replacement_pdf = create_demo_pdf(["Backup retention is 14 days."])
    with pytest.raises(RuntimeError, match="Crash"):
        service.ingest(principal, replacement_pdf, "changed.pdf", version.document_id)
    committed = service.list_documents(principal)[0]
    assert committed.version_id != version.version_id
    monkeypatch.setattr(service.adapter, "replace", original_replace)
    retry = service.ingest(principal, replacement_pdf, "changed.pdf", version.document_id)
    assert retry.version_id == committed.version_id
    answer = service.answer(principal, "What is the backup retention?")
    assert not answer.abstained and "14 days" in answer.text
    assert {citation.version_id for citation in answer.citations} == {committed.version_id}


def test_missing_derived_vectors_rebuild_on_read(service, principal):
    service.ingest(principal, create_demo_pdf(["Backup retention is 30 days."]), "policy.pdf")
    service.adapter.delete(principal)
    assert service.adapter.count(principal) == 0
    reader = principal.model_copy(update={"roles": ["reader"]})
    assert service.search(reader, "backup retention")
    assert service.adapter.count(principal) == 1


def test_concurrent_duplicate_uploads_have_one_active_version(service, principal):
    pdf = create_demo_pdf(["Concurrent policy has exactly one current version."])
    with ThreadPoolExecutor(max_workers=3) as pool:
        versions = list(pool.map(lambda _: service.ingest(principal, pdf, "same.pdf"), range(3)))
    assert len({version.version_id for version in versions}) == 1
    assert len(service.list_documents(principal)) == 1


def test_long_pages_do_not_repeat_final_fragments_or_corrupt_spans(service, principal):
    paragraphs = " ".join(f"Checkpoint {index} requires independent approval." for index in range(30))
    service.ingest(principal, create_demo_pdf([paragraphs]), "long.pdf")
    hits = service.search(principal, "checkpoint independent approval", "lexical", limit=50)
    assert 1 < len(hits) < 10
    for hit in hits:
        assert hit.chunk.end - hit.chunk.start == len(hit.chunk.text)
