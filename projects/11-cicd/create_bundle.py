"""Produce a digest-bound candidate bundle after a complete actual-model release gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from pais.operations import validate_release_bundle, validate_release_evaluation


def hash_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        content = path.read_bytes()
        digest.update(path.name.encode() + b"\0")
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--image-repository", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-lock", type=Path, default=os.environ.get("PAIS_MODEL_LOCK"))
    args = parser.parse_args()
    try:
        if args.model_lock is None:
            raise ValueError("A provisioned model lock is required")
        if not re.fullmatch(r"[a-z0-9][a-z0-9./_-]+", args.image_repository):
            raise ValueError("Image repository must be a lowercase registry path")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        verdict = validate_release_evaluation(json.loads(args.evaluation.read_text()), commit)
        metadata = json.loads(args.metadata.read_text())
        image_digest = metadata.get("containerimage.digest")
        compatibility = json.loads(Path("infra/release-compatibility.json").read_text())
        bundle = {
            "image": f"{args.image_repository}@{image_digest}",
            "git_commit": commit,
            "prompt_sha256": hash_files(
                [Path("packages/pais/rag.py"), Path("packages/pais/models.py")]
            ),
            "model_config_sha256": hash_files([args.model_lock]),
            "embedding_config_sha256": hash_files([args.model_lock]),
            "flag_schema_sha256": hash_files([Path("packages/pais/operations.py")]),
            "evaluation_sha256": verdict["report_sha256"],
            **{
                key: compatibility[key]
                for key in (
                    "state_schema",
                    "checkpoint_schema",
                    "minimum_readable_checkpoint_schema",
                    "migration_policy",
                )
            },
        }
        validate_release_bundle(bundle)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(bundle, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "candidate_bundle": str(args.output),
                    "image": bundle["image"],
                    "published": False,
                    "deployed": False,
                }
            )
        )
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"accepted": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
