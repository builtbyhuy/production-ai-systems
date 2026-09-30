"""Run Next, FastAPI and Playwright in one network namespace; save actual app evidence.

This launches only local test applications. The optional packaged Chromium runs as a trusted
browser test process; --no-sandbox is NOT an untrusted-code execution sandbox for P06.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from pais.rag import create_demo_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("fixture", "local"), default="fixture")
    parser.add_argument("--output-dir", type=Path, help="Separate evidence directory for this run")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    app = root / "apps/copilot"
    artifacts = (args.output_dir.resolve() if args.output_dir else root / "artifacts/ui-runs" /
                 (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + "-" + args.profile))
    artifacts.mkdir(parents=True, exist_ok=True)
    payload = create_demo_pdf([
        "Operations handbook. The Northfield pump station is maintained by the operations team.",
        ("Pressure procedure. The maximum safe operating pressure is 8 bar. "
        "The maintenance interval is 30 days. Escalate critical incidents within 15 minutes. "
        "Before maintenance, isolate the pump and verify zero pressure on the local gauge."),
        "Maintenance records. Every inspection must be recorded with the date and technician name.",
    ])
    (artifacts / "operations-manual.pdf").write_bytes(payload)
    started = time.perf_counter()
    wall_started = time.time()
    env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1", "PAIS_E2E_PROFILE": args.profile,
           "PAIS_E2E_PYTHON": sys.executable, "PAIS_UI_EVIDENCE_DIR": str(artifacts),
           "PAIS_BROWSER_RUNTIME": os.getenv("PAIS_BROWSER_RUNTIME", str(root / ".tools/browser-runtime"))}
    if not env.get("PAIS_BROWSER_EXECUTABLE"):
        probe = subprocess.run(["node", "scripts/prepare-browser.mjs"],
                               cwd=app, capture_output=True, text=True, check=False)
        if probe.returncode == 0:
            browser = json.loads(probe.stdout.strip().splitlines()[-1])
            env["PAIS_BROWSER_EXECUTABLE"] = browser["executable"]
            env["PAIS_BROWSER_VERSION"] = browser["version"]
        else:
            print("Packaged Chromium is unavailable; Playwright will require its installed browser.")
    with tempfile.TemporaryDirectory(prefix="pais-browser-") as temporary:
        env["PAIS_E2E_DB_PATH"] = str(Path(temporary) / "state.db")
        result = subprocess.run(["npm", "test"], cwd=app, env=env, check=False)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False)
    package = json.loads((app / "package.json").read_text())
    result_path = artifacts / "playwright-results.json"
    measured = (json.loads(result_path.read_text()).get("stats", {})
                if result_path.exists() and result_path.stat().st_mtime >= wall_started else {})
    build_id = app / ".next/BUILD_ID"
    model_lock = root / "models/local-models.lock.json"
    report = {
        "project": "P08", "profile": args.profile, "timestamp": datetime.now(UTC).isoformat(),
        "command": shlex.join([sys.executable, *sys.argv]),
        "parent_orchestration": os.getenv("PAIS_EVIDENCE_PARENT_COMMAND"),
        "api_python_executable": sys.executable,
        "tested_commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty_tree": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
        "versions": package["dependencies"] | package["devDependencies"],
        "dataset_sha256": hashlib.sha256(payload).hexdigest(),
        "frontend_build_id": build_id.read_text().strip() if build_id.exists() else None,
        "dependency_lock_sha256": hashlib.sha256((app / "package-lock.json").read_bytes()).hexdigest(),
        "model_lock_sha256": (hashlib.sha256(model_lock.read_bytes()).hexdigest()
                              if args.profile == "local" and model_lock.exists() else None),
        "configuration": {"viewports": ["1440x960"] if args.profile == "local" else ["1440x960", "390x844"], "workers": 1,
                          "fixture_stream_delay_ms": 0 if args.profile == "local" else 180, "buffered_output": True,
                          "browser": env.get("PAIS_BROWSER_VERSION", "operator-supplied executable")},
        "exit_status": result.returncode, "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "test_counts": measured,
        "screenshots": sorted(path.name for path in artifacts.glob("*.png") if path.stat().st_mtime >= wall_started),
        "results": "playwright-results.json",
        "limits": ("Fixture browser/stream contracts; no real-model quality or provider TTFT claim."
                   if args.profile == "fixture" else "Single actual local model browser smoke; not a quality benchmark or provider TTFT measurement."),
    }
    (artifacts / "browser-evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
