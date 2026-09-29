from concurrent.futures import ThreadPoolExecutor

import pytest
from pais.contracts import Citation, Principal
from pais.db import Database
from pydantic import ValidationError


def test_client_cannot_smuggle_admin_flag_into_principal_schema():
    with pytest.raises(ValidationError):
        Principal(subject="a", tenant_id="t", roles=["reader"], admin=True)


def test_role_guard_and_invalid_page_are_rejected():
    with pytest.raises(PermissionError):
        Principal(subject="a", tenant_id="t").require("reviewer")
    with pytest.raises(ValidationError):
        Citation(
            chunk_id="c",
            document_id="d",
            version_id="v",
            page_number=0,
            start=0,
            end=1,
            quote="x",
            claim="x",
        )


def test_transactions_rollback_and_serialize_competing_updates(tmp_path):
    db = Database(tmp_path / "state.db")
    db.initialize("CREATE TABLE count(n INTEGER NOT NULL); INSERT INTO count VALUES(0);")

    def increment(_):
        with db.transaction() as c:
            value = c.execute("SELECT n FROM count").fetchone()[0]
            c.execute("UPDATE count SET n=?", (value + 1,))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(increment, range(32)))
    with pytest.raises(RuntimeError), db.transaction() as c:
        c.execute("UPDATE count SET n=900")
        raise RuntimeError("Injected pre-commit crash")
    with db.transaction(False) as c:
        assert c.execute("SELECT n FROM count").fetchone()[0] == 32
