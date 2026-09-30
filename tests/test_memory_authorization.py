"""Memory authorization uses real SQLite authority without starting Redis or models."""
import pytest
from pais.contracts import Principal, utcnow
from pais.memory import MemoryService


class Cache:
    def __init__(self, _url):
        self.records = {}
        self.buffers = {}

    def get(self, principal, memory_id):
        return self.records.get((principal.tenant_id, memory_id))

    def sync(self, record, _ttl):
        self.records[(record.tenant_id, record.memory_id)] = record
        return True

    def append_message(self, principal, session_id, text):
        self.buffers.setdefault((principal.tenant_id, session_id), []).append(text)

    def messages(self, principal, session_id):
        return self.buffers.get((principal.tenant_id, session_id), [])


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setattr("pais.memory.RedisMemoryCache", Cache)
    service = MemoryService(tmp_path / "memory.db", "unused", vector_index=object(),
                            clock=lambda: 1000.0)
    with service.db.transaction() as conn:
        conn.execute("INSERT INTO mem_records VALUES(?,?,?,?,?,?,?,0,?,?)", (
            "a", "private", 1, "Private tenant memory", 1.0,
            '[{"source_id":"runbook","version":"v1"}]', 2000.0, 1000.0, utcnow(),
        ))
        conn.execute("INSERT INTO mem_sessions VALUES(?,?,?,?)", ("a", "owned", "alice", utcnow()))
        conn.execute("INSERT INTO mem_changes(tenant_id,memory_id,version,kind,timestamp) "
                     "VALUES(?,?,?,?,?)", ("a", "private", 1, "created", utcnow()))
    return service


@pytest.mark.parametrize("roles", [[], ["reviewer"], ["editor"]])
@pytest.mark.parametrize("method,args", [
    ("get", ("private",)),
    ("recall", ("private",)),
    ("changes", ()),
    ("start_session", ()),
    ("append_message", ("owned", "A new message")),
    ("buffer", ("owned",)),
    ("summarize", ("owned", ["private"])),
    ("summary", ("owned",)),
    ("expire", ()),
    ("flush", ()),
])
def test_memory_and_owned_sessions_reject_missing_read_role(memory, roles, method, args):
    principal = Principal(subject="alice", tenant_id="a", roles=roles)
    with pytest.raises(PermissionError, match="Reader role"):
        getattr(memory, method)(principal, *args)


@pytest.mark.parametrize("roles", [["reader"], ["writer"], ["admin"]])
def test_authorized_reader_writer_and_admin_can_read_owned_resources(memory, roles):
    principal = Principal(subject="alice", tenant_id="a", roles=roles)
    assert memory.get(principal, "private").text == "Private tenant memory"
    memory.append_message(principal, "owned", "Hello")
    assert memory.buffer(principal, "owned") == ["Hello"]
    assert memory.summarize(principal, "owned", ["private"])["summary"] == "Private tenant memory"
    assert memory.summary(principal, "owned")["references"] == {"private": 1}
    assert memory.changes(principal)[0]["kind"] == "created"


@pytest.mark.parametrize("subject,tenant", [("", "a"), ("alice", "")])
def test_memory_requires_nonempty_trusted_identity(memory, subject, tenant):
    with pytest.raises(PermissionError, match="Trusted subject"):
        memory.get(Principal(subject=subject, tenant_id=tenant, roles=["admin"]), "private")


def test_read_permission_preserves_tenant_and_session_ownership_checks(memory):
    with pytest.raises(LookupError):
        memory.get(Principal(subject="alice", tenant_id="b", roles=["reader"]), "private")
    with pytest.raises(PermissionError, match="owned"):
        memory.buffer(Principal(subject="bob", tenant_id="a", roles=["reader"]), "owned")
    reader = Principal(subject="alice", tenant_id="a", roles=["reader"])
    with pytest.raises(PermissionError, match="writer"):
        memory.put(reader, "private", "Changed", expected_version=1,
                   provenance=[{"source_id": "runbook", "version": "v2"}])
    with pytest.raises(PermissionError, match="writer"):
        memory.delete(reader, "private", expected_version=1)
    assert memory.get(reader, "private").version == 1
