import json

import pytest
from pais.contracts import Principal
from pais.vectors import QdrantIndex, VectorConflict


@pytest.fixture
def setup(tmp_path):
    index = QdrantIndex(tmp_path / "v.db")
    a = Principal(subject="owner", tenant_id="a", roles=["admin"])
    b = Principal(subject="owner-b", tenant_id="b", roles=["admin"])
    yield index, a, b
    index.close()


def test_actual_qdrant_hybrid_metadata_and_tenant_filter(setup):
    index, a, b = setup
    index.upsert(a, "a-1", "Approval timeout a_secret is fifteen minutes", {"category": "approval"})
    index.upsert(a, "a-2", "Backup retention is thirty days", {"category": "backup"})
    index.upsert(b, "b-1", "Approval timeout b_secret is two minutes", {"category": "approval"})
    hits = index.search(a, "approval timeout", metadata={"category": "approval"})
    assert [h.document_id for h in hits] == ["a-1"]
    assert all("b_secret" not in h.text for h in index.search(a, "b_secret"))
    with pytest.raises(ValueError, match="reserved"):
        index.search(a, "approval", metadata={"tenant_id": "b"})
    with pytest.raises(LookupError):
        index.delete(a, "b-1", 1)


@pytest.mark.parametrize("roles", [[], ["unknown"], ["reviewer"], ["editor"]])
@pytest.mark.parametrize("mode", ["hybrid", "dense", "sparse"])
def test_search_denies_missing_read_role_before_cache_embedding_or_query(setup, monkeypatch, roles, mode):
    index, a, _b = setup
    index.upsert(a, "private", "Private tenant approval policy")
    before = (index.cache_hits, index.cache_misses)

    def unexpected_query(*_args, **_kwargs):
        pytest.fail("Unauthorized search reached the Qdrant query boundary")

    monkeypatch.setattr(index.client, "query_points", unexpected_query)
    unauthorized = Principal(subject="alice", tenant_id="a", roles=roles)
    with pytest.raises(PermissionError, match="Reader role"):
        index.search(unauthorized, "Private tenant approval policy", mode=mode)
    assert (index.cache_hits, index.cache_misses) == before


@pytest.mark.parametrize("subject,tenant", [("", "a"), ("alice", "")])
def test_vector_reads_require_nonempty_trusted_identity(setup, subject, tenant):
    index, _a, _b = setup
    with pytest.raises(PermissionError, match="Trusted subject"):
        index.search(Principal(subject=subject, tenant_id=tenant, roles=["admin"]), "approval")


@pytest.mark.parametrize("roles", [["reader"], ["writer"], ["admin"]])
def test_canonical_read_roles_retain_tenant_filtered_search(setup, roles):
    index, a, b = setup
    index.upsert(a, "a-policy", "Tenant A approval policy")
    index.upsert(b, "b-policy", "Tenant B approval policy")
    principal = Principal(subject="alice", tenant_id="a", roles=roles)
    assert [hit.document_id for hit in index.search(principal, "approval policy")] == ["a-policy"]


def test_nonadmin_writer_can_mutate_but_reader_cannot(setup):
    index, _a, _b = setup
    writer = Principal(subject="operator", tenant_id="a", roles=["writer"])
    reader = Principal(subject="analyst", tenant_id="a", roles=["reader"])
    version = index.upsert(writer, "policy", "The approval timeout is fifteen minutes")
    assert index.search(reader, "approval timeout")[0].version == version
    with pytest.raises(PermissionError, match="writer"):
        index.upsert(reader, "policy", "Changed", expected_version=version)
    with pytest.raises(PermissionError, match="writer"):
        index.delete(reader, "policy", version)
    with pytest.raises(PermissionError, match="admin"):
        index.backup(reader)
    assert index.delete(writer, "policy", version) == version + 1
    assert index.search(reader, "approval timeout") == []


def test_update_delete_crash_window_reconciliation_and_no_resurrection(setup):
    index, a, _b = setup
    version = index.upsert(a, "same", "Old timeout fifteen minutes")
    next_version = index.upsert(a, "same", "New timeout thirty minutes", expected_version=version, materialize=False)
    assert index.search(a, "timeout") == []
    assert index.materialize(a) == 1
    assert index.search(a, "timeout")[0].version == next_version
    tombstone = index.delete(a, "same", next_version, materialize=False)
    assert index.search(a, "timeout") == []
    index.materialize(a)
    with pytest.raises(VectorConflict):
        index.upsert(a, "same", "Old timeout fifteen minutes", expected_version=version)
    assert tombstone == 3


def test_embedding_cache_is_tenant_and_configuration_scoped(setup):
    index, a, b = setup
    index.upsert(a, "one", "Identical source content")
    misses = index.cache_misses
    index.upsert(a, "two", "Identical source content")
    assert index.cache_hits == 1 and index.cache_misses == misses
    index.upsert(b, "three", "Identical source content")
    assert index.cache_misses == misses + 1


def test_portable_restore_verifies_real_vectors_metadata_and_tenant(setup, tmp_path):
    index, a, b = setup
    index.upsert(a, "one", "Approval timeout is fifteen minutes", {"category": "policy"})
    index.upsert(a, "deleted", "Remove this obsolete policy")
    index.delete(a, "deleted", 1)
    index.upsert(b, "b", "Private tenant B source")
    snapshot = index.backup(a)
    restored = QdrantIndex(tmp_path / "restored.db")
    try:
        report = restored.restore(a, snapshot)
        assert report == {"documents": 2, "vectors": 1}
        hit = restored.search(a, "approval timeout", metadata={"category": "policy"})[0]
        assert hit.document_id == "one" and hit.version == 1
        assert restored.search(b, "private") == []
        with pytest.raises(PermissionError, match="tenant"):
            restored.restore(b, snapshot)
        altered = json.loads(snapshot)
        altered["body"]["documents"][0]["text"] = "tampered"
        with pytest.raises(ValueError, match="checksum"):
            restored.restore(a, json.dumps(altered).encode())
    finally:
        restored.close()


def test_versioned_reindex_preserves_original_and_requires_new_name(setup):
    index, a, _b = setup
    index.upsert(a, "one", "Approval policy version")
    result = index.reindex(a, "pais_v2")
    assert result["documents"] == 1 and not result["automatic_cutover"]
    assert index.collection == "pais_v1"
    assert index.search(a, "approval")[0].document_id == "one"
    with pytest.raises(VectorConflict):
        index.reindex(a, "pais_v2")
