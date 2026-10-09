#!/usr/bin/env python3
"""Install or verify the current user's Codex and Herdr LaunchAgents."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "macos" / "LaunchAgents"
AGENTS = {
    "codex-app-server-ensure": {
        "label": "org.example.codex-app-server-ensure",
        "template": "org.example.codex-app-server-ensure.plist.in",
    },
    "herdr-server": {
        "label": "org.example.herdr-server",
        "template": "org.example.herdr-server.plist.in",
    },
}
AGENT_NAMES = tuple(AGENTS)


def render_agent(name: str, home: Path, codex_bin: str, herdr_bin: str, label: str | None = None, codex_home: Path | None = None) -> dict[str, Any]:
    """Render one LaunchAgent template into a plist mapping for a user."""
    spec = AGENTS[name]
    template_path = TEMPLATE_DIR / spec["template"]
    template = template_path.read_text(encoding="utf-8")
    rendered = (
        template.replace("@HOME@", escape(str(home)))
        .replace("@LABEL@", escape(label or spec["label"]))
        .replace("@CODEX_BIN@", escape(codex_bin))
        .replace("@CODEX_HOME@", escape(str(codex_home or (home / ".codex"))))
        .replace("@HERDR_BIN@", escape(herdr_bin))
    )
    return plistlib.loads(rendered.encode("utf-8"))


def launchctl_loaded(uid: int, label: str) -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{label}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def find_loaded_label(suffix: str) -> str | None:
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        fields = line.split()
        if fields and fields[-1].endswith(suffix):
            return fields[-1]
    return None


def process_running(uid: int, executable: str, arguments: list[str]) -> bool:
    pattern = "^" + re.escape(" ".join([executable, *arguments])) + "$"
    result = subprocess.run(
        ["pgrep", "-u", str(uid), "-f", pattern],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as temporary_file:
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def read_plist(path: Path) -> dict[str, Any] | None:
    try:
        value = plistlib.loads(path.read_bytes())
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None
    return value if isinstance(value, dict) else None


def backup(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.pre-fleet-{timestamp}.bak")
    shutil.copy2(path, backup_path)
    os.chmod(backup_path, 0o600)
    return backup_path


def resolve_codex_home(
    home: Path,
    inventory_path: Path,
    environ: dict[str, str] | None = None,
) -> Path:
    """Resolve this local host's inventory override before CODEX_HOME/default."""
    environment = os.environ if environ is None else environ
    inventory_override: str | None = None
    try:
        hosts = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        hosts = []
    if isinstance(hosts, list):
        local_hosts = [host for host in hosts if isinstance(host, dict) and host.get("local") is True]
        overrides = [host.get("codexHome") for host in local_hosts if host.get("codexHome") is not None]
        if len(overrides) > 1:
            raise ValueError("multiple local host CODEX_HOME overrides are configured")
        if overrides:
            value = overrides[0]
            if not isinstance(value, str):
                raise ValueError("invalid local host CODEX_HOME override")
            inventory_override = value

    raw = inventory_override if inventory_override is not None else environment.get("CODEX_HOME") or str(home / ".codex")
    if not raw.strip() or any(character in raw for character in "\0\r\n"):
        raise ValueError("invalid CODEX_HOME")
    if raw == "~":
        codex_home = home
    elif raw.startswith("~/"):
        relative = Path(raw[2:])
        if ".." in relative.parts:
            raise ValueError("CODEX_HOME cannot contain parent traversal")
        codex_home = home / relative
    else:
        codex_home = Path(raw)
        if not codex_home.is_absolute() or ".." in codex_home.parts:
            raise ValueError("CODEX_HOME must be absolute and cannot contain parent traversal")
    return codex_home.resolve()


def ensure_agents(*, install: bool) -> int:
    """Verify both user LaunchAgents or install and bootstrap them explicitly."""
    if sys.platform != "darwin":
        print("This installer only runs on macOS.", file=sys.stderr)
        return 2

    home = Path.home()
    inventory_path = Path(os.environ.get("FLEET_CONFIG_PATH", str(REPO_ROOT / "config" / "fleet.local.json"))).expanduser()
    try:
        codex_home = resolve_codex_home(home, inventory_path)
    except ValueError as error:
        print(f"{error}.", file=sys.stderr)
        return 2
    uid = os.getuid()
    codex_bin = shutil.which("codex")
    herdr_bin = shutil.which("herdr")
    if not codex_bin or not herdr_bin:
        print("codex and herdr must both be available on PATH.", file=sys.stderr)
        return 2

    destination = home / "Library" / "LaunchAgents"
    problems = 0
    for name in AGENT_NAMES:
        spec = AGENTS[name]
        label = find_loaded_label(name) or spec["label"]
        expected = render_agent(name, home, codex_bin, herdr_bin, label, codex_home)
        target = destination / f"{label}.plist"
        current = read_plist(target) if target.exists() else None
        loaded = launchctl_loaded(uid, label)

        if current != expected:
            if not install:
                print(f"{name}: installed plist differs or is missing")
                problems += 1
                continue
            if loaded:
                print(f"{label}: loaded; refusing to replace its plist while active", file=sys.stderr)
                problems += 1
                continue
            if target.exists():
                print(f"{label}: backed up existing plist to {backup(target).name}")
            data = plistlib.dumps(expected, fmt=plistlib.FMT_XML, sort_keys=False)
            atomic_write(target, data)
            current = expected
            print(f"{label}: installed")
        else:
            print(f"{label}: plist matches")

        if loaded:
            print(f"{label}: loaded in gui/{uid}")
            continue

        if name == "herdr-server" and process_running(uid, herdr_bin, ["server"]):
            print(f"{label}: existing Herdr server preserved; agent will load at next GUI login")
            continue

        if not install:
            print(f"{label}: not loaded in gui/{uid}")
            problems += 1
            continue

        result = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode:
            print(f"{label}: launchctl bootstrap failed", file=sys.stderr)
            problems += 1
        else:
            print(f"{label}: bootstrapped in gui/{uid}")

    return 1 if problems else 0


def main() -> int:
    """Run the macOS installer in check-only or explicit install mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--install", action="store_true", help="install missing agents and bootstrap unloaded jobs")
    mode.add_argument("--check", action="store_true", help="verify installed plists and launchd state (default)")
    args = parser.parse_args()
    return ensure_agents(install=args.install)


if __name__ == "__main__":
    raise SystemExit(main())
