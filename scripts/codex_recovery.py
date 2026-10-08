#!/usr/bin/env python3
"""Request an idempotent Codex app-server daemon start for one fleet host."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Callable

from codex_control import _codex_path, _route_is_valid

REMOTE_START_COMMAND = r'''for codex_path in "$HOME/.local/bin/codex" "$HOME/.codex/packages/app-server-daemon/current/bin/codex" "$HOME/.codex/packages/standalone/current/bin/codex"; do
  if [ -x "$codex_path" ]; then
    exec "$codex_path" app-server daemon start >/dev/null 2>&1
  fi
done
exit 127'''


class RecoveryError(RuntimeError):
    """Raised when a safe, fixed Codex daemon start cannot be requested."""

    pass


def recover_host(host: Any, run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run) -> str:
    """Request daemon start on one validated host and return the route used."""
    if not isinstance(host, dict):
        raise RecoveryError("Invalid recovery target")

    if host.get("local") is True:
        try:
            result = run([_codex_path(), "app-server", "daemon", "start"], capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RecoveryError("The local Codex daemon start request did not complete") from error
        if result.returncode == 0:
            return "local"
        raise RecoveryError("The local Codex daemon did not start; check its startup status")

    routes = host.get("sshRoutes")
    if not isinstance(routes, list):
        raise RecoveryError("No SSH recovery routes are configured")

    attempted: list[str] = []
    for route in routes:
        if not _route_is_valid(route):
            continue
        target = route["target"]
        alias = route["hostKeyAlias"]
        transport = route["transport"]
        attempted.append(transport)
        try:
            result = run(
                [
                    "ssh", "-T", "-q",
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=5",
                    "-o", "ServerAliveInterval=5",
                    "-o", "ServerAliveCountMax=2",
                    "-o", "StrictHostKeyChecking=yes",
                    "-o", f"HostKeyAlias={alias}",
                    target,
                    REMOTE_START_COMMAND,
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RecoveryError(f"Codex daemon start did not complete via {transport}") from error

        if result.returncode == 0:
            return transport
        if result.returncode == 255:
            continue
        raise RecoveryError(f"Codex daemon start failed via {transport}; check the host's startup status")

    if not attempted:
        raise RecoveryError("No valid SSH recovery routes are configured")
    raise RecoveryError("Could not reach the host over its configured SSH routes")


def main() -> int:
    """Read one recovery request from stdin and emit a content-free result."""
    try:
        request = json.loads(sys.stdin.readline())
        if not isinstance(request, dict):
            raise RecoveryError("Invalid recovery request")
        transport = recover_host(request.get("host"))
        print(json.dumps({
            "type": "recovery",
            "status": "start_requested",
            "transport": transport,
            "message": f"Codex daemon start requested via {transport}.",
        }))
        return 0
    except Exception:
        print(json.dumps({
            "type": "error",
            "message": "Could not start the selected host's Codex daemon. Check its route and startup status.",
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
