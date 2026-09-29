"""Render the versioned acceptance ledger without inventing absent evidence."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    data = json.loads((ROOT / "docs/PROJECT_LEDGER.json").read_text())
    lines = [
        "# Eighteen-project acceptance ledger",
        "",
        data["scope"],
        "",
        "Implementation and evidence are separate. `implemented` means the declared code and",
        "configuration exist; it does not mean the full project is accepted or deployed.",
        "Criteria use PASS, FAIL or NOT RUN. A project with a failed or unexecuted required",
        "criterion remains incomplete. Fixture output never establishes actual model quality.",
        "",
        "See [VERIFICATION.md](VERIFICATION.md) for integrated run identities, limitations and",
        "the final evidence index. Earlier observations retain their original dirty/unborn Git",
        "metadata. They are not retroactively relabeled as clean-commit runs.",
        "",
        "| Project | Implementation | Evidence exercised | Acceptance | Remaining requirement |",
        "|---|---|---|---|---|",
    ]
    for p in data["projects"]:
        lines.append(
            f"| [{p['id']} · {p['name']}](../{p['readme']}) | {p['implementation']} | "
            f"{p['evidence_level']} | {p['overall_acceptance']} | {p['blocker']} |"
        )
    for p in data["projects"]:
        lines += ["", f"## {p['id']} — {p['name']}", "", p["implementation_scope"], ""]
        for c in p["criteria"]:
            links = ", ".join(f"[{Path(f).name}](../{f})" for f in c.get("evidence", []))
            lines.append(f"- **{c['status'].upper().replace('_', ' ')} — {c['criterion']}**: {c['result']}" + (f" Evidence: {links}." if links else ""))
        lines += ["", f"**Next action:** {p['next_action']}", ""]
        if p.get("next_command"):
            lines += ["```bash", p["next_command"], "```", ""]
    (ROOT / "docs/PROJECT_LEDGER.md").write_text("\n".join(lines).rstrip() + "\n")


if __name__ == "__main__":
    main()
