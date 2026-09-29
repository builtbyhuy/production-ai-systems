import pytest
from pais.research import (
    AtomicFact,
    EvidenceBundle,
    ResearchClaim,
    ResearchDraft,
    ResearchService,
    demo_sources,
    validate_evidence,
)


def test_web_mode_requires_explicit_permission_before_any_fetch(tmp_path):
    from pais.contracts import Principal
    from pais.research import WebResearchConfig
    service = ResearchService(tmp_path / "web.db", [])
    config = WebResearchConfig(allowed_hosts=["example.com"], sources=demo_sources())
    with pytest.raises(PermissionError, match="explicit authorization"):
        service.run_web(Principal(subject="x", tenant_id="demo", roles=["admin"]),
                        "approval", config)


def test_local_mode_rejects_remote_or_credential_urls_before_optional_import(tmp_path):
    from pais.contracts import Principal
    service = ResearchService(tmp_path / "local.db", [])
    principal = Principal(subject="x", tenant_id="demo", roles=["admin"])
    for url in ("http://localhost:11434@evil.example", "http://example.com:11434",
                "http://127.0.0.1:11434/proxy", "http://127.0.0.1:11434?target=remote",
                "http://localhost:invalid", "http://localhost:11434\\evil.example"):
        with pytest.raises(PermissionError, match="loopback"):
            service.run(principal, "approval", profile="local", ollama_url=url)


def draft(value="15 minutes", sources=None):
    return ResearchDraft(title="Review timeout", claims=[ResearchClaim(
        claim_id="1", subject="approval", predicate="timeout", value=value,
        source_ids=["runbook-1"] if sources is None else sources,
    )])


def test_evidence_rejects_plausible_unsupported_claim():
    bundle = EvidenceBundle(sources=demo_sources())
    assert validate_evidence(draft(), bundle, "demo").accepted
    result = validate_evidence(draft("99 minutes"), bundle, "demo")
    assert not result.accepted and result.unsupported_claims == ["1"]


def test_conflicts_preserved_and_unknown_or_other_tenant_source_rejected():
    result = validate_evidence(draft(), EvidenceBundle(sources=demo_sources(conflicting=True)), "demo")
    assert not result.accepted
    assert set(result.conflicts[0]["values"]) == {"15 minutes", "30 minutes"}
    assert not validate_evidence(draft(sources=["invented"]), EvidenceBundle(sources=demo_sources()), "demo").accepted
    assert not validate_evidence(draft(), EvidenceBundle(sources=demo_sources()), "other").accepted


def test_quote_and_fact_value_must_exist_in_passage():
    source = demo_sources()[0]
    source.facts = [AtomicFact(subject="approval", predicate="timeout", value="15 minutes", quote="invented quote")]
    assert not validate_evidence(draft(), EvidenceBundle(sources=[source]), "demo").accepted


def test_source_id_uniqueness(tmp_path):
    source = demo_sources()[0]
    with pytest.raises(ValueError, match="unique"):
        ResearchService(tmp_path / "r.db", [source, source])
