"""Run the real native monitoring stack, actual traffic, trace, and alert lifecycle.

All processes are supervised in one network namespace. No provider calls are paid;
fixture model output and simulated ledger rates remain labeled separately from the
real Prometheus/Grafana/Tempo/Alertmanager integration evidence.
"""
import argparse
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml


class Supervisor:
    def __init__(self, output, env, max_rss_mib=1024):
        self.output, self.env, self.processes = output, env, {}
        self.handles = []
        self.peak_rss_bytes = 0
        self.max_rss_bytes = max_rss_mib * 1024**2

    def start(self, name, command, cwd=None, env=None, input_text=None):
        stream = (self.output/f"{name}.log").open("w")
        self.handles.append(stream)
        process = subprocess.Popen(command, cwd=cwd, env=self.env | (env or {}),
                                   stdin=subprocess.PIPE if input_text is not None else None,
                                   stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        self.processes[name] = process
        if input_text is not None:
            process.stdin.write(input_text.encode())
            process.stdin.close()
        return process

    def guard(self):
        # Host /proc IDs and namespace Popen IDs differ in this executor. Match
        # direct children through parent PID + NSpid before walking their trees.
        running = {p.pid for p in self.processes.values() if p.poll() is None}
        own_proc_pid = int(os.readlink("/proc/self"))
        parents, namespace_pids, rss_by_pid = {}, {}, {}
        for path in Path("/proc").iterdir():
            if not path.name.isdigit():
                continue
            try:
                fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
                pid = int(path.name)
                parents[pid] = int(fields[1])
                status = (path / "status").read_text().splitlines()
                nspid = next((line.split()[1:] for line in status if line.startswith("NSpid:")), [])
                namespace_pids[pid] = int(nspid[-1]) if nspid else pid
                rss_by_pid[pid] = next((int(line.split()[1])*1024 for line in status if line.startswith("VmRSS:")), 0)
            except (OSError, ValueError, IndexError):
                continue
        children = {pid for pid, parent in parents.items()
                    if parent == own_proc_pid and namespace_pids[pid] in running}
        while True:
            added = {pid for pid, parent in parents.items() if parent in children} - children
            if not added:
                break
            children.update(added)
        total = sum(rss_by_pid.get(pid, 0) for pid in children)
        self.peak_rss_bytes = max(self.peak_rss_bytes, total)
        if total > self.max_rss_bytes:
            raise RuntimeError(f"Monitoring drill exceeded its {self.max_rss_bytes // 1024**2} MiB RSS budget")

    def pause(self, seconds):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            self.guard()
            time.sleep(min(0.25, max(0, until-time.monotonic())))

    def stop(self):
        for process in reversed(list(self.processes.values())):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        for process in self.processes.values():
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for stream in self.handles:
            stream.close()


def binary(directory, name):
    matches = []
    for candidate in directory.rglob(name):
        if candidate.is_file():
            with candidate.open("rb") as stream:
                if stream.read(4) == b"\x7fELF":
                    matches.append(candidate)
    if len(matches) != 1:
        raise RuntimeError(f"Exactly one provisioned {name} executable is required below {directory}")
    matches[0].chmod(0o755)
    return matches[0]


def run(args):
    root = Path(__file__).resolve().parents[2]
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=True)
    runtime = root/".tools/monitoring-run"/secrets.token_hex(6)
    runtime.mkdir(parents=True)
    assets = args.binaries_dir.absolute()
    commands = {name: binary(assets/name, name) for name in ("prometheus", "grafana", "tempo", "alertmanager")}
    configs = runtime/"config"
    configs.mkdir()
    monitor = root/"infra/monitoring"
    prometheus = yaml.safe_load((monitor/"prometheus.yaml").read_text())
    prometheus["rule_files"] = [str(monitor/"rules.yaml")]
    prometheus["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"] = ["127.0.0.1:19093"]
    prometheus["scrape_configs"][0]["static_configs"][0]["targets"] = ["127.0.0.1:18180"]
    prometheus["scrape_configs"][0]["authorization"]["credentials_file"] = str(monitor/"fixtures/scrape-token")
    (configs/"prometheus.yaml").write_text(yaml.safe_dump(prometheus))
    alertmanager = yaml.safe_load((monitor/"alertmanager.yaml").read_text())
    alertmanager["receivers"][0]["webhook_configs"][0]["url"] = "http://127.0.0.1:18089/alerts"
    (configs/"alertmanager.yaml").write_text(yaml.safe_dump(alertmanager))
    tempo = yaml.safe_load((monitor/"tempo.yaml").read_text())
    tempo["server"]["http_listen_port"] = 13200
    tempo["distributor"]["receivers"]["otlp"]["protocols"]["http"]["endpoint"] = "127.0.0.1:14318"
    tempo["storage"]["trace"]["wal"]["path"] = str(runtime/"tempo/wal")
    tempo["storage"]["trace"]["local"]["path"] = str(runtime/"tempo/blocks")
    tempo["usage_report"] = {"reporting_enabled": False}
    (configs/"tempo.yaml").write_text(yaml.safe_dump(tempo))
    provisioning = configs/"provisioning"
    shutil.copytree(monitor/"provisioning", provisioning)
    sources_path = provisioning/"datasources/sources.yaml"
    sources = yaml.safe_load(sources_path.read_text())
    sources["datasources"][0]["url"] = "http://127.0.0.1:19090"
    sources["datasources"][1]["url"] = "http://127.0.0.1:13200"
    sources_path.write_text(yaml.safe_dump(sources))
    dashboard_path = provisioning/"dashboards/dashboards.yaml"
    dashboard = yaml.safe_load(dashboard_path.read_text())
    dashboard["providers"][0]["options"]["path"] = str(monitor/"dashboards")
    dashboard_path.write_text(yaml.safe_dump(dashboard))
    password = secrets.token_urlsafe(24)
    grafana_home = commands["grafana"].parent.parent
    (configs/"grafana.ini").write_text(f"""[server]
http_addr = 127.0.0.1
http_port = 13001
root_url = http://127.0.0.1:13001/
[paths]
data = {runtime/'grafana-data'}
logs = {runtime/'grafana-logs'}
plugins = {runtime/'grafana-plugins'}
provisioning = {provisioning}
[security]
admin_user = admin
admin_password = {password}
secret_key = {secrets.token_hex(32)}
disable_gravatar = true
[analytics]
reporting_enabled = false
check_for_updates = false
check_for_plugin_updates = false
[users]
allow_sign_up = false
[plugins]
preinstall_disabled = true
[unified_alerting]
enabled = false
""")
    for evidence in ("alerts.jsonl", "traffic.jsonl"):
        (output/evidence).write_text("")
    env = {key: value for key, value in os.environ.items() if key in {"PATH", "LD_LIBRARY_PATH", "SSL_CERT_FILE", "TZ"}}
    env.update({"PYTHONPATH": str(root)+os.pathsep+str(root/"packages"),
                "PAIS_PROFILE": "fixture", "PAIS_RELEASE": "native-monitoring",
                "PAIS_OTLP_ENDPOINT": "http://127.0.0.1:14318/v1/traces",
                "GOMAXPROCS": "1", "GOMEMLIMIT": "160MiB"})
    supervisor = Supervisor(output, env, args.max_rss_mib)
    start = time.perf_counter()
    report = {"project": "P05", "profile": "native-observability-fixture-model",
              "started_at": datetime.now(UTC).isoformat(),
              "status": "running", "model_quality": "not evaluated", "price_basis": "simulation",
              "sampling_rate": 1.0, "trace_retention_hours": 24, "metrics_retention_hours": 48,
              "rss_budget_bytes": supervisor.max_rss_bytes,
              "rss_measurement": "sampled sum of supervised process-tree VmRSS; host PID/NSpid mapping; shared pages may be counted more than once"}
    (output/"report.json").write_text(json.dumps(report, indent=2))
    try:
        supervisor.start("alert-sink", [sys.executable, str(monitor/"alert_sink.py"), "--port", "18089", "--output", str(output/"alerts.jsonl")])
        supervisor.start("tempo", [str(commands["tempo"]), "-config.file="+str(configs/"tempo.yaml")])
        supervisor.start("alertmanager", [str(commands["alertmanager"]), "--config.file="+str(configs/"alertmanager.yaml"),
                         "--web.listen-address=127.0.0.1:19093", "--cluster.listen-address=",
                         "--storage.path="+str(runtime/"alertmanager")])
        supervisor.start("prometheus", [str(commands["prometheus"]), "--config.file="+str(configs/"prometheus.yaml"),
                         "--web.listen-address=127.0.0.1:19090", "--storage.tsdb.path="+str(runtime/"prometheus"),
                         "--storage.tsdb.retention.time=48h"])
        supervisor.start("grafana", [str(commands["grafana"]), "server", "--homepath", str(grafana_home), "--config", str(configs/"grafana.ini")],
                         env={"GOMEMLIMIT": "256MiB"})
        db = runtime/"application.sqlite"
        supervisor.start("api", [sys.executable, str(Path(__file__).with_name("native_app.py")), "--db", str(db), "--output", str(output)], cwd=root)
        with httpx.Client(timeout=15, trust_env=False) as client:
            for name, url in {"api": "http://127.0.0.1:18180/api/health", "prometheus": "http://127.0.0.1:19090/-/ready",
                              "tempo": "http://127.0.0.1:13200/ready", "alertmanager": "http://127.0.0.1:19093/-/ready",
                              "grafana": "http://127.0.0.1:13001/api/health"}.items():
                ready = False
                for _ in range(60):
                    if supervisor.processes[name].poll() is not None:
                        raise RuntimeError(f"{name} exited during startup; inspect {name}.log")
                    try:
                        if client.get(url).status_code == 200:
                            ready = True
                            break
                    except httpx.HTTPError:
                        pass
                    supervisor.pause(1)
                if not ready:
                    raise RuntimeError(f"{name} did not become ready")
                print(json.dumps({"ready": name}), flush=True)
            headers = {"Authorization": "Bearer fixture-admin"}
            def chat(fail=False):
                before = time.perf_counter()
                result = client.post("http://127.0.0.1:18180/api/chat/stream", headers=headers | (
                    {"x-pais-test-fault": "fail-once"} if fail else {}),
                    json={"message_id": secrets.token_hex(12), "question": "What is the retry timeout?"})
                row = {"seconds": time.perf_counter()-before, "http_status": result.status_code,
                       "stream_error": '"type":"error"' in result.text, "injected_failure": fail}
                with (output/"traffic.jsonl").open("a") as stream:
                    stream.write(json.dumps(row)+"\n")
                supervisor.guard()
                return row
            chat(True)
            chat()
            supervisor.pause(7)
            for _ in range(19):
                chat(True)
            slow = [chat() for _ in range(5)]
            report["slow_request_seconds"] = max(r["seconds"] for r in slow)
            job = client.post("http://127.0.0.1:18180/api/observability/drill-job", headers=headers)
            job.raise_for_status()
            job_info = job.json()
            worker = supervisor.start("worker", [sys.executable, str(Path(__file__).with_name("native_app.py")),
                                      "--db", str(db), "--output", str(output), "--worker-job", job_info["job_id"]], cwd=root)
            worker_deadline = time.monotonic()+30
            while worker.poll() is None and time.monotonic() < worker_deadline:
                supervisor.pause(0.1)
            if worker.poll() is None:
                raise RuntimeError("Durable trace worker exceeded its 30 second deadline")
            if worker.returncode:
                raise RuntimeError("Durable trace worker failed")
            report["job"] = job_info
            report["worker_status"] = json.loads((output/"worker-result.json").read_text())["status"]
            alert_states = set()
            trace_seen = False
            for second in range(195):
                client.get("http://127.0.0.1:18180/api/health")
                if second % 5 == 0:
                    alerts = client.get("http://127.0.0.1:18089/alerts").json()
                    for notification in alerts:
                        for alert in notification["alerts"]:
                            alert_states.add((alert["labels"].get("alertname"), alert["status"]))
                    trace_response = client.get("http://127.0.0.1:13200/api/traces/"+job_info["trace_id"], headers={"Accept": "application/json"})
                    if trace_response.status_code == 200 and "job.execute" in trace_response.text and "job.publish" in trace_response.text:
                        (output/"distributed-trace.json").write_text(trace_response.text)
                        trace_seen = True
                    if second % 15 == 0:
                        print(json.dumps({"elapsed_recovery_seconds": second, "alert_states": sorted(alert_states),
                                          "distributed_trace": trace_seen}), flush=True)
                    if {("PaisErrorSpike", "firing"), ("PaisErrorSpike", "resolved"),
                        ("PaisSlowProtectedDelivery", "firing"), ("PaisSlowProtectedDelivery", "resolved")}.issubset(alert_states) and trace_seen:
                        break
                supervisor.pause(1)
            metric_text = client.get("http://127.0.0.1:18180/api/metrics", headers=headers).text
            (output/"metrics.prom").write_text(metric_text)
            ledger = json.loads((output/"ledger.json").read_text())
            query = client.get("http://127.0.0.1:19090/api/v1/query", params={"query": 'sum(pais_ledger_cost_microusd{kind="reported",release="native-monitoring"})'})
            query.raise_for_status()
            (output/"ledger-query.json").write_text(json.dumps(query.json(), indent=2))
            rows = query.json()["data"]["result"]
            measured = float(rows[0]["value"][1]) if rows else None
            dashboard_response = client.get("http://127.0.0.1:13001/api/dashboards/uid/pais-operations", auth=("admin", password))
            dashboard_response.raise_for_status()
            (output/"grafana-dashboard.json").write_text(json.dumps(dashboard_response.json(), indent=2))
            report.update({"alert_states": sorted(alert_states), "distributed_trace_observed": trace_seen,
                           "ledger_reported_microusd": ledger["reported"], "prometheus_reported_microusd": measured,
                           "ledger_metric_matches": ledger["reported"] == measured,
                           "grafana_provisioned_panels": len(dashboard_response.json()["dashboard"]["panels"]),
                           "model_quality": "fixture outputs excluded from quality claims"})
            chromium = root/"artifacts/ui/browser-runtime/chromium"
            if args.chromium:
                chromium = args.chromium.absolute()
            if chromium.is_file():
                config = {"url": "http://127.0.0.1:13001", "password": password,
                          "chromiumPath": str(chromium), "output": str(output/"grafana-dashboard.png")}
                shot = supervisor.start("browser", ["node", str(Path(__file__).with_name("screenshot.mjs"))],
                                        input_text=json.dumps(config), cwd=root)
                for _ in range(240):
                    if shot.poll() is not None:
                        break
                    supervisor.pause(0.25)
                report["screenshot"] = "captured" if shot.returncode == 0 else "failed"
            else:
                report["screenshot"] = "not_run: browser binary unavailable"
            expected = {("PaisErrorSpike", "firing"), ("PaisErrorSpike", "resolved"),
                        ("PaisSlowProtectedDelivery", "firing"), ("PaisSlowProtectedDelivery", "resolved")}
            report["status"] = "verified_scope" if (expected.issubset(alert_states) and trace_seen
                               and report["ledger_metric_matches"] and report["worker_status"] == "succeeded"
                               and supervisor.peak_rss_bytes > 0
                               and report["screenshot"] != "failed") else "failed"
    except Exception as exc:  # noqa: BLE001 -- supervisor must record failures and stop all children.
        report["status"] = "failed"
        report["error"] = str(exc)
    finally:
        report["duration_seconds"] = time.perf_counter()-start
        report["peak_service_rss_bytes"] = supervisor.peak_rss_bytes
        supervisor.stop()
        (output/"report.json").write_text(json.dumps(report, indent=2))
        # Runtime state contains a throwaway local Grafana password; never package it as evidence.
        shutil.rmtree(runtime)
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["status"] == "verified_scope" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binaries-dir", type=Path, default=Path(".tools/monitoring"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/p05-native"))
    parser.add_argument("--chromium", type=Path)
    parser.add_argument("--max-rss-mib", type=int, default=1024,
                        help="Sampled combined service/browser RSS cap; 1024 by default, maximum 1536")
    arguments = parser.parse_args()
    if not 256 <= arguments.max_rss_mib <= 1536:
        parser.error("--max-rss-mib must be between 256 and 1536")
    raise SystemExit(run(arguments))
