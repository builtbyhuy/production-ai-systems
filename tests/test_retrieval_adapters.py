from __future__ import annotations

import pytest
from pais.contracts import Principal
from pais.db import Database
from pais.models import ModelFailure
from pais.retrieval import VectorRecord, get_adapter, reciprocal_rank_fusion


@pytest.fixture(params=["sqlite", "lancedb"])
def adapter(request, tmp_path):
    # Both real storage dependencies are required. A missing adapter fails, never skips.
    return get_adapter(request.param, Database(tmp_path / "state.sqlite"), 4)


def user(tenant="tenant-a", roles=None):
    return Principal(subject="test", tenant_id=tenant, roles=roles or ["admin"])


def test_crud_persistence_and_authorized_filtering(adapter, tmp_path):
    alice, bob = user(), user("tenant-b")
    adapter.upsert(alice, [VectorRecord("a", alice.tenant_id, [0.8, 0.2, 0, 0])])
    adapter.upsert(bob, [VectorRecord(f"b{index}", bob.tenant_id, [1, 0, 0, 0]) for index in range(8)])
    # The other tenant has better neighbours, so post-filtering a global top-k would fail.
    assert [hit.chunk_id for hit in adapter.search(alice, [1, 0, 0, 0], 1)] == ["a"]
    adapter.upsert(alice, [VectorRecord("a", alice.tenant_id, [0, 1, 0, 0]),
                           VectorRecord("a2", alice.tenant_id, [1, 0, 0, 0])])
    assert adapter.count(alice) == 2
    assert adapter.search(alice, [1, 0, 0, 0], 1)[0].chunk_id == "a2"
    reopened = get_adapter(adapter.name, Database(tmp_path / "state.sqlite"), 4)
    assert reopened.count(alice) == 2
    assert reopened.search(alice, [1, 0, 0, 0], 1)[0].chunk_id == "a2"
    adapter.delete(alice, ["a2"])
    assert adapter.count(alice) == 1
    adapter.delete(alice)
    assert adapter.search(alice, [1, 0, 0, 0]) == []
    assert adapter.count(bob) == 8


def test_adapter_rejects_tenant_forgery_and_foreign_id(adapter):
    alice, bob = user(), user("tenant-b")
    adapter.upsert(bob, [VectorRecord("reserved", bob.tenant_id, [1, 0, 0, 0])])
    with pytest.raises(PermissionError):
        adapter.upsert(alice, [VectorRecord("fake", bob.tenant_id, [1, 0, 0, 0])])
    with pytest.raises(PermissionError):
        adapter.upsert(alice, [VectorRecord("reserved", alice.tenant_id, [1, 0, 0, 0])])
    adapter.delete(alice, ["reserved"])
    assert adapter.count(bob) == 1
    assert adapter.count(alice) == 0


def test_adapter_reader_cannot_mutate_and_unprivileged_cannot_read(adapter):
    reader = user(roles=["reader"])
    with pytest.raises(PermissionError):
        adapter.upsert(reader, [VectorRecord("x", reader.tenant_id, [1, 0, 0, 0])])
    with pytest.raises(PermissionError):
        adapter.delete(reader)
    with pytest.raises(PermissionError):
        adapter.search(user(roles=["billing"]), [1, 0, 0, 0])


@pytest.mark.parametrize("vector", [[0, 0, 0, 0], [1, 2], [float("nan"), 0, 0, 0],
                                   [float("inf"), 0, 0, 0]])
def test_adapter_rejects_invalid_vectors_without_partial_write(adapter, vector):
    principal = user()
    with pytest.raises(ModelFailure):
        adapter.upsert(principal, [VectorRecord("bad", principal.tenant_id, vector)])
    assert adapter.count(principal) == 0


def test_filter_values_are_data_even_when_they_look_like_sql(adapter):
    literal_tenant = user("tenant-a' OR 1=1 --")
    other = user("other")
    adapter.upsert(other, [VectorRecord("other", other.tenant_id, [1, 0, 0, 0])])
    adapter.upsert(literal_tenant, [VectorRecord("id'quoted", literal_tenant.tenant_id, [0, 1, 0, 0])])
    assert [hit.chunk_id for hit in adapter.search(literal_tenant, [1, 0, 0, 0])] == ["id'quoted"]
    adapter.delete(literal_tenant)
    assert adapter.count(other) == 1


def test_rrf_combines_evidence_without_score_scale_assumptions():
    fused = reciprocal_rank_fusion([["lexical-only", "shared"], ["dense-only", "shared"]])
    assert fused[0][0] == "shared"
    assert fused[0][1] == pytest.approx(2 / 62)
    assert reciprocal_rank_fusion([["x", "x"]]) == reciprocal_rank_fusion([["x"]])
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["x"]], k=0)
