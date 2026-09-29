"""Execute the declared sandbox denial/resource acceptance only with a real boundary."""
import argparse
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from pais.sandbox import SandboxLimits, SandboxRunner, SandboxUnavailable


def run(args):
    runner = SandboxRunner(image=args.image, endpoint=args.endpoint, enabled=args.enabled,
                           limits=SandboxLimits(wall_seconds=4, cpu_seconds=1, memory_mb=128,
                                                processes=16, output_bytes=4096))
    try:
        boundary = runner.preflight()
    except SandboxUnavailable as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc), "executed_submissions": 0}))
        return 2
    with tempfile.TemporaryDirectory(prefix="pais-host-sentinel-") as directory:
        sentinel = Path(directory)/"host-only.txt"
        sentinel.write_text("fixture host sentinel; not a credential")
        probes = {
            "functional": "print(2 + 3)",
            "host_file": f"try:\n open({str(sentinel)!r}).read()\n print('FAILED: host readable')\nexcept OSError:\n print('denied')",
            "root_write": "try:\n open('/pais-forbidden','w').write('x')\n print('FAILED: root writable')\nexcept OSError:\n print('denied')",
            "network": "import socket\ntry:\n socket.create_connection(('1.1.1.1',443),timeout=.5)\n print('FAILED: network')\nexcept OSError:\n print('denied')",
            "credentials": "import os\nprint('clean' if all(x not in os.environ for x in ['OPENAI_API_KEY','AWS_SECRET_ACCESS_KEY','PAIS_AUTH_TOKENS']) else 'FAILED')",
            "memory": "x=bytearray(512*1024*1024);print('FAILED: allocation')",
            "cpu": "while True: pass",
            "wall_time": "import time;time.sleep(100)",
            "output": "print('x'*1000000)",
            "processes": "import os,time\ntry:\n for i in range(64):\n  if os.fork()==0:\n   time.sleep(3)\n   os._exit(0)\n print('FAILED: process limit')\nexcept OSError:\n print('denied',flush=True)\n",
        }
        results = {name: asdict(runner.run_python(code)) for name, code in probes.items()}
    checks = {"functional": results["functional"]["stdout"].strip() == "5",
              "host_file": "denied" in results["host_file"]["stdout"],
              "root_write": "denied" in results["root_write"]["stdout"],
              "network": "denied" in results["network"]["stdout"],
              "credentials": results["credentials"]["stdout"].strip() == "clean",
              "memory": results["memory"]["exit_code"] != 0,
              "cpu": results["cpu"]["exit_code"] != 0 and not results["cpu"]["timed_out"],
              "wall_time": results["wall_time"]["timed_out"],
              "output": results["output"]["truncated"],
              "processes": "denied" in results["processes"]["stdout"]}
    report = {"status": "verified_scope" if all(checks.values()) else "failed", "checks": checks,
              "boundary": boundary, "results": results,
              "limits": ["Shared kernel; this drill is not a container-escape audit"]}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--enabled", action="store_true")
    parser.add_argument("--image", default=os.environ.get("PAIS_SANDBOX_IMAGE"))
    parser.add_argument("--endpoint", default=os.environ.get("PAIS_SANDBOX_ENDPOINT"))
    parser.add_argument("--output", type=Path)
    raise SystemExit(run(parser.parse_args()))
