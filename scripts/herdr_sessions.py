#!/usr/bin/env python3
"""Allowlisted Herdr named-session lifecycle bridge for the local dashboard."""

from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any

SESSION_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class HerdrControlError(RuntimeError):
    """Raised when an allowlisted Herdr session request cannot be completed."""

    pass


def _herdr_path() -> str:
    configured = os.environ.get("HERDR_CLI_PATH")
    home = pathlib.Path.home()
    candidates = [configured] if configured else []
    candidates.extend([
        str(home / ".local/bin/herdr"),
        str(home / ".nix-profile/bin/herdr"),
        "/opt/homebrew/bin/herdr",
        "/usr/local/bin/herdr",
    ])
    for candidate in candidates:
        if candidate and pathlib.Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    discovered = shutil.which("herdr")
    if discovered:
        return discovered
    raise HerdrControlError("Herdr CLI was not found on the dashboard host")


def _valid_route(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    target = value.get("target")
    alias = value.get("hostKeyAlias")
    return (
        value.get("transport") in {"zerotier", "tailscale"}
        and isinstance(target, str)
        and len(target) <= 255
        and not target.startswith("-")
        and target.isascii()
        and all(char.isalnum() or char in "@._:-" for char in target)
        and isinstance(alias, str)
        and len(alias) <= 120
        and alias.isascii()
        and all(char.isalnum() or char in "._:-" for char in alias)
    )


def _run_local(args: list[str], timeout: float = 8) -> subprocess.CompletedProcess[str]:
    try:
        env = {**os.environ, "HERDR_ENV": "1"}
        return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False, env=env)
    except Exception as error:
        raise HerdrControlError("Herdr command could not be started") from error


def _remote_command(action: str, name: str | None = None) -> str:
    candidates = '"$HOME/.local/bin/herdr" "$HOME/.nix-profile/bin/herdr" "/opt/homebrew/bin/herdr"'
    opt_in = "export HERDR_ENV=1\n"
    if action == "list":
        args = "session list --json"
    elif action == "stop" and name:
        args = f"session stop {shlex.quote(name)} --json"
    elif action == "start" and name:
        return f'''{opt_in}for herdr_path in {candidates}; do
  if [ -x "$herdr_path" ]; then
    nohup "$herdr_path" --session {shlex.quote(name)} server </dev/null >/dev/null 2>&1 &
    exit 0
  fi
done
exit 127'''
    else:
        raise HerdrControlError("Invalid Herdr operation")
    return f'''{opt_in}for herdr_path in {candidates}; do
  if [ -x "$herdr_path" ]; then
    exec "$herdr_path" {args}
  fi
done
exit 127'''


def _run_route(route: dict[str, str], action: str, name: str | None = None, timeout: float = 8) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run([
            "ssh", "-T", "-q",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"HostKeyAlias={route['hostKeyAlias']}",
            "--", route["target"], _remote_command(action, name),
        ], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False)
    except Exception as error:
        raise HerdrControlError("Herdr SSH request failed") from error


