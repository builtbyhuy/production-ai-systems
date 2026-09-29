"""AI SDK UI message stream v1. Content is validated before text-start.

The 64-character delivery chunks are buffered-answer presentation, not provider tokens.
No unbounded producer queue is used: each event is yielded under ASGI backpressure.
"""
from __future__ import annotations

import json
from typing import Any


def event(kind: str, **data: Any) -> bytes:
    return ("data: " + json.dumps({"type": kind, **data}, ensure_ascii=False,
                                 separators=(",", ":")) + "\n\n").encode("utf-8")


DONE = b"data: [DONE]\n\n"


def answer_metadata(answer, *, replayed: bool = False) -> dict:
    return {
        "profile": str(answer.profile), "model": answer.model, "abstained": answer.abstained,
        "buffered": True, "replayed": replayed, "requestId": answer.request_id,
        "providerCancellation": "unsupported-by-synchronous-rag-contract",
    }
