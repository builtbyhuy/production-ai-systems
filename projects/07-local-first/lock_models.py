"""Record already provisioned local models. This command never downloads a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

import httpx

PINNED_RERANKER_REVISION = "233902d25c440f23af6f7d6e94d2946bac0bee0a"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--generation", default="qwen2.5:1.5b")
    parser.add_argument("--embedding", default="all-minilm:22m")
    parser.add_argument("--dimensions", type=int, default=384)
    parser.add_argument("--reranker-dir", type=Path, required=True)
    parser.add_argument("--runtime-reranker-path", type=Path,
                        help="Optional absolute path for this same model directory inside a container")
    parser.add_argument("--reranker-repository", default="cross-encoder/ms-marco-MiniLM-L6-v2")
    parser.add_argument("--reranker-revision", default=PINNED_RERANKER_REVISION)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.runtime_reranker_path is not None and not args.runtime_reranker_path.is_absolute():
        parser.error("The container/runtime reranker path must be absolute")
    parsed = urlparse(args.ollama_url)
    if (parsed.scheme != "http" or parsed.hostname not in
            {"127.0.0.1", "localhost", "::1", "ollama", "host.docker.internal"}
            or parsed.username or parsed.password):
        parser.error("Only a local Ollama service can be locked")
    model_dir = args.reranker_dir.resolve()
    if not model_dir.is_dir():
        parser.error("The reranker directory must already exist")
    manifest = {}
    for path in sorted(model_dir.rglob("*")):
        if path.is_file() and path.suffix in {".json", ".txt", ".safetensors"} and ".cache" not in path.parts:
            if not path.resolve().is_relative_to(model_dir):
                parser.error("Use hf download --local-dir; external symlinks are not a self-contained model")
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            manifest[str(path.relative_to(model_dir))] = digest.hexdigest()
    if "config.json" not in manifest or not any(name.endswith(".safetensors") for name in manifest):
        parser.error("Reranker needs config.json and safetensors weights")
    try:
        with httpx.Client(timeout=10.0, trust_env=False) as client:
            response = client.get(args.ollama_url.rstrip("/") + "/api/tags")
            response.raise_for_status()
        models = {item["name"]: item for item in response.json()["models"]}
        generation = models[args.generation]
        embedding = models[args.embedding]
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}))
        return 2
    lock = {
        "schema_version": 1,
        "generation": {"name": args.generation, "digest": generation["digest"]},
        "embedding": {"name": args.embedding, "digest": embedding["digest"], "dimensions": args.dimensions},
        "reranker": {"repository": args.reranker_repository, "revision": args.reranker_revision,
                     "path": str(args.runtime_reranker_path or model_dir), "files": manifest},
        "provisioning_note": "Model revision selected before download; file hashes bind this exact local copy.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(lock, indent=2) + "\n")
    print(json.dumps({"status": "locked", "path": str(args.output.resolve()), "reranker_files": len(manifest),
                      "generation_digest": generation["digest"], "embedding_digest": embedding["digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
