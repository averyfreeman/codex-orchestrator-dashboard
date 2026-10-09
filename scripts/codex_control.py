#!/usr/bin/env python3
"""Dashboard-scoped Codex turn bridge over the host's app-server control socket.

The gateway passes a single JSON request on stdin. This process emits only
content-safe JSON events on stdout; prompts and terminal output are never
written to gateway logs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import secrets
import select
import shutil
import subprocess
import sys
import time
from typing import Any

class ControlError(RuntimeError):
    """Raised when the selected Codex app-server transport or RPC fails."""

    pass


def emit(value: dict[str, Any]) -> None:
    """Write one JSON event to stdout for the dashboard route to project."""
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _route_is_valid(route: Any) -> bool:
    if not isinstance(route, dict):
        return False
    target = route.get("target")
    alias = route.get("hostKeyAlias")
    return (
        route.get("transport") in {"zerotier", "tailscale"}
        and isinstance(target, str)
        and len(target) <= 255
        and not target.startswith("-")
        and all(char.isalnum() or char in "@._:-" for char in target)
        and isinstance(alias, str)
        and len(alias) <= 120
        and all(char.isalnum() or char in "._:-" for char in alias)
    )


def _codex_home_path(host: Any = None) -> pathlib.Path:
    raw = host.get("codexHome") if isinstance(host, dict) else None
    raw = raw or os.environ.get("CODEX_HOME") or "~/.codex"
    if not isinstance(raw, str) or not raw or any(char in raw for char in "\x00\r\n"):
        raise ControlError("Invalid CODEX_HOME inventory override")
    if raw == "~":
        return pathlib.Path.home().resolve()
    if raw.startswith("~/"):
        suffix = pathlib.PurePosixPath(raw[2:])
        if ".." in suffix.parts:
            raise ControlError("Invalid CODEX_HOME inventory override")
        return (pathlib.Path.home() / pathlib.Path(*suffix.parts)).resolve()
    candidate = pathlib.Path(raw)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise ControlError("Invalid CODEX_HOME inventory override")
    return candidate.resolve()


def _codex_path(host: Any = None) -> str:
    configured = os.environ.get("CODEX_CLI_PATH")
    candidates = [configured] if configured else []
    home = pathlib.Path.home()
    codex_home = _codex_home_path(host)
    candidates.extend([
        str(home / ".local/bin/codex"),
        str(codex_home / "packages/app-server-daemon/current/bin/codex"),
        str(codex_home / "packages/standalone/current/bin/codex"),
    ])
    for candidate in candidates:
        if candidate and pathlib.Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    discovered = shutil.which("codex")
    if discovered:
        return discovered
    raise ControlError("Codex CLI was not found on the dashboard host")


class AppServerConnection:
    """Synchronous JSON-RPC connection over the host-local app-server proxy."""

    def __init__(self, process: subprocess.Popen[bytes], home: str, transport: str):
        """Bind a proxy subprocess and initialize its framing and event state."""
        self.process = process
        self.home = home
        self.transport = transport
        self.buffer = bytearray()
        self.request_id = 0
        self.queued_messages: list[dict[str, Any]] = []
        self.network_access = True

    def _read_more(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Timed out waiting for app-server")
        fd = self.process.stdout.fileno() if self.process.stdout else -1
        readable, _, _ = select.select([fd], [], [], remaining)
        if not readable:
            raise TimeoutError("Timed out waiting for app-server")
        chunk = os.read(fd, 65536)
        if not chunk:
            raise EOFError("App-server transport closed")
        self.buffer.extend(chunk)

    def _read_until(self, token: bytes, timeout: float = 8) -> bytes:
        deadline = time.monotonic() + timeout
        while token not in self.buffer:
            self._read_more(deadline)
        end = self.buffer.index(token) + len(token)
        value = bytes(self.buffer[:end])
        del self.buffer[:end]
        return value

    def _read_exact(self, size: int, deadline: float) -> bytes:
        while len(self.buffer) < size:
            self._read_more(deadline)
        value = bytes(self.buffer[:size])
        del self.buffer[:size]
        return value

    def _write(self, value: bytes) -> None:
        if not self.process.stdin:
            raise ControlError("App-server transport is unavailable")
        self.process.stdin.write(value)
        self.process.stdin.flush()

    def _write_frame(self, data: bytes, opcode: int = 1) -> None:
        size = len(data)
        header = bytearray([0x80 | opcode])
        if size < 126:
            header.append(0x80 | size)
        elif size < 65536:
            header.extend([0x80 | 126])
            header.extend(size.to_bytes(2, "big"))
        else:
            header.extend([0x80 | 127])
            header.extend(size.to_bytes(8, "big"))
        mask = secrets.token_bytes(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self._write(bytes(header) + mask + masked)

    def _read_frame(self, deadline: float) -> tuple[bool, int, bytes]:
        first, second = self._read_exact(2, deadline)
        final = bool(first & 0x80)
        opcode = first & 0x0F
        size = second & 0x7F
        if size == 126:
            size = int.from_bytes(self._read_exact(2, deadline), "big")
        elif size == 127:
            size = int.from_bytes(self._read_exact(8, deadline), "big")
        if size > 2_000_000:
            raise ControlError("App-server event exceeded the size limit")
        mask = self._read_exact(4, deadline) if second & 0x80 else b""
        data = self._read_exact(size, deadline)
        if mask:
            data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        return final, opcode, data

    def _read_message(self, timeout: float = 30) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        fragment_opcode = 0
        fragments: list[bytes] = []
        while True:
            final, opcode, data = self._read_frame(deadline)
            if opcode == 9:
                self._write_frame(data, opcode=10)
                continue
            if opcode == 8:
                raise EOFError("App-server transport closed")
            if opcode == 0:
                fragments.append(data)
                if not final:
                    continue
                opcode = fragment_opcode
                data = b"".join(fragments)
                fragments.clear()
            elif not final:
                fragment_opcode = opcode
                fragments = [data]
                continue
            if opcode != 1:
                continue
            try:
                value = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ControlError("App-server sent an invalid JSON-RPC message") from error
            if isinstance(value, dict):
                return value

    def _websocket_handshake(self) -> None:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        self._write((
            "GET / HTTP/1.1\r\n"
            "Host: localhost\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii"))
        header = self._read_until(b"\r\n\r\n").decode("utf-8", errors="replace")
        lines = header.split("\r\n")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if not lines[0].startswith("HTTP/1.1 101") or headers.get("sec-websocket-accept") != expected:
            raise ControlError("App-server WebSocket handshake failed")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        """Send a JSON-RPC notification that does not expect a response."""
        self._write_frame(json.dumps({"method": method, "params": params or {}}, separators=(",", ":")).encode())

    def response(self, request_id: int | str, result: dict[str, Any]) -> None:
        """Answer a server-originated permission request with a JSON-RPC result."""
        self._write_frame(json.dumps({"id": request_id, "result": result}, separators=(",", ":")).encode())

    def request(self, method: str, params: dict[str, Any], timeout: float = 15) -> dict[str, Any]:
        """Send a request and wait for its matching app-server response."""
        self.request_id += 1
        request_id = self.request_id
        self._write_frame(json.dumps({"id": request_id, "method": method, "params": params}, separators=(",", ":")).encode())
        deadline = time.monotonic() + timeout
        while True:
            message = self._read_message(max(0.1, deadline - time.monotonic()))
            if message.get("method") and "id" in message:
                self._handle_server_request(message)
                continue
            if message.get("id") == request_id:
                if "error" in message:
                    raise ControlError(f"App-server rejected {method}")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise ControlError(f"App-server returned an invalid {method} response")
                return result
            self.queued_messages.append(message)

    def next_message(self, timeout: float = 30) -> dict[str, Any]:
        """Return the next decoded notification or server-originated request."""
        if self.queued_messages:
            return self.queued_messages.pop(0)
        return self._read_message(timeout)

    def _handle_server_request(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        request_id = message.get("id")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "item/commandExecution/requestApproval":
            # `approvalPolicy=never` auto-runs commands allowed by the active
            # sandbox. An unexpected escape request is declined to preserve it.
            self.response(request_id, {"decision": "decline"})
        elif method == "item/fileChange/requestApproval":
            root = params.get("grantRoot")
            inside_home = isinstance(root, str) and _is_within_home(root, self.home)
            self.response(request_id, {"decision": "accept" if inside_home else "decline"})
        elif method == "item/permissions/requestApproval":
            permissions = params.get("permissions")
            self.response(request_id, {
                "permissions": _granted_permissions(permissions, self.home, self.network_access),
                "scope": "turn",
            })
        elif method == "item/tool/requestUserInput":
            questions = params.get("questions") if isinstance(params.get("questions"), list) else []
            answers = {question.get("id"): {"answers": []} for question in questions if isinstance(question, dict) and isinstance(question.get("id"), str)}
            self.response(request_id, {"answers": answers})
        elif method == "mcpServer/elicitation/request":
            self.response(request_id, {"action": "decline"})
        else:
            self._write_frame(json.dumps({
                "id": request_id,
                "error": {"code": -32601, "message": "Dashboard does not support this app-server request"},
            }, separators=(",", ":")).encode())

    def initialize(self) -> None:
        """Negotiate the supported app-server protocol before other methods."""
        self._websocket_handshake()
        self.request("initialize", {
            "clientInfo": {"name": "codex-orchestrator-dashboard", "title": "Codex Orchestrator Dashboard", "version": "0.2.0"},
            "capabilities": {"experimentalApi": True},
        })
        self.notify("initialized")

    def close(self) -> None:
        """Close the underlying proxy process and its local pipes."""
        try:
            self._write_frame(b"", opcode=8)
        except Exception:
            pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)


def _is_within_home(value: str, home: str) -> bool:
    try:
        candidate = pathlib.Path(value).expanduser()
        if not candidate.is_absolute():
            return False
        path = candidate.resolve(strict=False)
        root = pathlib.Path(home).resolve(strict=False)
        return path == root or root in path.parents
    except (OSError, RuntimeError):
        return False


def _granted_permissions(value: Any, home: str, network_access: bool) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    granted: dict[str, Any] = {}
    filesystem = value.get("fileSystem")
    if isinstance(filesystem, dict):
        safe_filesystem: dict[str, Any] = {}
        for key in ("read", "write"):
            paths = filesystem.get(key)
            if isinstance(paths, list):
                allowed = [path for path in paths if isinstance(path, str) and _is_within_home(path, home)]
                if allowed:
                    safe_filesystem[key] = allowed
            elif key in filesystem and paths is not None:
                return granted
        entries = filesystem.get("entries")
        allowed_entries = []
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict) or entry.get("access") not in {"read", "write"}:
                    continue
                spec = entry.get("path")
                if isinstance(spec, dict) and spec.get("type") == "path" and isinstance(spec.get("path"), str) and _is_within_home(spec["path"], home):
                    allowed_entries.append({"path": {"type": "path", "path": spec["path"]}, "access": entry["access"]})
        elif "entries" in filesystem and entries is not None:
            return granted
        if allowed_entries:
            safe_filesystem["entries"] = allowed_entries
        depth = filesystem.get("globScanMaxDepth")
        if isinstance(depth, int) and not isinstance(depth, bool) and 0 < depth <= 64 and safe_filesystem:
            safe_filesystem["globScanMaxDepth"] = depth
        if safe_filesystem:
            granted["fileSystem"] = safe_filesystem
    network = value.get("network")
    if isinstance(network, dict) and network.get("enabled") is True and network_access:
        granted["network"] = {"enabled": True}
    return granted


def _permissions_fit_profile(value: Any, home: str, network_access: bool) -> bool:
    return isinstance(value, dict) and _granted_permissions(value, home, network_access) == value


def _spawn_local(host: dict[str, Any]) -> tuple[subprocess.Popen[bytes], str, str]:
    codex_home = _codex_home_path(host)
    codex = _codex_path(host)
    home = str(pathlib.Path.home().resolve())
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    process = subprocess.Popen(
        [codex, "app-server", "proxy", "--sock", str(codex_home / "app-server-control/app-server-control.sock")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        bufsize=0,
    )
    return process, home, "local"


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _remote_proxy_command(host: dict[str, Any]) -> str:
    raw = host.get("codexHome") or "~/.codex"
    if not isinstance(raw, str) or any(char in raw for char in "\x00\r\n"):
        raise ControlError("Invalid CODEX_HOME inventory override")
    if raw == "~":
        assignment = 'CODEX_HOME="$HOME"'
    elif raw.startswith("~/"):
        suffix = pathlib.PurePosixPath(raw[2:])
        if ".." in suffix.parts:
            raise ControlError("Invalid CODEX_HOME inventory override")
        assignment = f'CODEX_HOME="$HOME"/{_shell_quote(raw[2:])}'
    elif pathlib.Path(raw).is_absolute() and ".." not in pathlib.Path(raw).parts:
        assignment = f"CODEX_HOME={_shell_quote(raw)}"
    else:
        raise ControlError("Invalid CODEX_HOME inventory override")
    return (
        f"{assignment}; export CODEX_HOME; "
        "printf 'DASHBOARD_HOME=%s\\n' \"$HOME\"; "
        "for codex_path in \"$HOME/.local/bin/codex\" \"$CODEX_HOME/packages/app-server-daemon/current/bin/codex\" \"$CODEX_HOME/packages/standalone/current/bin/codex\"; do "
        "if [ -x \"$codex_path\" ]; then exec \"$codex_path\" app-server proxy --sock \"$CODEX_HOME/app-server-control/app-server-control.sock\"; fi; "
        "done; exit 127"
    )


def _spawn_remote(route: dict[str, str], host: dict[str, Any]) -> tuple[subprocess.Popen[bytes], str, str]:
    process = subprocess.Popen(
        [
            "ssh", "-T", "-q",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"HostKeyAlias={route['hostKeyAlias']}",
            "--", route["target"], _remote_proxy_command(host),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    if not process.stdout:
        process.terminate()
        raise ControlError("Remote Codex proxy did not start")
    ready, _, _ = select.select([process.stdout.fileno()], [], [], 8)
    line = process.stdout.readline() if ready else b""
    if not line.startswith(b"DASHBOARD_HOME="):
        process.terminate()
        raise ControlError("Remote Codex proxy did not start")
    home = line.removeprefix(b"DASHBOARD_HOME=").decode("utf-8", errors="strict").strip()
    if not home.startswith("/") or "\x00" in home or len(home) > 1024:
        process.terminate()
        raise ControlError("Remote home directory was invalid")
    return process, home, route["transport"]


def connect_app_server(host: dict[str, Any]) -> AppServerConnection:
    """Connect to one allowlisted local or strict-SSH host app-server proxy."""
    if host.get("local") is True:
        process, home, transport = _spawn_local(host)
        connection = AppServerConnection(process, home, transport)
        try:
            connection.initialize()
            return connection
        except Exception:
            connection.close()
            raise

    routes = host.get("sshRoutes")
    if not isinstance(routes, list) or not routes or not all(_route_is_valid(route) for route in routes):
        raise ControlError("No safe SSH routes are configured for this host")
    errors = []
    for route in routes:
        process = None
        try:
            process, home, transport = _spawn_remote(route, host)
            connection = AppServerConnection(process, home, transport)
            connection.initialize()
            return connection
        except Exception:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
            errors.append(route["transport"])
    if errors:
        raise ControlError("Codex app-server unavailable via " + ", ".join(errors))
    raise ControlError("Codex app-server unavailable")


def managed_thread_settings(home: str, network_access: bool) -> dict[str, Any]:
    """Build approval and sandbox settings for a dashboard-managed thread."""
    return {
        "approvalPolicy": "never",
        "sandbox": "workspace-write",
        "cwd": home,
        "runtimeWorkspaceRoots": [home],
        "model": "gpt-6-luna",
        "config": {
            "sandbox_workspace_write": {
                "writable_roots": [home],
                "network_access": network_access,
            },
            "web_search": "live" if network_access else "disabled",
        },
    }


def turn_sandbox_policy(home: str, network_access: bool) -> dict[str, Any]:
    """Build the per-turn writable-home and command-network policy."""
    return {
        "type": "workspaceWrite",
        "writableRoots": [home],
        "networkAccess": network_access,
    }


def project_notification(message: dict[str, Any]) -> dict[str, Any] | None:
    """Project app-server messages into bounded, prompt-safe dashboard events."""
    method = message.get("method")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    if method == "item/agentMessage/delta":
        delta = params.get("delta")
        return {"type": "delta", "delta": delta} if isinstance(delta, str) else None
    if method == "turn/started":
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        return {"type": "turn", "status": "inProgress", "turnId": turn.get("id")}
    if method == "item/started":
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        kind = item.get("type")
        if isinstance(kind, str):
            return {"type": "activity", "status": "started", "kind": kind[:80]}
    if method == "item/completed":
        item = params.get("item") if isinstance(params.get("item"), dict) else {}
        if item.get("type") == "agentMessage" and isinstance(item.get("text"), str):
            return {"type": "message", "text": item["text"]}
        kind = item.get("type")
        if isinstance(kind, str):
            return {"type": "activity", "status": "completed", "kind": kind[:80]}
    if method == "thread/tokenUsage/updated":
        usage = params.get("tokenUsage") if isinstance(params.get("tokenUsage"), dict) else {}
        total = usage.get("total") if isinstance(usage.get("total"), dict) else {}
        return {
            "type": "usage",
            "inputTokens": _nonnegative_int(total.get("inputTokens")),
            "cachedInputTokens": _nonnegative_int(total.get("cachedInputTokens")),
            "outputTokens": _nonnegative_int(total.get("outputTokens")),
            "reasoningTokens": _nonnegative_int(total.get("reasoningOutputTokens")),
            "totalTokens": _nonnegative_int(total.get("totalTokens")),
        }
    if method == "turn/completed":
        turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
        return {
            "type": "completed",
            "status": str(turn.get("status", "unknown"))[:40],
            "turnId": turn.get("id") if isinstance(turn.get("id"), str) else None,
            "failed": bool(turn.get("error")),
        }
    return None


def _nonnegative_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def run_turn(request: dict[str, Any]) -> None:
    """Create or resume a thread, stream one turn, and emit projected events."""
    host = request.get("host")
    prompt = request.get("prompt")
    thread_id = request.get("threadId")
    network_access = request.get("networkAccess") is True
    if not isinstance(host, dict) or not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 40_000:
        raise ControlError("Invalid Codex turn request")
    if thread_id is not None and (not isinstance(thread_id, str) or len(thread_id) > 160):
        raise ControlError("Invalid Codex thread identifier")

    connection = connect_app_server(host)
    connection.network_access = network_access
    try:
        settings = managed_thread_settings(connection.home, network_access)
        if thread_id:
            thread = connection.request("thread/resume", {"threadId": thread_id, **settings})
        else:
            thread = connection.request("thread/start", settings)
        thread_data = thread.get("thread") if isinstance(thread.get("thread"), dict) else {}
        resolved_thread_id = thread_data.get("id") or thread.get("threadId") or thread_id
        if not isinstance(resolved_thread_id, str):
            raise ControlError("Codex did not return a thread identifier")
        turn_result = connection.request("turn/start", {
            "threadId": resolved_thread_id,
            "input": [{"type": "text", "text": prompt}],
            "approvalPolicy": "never",
            "sandboxPolicy": turn_sandbox_policy(connection.home, network_access),
            "model": "gpt-6-luna",
            "effort": "max",
        })
        turn_data = turn_result.get("turn") if isinstance(turn_result.get("turn"), dict) else {}
        turn_id = turn_data.get("id")
        if not isinstance(turn_id, str):
            raise ControlError("Codex did not return a turn identifier")
        emit({"type": "started", "threadId": resolved_thread_id, "turnId": turn_id, "transport": connection.transport, "networkAccess": network_access})
        terminal = False
        while not terminal:
            try:
                message = connection.next_message(timeout=45)
            except TimeoutError:
                emit({"type": "heartbeat"})
                continue
            if message.get("method") and "id" in message:
                connection._handle_server_request(message)
                continue
            projected = project_notification(message)
            if projected:
                if projected.get("type") == "completed":
                    projected["turnId"] = projected.get("turnId") or turn_id
                    terminal = True
                emit(projected)
        emit({"type": "streamEnded", "threadId": resolved_thread_id, "turnId": turn_id})
    finally:
        connection.close()


def run_interrupt(request: dict[str, Any]) -> None:
    """Request interruption for the specified host, thread, and turn IDs."""
    host = request.get("host")
    thread_id = request.get("threadId")
    turn_id = request.get("turnId")
    if not isinstance(host, dict) or not isinstance(thread_id, str) or len(thread_id) > 160 or not isinstance(turn_id, str) or len(turn_id) > 160:
        raise ControlError("Invalid interrupt request")
    connection = connect_app_server(host)
    try:
        connection.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        emit({"type": "interrupted", "threadId": thread_id, "turnId": turn_id, "transport": connection.transport, "accepted": True})
    finally:
        connection.close()


def main() -> int:
    """Dispatch one JSON stdin request in turn or interrupt mode."""
    try:
        request = json.loads(sys.stdin.readline())
        if not isinstance(request, dict):
            raise ControlError("Invalid dashboard request")
        mode = request.get("mode")
        if mode == "turn":
            run_turn(request)
        elif mode == "interrupt":
            run_interrupt(request)
        else:
            raise ControlError("Unsupported Codex control operation")
        return 0
    except Exception:
        emit({"type": "error", "message": "Codex app-server control failed. Check the selected host's connectivity and app-server status."})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
