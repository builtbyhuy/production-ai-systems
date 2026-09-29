"""Regression tests proposed for the MIT-licensed upstream SQLite checkpoint package."""

import sqlite3

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.sqlite import SqliteSaver


def test_delete_thread_rolls_back_both_tables_on_second_delete_failure():
    with SqliteSaver.from_conn_string(":memory:") as saver:
        config = saver.put(
            {"configurable": {"thread_id": "atomic-thread", "checkpoint_ns": ""}},
            empty_checkpoint(),
            {"source": "input", "step": 0, "parents": {}},
            {},
        )
        saver.put_writes(config, [("channel", "pending value")], "task-1")
        saver.conn.execute("""
            CREATE TRIGGER reject_pending_delete BEFORE DELETE ON writes
            BEGIN SELECT RAISE(ABORT, 'injected second-delete failure'); END
        """)
        saver.conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="second-delete failure"):
            saver.delete_thread("atomic-thread")
        assert saver.conn.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 1
        assert saver.conn.execute("SELECT count(*) FROM writes").fetchone()[0] == 1
        assert not saver.conn.in_transaction
        saver.conn.execute("DROP TRIGGER reject_pending_delete")
        saver.conn.commit()
        saver.delete_thread("atomic-thread")
        assert saver.conn.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 0
        assert saver.conn.execute("SELECT count(*) FROM writes").fetchone()[0] == 0


def test_cursor_rolls_back_when_body_is_interrupted():
    with SqliteSaver.from_conn_string(":memory:") as saver:
        saver.setup()
        with pytest.raises(KeyboardInterrupt), saver.cursor() as cursor:
            cursor.execute(
                "INSERT INTO writes VALUES('t','','c','task',0,'channel','json',?)", (b'"value"',)
            )
            raise KeyboardInterrupt
        assert saver.conn.execute("SELECT count(*) FROM writes").fetchone()[0] == 0
        assert not saver.conn.in_transaction
        with pytest.raises(sqlite3.ProgrammingError, match="closed cursor"):
            cursor.execute("SELECT 1")


def test_cursor_closes_and_rolls_back_if_commit_fails():
    class FailingCommitConnection(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("injected commit failure")

    connection = sqlite3.connect(":memory:", factory=FailingCommitConnection)
    try:
        saver = SqliteSaver(connection)
        saver.setup()
        with (
            pytest.raises(sqlite3.OperationalError, match="commit failure"),
            saver.cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO writes VALUES('t','','c','task',0,'channel','json',?)", (b'"value"',)
            )
        assert connection.execute("SELECT count(*) FROM writes").fetchone()[0] == 0
        assert not connection.in_transaction
        with pytest.raises(sqlite3.ProgrammingError, match="closed cursor"):
            cursor.execute("SELECT 1")
    finally:
        connection.close()


def test_nontransaction_cursor_preserves_caller_transaction():
    with SqliteSaver.from_conn_string(":memory:") as saver:
        saver.setup()
        with (
            pytest.raises(ValueError, match="caller owns transaction"),
            saver.cursor(transaction=False) as cursor,
        ):
            cursor.execute(
                "INSERT INTO writes VALUES('t','','c','task',0,'channel','json',?)", (b'"value"',)
            )
            raise ValueError("caller owns transaction")
        assert saver.conn.in_transaction
        saver.conn.rollback()
        assert saver.conn.execute("SELECT count(*) FROM writes").fetchone()[0] == 0
