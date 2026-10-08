#!/usr/bin/env python3
"""Apply shared Codex defaults while preserving machine-specific configuration."""

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
from typing import Any

ROOT_KEYS = ("model", "model_reasoning_effort", "approval_policy", "sandbox_mode", "web_search")
ROOT_KEY_PATTERN = re.compile(r"^\s*(model|model_reasoning_effort|approval_policy|sandbox_mode|web_search)\s*=")
TABLE_PATTERN = re.compile(r"^\s*\[\[?.*\]\]?\s*(?:#.*)?$")
SECTION_PATTERN = re.compile(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$")
PERMISSION_TABLE = "sandbox_workspace_write"
PERMISSION_KEYS = ("network_access", "writable_roots")
PERMISSION_KEY_PATTERN = re.compile(r"^\s*(network_access|writable_roots)\s*=")
PERMISSION_DOTTED_PATTERN = re.compile(r"^\s*sandbox_workspace_write\.(network_access|writable_roots)\s*=")


def read_profile(path: Path) -> dict[str, Any]:
    """Load and validate the exact shared Codex profile schema from JSON."""
    profile = json.loads(path.read_text(encoding="utf-8"))
    expected_keys = set(ROOT_KEYS) | {PERMISSION_TABLE}
    if not isinstance(profile, dict) or set(profile) != expected_keys:
        raise ValueError(f"profile must contain exactly these keys: {', '.join((*ROOT_KEYS, PERMISSION_TABLE))}")
    if any(not isinstance(profile[key], str) for key in ROOT_KEYS):
        raise ValueError(f"profile root values must be strings: {', '.join(ROOT_KEYS)}")
    permissions = profile[PERMISSION_TABLE]
    if (
        not isinstance(permissions, dict)
        or set(permissions) != set(PERMISSION_KEYS)
        or not isinstance(permissions["network_access"], bool)
        or not isinstance(permissions["writable_roots"], list)
        or any(not isinstance(root, str) for root in permissions["writable_roots"])
    ):
        raise ValueError(f"{PERMISSION_TABLE} must contain network_access and a string-array writable_roots")
    return profile


def render_root_value(key: str, value: str, newline: str = "\n") -> str:
    """Render a profile root setting as a TOML assignment."""
    return f"{key} = {json.dumps(value)}{newline}"


def render_toml_value(value: Any) -> str:
    """Render a supported boolean, string, or string-array TOML value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(item) for item in value) + "]"
    return json.dumps(value)


def resolve_home_roots(profile: dict[str, Any], home: Path) -> dict[str, Any]:
    """Return a profile copy with home-root tokens expanded for one host."""
    resolved = {**profile, PERMISSION_TABLE: dict(profile[PERMISSION_TABLE])}
    home_root = home.expanduser().absolute()
    roots = []
    for root in resolved[PERMISSION_TABLE]["writable_roots"]:
        if root == "$HOME" or root == "~":
            roots.append(str(home_root))
        elif root.startswith("$HOME/"):
            roots.append(str(home_root / root[len("$HOME/"):]))
        elif root.startswith("~/"):
            roots.append(str(home_root / root[2:]))
        else:
            roots.append(root)
    resolved[PERMISSION_TABLE]["writable_roots"] = roots
    return resolved


def merge_profile(original: str, profile: dict[str, Any], home: Path | None = None) -> str:
    """Merge declared defaults while preserving unrelated TOML configuration."""
    profile = resolve_home_roots(profile, home or Path.home())
    root_lines: list[str] = []
    table_lines: list[str] = []
    seen_root: set[str] = set()
    seen_permissions: set[str] = set()
    in_table = False
    permission_table_seen = False
    permission_section_active = False
    dotted_permissions_seen = False

    def append_missing_permission_keys(target: list[str], newline: str) -> None:
        for key in PERMISSION_KEYS:
            if key not in seen_permissions:
                value = profile[PERMISSION_TABLE][key]
                target.append(f"{key} = {render_toml_value(value)}{newline}")
                seen_permissions.add(key)

    for line in original.splitlines(keepends=True):
        clean_line = line.rstrip("\r\n")
        section = SECTION_PATTERN.match(clean_line)
        if TABLE_PATTERN.match(clean_line):
            if permission_section_active:
                newline = "\r\n" if line.endswith("\r\n") else "\n"
                append_missing_permission_keys(table_lines, newline)
            permission_section_active = bool(section and section.group(1).strip() == PERMISSION_TABLE)
            if permission_section_active:
                if permission_table_seen or dotted_permissions_seen:
                    raise ValueError(f"multiple {PERMISSION_TABLE} table definitions")
                permission_table_seen = True
            in_table = True
        if not in_table:
            match = ROOT_KEY_PATTERN.match(line)
            if match:
                key = match.group(1)
                if key in seen_root:
                    raise ValueError(f"duplicate root Codex setting: {key}")
                seen_root.add(key)
                ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
                root_lines.append(render_root_value(key, profile[key], ending or "\n"))
                continue
            dotted = PERMISSION_DOTTED_PATTERN.match(line)
            if dotted:
                key = dotted.group(1)
                if permission_table_seen:
                    raise ValueError(f"{PERMISSION_TABLE} is defined as both dotted keys and a table")
                if key in seen_permissions:
                    raise ValueError(f"duplicate {PERMISSION_TABLE}.{key} setting")
                dotted_permissions_seen = True
                seen_permissions.add(key)
                ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
                root_lines.append(f"{PERMISSION_TABLE}.{key} = {render_toml_value(profile[PERMISSION_TABLE][key])}{ending or chr(10)}")
                continue
            root_lines.append(line)
        else:
            if permission_section_active:
                match = PERMISSION_KEY_PATTERN.match(line)
                if match:
                    key = match.group(1)
                    if key in seen_permissions:
                        raise ValueError(f"duplicate {PERMISSION_TABLE}.{key} setting")
                    seen_permissions.add(key)
                    ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
                    table_lines.append(f"{key} = {render_toml_value(profile[PERMISSION_TABLE][key])}{ending or chr(10)}")
                    continue
            table_lines.append(line)

    newline = "\r\n" if "\r\n" in original else "\n"
    if permission_section_active:
        append_missing_permission_keys(table_lines, newline)

    missing = [key for key in ROOT_KEYS if key not in seen_root]
    if missing:
        if root_lines and not root_lines[-1].endswith(("\n", "\r")):
            root_lines[-1] += newline
        if root_lines and root_lines[-1].strip():
            root_lines.append(newline)
        root_lines.extend(render_root_value(key, profile[key], newline) for key in missing)
        if table_lines and root_lines and root_lines[-1].strip():
            root_lines.append(newline)

    if not permission_table_seen and not dotted_permissions_seen:
        if table_lines and table_lines[-1].strip():
            table_lines.append(newline)
        table_lines.append(f"[{PERMISSION_TABLE}]{newline}")
        append_missing_permission_keys(table_lines, newline)
    elif dotted_permissions_seen:
        for key in PERMISSION_KEYS:
            if key not in seen_permissions:
                root_lines.append(f"{PERMISSION_TABLE}.{key} = {render_toml_value(profile[PERMISSION_TABLE][key])}{newline}")
                seen_permissions.add(key)

    merged = "".join(root_lines + table_lines)
    tomllib.loads(merged)
    return merged


def apply_profile(config_path: Path, profile: dict[str, Any], write: bool, home: Path | None = None) -> bool:
    """Check profile drift or atomically write the merged config with a backup."""
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(config_path.parent, 0o700)
    except OSError:
        pass
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if original:
        tomllib.loads(original)
    merged = merge_profile(original, profile, home)
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
    """Run the profile synchronizer's explicit ``--check`` or ``--write`` mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "config.toml")
    parser.add_argument("--home", type=Path, default=Path.home(), help="host user's home directory for the $HOME writable-root token")
    parser.add_argument("--profile", type=Path, default=Path(__file__).resolve().parents[1] / "config/codex-fleet-profile.json")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="report drift without writing")
    mode.add_argument("--write", action="store_true", help="apply the profile and preserve other settings")
    args = parser.parse_args()
    try:
        drift = apply_profile(args.config, read_profile(args.profile), args.write, args.home)
    except (OSError, ValueError, tomllib.TOMLDecodeError, json.JSONDecodeError) as error:
        print(f"Codex profile sync failed: {error}", file=sys.stderr)
        return 2
    return 1 if args.check and drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
