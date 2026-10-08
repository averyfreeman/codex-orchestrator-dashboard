#!/usr/bin/env python3
"""Apply the fleet's four shared Codex defaults without replacing host config."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT_KEYS = ("model", "model_reasoning_effort", "approval_policy", "sandbox_mode")
ROOT_KEY_PATTERN = re.compile(r"^\s*(model|model_reasoning_effort|approval_policy|sandbox_mode)\s*=")
TABLE_PATTERN = re.compile(r"^\s*\[\[?.*\]\]?\s*(?:#.*)?$")


def read_profile(path: Path) -> dict[str, str]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    if set(profile) != set(ROOT_KEYS) or any(not isinstance(profile[key], str) for key in ROOT_KEYS):
        raise ValueError(f"profile must contain exactly these string keys: {', '.join(ROOT_KEYS)}")
    return profile


def render_root_value(key: str, value: str, newline: str = "\n") -> str:
    return f"{key} = {json.dumps(value)}{newline}"


def merge_profile(original: str, profile: dict[str, str]) -> str:
    root_lines: list[str] = []
    table_lines: list[str] = []
    seen: set[str] = set()
    in_table = False
    for line in original.splitlines(keepends=True):
        if TABLE_PATTERN.match(line.rstrip("\r\n")):
            in_table = True
        if not in_table:
            match = ROOT_KEY_PATTERN.match(line)
            if match:
                key = match.group(1)
                if key in seen:
                    raise ValueError(f"duplicate root Codex setting: {key}")
                seen.add(key)
                ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
                root_lines.append(render_root_value(key, profile[key], ending or "\n"))
                continue
            root_lines.append(line)
        else:
            table_lines.append(line)

    newline = "\r\n" if "\r\n" in original else "\n"
    missing = [key for key in ROOT_KEYS if key not in seen]
    if missing:
        if root_lines and not root_lines[-1].endswith(("\n", "\r")):
            root_lines[-1] += newline
        if root_lines and root_lines[-1].strip():
            root_lines.append(newline)
        root_lines.extend(render_root_value(key, profile[key], newline) for key in missing)
        if table_lines and root_lines and root_lines[-1].strip():
            root_lines.append(newline)

    merged = "".join(root_lines + table_lines)
    tomllib.loads(merged)
    return merged


def apply_profile(config_path: Path, profile: dict[str, str], write: bool) -> bool:
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(config_path.parent, 0o700)
    except OSError:
        pass
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if original:
        tomllib.loads(original)
    merged = merge_profile(original, profile)
    if merged == original and config_path.exists():
        print("Codex fleet profile already matches")
        return False
    if not write:
        print("Codex fleet profile differs")
        return True

    if config_path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = config_path.with_name(f"{config_path.name}.pre-fleet-{timestamp}.bak")
        shutil.copy2(config_path, backup_path)
        os.chmod(backup_path, 0o600)

    descriptor, temp_name = tempfile.mkstemp(prefix=".config.toml.", dir=config_path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.write(merged)
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, config_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    print("Updated Codex fleet profile" + (" with a private backup" if original else ""))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "config.toml")
    parser.add_argument("--profile", type=Path, default=Path(__file__).resolve().parents[1] / "config/codex-fleet-profile.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report drift without writing")
    mode.add_argument("--write", action="store_true", help="apply the profile and preserve other settings")
    args = parser.parse_args()
    try:
        drift = apply_profile(args.config, read_profile(args.profile), args.write)
    except (OSError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        print(f"Codex profile sync failed: {error}", file=sys.stderr)
        return 2
    return 1 if args.check and drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
