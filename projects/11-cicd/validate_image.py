"""Validate an operator-provided immutable image reference without pulling it."""

import re
import sys


def validate_image(value: str) -> str:
    if not re.fullmatch(r"[^\s@]+@sha256:[a-f0-9]{64}", value):
        raise ValueError("Image must be an explicit repository@sha256:<64 hex> reference")
    return value


if __name__ == "__main__":
    try:
        validate_image(sys.argv[1] if len(sys.argv) == 2 else "")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
