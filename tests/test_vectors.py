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
