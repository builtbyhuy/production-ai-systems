#!/usr/bin/env python3
"""Run native Ollama and a command in one process/network namespace, then stop owned server."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--provision",
        action="store_true",
        help="Explicitly pull the two pinned-name small models; lock digests afterwards",
    )
    parser.add_argument("--port", type=int, default=11434)
    parser.add_argument(
        "--pull", action="append", default=[], help="Explicit additional local model to provision"
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("Supply an executable command after --")
    binary = (
        os.environ.get("PAIS_OLLAMA_BIN")
        or shutil.which("ollama")
        or str(ROOT / ".tools/ollama/bin/ollama")
    )
    if not Path(binary).is_file():
        print(
            "Missing Ollama. Install official native Ollama, then set PAIS_OLLAMA_BIN.",
            file=sys.stderr,
        )
        return 2
    env = dict(
        os.environ,
        OLLAMA_HOST=f"127.0.0.1:{args.port}",
        OLLAMA_MODELS=str(ROOT / "models/ollama"),
        OLLAMA_NUM_PARALLEL="1",
        OLLAMA_MAX_LOADED_MODELS="2",
        OLLAMA_NO_CLOUD="1",
        OLLAMA_CONTEXT_LENGTH="2048",
        PAIS_OLLAMA_URL=f"http://127.0.0.1:{args.port}",
        OMP_NUM_THREADS="2",
        MKL_NUM_THREADS="2",
        TOKENIZERS_PARALLELISM="false",
        HF_HUB_DISABLE_TELEMETRY="1",
        LANGSMITH_TRACING="false",
        LANGCHAIN_TRACING_V2="false",
        DEEPEVAL_TELEMETRY_OPT_OUT="YES",
        RAGAS_DO_NOT_TRACK="true",
        LITELLM_LOCAL_MODEL_COST_MAP="True",
    )
    logpath = ROOT / "artifacts/ollama-server.log"
    logpath.parent.mkdir(parents=True, exist_ok=True)
    lock = ROOT / "models/local-models.lock.json"
    env["PAIS_MODEL_LOCK"] = str(lock)
    with logpath.open("a") as log:
        server = subprocess.Popen(
            [binary, "serve"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
        )
        try:
            with httpx.Client(base_url=env["PAIS_OLLAMA_URL"], timeout=10, trust_env=False) as client:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError(f"Ollama exited {server.returncode}; inspect {logpath}")
                    try:
                        if client.get("/api/version").is_success:
                            break
                    except httpx.HTTPError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Ollama readiness timeout")
                if args.provision or args.pull:
                    for name in (
                        ["all-minilm:22m", "qwen2.5:1.5b"] if args.provision else []
                    ) + args.pull:
                        last = None
                        with client.stream(
                            "POST", "/api/pull", json={"model": name, "stream": True}, timeout=300
                        ) as response:
                            response.raise_for_status()
                            for line in response.iter_lines():
                                if not line:
                                    continue
                                data = json.loads(line)
                                if data.get("error"):
                                    raise RuntimeError(data["error"])
                                if data.get("status") != last:
                                    last = data.get("status")
                                    print(
                                        json.dumps(
                                            {
                                                "model": name,
                                                "status": last,
                                                "bytes": data.get("total"),
                                            }
                                        ),
                                        flush=True,
                                    )
                    print(
                        "Model provisioning complete; actual generation remains a separate check.",
                        flush=True,
                    )
                inventory = ROOT / "artifacts/local-model-inventory.json"
                version = client.get("/api/version")
                tags = client.get("/api/tags")
                version.raise_for_status()
                tags.raise_for_status()
                inventory.write_text(
                    json.dumps(
                        {"runtime": version.json(), "provisioned_models": tags.json()["models"]},
                        indent=2,
                    )
                    + "\n"
                )
                env["PAIS_MODEL_INVENTORY"] = str(inventory)
            return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode
        except (RuntimeError, httpx.HTTPError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        finally:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
