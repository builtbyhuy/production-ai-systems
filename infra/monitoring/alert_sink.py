"""Local test-only Alertmanager destination. Stores firing AND resolved notifications."""
import argparse
import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8089)
    parser.add_argument("--output", default="var/alerts.jsonl")
    args = parser.parse_args()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path != "/alerts":
                self.send_error(404)
                return
            with lock:
                # Bounded tail prevents an unbounded response or a race with an append.
                rows = target.read_text().splitlines()[-100:] if target.exists() else []
            payload = ("["+",".join(rows)+"]").encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            if self.path != "/alerts":
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("body limit")
                payload = json.loads(self.rfile.read(length))
                selected = {"received_at": datetime.now(UTC).isoformat(),
                            "status": payload["status"], "alerts": [
                                {"status": a["status"], "labels": a.get("labels", {}),
                                 "startsAt": a.get("startsAt"), "endsAt": a.get("endsAt")}
                                for a in payload["alerts"]]}
            except (ValueError, KeyError, TypeError):
                self.send_error(400)
                return
            with lock, target.open("a") as stream:
                stream.write(json.dumps(selected)+"\n")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
