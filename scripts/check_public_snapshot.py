#!/usr/bin/env python3
"""Reject common private host data and credential patterns before publication."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


IPV4 = re.compile(r"(?<![\w.-])(?:\d{1,3}\.){3}\d{1,3}(?![\w.-])")
EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
HOME_PATH = re.compile(r"/(?:Users|home)/([^/\s:'\"<>]+)")
PRIVATE_DOMAIN = re.compile(r"\b[\w.-]+\.ts\.net\b", re.IGNORECASE)
SECRET = re.compile(
    r"\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b|-----BEGIN (?:OPENSSH|RSA|EC|DSA|PGP) PRIVATE KEY-----"
)


def is_example_ip(address: str) -> bool:
    parts = tuple(int(part) for part in address.split("."))
    if any(part > 255 for part in parts):
        return True
    return (
        parts[0] == 127
        or parts[:3] == (192, 0, 2)
        or parts[:3] == (198, 51, 100)
        or parts[:3] == (203, 0, 113)
        or address in {"0.0.0.0", "255.255.255.255"}
    )


def public_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    paths = [root / value.decode() for value in result.stdout.split(b"\0") if value]
    return [path for path in paths if path.is_file()]


def findings(path: Path, content: str) -> list[str]:
    problems = []
    for match in IPV4.finditer(content):
        if not is_example_ip(match.group()):
            problems.append("non-example IPv4 address")
            break
    if any(not address.endswith((".example", ".test", ".invalid")) and address != "example.com" for address in EMAIL.findall(content)):
        problems.append("non-example email address")
    if any(name.lower() not in {"example", "operator", "user"} for name in HOME_PATH.findall(content)):
        problems.append("user-specific home path")
    if PRIVATE_DOMAIN.search(content):
        problems.append("private tailnet domain")
    if SECRET.search(content):
        problems.append("credential-like token")
    return problems


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failed = False
    for path in public_files(root):
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for problem in findings(path, content):
            print(f"{path.relative_to(root)}: {problem}", file=sys.stderr)
            failed = True
    if failed:
        return 1
    print("Public snapshot scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
