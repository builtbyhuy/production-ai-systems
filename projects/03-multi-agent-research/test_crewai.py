import os

import pytest

os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"

from pais.contracts import Principal
from pais.research import ResearchService, demo_sources
from pais.workflows import ApprovalService


@pytest.fixture
def principal():
    return Principal(subject="operator", tenant_id="demo", roles=["admin"])


def test_actual_four_role_orchestration_and_human_approval(tmp_path, principal):
    service = ResearchService(tmp_path / "r.db", demo_sources())
    result = service.run(principal, "approval timeout", reviewer=principal.subject)
    assert result["status"] == "needs_approval", result
    assert result["calls"] == 4
    assert result["tools_executed"] == ["corpus_lookup", "inspect_evidence"]
    assert not result["model_quality_verified"]
    complete = [r["role"] for r in service.history(principal, result["run_id"]) if r["event"] == "task_completed"]
    assert complete == list(service.required_roles)
    approvals = ApprovalService(tmp_path / "r.db")
    item = approvals.get(principal, result["approval_id"])
    approvals.capability_flags.set(principal, "agent.execute", True, reason="fixture research action")
    assert approvals.decide(principal, item.approval_id, "approve", item.action_hash, item.action.context_version).status == "executed"


def test_unsupported_claim_rejected_then_bounded_revision_fixes_it(tmp_path, principal):
    service = ResearchService(tmp_path / "r.db", demo_sources())
    bad = service.run(principal, "approval timeout", hallucinate=True, max_revisions=0)
    assert bad["status"] == "insufficient_evidence", bad
    assert bad["validation"]["unsupported_claims"] == ["claim-1"]
    repaired = service.run(principal, "approval timeout", hallucinate=True, max_revisions=1)
    assert repaired["status"] == "needs_approval", repaired
    assert repaired["calls"] == 8 and repaired["rounds"] == 2


def test_conflicts_and_poisoned_sources_do_not_gain_authority(tmp_path, principal):
    conflicted = ResearchService(tmp_path / "conflict.db", demo_sources(conflicting=True))
    result = conflicted.run(principal, "approval timeout")
    assert result["status"] == "insufficient_evidence", result
    assert result["validation"]["conflicts"]
    poisoned = ResearchService(tmp_path / "poison.db", demo_sources(malicious=True))
    safe = poisoned.run(principal, "approval timeout")
    assert safe["status"] == "needs_approval", safe
    assert set(safe["tools_executed"]) == {"corpus_lookup", "inspect_evidence"}


def test_budget_exhaustion_missing_agent_and_isolation(tmp_path, principal):
    service = ResearchService(tmp_path / "r.db", demo_sources())
    exhausted = service.run(principal, "approval timeout", max_calls=2)
    assert exhausted["status"] == "failed", exhausted
    assert exhausted["calls"] == 2
    with pytest.raises(ValueError, match="four required"):
        service.run(principal, "approval timeout", roles=("researcher", "writer"))
    with pytest.raises(LookupError):
        service.get(principal.model_copy(update={"tenant_id": "other"}), exhausted["run_id"])


def test_authorized_web_adapter_uses_bounded_pinned_policy_and_actual_crewai(tmp_path, principal):
    from pais.research import WebResearchConfig
    from pais.security import SafeURLPolicy
    calls = []

    class FixturePinnedTransport:
        pins_validated_addresses = True

        def fetch(self, target, **bounds):
            calls.append((target, bounds))
            return b"Approval timeout is 15 minutes."

    source = demo_sources()[0].model_copy(update={"uri": "https://evidence.example/runbook"})
    config = WebResearchConfig(allowed_hosts=["evidence.example"], sources=[source])
    policy = SafeURLPolicy({"evidence.example"}, resolver=lambda *a, **k: [
        (2, 1, 6, "", ("93.184.216.34", 443)),
    ])
    service = ResearchService(tmp_path / "web.db", [])
    result = service.run_web(principal, "approval timeout", config, authorized=True,
        inference_profile="fixture", transport=FixturePinnedTransport(), url_policy=policy)
    assert result["status"] == "needs_approval", result
    assert result["research_mode"] == "authorized-web"
    assert len(result["acquisition"]) == len(calls) == 1
    assert calls[0][1]["timeout"] <= 10
    assert calls[0][1]["max_bytes"] == config.max_bytes_per_source
    assert result["model_quality_verified"] is False
