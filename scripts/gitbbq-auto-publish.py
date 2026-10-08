#!/usr/bin/env python3
"""Run verified Git BBQ stage/commit/tag/push after a completed repo turn."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

def gitbbq_command() -> str:
    configured = os.environ.get("GIT_BBQ_BIN")
    if configured:
        return configured
    on_path = shutil.which("git-bbq")
    if on_path:
        return on_path
    candidates = list((Path.home() / ".codex" / "plugins" / "cache").glob("*/git-bbq*/**/runtime/bin/*/git-bbq"))
    if candidates:
        return str(max(candidates, key=lambda path: path.stat().st_mtime))
    raise RuntimeError("Git BBQ executable is unavailable")


def run(
    args: list[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 600,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout, check=False)


def git(*args: str) -> str:
    result = run(["git", *args], timeout=20)
    if result.returncode != 0:
        raise RuntimeError("Git state could not be read")
    return result.stdout.strip()


def respond(message: str | None = None) -> int:
    value: dict[str, object] = {"continue": True}
    if message:
        value["systemMessage"] = message
    print(json.dumps(value))
    return 0


def execute_action(action: str, options: list[str]) -> None:
    executable = gitbbq_command()
    plan = run([executable, "githabits", "plan", "--action", action, *options, "--json"], timeout=30)
    if plan.returncode != 0:
        raise RuntimeError(f"Git BBQ could not plan {action}")
    try:
        policy = json.loads(plan.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Git BBQ returned an invalid {action} plan") from error
    if not policy.get("allowed"):
        raise RuntimeError(f"Git BBQ policy blocked {action}")

    result = run([executable, "githabits", "execute", "--approve", "--action", action, *options, "--json"], timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"Git BBQ {action} failed")


def next_patch_tag() -> tuple[str, list[str]]:
    tags = [tag for tag in git("tag", "--list", "v*").splitlines() if re.fullmatch(r"v\d+\.\d+\.\d+", tag)]
    versions = [tuple(int(part) for part in tag[1:].split(".")) for tag in tags]
    if not versions:
        return "v0.1.0", []
    major, minor, patch = max(versions)
    return f"v{major}.{minor}.{patch + 1}", tags


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return respond()

    if payload.get("hook_event_name") != "Stop" or payload.get("stop_hook_active") is True:
        return respond()
    event_cwd = Path(payload.get("cwd") or os.getcwd()).resolve()
    if event_cwd != ROOT:
        return respond()
    if git("branch", "--show-current") != "main":
        return respond()
    if run(["git", "remote", "get-url", "origin"], timeout=20).returncode != 0:
        return respond()
    if not git("status", "--porcelain", "--untracked-files=all"):
        return respond()

    checks = [
        ["python3", "scripts/check_public_snapshot.py"],
        ["npm", "test"],
        ["npm", "run", "lint"],
        ["npx", "tsc", "--noEmit"],
        ["npm", "run", "build"],
        ["python3", "scripts/test_sync_codex_profile.py"],
        ["python3", "-m", "unittest", "scripts/test_macos_launchagents.py"],
        ["python3", "-m", "py_compile", "scripts/probe.py", "scripts/sync_codex_profile.py", "scripts/check_public_snapshot.py", "scripts/gitbbq-auto-publish.py", "ansible/inventory.py"],
        ["ansible-playbook", "-i", "inventory.py", "--syntax-check", "playbooks/sync-linux-fleet.yml"],
    ]
    for command in checks:
        cwd = ROOT / "ansible" if command[0] == "ansible-playbook" else ROOT
        env = os.environ.copy()
        if command[0] == "ansible-playbook":
            env["FLEET_CONFIG_PATH"] = str(ROOT / "config" / "fleet.example.json")
        result = run(command, cwd=cwd, env=env)
        if result.returncode != 0:
            return respond("Auto-publish skipped because a repository check failed. Review the local run before publishing.")

    if run(["git", "diff", "--check"]).returncode != 0:
        return respond("Auto-publish skipped because the patch check failed.")
    if not git("status", "--porcelain", "--untracked-files=all"):
        return respond()

    message = "chore: publish verified dashboard changes"
    execute_action("stage", ["--path", "."])
    if not git("diff", "--cached", "--name-only"):
        return respond()
    execute_action("commit", ["--message", message])

    tag, existing = next_patch_tag()
    tag_options = ["--tag", tag]
    for item in existing:
        tag_options.extend(["--existing-tag", item])
    execute_action("tag", tag_options)
    execute_action("push", ["--branch", "main"])
    return respond("Verified changes were committed, tagged, and pushed.")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        raise SystemExit(respond("Auto-publish did not complete. Review the local Git state."))
