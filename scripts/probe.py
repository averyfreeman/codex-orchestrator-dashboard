import base64
import glob
import getpass
import hashlib
import json
import os
import pathlib
import platform
import select
import subprocess
import time

HOME = pathlib.Path.home()

def run(args, timeout=8):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except Exception as exc:
        return "", str(exc), 1

def first_executable(paths):
    for value in paths:
        if pathlib.Path(value).is_file() and os.access(value, os.X_OK):
            return value
    return None

def launchd_job_loaded(suffix):
    out, _, code = run(["launchctl", "list"])
    if code != 0:
        return False
    return any(line.split() and line.split()[-1].endswith(suffix) for line in out.splitlines())

codex = first_executable([
    str(HOME / ".local/bin/codex"),
    str(HOME / ".codex/packages/app-server-daemon/current/bin/codex"),
    str(HOME / ".codex/packages/standalone/current/bin/codex"),
])
herdr = first_executable([
    str(HOME / ".local/bin/herdr"),
    str(HOME / ".nix-profile/bin/herdr"),
    "/opt/homebrew/bin/herdr",
])

app = {"status": "unavailable", "version": None, "remoteControlEnabled": None, "remoteControlRuntime": "unknown", "loadedThreads": None, "startup": "unknown", "error": None}
processes = []
if codex:
    out, err, code = run([codex, "app-server", "daemon", "version"])
    try:
        version = json.loads(out)
        app["status"] = version.get("status", "unknown")
        app["version"] = version.get("appServerVersion") or version.get("managedCodexVersion")
        app["error"] = None if code == 0 else (err or "daemon status failed")
    except Exception:
        app["error"] = err or out or "daemon status did not return JSON"
    settings_path = HOME / ".codex/app-server-daemon/settings.json"
    try:
        settings = json.loads(settings_path.read_text())
        app["remoteControlEnabled"] = settings.get("remoteControlEnabled")
    except Exception:
        pass
    pid = None
    try:
        pid_record = json.loads((HOME / ".codex/app-server-daemon/app-server.pid").read_text())
        pid = int(pid_record.get("pid"))
    except Exception:
        pass
    pids = [pid] if pid else []
    if pids:
        out, _, _ = run(["ps", "-p", ",".join(map(str, pids)), "-o", "pid=,pcpu=,pmem=,rss=,etime=,comm="])
        for line in out.splitlines():
            fields = line.split(None, 5)
            if len(fields) >= 6:
                try:
                    processes.append({"pid": int(fields[0]), "cpuPercent": float(fields[1]), "memoryPercent": float(fields[2]), "memoryMb": round(int(fields[3]) / 1024, 1), "elapsed": fields[4], "command": fields[5]})
                except Exception:
                    pass

