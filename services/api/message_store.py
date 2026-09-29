"""Durable request claims and UI reconciliation, scoped to a trusted principal.

A disconnect ends delivery, not an uninterruptible provider call. Its claim remains pending
until the call returns. Retrying a pending claim never starts a second generation. A crashed
process leaves a pending claim that needs explicit operator reconciliation; we prefer this
visible failure over guessing whether an upstream request incurred cost.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from pais.contracts import Answer, Principal, utcnow
from pais.db import Database


class MessageConflict(ValueError):
    pass


class MessageInProgress(MessageConflict):
    pass


@dataclass(frozen=True)
class Claim:
    answer_id: str
    request_id: str
    attempt: int
    answer: Answer | None = None


class MessageStore:
    def __init__(self, db_path: str):
        self.db = Database(db_path)
        self.db.initialize("""
            CREATE TABLE IF NOT EXISTS api_messages (
              tenant_id TEXT NOT NULL, subject TEXT NOT NULL, message_id TEXT NOT NULL,
              conversation_id TEXT NOT NULL, question TEXT NOT NULL, question_hash TEXT NOT NULL,
              answer_id TEXT NOT NULL, request_id TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('pending','completed','failed')),
              delivery TEXT NOT NULL DEFAULT 'open', attempts INTEGER NOT NULL DEFAULT 1,
              answer_json TEXT, error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
              PRIMARY KEY(tenant_id, subject, message_id)
            );
            CREATE INDEX IF NOT EXISTS api_conversation
            ON api_messages(tenant_id,subject,conversation_id,created_at);
        """)

    def claim(self, principal: Principal, message_id: str, conversation_id: str, question: str) -> Claim:
        identity = (principal.tenant_id, principal.subject, message_id)
        digest = hashlib.sha256(question.encode()).hexdigest()
        stable_key = json.dumps(identity, separators=(",", ":"))
        answer_id = str(uuid5(NAMESPACE_URL, "pais:answer:" + stable_key))
        request_id = str(uuid5(NAMESPACE_URL, "pais:request:" + stable_key))
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM api_messages WHERE tenant_id=? AND subject=? AND message_id=?", identity
            ).fetchone()
            if row:
                if row["question_hash"] != digest or row["conversation_id"] != conversation_id:
                    raise MessageConflict("This message ID already belongs to a different request.")
                if row["status"] == "completed":
                    return Claim(row["answer_id"], row["request_id"], row["attempts"],
                                 Answer.model_validate_json(row["answer_json"]))
                if row["status"] == "pending":
                    raise MessageInProgress(
                        "This request is still processing. Retry when it has finished; no duplicate was started."
                    )
                attempt = row["attempts"] + 1
                conn.execute(
                    "UPDATE api_messages SET status='pending', delivery='open', attempts=?, "
                    "error_code=NULL, updated_at=? WHERE tenant_id=? AND subject=? AND message_id=?",
                    (attempt, utcnow(), *identity),
                )
                return Claim(answer_id, request_id, attempt)
            now = utcnow()
            conn.execute(
                "INSERT INTO api_messages (tenant_id,subject,message_id,conversation_id,question,"
                "question_hash,answer_id,request_id,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,'pending',?,?)",
                (*identity, conversation_id, question, digest, answer_id, request_id, now, now),
            )
            return Claim(answer_id, request_id, 1)

    def complete(self, principal: Principal, message_id: str, answer: Answer) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE api_messages SET status='completed',answer_json=?,updated_at=? "
                "WHERE tenant_id=? AND subject=? AND message_id=? AND status='pending'",
                (answer.model_dump_json(), utcnow(), principal.tenant_id, principal.subject, message_id),
            )

    def failed(self, principal: Principal, message_id: str, code: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE api_messages SET status='failed',error_code=?,updated_at=? "
                "WHERE tenant_id=? AND subject=? AND message_id=? AND status='pending'",
                (code, utcnow(), principal.tenant_id, principal.subject, message_id),
            )

    def delivery_stopped(self, principal: Principal, message_id: str) -> None:
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE api_messages SET delivery='stopped',updated_at=? "
                "WHERE tenant_id=? AND subject=? AND message_id=?",
                (utcnow(), principal.tenant_id, principal.subject, message_id),
            )

    def list(self, principal: Principal, conversation_id: str, limit: int = 30) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT message_id,question,answer_id,status,delivery,answer_json,error_code,created_at "
                "FROM api_messages WHERE tenant_id=? AND subject=? AND conversation_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (principal.tenant_id, principal.subject, conversation_id, min(limit, 100)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]
