"""Explicit, bounded web research. No network calls occur without --authorize-web."""
import argparse
import json
from pathlib import Path

from pais.contracts import Principal
from pais.research import ResearchService, WebResearchConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--subject", default="local-web-operator")
    parser.add_argument("--profile", choices=["fixture", "local"], default="local")
    parser.add_argument("--authorize-web", action="store_true")
    parser.add_argument("--state", type=Path, default=Path("artifacts/web-research.db"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/web-research.json"))
    args = parser.parse_args()
    if not args.authorize_web:
        parser.error("--authorize-web is required before any source acquisition")
    config = WebResearchConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
    # Standalone local operator command. This is not an HTTP authentication endpoint.
    principal = Principal(subject=args.subject, tenant_id=args.tenant, roles=["admin"])
    result = ResearchService(args.state, []).run_web(
        principal, args.question, config, authorized=True, inference_profile=args.profile,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "needs_approval" else 1


if __name__ == "__main__":
    raise SystemExit(main())
