from concurrent.futures import ThreadPoolExecutor

import pytest
from pais.contracts import Action, Principal
from pais.workflows import ApprovalConflict, ApprovalService, review_signals


@pytest.fixture(autouse=True)
def enable_effects(tmp_path):
    from pais.operations import CapabilityFlags
    CapabilityFlags(tmp_path / "state.db").set(
        Principal(subject="operator", tenant_id="a", roles=["admin"]),
        "agent.execute", True, reason="explicit fixture setup",
    )


@pytest.fixture
def actors():
    return (
        Principal(subject="requester", tenant_id="a", roles=["writer"]),
        Principal(subject="reviewer", tenant_id="a", roles=["reviewer"]),
    )


def action(key="once", version="v1"):
    return Action(tool="record_note", arguments={"note": "Make this exact note"},
                  context_version=version, idempotency_key=key)


def test_actual_langgraph_restart_and_idempotent_effect(tmp_path, actors):
    requester, reviewer = actors
    path = tmp_path / "state.db"
    first = ApprovalService(path)
    item = first.request(requester, action(), reviewer.subject)
    assert item.status == "pending"
    assert (tmp_path / "state.db.approvals.sqlite").is_file()
    second = ApprovalService(path)
    done = second.decide(reviewer, item.approval_id, "approve", item.action_hash, "v1")
    assert done.status == "executed"
    second.resume(reviewer, item.approval_id)
    second.decide(reviewer, item.approval_id, "approve", item.action_hash, "v1")
    assert second.effects.count(reviewer) == 1
    assert [x["event"] for x in second.history(reviewer, item.approval_id)] == [
        "requested", "approved", "executed",
    ]


@pytest.mark.parametrize("subject,tenant,roles,error", [
    ("reviewer", "b", ["reviewer"], LookupError),
    ("intruder", "a", ["admin"], PermissionError),
    ("reviewer", "a", ["reader"], PermissionError),
    ("requester", "a", ["reviewer"], PermissionError),
])
def test_wrong_identity_cannot_resume(tmp_path, actors, subject, tenant, roles, error):
    requester, reviewer = actors
    service = ApprovalService(tmp_path / "state.db")
    item = service.request(requester, action(), reviewer.subject)
    intruder = Principal(subject=subject, tenant_id=tenant, roles=roles)
    with pytest.raises(error):
        service.decide(intruder, item.approval_id, "approve", item.action_hash, "v1")
    assert service.effects.count(reviewer) == 0


def test_expiry_is_persisted_and_rejection_has_no_effect(tmp_path, actors):
    requester, reviewer = actors
    now = [1000.0]
    service = ApprovalService(tmp_path / "state.db", clock=lambda: now[0])
    item = service.request(requester, action(), reviewer.subject, ttl_seconds=1)
    now[0] = 1002.0
    with pytest.raises(ApprovalConflict, match="expired"):
        service.decide(reviewer, item.approval_id, "approve", item.action_hash, "v1")
    assert service.get(reviewer, item.approval_id).status == "expired"
    second = service.request(requester, action("second"), reviewer.subject)
    assert service.decide(reviewer, second.approval_id, "reject", second.action_hash, "v1").status == "rejected"
    assert service.effects.count(reviewer) == 0


def test_changed_action_stale_context_and_revoked_reviewer(tmp_path, actors):
    requester, reviewer = actors
    service = ApprovalService(tmp_path / "state.db")
    item = service.request(requester, action(), reviewer.subject)
    with pytest.raises(ApprovalConflict, match="Action changed"):
        service.decide(reviewer, item.approval_id, "approve", "fake-hash", "v1")
    service.update_context(requester, "default", "v2")
    with pytest.raises(ApprovalConflict, match="Source context changed"):
        service.decide(reviewer, item.approval_id, "approve", item.action_hash, "v1")
    service.update_context(requester, "default", "v1")
    revoked = ApprovalService(tmp_path / "state.db", authorizer=lambda p: p.model_copy(update={"roles": ["reader"]}))
    with pytest.raises(PermissionError):
        revoked.decide(reviewer, item.approval_id, "approve", item.action_hash, "v1")


def test_concurrent_opposed_decisions_have_one_winner(tmp_path, actors):
    requester, reviewer = actors
    path = tmp_path / "state.db"
    item = ApprovalService(path).request(requester, action(), reviewer.subject)

    def decide(value):
        try:
            return ApprovalService(path).decide(reviewer, item.approval_id, value, item.action_hash, "v1").status
        except ApprovalConflict:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(decide, ["approve", "reject"]))
    assert results.count("conflict") == 1
    assert set(results) <= {"conflict", "executed", "rejected"}
    assert ApprovalService(path).effects.count(reviewer) <= 1


def test_crash_after_downstream_commit_then_resume(tmp_path, actors):
    requester, reviewer = actors
    path = tmp_path / "state.db"

    def crash():
        raise RuntimeError("process dies after downstream commit")

    service = ApprovalService(path, after_effect=crash)
    item = service.request(requester, action(), reviewer.subject)
    with pytest.raises(RuntimeError, match="process dies"):
        service.decide(reviewer, item.approval_id, "approve", item.action_hash, "v1")
    assert service.effects.count(reviewer) == 1
    assert service.get(reviewer, item.approval_id).status == "approved"
    restarted = ApprovalService(path)
    assert restarted.resume(reviewer, item.approval_id).status == "executed"
    assert restarted.effects.count(reviewer) == 1


def test_edit_requires_new_review_and_new_idempotency_key(tmp_path, actors):
    requester, reviewer = actors
    service = ApprovalService(tmp_path / "state.db")
    original = service.request(requester, action(), reviewer.subject)
    with pytest.raises(ApprovalConflict, match="new idempotency"):
        service.edit_and_reapprove(requester, original.approval_id, action(), original.action_hash)
    replacement = service.edit_and_reapprove(requester, original.approval_id, action("edited"), original.action_hash)
    assert replacement.approval_id != original.approval_id
    assert replacement.status == "pending"
    assert service.get(requester, original.approval_id).status == "cancelled"
    with pytest.raises(ApprovalConflict):
        service.decide(reviewer, original.approval_id, "approve", original.action_hash, "v1")
    service.decide(reviewer, replacement.approval_id, "approve", replacement.action_hash, "v1")
    assert service.effects.count(reviewer) == 1


def test_idempotency_payload_binding_and_tool_allowlist(tmp_path, actors):
    requester, reviewer = actors
    service = ApprovalService(tmp_path / "state.db")
    original = service.request(requester, action(), reviewer.subject)
    assert service.request(requester, action(), reviewer.subject).approval_id == original.approval_id
    with pytest.raises(ApprovalConflict):
        service.request(requester, action(version="v2"), reviewer.subject)
    with pytest.raises(PermissionError):
        service.request(requester, action().model_copy(update={"tool": "shell"}), reviewer.subject)


def test_review_signals_and_nonfinite_input():
    assert review_signals(1.0, [], False) == []
    assert len(review_signals(0.4, ["conflict"], True)) == 3
    with pytest.raises(ValueError):
        review_signals(float("nan"), [], False)
