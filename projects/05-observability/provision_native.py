"""Download pinned official Linux binaries through the configured network route.

Archives are checksum verified before safe extraction. No cloud service or API spend.
"""
import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path

import httpx

ASSETS = {
    "prometheus": {
        "version": "3.4.2",
        "url": "https://github.com/prometheus/prometheus/releases/download/v3.4.2/prometheus-3.4.2.linux-amd64.tar.gz",
        "checksums": "https://github.com/prometheus/prometheus/releases/download/v3.4.2/sha256sums.txt",
    },
    "grafana": {
        "version": "12.0.2",
        "url": "https://dl.grafana.com/oss/release/grafana-12.0.2.linux-amd64.tar.gz",
        "checksums": "https://dl.grafana.com/oss/release/grafana-12.0.2.linux-amd64.tar.gz.sha256",
    },
    "tempo": {
        "version": "2.8.0",
        "url": "https://github.com/grafana/tempo/releases/download/v2.8.0/tempo_2.8.0_linux_amd64.tar.gz",
        "checksums": "https://github.com/grafana/tempo/releases/download/v2.8.0/SHA256SUMS",
    },
    "alertmanager": {
        "version": "0.28.1",
        "url": "https://github.com/prometheus/alertmanager/releases/download/v0.28.1/alertmanager-0.28.1.linux-amd64.tar.gz",
        "checksums": "https://github.com/prometheus/alertmanager/releases/download/v0.28.1/sha256sums.txt",
    },
}


def provision(target: Path):
    target.mkdir(parents=True, exist_ok=True)
    total = 0
    manifest = {}
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for name, spec in ASSETS.items():
            basename = spec["url"].rsplit("/", 1)[-1]
            checksum_response = client.get(spec["checksums"])
            checksum_response.raise_for_status()
            lines = checksum_response.text.strip().splitlines()
            matching = [line for line in lines if basename in line]
            if not matching and len(lines) == 1:
                matching = lines
            if len(matching) != 1 or not re.match(r"^[a-fA-F0-9]{64}(?:\s|$)", matching[0]):
                raise RuntimeError(f"Cannot verify official checksum for {name}")
            expected = matching[0].split()[0].lower()
            archive = target/basename
            if not archive.exists() or hashlib.file_digest(archive.open("rb"), "sha256").hexdigest() != expected:
                temporary = archive.with_suffix(".partial")
                size, digest = 0, hashlib.sha256()
                with client.stream("GET", spec["url"]) as response, temporary.open("wb") as stream:
                    response.raise_for_status()
                    for chunk in response.iter_bytes(1024*1024):
                        size += len(chunk)
                        if size > 300_000_000 or total+size > 1_000_000_000:
                            raise RuntimeError("Native artifact download budget exceeded")
                        digest.update(chunk)
                        stream.write(chunk)
                if digest.hexdigest() != expected:
                    temporary.unlink(missing_ok=True)
                    raise RuntimeError(f"Official checksum mismatch for {name}")
                temporary.replace(archive)
            total += archive.stat().st_size
            destination = target/name
            destination.mkdir(exist_ok=True)
            stamp = destination/"installed-sha256.txt"
            if not stamp.exists() or stamp.read_text() != expected:
                with tarfile.open(archive) as bundle:
                    if sum(member.size for member in bundle.getmembers()) > 1_500_000_000:
                        raise RuntimeError("Expanded binary distribution exceeds the disk budget")
                    bundle.extractall(destination, filter="data")
                stamp.write_text(expected)
            manifest[name] = spec | {"sha256": expected, "bytes": archive.stat().st_size,
                                     "directory": str(destination.absolute())}
            (target/"manifest.json").write_text(json.dumps(manifest, indent=2))
            print(json.dumps({"installed": name, "version": spec["version"],
                              "verified_sha256": expected, "bytes": archive.stat().st_size}), flush=True)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, default=Path(".tools/monitoring"))
    arguments = parser.parse_args()
    provision(arguments.target)
