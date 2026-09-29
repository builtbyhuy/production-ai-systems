"""Render reviewable manifests only from matching release evidence; never apply them."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

import yaml
from pais.operations import validate_release_bundle, validate_release_evaluation


def render(
    bundle: dict,
    evaluation: dict,
    *,
    hostname: str,
    storage_class: str,
    gitops_url: str,
    gitops_revision: str,
    output: Path,
) -> list[str]:
    validate_release_bundle(bundle)
    verdict = validate_release_evaluation(evaluation, bundle["git_commit"])
    if verdict["report_sha256"] != bundle["evaluation_sha256"]:
        raise ValueError("Bundle and evaluation hashes differ")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,250}", hostname):
        raise ValueError("Invalid staging hostname")
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,62}", storage_class):
        raise ValueError("Invalid node-local POSIX storage class")
    if not re.fullmatch(
        r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", gitops_url
    ):
        raise ValueError("Supply the actual authorized GitHub GitOps repository URL")
    if not re.fullmatch(r"[a-f0-9]{40}", gitops_revision):
        raise ValueError("GitOps revision must be a reviewed full Git commit")
    replacements = {
        "APP_IMAGE": bundle["image"],
        "RELEASE_COMMIT": bundle["git_commit"],
        "STATE_STORAGE_CLASS": storage_class,
        "HOSTNAME": hostname,
        "GITOPS_URL": gitops_url,
        "GITOPS_REVISION": gitops_revision,
    }
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in ("app-rollout", "argocd-application"):
        content = Path(f"infra/kubernetes/{name}.template.yaml").read_text()
        for key, value in replacements.items():
            content = content.replace(f"@@{key}@@", value)
        if "@@" in content:
            raise ValueError("Unresolved deployment placeholder")
        for document in yaml.safe_load_all(content):
            if not isinstance(document, dict) or not document.get("kind"):
                raise ValueError("Malformed Kubernetes document")
        path = output / f"{name}.yaml"
        path.write_text(content)
        paths.append(str(path))
    shutil.copy2("infra/kubernetes/analysis-template.yaml", output / "analysis-template.yaml")
    (output / "release-bundle.json").write_text(json.dumps(bundle, indent=2) + "\n")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--hostname", required=True)
    parser.add_argument("--storage-class", required=True)
    parser.add_argument("--gitops-url", required=True)
    parser.add_argument("--gitops-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        paths = render(
            json.loads(args.bundle.read_text()),
            json.loads(args.evaluation.read_text()),
            hostname=args.hostname,
            storage_class=args.storage_class,
            gitops_url=args.gitops_url,
            gitops_revision=args.gitops_revision,
            output=args.output,
        )
        print(json.dumps({"rendered": paths, "applied": False, "cluster_verified": False}))
        return 0
    except (ValueError, OSError, yaml.YAMLError) as exc:
        print(json.dumps({"accepted": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
