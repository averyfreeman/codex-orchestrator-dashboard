#!/usr/bin/env python3
"""Build Ansible inventory from the ignored local fleet configuration."""

import json
import os
import pathlib
import subprocess
import sys


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG_PATH = pathlib.Path(os.environ.get(
    "FLEET_CONFIG_PATH",
    str(REPO_ROOT / "config" / "fleet.local.json"),
)).expanduser()


def load_hosts() -> list[dict]:
    try:
        value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []


def ssh_available(target: str, alias: str) -> bool:
    try:
        result = subprocess.run(
            [
                "ssh", "-T", "-oBatchMode=yes", "-oConnectTimeout=3",
                "-oStrictHostKeyChecking=yes", f"-oHostKeyAlias={alias}",
                target, "true",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def valid_codex_home_override(value: object) -> bool:
    if not isinstance(value, str) or not value.strip() or any(character in value for character in "\0\r\n"):
        return False
    if value == "~":
        return True
    if value.startswith("~/"):
        return ".." not in pathlib.PurePosixPath(value[2:]).parts and ".." not in value[2:].split("\\")
    path = pathlib.PurePosixPath(value)
    return path.is_absolute() and ".." not in path.parts


def inventory() -> dict:
    hostvars = {}
    host_slugs = []
    for host in load_hosts():
        slug = host.get("slug")
        routes = host.get("sshRoutes")
        codex_home = host.get("codexHome")
        if codex_home is not None and not valid_codex_home_override(codex_home):
            continue
        if not isinstance(slug, str) or host.get("local") or not isinstance(routes, list) or not routes:
            continue

        selected = next(
            (
                route for route in routes
                if isinstance(route, dict)
                and isinstance(route.get("target"), str)
                and isinstance(route.get("hostKeyAlias"), str)
                and ssh_available(route["target"], route["hostKeyAlias"])
            ),
            routes[0],
        )
        target = selected.get("target") if isinstance(selected, dict) else None
        alias = selected.get("hostKeyAlias") if isinstance(selected, dict) else None
        if not isinstance(target, str) or "@" not in target or not isinstance(alias, str):
            continue
        user, address = target.rsplit("@", 1)
        hostvars[slug] = {
            "ansible_host": address,
            "ansible_user": user,
            "ansible_ssh_common_args": f"-o HostKeyAlias={alias} -o StrictHostKeyChecking=yes",
            "fleet_transport": selected.get("transport", "unknown"),
        }
        if codex_home is not None:
            hostvars[slug]["fleet_codex_home_override"] = codex_home
        host_slugs.append(slug)

    return {"linux_fleet": {"hosts": host_slugs}, "_meta": {"hostvars": hostvars}}


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--host":
        print("{}")
    else:
        print(json.dumps(inventory()))
