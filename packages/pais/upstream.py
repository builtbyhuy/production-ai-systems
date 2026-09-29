"""Offline reproduction for the pinned upstream checkpoint transaction defect."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from pais.evidence import ROOT


def demo(profile: str = "fixture", output_dir: str | None = None) -> dict:
    if profile not in {"fixture", "local"}:
        raise RuntimeError(
            "Upstream publication is a separate approved action; use the local regression demo"
        )
    output = Path(output_dir or ROOT / "artifacts/p18-outputs") / "upstream-verification.json"
    process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "projects/18-upstream-contribution/verify_patch.py"),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if not output.is_file():
        raise RuntimeError(process.stdout[-1500:] + process.stderr[-1500:])
    report = json.loads(output.read_text())
    return {
        "project": "P18",
        "profile": profile,
        "passed": report["passed"],
        "real_dependency": "Pinned upstream SqliteSaver implementation and tests",
        "upstream_commit": report["manifest"]["configuration"]["upstream_commit"],
        "runs": {
            name: {"exit_status": run["exit_status"], "output_tail": run["output_tail"][-1800:]}
            for name, run in report["runs"].items()
        },
        "publication": report["publication"],
        "evidence": str(output),
        "limits": report["limits"],
    }
