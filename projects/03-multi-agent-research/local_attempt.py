"""One bounded actual-local CrewAI acceptance attempt, preserving failed outcomes."""
import json
import os
import sys
import time
from pathlib import Path

from pais.contracts import Principal
from pais.evidence import manifest, write_report
from pais.research import ResearchService, demo_sources


def main() -> int:
    os.environ["CREWAI_DISABLE_TELEMETRY"] = "true"
    os.environ["OTEL_SDK_DISABLED"] = "true"
    directory = Path("artifacts/stateful")
    directory.mkdir(parents=True, exist_ok=True)
    service = ResearchService(directory / "p03-local-state.db", demo_sources())
    principal = Principal(subject="local-operator", tenant_id="demo", roles=["admin"])
    info = manifest("local", sys.argv, {"max_calls": 8, "max_revisions": 0,
                                      "deadline_seconds": 90, "model": "qwen2.5:1.5b"})
    began = time.perf_counter()
    result = service.run(principal, "approval timeout", profile="local", max_calls=8,
                         max_revisions=0, deadline_seconds=90, model="qwen2.5:1.5b",
                         ollama_url=os.environ.get("PAIS_OLLAMA_URL", "http://127.0.0.1:11434"))
    history = service.history(principal, result["run_id"])
    report = {"manifest": info, "project": "03", "profile": "local", "result": result,
              "history": history, "elapsed_seconds": time.perf_counter() - began,
              "model_responses": sum(event["event"] == "model_usage" for event in history),
              "tool_executions": sum(event["event"] == "tool_result" for event in history),
              "exit_status": 0 if result["status"] == "needs_approval" else 1}
    write_report(directory / "p03-local-attempt.json", report)
    print(json.dumps({key: value for key, value in report.items() if key not in {"manifest", "history"}}, indent=2))
    return report["exit_status"]


if __name__ == "__main__":
    raise SystemExit(main())