def _parse_sessions(stdout: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise HerdrControlError("Herdr returned invalid session metadata") from error
    raw_sessions = value.get("sessions") if isinstance(value, dict) else None
    if not isinstance(raw_sessions, list):
        raise HerdrControlError("Herdr session list was unavailable")
    sessions = []
    for item in raw_sessions:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"]
        sessions.append({
            "name": name[:80],
            "running": item.get("running") is True,
            "default": item.get("default") is True,
        })
    return sessions


def _run_list(host: dict[str, Any], route: dict[str, str] | None) -> list[dict[str, Any]]:
    result = _run_local([_herdr_path(), "session", "list", "--json"]) if host.get("local") is True else _run_route(route or {}, "list")
    if result.returncode != 0:
        raise HerdrControlError("Herdr session list failed")
    return _parse_sessions(result.stdout)


def _select_connection(host: dict[str, Any]) -> tuple[dict[str, str] | None, list[dict[str, Any]]]:
    if host.get("local") is True:
        return None, _run_list(host, None)
    routes = host.get("sshRoutes")
    if not isinstance(routes, list) or not routes or not all(_valid_route(route) for route in routes):
        raise HerdrControlError("No safe SSH routes are configured for this host")
    failures = []
    for route in routes:
        try:
            return route, _run_list(host, route)
        except HerdrControlError:
            failures.append(route["transport"])
    raise HerdrControlError("Herdr is unavailable via " + ", ".join(failures))


def _mutate(host: dict[str, Any], route: dict[str, str] | None, action: str, name: str) -> None:
    if host.get("local") is True:
        if action == "stop":
            result = _run_local([_herdr_path(), "session", "stop", name, "--json"], timeout=12)
        else:
            try:
                subprocess.Popen(
                    [_herdr_path(), "--session", name, "server"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={**os.environ, "HERDR_ENV": "1"},
                    start_new_session=True,
                    close_fds=True,
                )
            except Exception as error:
                raise HerdrControlError("Herdr session server could not be started") from error
            return
    else:
        result = _run_route(route or {}, action, name, timeout=12)
    if result.returncode != 0:
        # A connection can close after a start/stop was applied. Do not retry a
        # mutation on the fallback route; the caller reconciles with list.
        raise HerdrControlError("Herdr session action did not return successfully")


def run(request: dict[str, Any]) -> dict[str, Any]:
    """List or mutate one validated named Herdr session and return its status."""
    host = request.get("host")
    action = request.get("action")
    name = request.get("name")
    if not isinstance(host, dict) or action not in {"list", "start", "stop"}:
        raise HerdrControlError("Invalid Herdr control request")
    if action != "list":
        if not isinstance(name, str) or not SESSION_NAME.fullmatch(name) or name == "default":
            raise HerdrControlError("Use a named session from a–z, 0–9, _ or -; the default session is protected")

    route, sessions = _select_connection(host)
    transport = "local" if route is None else route["transport"]
    if action == "list":
        return {"sessions": sessions, "transport": transport}

    existing = next((session for session in sessions if session["name"] == name), None)
    if action == "start" and existing and existing["running"]:
        return {"action": action, "name": name, "state": "running", "alreadyRunning": True, "transport": transport}
    if action == "stop" and (existing is None or not existing["running"]):
        return {"action": action, "name": name, "state": "stopped", "alreadyStopped": True, "transport": transport}

    # Each start/stop is sent only once over the route that passed the
    # read-only list check. This avoids duplicate work after an uncertain SSH
    # disconnect; final state is reconciled with a fresh list response.
    _mutate(host, route, action, name)
    deadline = time.monotonic() + (10 if action == "start" else 8)
    observed = existing
    while time.monotonic() < deadline:
        try:
            current = _run_list(host, route)
            observed = next((session for session in current if session["name"] == name), None)
            if (action == "start" and observed and observed["running"]) or (action == "stop" and (observed is None or not observed["running"])):
                return {"action": action, "name": name, "state": "running" if action == "start" else "stopped", "alreadyRunning": False, "alreadyStopped": False, "transport": transport}
        except HerdrControlError:
            pass
        time.sleep(0.35)

    state = "starting" if action == "start" else "stopping"
    return {"action": action, "name": name, "state": state, "alreadyRunning": False, "alreadyStopped": False, "transport": transport}


def main() -> int:
    """Read one JSON request from stdin and emit the bounded Herdr response."""
    try:
        request = json.loads(sys.stdin.readline())
        if not isinstance(request, dict):
            raise HerdrControlError("Invalid Herdr control request")
        print(json.dumps({"ok": True, **run(request)}, separators=(",", ":")), flush=True)
        return 0
    except Exception:
        print(json.dumps({"ok": False, "error": "Herdr session operation failed. Check the selected host and Herdr status."}, separators=(",", ":")), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
