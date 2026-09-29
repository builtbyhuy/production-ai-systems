"""P07 real selected storage, explicit models, resource measurements, and failure path."""
from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from pais.evidence import manifest, write_report
from pais.models import MissingPrerequisite
from pais.retrieval import demo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["fixture", "local"], required=True)
    parser.add_argument("--backend", choices=["sqlite", "lancedb"], default="sqlite")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {"manifest": manifest(args.profile, [sys.executable, *sys.argv], vars(args))}
    started = time.perf_counter()
    try:
        result = demo(profile=args.profile, backend=args.backend)
        status = 0 if all(result["checks"].values()) else 1
        report.update({"result": result, "exit_status": status})
    except MissingPrerequisite as exc:
        status = 2
        report.update({"exit_status": status, "status": "blocked", "error": str(exc)})
    report["elapsed_seconds"] = time.perf_counter() - started
    report["process_peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if args.output:
        write_report(args.output, report)
        print(json.dumps({"report": str(args.output), "exit_status": status,
                          "elapsed_seconds": report["elapsed_seconds"]}))
    else:
        print(json.dumps(report, indent=2, default=str))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
