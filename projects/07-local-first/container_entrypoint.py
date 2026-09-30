"""Read an operator-mounted credential file and start the local API.

The image owns dependencies and the API. This small launcher keeps credential JSON
out of Compose interpolation and removes inherited proxy configuration at runtime.
It never downloads, provisions models, changes host networking, or enables fixture auth.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def runtime_environment() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if "proxy" not in key.casefold()}
    source = Path(env.get("PAIS_AUTH_TOKENS_FILE", "/run/secrets/pais_auth_tokens"))
    if source.stat().st_size > 1024 * 1024:
        raise ValueError("Credential file exceeds the local deployment limit")
    credentials = json.loads(source.read_text())
    if not isinstance(credentials, dict) or not credentials:
        raise ValueError("Credential file must contain a nonempty trusted token mapping")
    for token, principal in credentials.items():
        if not isinstance(token, str) or len(token) < 24 or not isinstance(principal, dict):
            raise ValueError("Use independent opaque credentials of at least 24 characters")
        if not all(isinstance(principal.get(key), str) and principal[key]
                   for key in ("subject", "tenant_id")):
            raise ValueError("Each credential needs a trusted subject and tenant")
        roles = principal.get("roles")
        if not isinstance(roles, list) or not roles or not set(roles) <= {"reader", "writer", "admin"}:
            raise ValueError("Credential roles must be explicit reader/writer/admin values")
    env.update(PAIS_AUTH_TOKENS=json.dumps(credentials), PAIS_PROFILE="local",
               PAIS_ALLOW_FIXTURE_AUTH="0", HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
               HF_HUB_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1")
    return env


def main() -> int:
    try:
        env = runtime_environment()
    except (OSError, TypeError, ValueError):
        print("Local API blocked: supply a valid operator-mounted credential file.", file=sys.stderr)
        return 2
    os.execvpe(sys.executable, [sys.executable, "-m", "uvicorn", "services.api.app:app",
                              "--host", "0.0.0.0", "--port", "8000", "--workers", "1",
                              "--timeout-graceful-shutdown", "90"], env)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