def rpc_status(codex_path):
    socket_path = HOME / ".codex/app-server-control/app-server-control.sock"
    proc = subprocess.Popen([codex_path, "app-server", "proxy", "--sock", str(socket_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
    buffer = bytearray()
    fd = proc.stdout.fileno()
    def read_more(deadline):
        remaining = deadline - time.time()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise TimeoutError("app-server proxy timed out")
        chunk = os.read(fd, 65536)
        if not chunk:
            raise EOFError("app-server proxy closed")
        buffer.extend(chunk)
    def take(size, deadline):
        while len(buffer) < size:
            read_more(deadline)
        data = bytes(buffer[:size]); del buffer[:size]
        return data
    def send_frame(data, opcode=1):
        if not isinstance(data, bytes): data = data.encode()
        length = len(data)
        header = bytearray([0x80 | opcode])
        if length < 126: header.append(0x80 | length)
        elif length < 65536: header.extend((0x80 | 126).to_bytes(1, "big")); header.extend(length.to_bytes(2, "big"))
        else: header.extend((0x80 | 127).to_bytes(1, "big")); header.extend(length.to_bytes(8, "big"))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        proc.stdin.write(bytes(header) + mask + masked); proc.stdin.flush()
    def receive_frame(deadline):
        first, second = take(2, deadline)
        opcode = first & 0x0f
        length = second & 0x7f
        if length == 126: length = int.from_bytes(take(2, deadline), "big")
        elif length == 127: length = int.from_bytes(take(8, deadline), "big")
        mask = take(4, deadline) if second & 0x80 else b""
        data = take(length, deadline)
        if mask: data = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
        return opcode, data
    def request(request_id, method, params=None):
        send_frame(json.dumps({"id": request_id, "method": method, "params": params or {}}, separators=(",", ":")))
        deadline = time.time() + 8
        while time.time() < deadline:
            opcode, data = receive_frame(deadline)
            if opcode == 9: send_frame(data, opcode=10); continue
            if opcode != 1: continue
            value = json.loads(data)
            if value.get("id") == request_id: return value
        raise TimeoutError(method + " timed out")
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        request_bytes = ("GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" + f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode()
        proc.stdin.write(request_bytes); proc.stdin.flush()
        deadline = time.time() + 8
        while b"\r\n\r\n" not in buffer: read_more(deadline)
        header, _, rest = bytes(buffer).partition(b"\r\n\r\n"); buffer = bytearray(rest)
        lines = header.decode("utf-8", errors="replace").split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                name, value = line.split(":", 1); headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if not lines[0].startswith("HTTP/1.1 101") or headers.get("sec-websocket-accept") != expected:
            raise RuntimeError("app-server WebSocket handshake failed")
        if "error" in request(1, "initialize", {"clientInfo": {"name": "codex-fleet-dashboard", "title": "Codex fleet dashboard", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}):
            raise RuntimeError("app-server initialize failed")
        send_frame(json.dumps({"method": "initialized", "params": {}}, separators=(",", ":")))
        runtime_response = request(2, "remoteControl/status/read")
        thread_response = request(3, "thread/loaded/list")
        runtime = runtime_response.get("result", {}).get("status", "unknown")
        loaded = thread_response.get("result", {}).get("data", [])
        return {"runtime": runtime, "loadedThreads": len(loaded) if isinstance(loaded, list) else None, "error": None}
    finally:
        try:
            proc.stdin.close(); proc.terminate(); proc.wait(timeout=2)
        except Exception:
            try: proc.kill()
            except Exception: pass

if codex and app["status"] == "running":
    try:
        rpc = rpc_status(codex)
        app["remoteControlRuntime"] = rpc["runtime"]
        app["loadedThreads"] = rpc["loadedThreads"]
    except Exception as exc:
        app["remoteControlRuntime"] = "unknown"
        app["error"] = app["error"] or ("Remote Control status: " + str(exc)[:200])

if platform.system() == "Darwin":
    app["startup"] = "enabled" if launchd_job_loaded("codex-app-server-ensure") else "not configured"
else:
    unit, _, enabled = run(["systemctl", "--user", "is-enabled", "codex-app-server.service"])
    timer, _, timer_active = run(["systemctl", "--user", "is-active", "codex-app-server-ensure.timer"])
    linger, _, _ = run(["loginctl", "show-user", getpass.getuser(), "-p", "Linger"])
    app["startup"] = "enabled · ensure timer active · linger" if enabled == 0 and timer_active == 0 and "Linger=yes" in linger else ("enabled" if enabled == 0 else "not configured")

# If a desktop app or another supervisor launched a daemon, its PID record may
# live outside the default CODEX_HOME. Restrict process metadata to this user.
ps_args = ["ps", "-axo", "uid=,pid=,pcpu=,pmem=,rss=,etime=,comm=,args="] if platform.system() == "Darwin" else ["ps", "-eo", "uid=,pid=,pcpu=,pmem=,rss=,etime=,comm=,args="]
out, _, _ = run(ps_args)
known_pids = {item["pid"] for item in processes}
for line in out.splitlines():
    fields = line.split(None, 7)
    if len(fields) < 8 or fields[0] != str(os.getuid()):
        continue
    command_line = fields[7]
    executable = command_line.split(None, 1)[0] if command_line.split(None, 1) else ""
    try:
        found_pid = int(fields[1])
        if found_pid in known_pids:
            continue
        executable_name = pathlib.Path(executable).name
        if executable_name == "codex" and "app-server" in command_line and "--managed-daemon" in command_line:
            command = fields[6]
        elif executable_name == "herdr" and " server" in command_line:
            command = "herdr server"
        else:
            continue
        processes.append({"pid": found_pid, "cpuPercent": float(fields[2]), "memoryPercent": float(fields[3]), "memoryMb": round(int(fields[4]) / 1024, 1), "elapsed": fields[5], "command": command})
        known_pids.add(found_pid)
    except Exception:
        pass

herdr_status = {"status": "not installed" if not herdr else "not running", "version": None, "startup": "unknown", "agents": [], "workspaces": [], "error": None}
if herdr:
    out, err, code = run([herdr, "status", "server", "--json"])
    try:
        data = json.loads(out)
        server = data.get("server", data)
        client = data.get("client", {})
        herdr_status["status"] = server.get("status", "unknown")
        herdr_status["version"] = server.get("version") or client.get("version")
    except Exception:
        herdr_status["error"] = err or out or "Herdr status unavailable"
    for command, key in (("agent", "agents"), ("workspace", "workspaces")):
        out, err, code = run([herdr, command, "list"])
        try:
            envelope = json.loads(out)
            result = envelope.get("result", {})
            if key == "agents":
                herdr_status[key] = [{"id": str(item.get("id", "unknown")), "name": str(item.get("name") or item.get("agent") or item.get("id") or "Agent"), "state": str(item.get("status") or item.get("state") or "unknown"), "pid": item.get("pid") if isinstance(item.get("pid"), int) else None} for item in result.get("agents", [])]
            else:
                herdr_status[key] = [str(item.get("label") or item.get("workspace_id") or item.get("number") or "Workspace") for item in result.get("workspaces", [])]
        except Exception:
            if code != 0:
                herdr_status["error"] = err or out or f"Herdr {command} query failed"

    if platform.system() == "Darwin":
        herdr_status["startup"] = "enabled" if launchd_job_loaded("herdr-server") else "not configured"
    else:
        enabled_out, _, enabled_code = run(["systemctl", "--user", "is-enabled", "herdr-server.service"])
        _, _, active_code = run(["systemctl", "--user", "is-active", "herdr-server.service"])
        linger_out, _, _ = run(["loginctl", "show-user", getpass.getuser(), "-p", "Linger"])
        if enabled_code == 0:
            if active_code == 0:
                herdr_status["startup"] = "enabled · active · linger" if "Linger=yes" in linger_out else "enabled · active"
            elif herdr_status["status"] == "running":
                herdr_status["startup"] = "enabled · existing server outside systemd"
            else:
                herdr_status["startup"] = "enabled · not running"
        else:
            herdr_status["startup"] = "not configured"

known_pids = {item["pid"] for item in processes}
for agent in herdr_status.get("agents", []):
    agent_pid = agent.get("pid")
    if not isinstance(agent_pid, int) or agent_pid in known_pids:
        continue
    out, _, _ = run(["ps", "-p", str(agent_pid), "-o", "pid=,pcpu=,pmem=,rss=,etime=,comm="])
    for line in out.splitlines():
        fields = line.split(None, 5)
        if len(fields) >= 6:
            try:
                processes.append({"pid": int(fields[0]), "cpuPercent": float(fields[1]), "memoryPercent": float(fields[2]), "memoryMb": round(int(fields[3]) / 1024, 1), "elapsed": fields[4], "command": fields[5]})
                known_pids.add(agent_pid)
            except Exception:
                pass

worktrees = []
for state_file in glob.glob(str(HOME / ".treehouse/**/treehouse-state.json"), recursive=True):
    try:
        state = json.loads(pathlib.Path(state_file).read_text())
        for item in state.get("worktrees", []):
            worktrees.append({"name": str(item.get("name", "worktree")), "path": str(item.get("path", "")), "createdAt": item.get("created_at")})
    except Exception:
        pass

def network_info():
    result = {"localIp": None, "tailscaleIp": None, "zerotierIp": None}
    if platform.system() == "Darwin":
        out, _, code = run(["ipconfig", "getifaddr", "en0"])
        if code == 0 and out:
            result["localIp"] = out.splitlines()[0].strip()
        for tailscale_bin in ("/Applications/Tailscale.app/Contents/MacOS/Tailscale", "/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale"):
            if pathlib.Path(tailscale_bin).is_file():
                out, _, code = run([tailscale_bin, "ip", "-4"])
                if code == 0 and out:
                    result["tailscaleIp"] = out.splitlines()[0].strip()
                    break
        for zerotier_bin in ("/opt/homebrew/bin/zerotier-cli", "/usr/local/bin/zerotier-cli"):
            if pathlib.Path(zerotier_bin).is_file():
                out, _, code = run([zerotier_bin, "listnetworks"])
                if code == 0:
                    for line in out.splitlines():
                        if " OK " in line:
                            candidate = line.split()[-1].split("/")[0]
                            if candidate.count(".") == 3:
                                result["zerotierIp"] = candidate
                                break
                    break
    else:
        out, _, code = run(["ip", "-j", "addr"])
        if code == 0:
            try:
                interfaces = json.loads(out)
                for iface in interfaces:
                    name = iface.get("ifname", "")
                    ipv4 = [info.get("local") for info in iface.get("addr_info", []) if info.get("family") == "inet" and info.get("scope") == "global"]
                    ipv4 = [value for value in ipv4 if value]
                    if not ipv4:
                        continue
                    if name == "tailscale0":
                        result["tailscaleIp"] = ipv4[0]
                    elif name.startswith("zt"):
                        result["zerotierIp"] = ipv4[0]
                    elif result["localIp"] is None and name != "lo" and not name.startswith(("br", "docker", "virbr", "veth", "tun", "wg")):
                        result["localIp"] = ipv4[0]
            except Exception:
                pass
    return result

print(json.dumps({"host": platform.node(), "os": platform.platform(), "ips": network_info(), "appServer": app, "herdr": herdr_status, "processes": processes, "worktrees": worktrees}))
