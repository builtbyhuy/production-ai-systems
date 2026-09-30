"""One bounded actual-local LangGraph acceptance attempt, preserving failed outcomes."""
import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from pais.contracts import Principal
from pais.evidence import manifest, write_report
from pais.research import ResearchService, demo_sources
from pais.workflows import ApprovalService


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Fresh output directory; existing directories are refused")
    parser.add_argument("--approve-local", action="store_true",
                        help="Explicitly authorize this local operator to review and record the local report effect")
    args = parser.parse_args()
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    directory = args.output or Path("artifacts/stateful") / ("p03-langgraph-local-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ"))
    directory.mkdir(parents=True, exist_ok=False)
    service = ResearchService(directory / "research.db", demo_sources())
    principal = Principal(subject="local-operator", tenant_id="demo", roles=["admin"])
    info = manifest("local", sys.argv, {"max_calls": 8, "max_revisions": 0,
                                      "deadline_seconds": 90, "model": "qwen2.5:1.5b",
                                      "approve_local": args.approve_local})
    began = time.perf_counter()
    result = service.run(principal, "approval timeout", profile="local", max_calls=8,
                         max_revisions=0, deadline_seconds=90, model="qwen2.5:1.5b",
                         ollama_url=os.environ.get("PAIS_OLLAMA_URL", "http://127.0.0.1:11434"),
                         reviewer=principal.subject)
    approval = None
    receipt = None
    if result["status"] == "needs_approval" and args.approve_local:
        approvals = ApprovalService(directory / "research.db")
        pending = approvals.get(principal, result["approval_id"])
        approvals.capability_flags.set(principal, "agent.execute", True, reason="authorized local research review")
        approval = approvals.decide(principal, pending.approval_id, "approve",
                                    pending.action_hash, pending.action.context_version)
        receipt = approvals.effects.receipt(principal, pending.action.idempotency_key, pending.action_hash)
        if approval.status != "executed" or receipt is None or receipt.get("external_delivery") is not False:
            raise RuntimeError("Authorized local approval did not record its expected local effect")
    history = service.history(principal, result["run_id"])
    report = {"manifest": info, "project": "03", "profile": "local", "result": result,
              "history": history, "elapsed_seconds": time.perf_counter() - began,
              "model_responses": sum(event["event"] == "model_usage" for event in history),
              "tool_executions": sum(event["event"] == "tool_result" for event in history),
              "approval": approval.model_dump(mode="json") if approval else None,
              "effect_receipt": receipt, "external_delivery": False,
              "exit_status": 0 if result["status"] == "needs_approval" else 1}
    write_report(directory / "report.json", report)
    print(json.dumps({key: value for key, value in report.items() if key not in {"manifest", "history"}}, indent=2))
    return report["exit_status"]


if __name__ == "__main__":
    raise SystemExit(main())
