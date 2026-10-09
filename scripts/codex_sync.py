#!/usr/bin/env python3
"""Bounded Codex fleet inspection and sync operations.

The dashboard sends one JSON request on stdin and receives content-free status
or a short-lived, in-memory transfer snapshot on stdout. This helper is also
sent over the inventory's strict SSH route with ``python3 -c``; it never accepts
an arbitrary command or destination path from the browser.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
from typing import Any

MAX_TRANSFER_BYTES = 24 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024
SAFE_PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.config\.toml$")
SAFE_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,100}$")
SAFE_PLUGIN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")
SAFE_MARKETPLACE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")
OPENAI_MANAGED_MARKETPLACES = frozenset({
    "openai-bundled",
    "openai-curated",
    "openai-curated-remote",
    "openai-primary-runtime",
})
VERSION_RE = re.compile(r"^(?:codex-cli\s+)?(\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)$", re.IGNORECASE)
SECRET_KEY_RE = re.compile(r"(?:secret|token|password|credential|api[_-]?key|private[_-]?key|authorization)", re.IGNORECASE)
SECRET_CONTENT_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\s*[:=]\s*[\"']?[^\s\"']{12,})"
)
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".cache", ".system", "system"}
SKIP_FILES = {".ds_store", "thumbs.db"}

SAFE_STRING_VALUES: dict[str, set[str] | None] = {
    "model": None,
    "model_reasoning_effort": {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"},
    "plan_mode_reasoning_effort": {"minimal", "low", "medium", "high", "xhigh", "max", "ultra"},
    "approval_policy": {"never", "on-request", "on-failure", "untrusted"},
    "sandbox_mode": {"read-only", "workspace-write", "danger-full-access"},
    "web_search": {"disabled", "cached", "live"},
    "personality": {"friendly", "pragmatic", "none"},
    "model_verbosity": {"low", "medium", "high"},
    "service_tier": {"auto", "priority", "flex"},
}


class SyncError(RuntimeError):
    """A safe, user-displayable error from the bounded sync helper."""


def _emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: pathlib.Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _is_within(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _is_managed_cache(path: pathlib.Path, codex_home: pathlib.Path) -> bool:
    home = pathlib.Path.home().resolve()
    roots = [codex_home / "plugins" / "cache", codex_home / ".tmp", home / ".cache"]
    return any(_is_within(path, root) for root in roots)


def _assert_no_symlink_components(path: pathlib.Path, anchor: pathlib.Path) -> pathlib.Path:
    try:
        relative = path.relative_to(anchor)
    except ValueError as error:
        raise SyncError("A sync destination escaped its user-owned root") from error
    cursor = anchor
    if cursor.is_symlink():
        raise SyncError("A sync destination contains a symbolic link")
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SyncError("A sync destination contains a symbolic link")
    return cursor


def _private_directory(path: pathlib.Path, anchor: pathlib.Path) -> pathlib.Path:
    directory = _assert_no_symlink_components(path, anchor)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not directory.is_dir():
        raise SyncError("A private sync directory is not a regular directory")
    cursor = directory
    while cursor != anchor:
        os.chmod(cursor, 0o700)
        cursor = cursor.parent
    return directory


def _resolve_codex_home(override: Any) -> pathlib.Path:
    home = pathlib.Path.home().resolve()
    raw = override if isinstance(override, str) and override else os.environ.get("CODEX_HOME")
    if not raw:
        return (home / ".codex").resolve()
    raw = raw.strip()
    if "\x00" in raw or "\n" in raw or "\r" in raw:
        raise SyncError("Invalid CODEX_HOME inventory override")
    if raw == "~":
        return home
    if raw.startswith("~/"):
        suffix = pathlib.PurePosixPath(raw[2:])
        if ".." in suffix.parts:
            raise SyncError("Invalid CODEX_HOME inventory override")
        return (home / pathlib.Path(*suffix.parts)).resolve()
    candidate = pathlib.Path(raw)
    if not candidate.is_absolute() or ".." in candidate.parts:
        raise SyncError("CODEX_HOME overrides must be absolute or start with ~/ and cannot contain ..")
    return candidate.resolve()


def _codex_env(codex_home: pathlib.Path) -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    env.setdefault("HOME", str(pathlib.Path.home()))
    return env


def _codex_path(codex_home: pathlib.Path) -> str | None:
    home = pathlib.Path.home()
    candidates = [
        home / ".local/bin/codex",
        codex_home / "packages/app-server-daemon/current/bin/codex",
        codex_home / "packages/standalone/current/bin/codex",
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("codex")


def _run(args: list[str], *, env: dict[str, str], timeout: int = 15, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, input=input_text, capture_output=True, text=True, timeout=timeout, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SyncError("A bounded Codex sync command did not complete") from error


def _version_from_output(output: str) -> str | None:
    for line in output.splitlines():
        match = VERSION_RE.fullmatch(line.strip())
        if match:
            return match.group(1)
        match = re.search(r"\b(\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?)\b", line)
        if match:
            return match.group(1)
    return None


def _normalize_host_paths(value: Any, home: pathlib.Path) -> Any:
    if isinstance(value, str):
        text = value.replace(str(home), "~")
        return re.sub(r"/(?:Users|home)/[^/\s]+", lambda match: "/Users/<home>" if "/Users/" in match.group(0) else "/home/<home>", text)
    if isinstance(value, list):
        return [_normalize_host_paths(item, home) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_host_paths(item, home) for key, item in value.items()}
    return value


def _redact_and_normalize(value: Any, home: pathlib.Path, parent_key: str = "") -> Any:
    if SECRET_KEY_RE.search(parent_key):
        return "<preserved-secret>"
    if isinstance(value, dict):
        return {
            str(key): _redact_and_normalize(item, home, str(key))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not SECRET_KEY_RE.search(str(key))
        }
    if isinstance(value, list):
        return [_redact_and_normalize(item, home, parent_key) for item in value]
    return _normalize_host_paths(value, home)


def _toml_state(path: pathlib.Path, filename: str, home: pathlib.Path) -> dict[str, Any]:
    if path.is_symlink():
        return {"name": filename, "exists": True, "hash": None, "portable": {}, "unclassified": {"<symlink>": "blocked"}, "invalid": True}
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return {"name": filename, "exists": True, "hash": None, "portable": {}, "unclassified": {"<file-too-large>": "blocked"}, "invalid": True}
        raw = path.read_bytes()
        parsed = tomllib.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return {"name": filename, "exists": False, "hash": None, "portable": {}, "unclassified": {}, "invalid": False}
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {"name": filename, "exists": True, "hash": _file_hash(path), "portable": {}, "unclassified": {"<invalid-toml>": "invalid"}, "invalid": True}

    portable: dict[str, Any] = {}
    unclassified: dict[str, str] = {}
    for key, value in parsed.items():
        if key in SAFE_STRING_VALUES:
            allowed = SAFE_STRING_VALUES[key]
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,119}", value) and not SECRET_CONTENT_RE.search(value) and (allowed is None or value in allowed):
                portable[key] = value
            else:
                unclassified[key] = _hash(_redact_and_normalize(value, home))
            continue
        if key == "features" and isinstance(value, dict):
            for feature, feature_value in value.items():
                if re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(feature)) and isinstance(feature_value, bool):
                    portable[f"features.{feature}"] = feature_value
                else:
                    unclassified[f"features.{feature}"] = _hash(_redact_and_normalize(feature_value, home, str(feature)))
            continue
        if key == "sandbox_workspace_write" and isinstance(value, dict):
            for nested_key, nested_value in value.items():
                if nested_key == "network_access" and isinstance(nested_value, bool):
                    portable["sandbox_workspace_write.network_access"] = nested_value
                else:
                    unclassified[f"sandbox_workspace_write.{nested_key}"] = _hash(_redact_and_normalize(nested_value, home, str(nested_key)))
            continue
        # Names that look like credential fields are intentionally absent from
        # summaries and comparison hashes. Their complete target values stay put.
        if SECRET_KEY_RE.search(str(key)):
            continue
        unclassified[str(key)] = _hash(_redact_and_normalize(value, home, str(key)))

    return {"name": filename, "exists": True, "hash": hashlib.sha256(raw).hexdigest(), "portable": portable, "unclassified": unclassified, "invalid": False}


def _profile_files(codex_home: pathlib.Path) -> list[str]:
    found: list[str] = []
    try:
        for child in codex_home.iterdir():
            if child.is_file() and SAFE_PROFILE.fullmatch(child.name):
                found.append(child.name)
    except OSError:
        return []
    return sorted(found)


def _toml_inventory(codex_home: pathlib.Path, home: pathlib.Path) -> dict[str, Any]:
    names = ["config.toml", *_profile_files(codex_home)]
    states = [_toml_state(codex_home / name, name, home) for name in names]
    return {
        "files": states,
        "profileNames": names[1:],
        "hash": _hash([(item["name"], item["hash"]) for item in states]),
    }


def _marketplace_source(value: Any, root: Any, codex_home: pathlib.Path, marketplace_name: str | None = None) -> dict[str, Any]:
    root_path: pathlib.Path | None = None
    if isinstance(root, str) and root:
        try:
            root_path = pathlib.Path(root).expanduser().resolve()
        except OSError:
            root_path = None
    source_text = ""
    source_kind = "unknown"
    ref: str | None = None
    sparse: list[str] = []
    if isinstance(value, str):
        source_text = value.strip()
        if source_text.startswith(("https://", "http://", "ssh://", "git@")) or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:@[A-Za-z0-9._/-]+)?", source_text):
            source_kind = "git"
        elif source_text.startswith(("/", "~/")):
            source_kind = "local"
    elif isinstance(value, dict):
        ref_value = value.get("ref")
        if isinstance(ref_value, str) and re.fullmatch(r"[A-Za-z0-9._/-]{1,160}", ref_value):
            ref = ref_value
        sparse_value = value.get("sparsePaths", value.get("sparse_paths", []))
        if isinstance(sparse_value, list):
            sparse = [item for item in sparse_value if isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9._/-]{1,180}", item) and ".." not in pathlib.PurePosixPath(item).parts][:20]
        for key in ("gitUrl", "url", "repository", "repo", "source", "path", "value"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate and candidate not in {"git", "github", "local"}:
                source_text = candidate.strip()
                break
        kind = str(value.get("type", value.get("kind", value.get("sourceType", value.get("source", ""))))).lower()
        if kind in {"local", "directory"}:
            source_kind = "local"
        elif kind in {"git", "github", "gitlab", "url"}:
            source_kind = "git"
        if source_kind == "unknown" and (source_text.startswith(("https://", "http://", "ssh://", "git@")) or re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:@[A-Za-z0-9._/-]+)?", source_text)):
            source_kind = "git"
        elif source_kind == "unknown" and source_text.startswith(("/", "~/")):
            source_kind = "local"
    managed_cache = bool(root_path and root_path.exists() and _is_managed_cache(root_path, codex_home))
    if marketplace_name in OPENAI_MANAGED_MARKETPLACES and managed_cache and source_kind in {"local", "unknown"}:
        # These exact Codex-owned marketplace identifiers are refreshed by
        # Codex itself. Their generated roots are inventory evidence only;
        # they are never copied as plugin package sources.
        source_kind = "managed"
    elif managed_cache and source_kind == "local":
        # Codex snapshots, bundled marketplaces, and package caches are not
        # editable source packages and may never be copied to another host.
        source_kind = "unknown"
    if source_kind == "git":
        if not _safe_remote_source(source_text):
            source_kind = "unknown"
        else:
            source_text = source_text
    elif source_kind in {"local", "managed"}:
        source_text = ""
    return {"kind": source_kind, "source": source_text if source_kind == "git" else None, "ref": ref, "sparsePaths": sparse, "root": str(root_path) if root_path else None}


def _safe_remote_source(source: str) -> bool:
    if not source or len(source) > 500 or any(char in source for char in "\r\n\x00"):
        return False
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:@[A-Za-z0-9._/-]+)?", source):
        return True
    if source.startswith("https://"):
        from urllib.parse import urlsplit
        parts = urlsplit(source)
        return bool(parts.hostname) and not parts.username and not parts.password and not parts.query and not parts.fragment
    if source.startswith("ssh://"):
        from urllib.parse import urlsplit
        parts = urlsplit(source)
        return bool(parts.hostname) and not parts.username and not parts.password and not parts.query and not parts.fragment
    if re.fullmatch(r"git@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+(?:\.git)?", source):
        return ".." not in pathlib.PurePosixPath(source.split(":", 1)[1]).parts
    return False


def _read_plugin_cli(codex: str, env: dict[str, str], codex_home: pathlib.Path, include_package_content: bool) -> dict[str, Any]:
    marketplaces_result = _run([codex, "plugin", "marketplace", "list", "--json"], env=env)
    plugins_result = _run([codex, "plugin", "list", "--json"], env=env)
    if marketplaces_result.returncode != 0 or plugins_result.returncode != 0:
        return {"available": False, "error": "Codex plugin commands are not available", "marketplaces": [], "plugins": [], "localPackages": {}, "hash": _hash("unavailable")}
    try:
        marketplace_json = json.loads(marketplaces_result.stdout)
        plugins_json = json.loads(plugins_result.stdout)
    except json.JSONDecodeError:
        return {"available": False, "error": "Codex returned an unrecognized plugin inventory", "marketplaces": [], "plugins": [], "localPackages": {}, "hash": _hash("invalid")}

    rows = marketplace_json.get("marketplaces", []) if isinstance(marketplace_json, dict) else marketplace_json
    if not isinstance(rows, list):
        rows = []
    marketplaces: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or not SAFE_MARKETPLACE_NAME.fullmatch(name):
            continue
        descriptor = _marketplace_source(item.get("marketplaceSource", item.get("source")), item.get("root", item.get("installedRoot")), codex_home, name)
        if descriptor["kind"] == "unknown":
            continue
        marketplaces.append({"name": name, **descriptor})

    installed = plugins_json.get("installed", []) if isinstance(plugins_json, dict) else []
    if not isinstance(installed, list):
        installed = []
    plugins: list[dict[str, Any]] = []
    local_packages: dict[str, Any] = {}
    marketplace_map = {entry["name"]: entry for entry in marketplaces}
    for item in installed:
        market = item.get("marketplaceName") or item.get("marketplace") if isinstance(item, dict) else None
        if isinstance(market, str) and market in OPENAI_MANAGED_MARKETPLACES and market not in marketplace_map:
            # Some Codex releases list installed plugins under the canonical
            # OpenAI marketplace ID while marketplace list exposes a broader
            # generated registry under another ID. The fixed ID still means
            # Codex owns installation; no cache path is inferred or copied.
            descriptor = {"name": market, "kind": "managed", "source": None, "ref": None, "sparsePaths": [], "root": None}
            marketplaces.append(descriptor)
            marketplace_map[market] = descriptor
    for item in installed:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        market = item.get("marketplaceName") or item.get("marketplace")
        if not isinstance(name, str) or not SAFE_PLUGIN_NAME.fullmatch(name) or not isinstance(market, str) or not SAFE_MARKETPLACE_NAME.fullmatch(market):
            continue
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            enabled = True
        market_info = marketplace_map.get(market, {"name": market, "kind": "unknown", "source": None, "ref": None, "sparsePaths": [], "root": None})
        source_info = item.get("source")
        if market_info["kind"] != "managed" and isinstance(source_info, dict) and str(source_info.get("type", source_info.get("sourceType", source_info.get("kind", "")))).lower() == "local":
            market_info = {**market_info, "kind": "local"}
        version = item.get("version")
        record = {"name": name, "marketplaceName": market, "enabled": enabled, "marketplaceKind": market_info["kind"], "selector": f"{name}@{market}"}
        if isinstance(version, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,100}", version):
            record["version"] = version
        plugins.append(record)
        if market_info["kind"] == "local":
            package = _find_local_plugin_package(market_info, name, codex_home)
            if package["ok"]:
                if include_package_content:
                    local_packages[record["selector"]] = package["files"]
                record["packageHash"] = package["hash"]
            else:
                record["transferBlocked"] = True

    plugins.sort(key=lambda entry: (entry["marketplaceName"].lower(), entry["name"].lower()))
    marketplaces.sort(key=lambda entry: entry["name"].lower())
    internal_marketplaces = [
        {key: value for key, value in item.items() if key != "root"}
        for item in marketplaces
    ]
    return {
        "available": True,
        "error": None,
        "marketplaces": marketplaces,
        "plugins": plugins,
        "localPackages": local_packages,
        "hash": _hash({"marketplaces": internal_marketplaces, "plugins": plugins}),
    }


def _safe_file_content(data: bytes) -> bool:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return SECRET_CONTENT_RE.search(text) is None


def _collect_regular_tree(root: pathlib.Path, *, require_skill: bool = False) -> tuple[dict[str, str], str | None]:
    if root.is_symlink() or not root.is_dir():
        return {}, "source is not a regular directory"
    files: dict[str, str] = {}
    total = 0
    has_skill = False
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if any("\\" in part or any(ord(char) < 32 or ord(char) == 127 for char in part) for part in relative.parts):
            return {}, "source contains an unsafe file name"
        if any(part in SKIP_DIRS or part.startswith(".codex-sync") for part in relative.parts):
            continue
        if path.is_symlink():
            return {}, "source contains a symbolic link"
        if path.is_dir():
            continue
        if not path.is_file() or path.name.lower() in SKIP_FILES:
            continue
        if path.name.lower().startswith(".env") or SECRET_KEY_RE.search(path.name):
            return {}, "source contains a credential-named file"
        if path.stat().st_size > MAX_FILE_BYTES:
            return {}, "a source file exceeds the transfer limit"
        data = path.read_bytes()
        if not _safe_file_content(data):
            return {}, "a source file looks like it contains credentials"
        total += len(data)
        if total > MAX_TRANSFER_BYTES:
            return {}, "source exceeds the transfer size limit"
        if relative.as_posix().lower() == "skill.md" or relative.name.lower() == "skill.md":
            has_skill = True
        files[relative.as_posix()] = base64.b64encode(data).decode("ascii")
    if require_skill and not has_skill:
        return {}, "skill directory has no SKILL.md"
    return files, None


def _find_local_plugin_package(marketplace: dict[str, Any], plugin_name: str, codex_home: pathlib.Path) -> dict[str, Any]:
    root_value = marketplace.get("root")
    if not isinstance(root_value, str):
        return {"ok": False, "reason": "local marketplace root is unavailable"}
    root = pathlib.Path(root_value).resolve()
    candidates = [root / "marketplace.json", root / ".agents/plugins/marketplace.json"]
    catalog = None
    for candidate in candidates:
        try:
            if candidate.is_symlink():
                continue
            parsed = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(parsed, dict) and isinstance(parsed.get("plugins"), list):
                catalog = parsed
                break
        except (OSError, json.JSONDecodeError):
            continue
    if not catalog:
        return {"ok": False, "reason": "local marketplace catalog is unavailable"}
    for item in catalog["plugins"]:
        if not isinstance(item, dict) or item.get("name") != plugin_name:
            continue
        source = item.get("source")
        if not isinstance(source, dict) or source.get("source") != "local" or not isinstance(source.get("path"), str):
            return {"ok": False, "reason": "plugin does not have a local folder source"}
        relative = pathlib.PurePosixPath(source["path"])
        if relative.is_absolute() or ".." in relative.parts or not source["path"].startswith("./"):
            return {"ok": False, "reason": "plugin source path is unsafe"}
        package_root = (root / pathlib.Path(*relative.parts)).resolve()
        try:
            package_root.relative_to(root)
        except ValueError:
            return {"ok": False, "reason": "plugin source escapes its local marketplace"}
        if _is_managed_cache(package_root, codex_home):
            return {"ok": False, "reason": "plugin source points into a managed cache"}
        manifest = package_root / "plugin.json"
        if not manifest.is_file():
            manifest = package_root / ".codex-plugin/plugin.json"
        try:
            if manifest.is_symlink():
                return {"ok": False, "reason": "plugin manifest is a symbolic link"}
            decoded = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"ok": False, "reason": "plugin manifest is invalid"}
        if not isinstance(decoded, dict) or decoded.get("name") != plugin_name:
            return {"ok": False, "reason": "plugin manifest name does not match the marketplace entry"}
        files, error = _collect_regular_tree(package_root)
        if error:
            return {"ok": False, "reason": error}
        if not files:
            return {"ok": False, "reason": "plugin package is empty"}
        return {"ok": True, "files": files, "hash": _hash(files)}
    return {"ok": False, "reason": "plugin was not found in the local marketplace catalog"}


def _skill_inventory(home: pathlib.Path, codex_home: pathlib.Path, include_content: bool) -> dict[str, Any]:
    roots = {"agents": home / ".agents/skills", "codex": codex_home / "skills"}
    anchors = {"agents": home, "codex": codex_home}
    skills: dict[str, Any] = {}
    blocked: list[str] = []
    for kind, root in roots.items():
        try:
            _assert_no_symlink_components(root, anchors[kind])
        except SyncError:
            blocked.append(f"{kind}/<unsafe-root>")
            continue
        if root.exists() and not root.is_dir():
            blocked.append(f"{kind}/<unsafe-root>")
            continue
        try:
            entries = sorted(root.iterdir()) if root.is_dir() and not root.is_symlink() else []
        except OSError:
            entries = []
        for entry in entries:
            if entry.name in SKIP_DIRS or entry.name.startswith(".") or not SAFE_SLUG.fullmatch(entry.name):
                continue
            if entry.is_symlink():
                blocked.append(f"{kind}/{entry.name}")
                continue
            if not entry.is_dir():
                continue
            files, error = _collect_regular_tree(entry, require_skill=True)
            key = f"{kind}/{entry.name}"
            if error:
                blocked.append(key)
                continue
            file_hashes = {
                relative: hashlib.sha256(base64.b64decode(encoded)).hexdigest()
                for relative, encoded in files.items()
            }
            content = files if include_content else {}
            skills[key] = {"hash": _hash(file_hashes), "files": content, "fileNames": sorted(files), "fileHashes": file_hashes}
    return {"skills": skills, "blocked": blocked, "hash": _hash({key: row["hash"] for key, row in sorted(skills.items())})}


def _active_turn_state(codex: str, env: dict[str, str], codex_home: pathlib.Path) -> dict[str, Any]:
    """Ask the local app-server for loaded-thread status, when it exposes it.

    A missing or unfamiliar activity field is unknown and therefore blocks an
    automatic restart. Loaded threads alone are not treated as active turns.
    """
    socket_path = codex_home / "app-server-control/app-server-control.sock"
    if not socket_path.exists():
        return {"count": None, "known": False}
    proc: subprocess.Popen[bytes] | None = None
    try:
        proc = subprocess.Popen(
            [codex, "app-server", "proxy", "--sock", str(socket_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            bufsize=0,
        )
        if proc.stdin is None or proc.stdout is None:
            return {"count": None, "known": False}
        fd = proc.stdout.fileno()
        buffer = bytearray()

        def read_until(token: bytes, deadline: float) -> bytes:
            while token not in buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                    raise TimeoutError
                chunk = os.read(fd, 65536)
                if not chunk:
                    raise EOFError
                buffer.extend(chunk)
            end = buffer.index(token) + len(token)
            value = bytes(buffer[:end])
            del buffer[:end]
            return value

        def read_exact(size: int, deadline: float) -> bytes:
            while len(buffer) < size:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                    raise TimeoutError
                chunk = os.read(fd, 65536)
                if not chunk:
                    raise EOFError
                buffer.extend(chunk)
            value = bytes(buffer[:size])
            del buffer[:size]
            return value

        def send_frame(value: dict[str, Any]) -> None:
            data = json.dumps(value, separators=(",", ":")).encode("utf-8")
            mask = os.urandom(4)
            length = len(data)
            header = bytearray([0x81])
            if length < 126:
                header.append(0x80 | length)
            elif length < 65536:
                header.extend([0x80 | 126])
                header.extend(length.to_bytes(2, "big"))
            else:
                header.extend([0x80 | 127])
                header.extend(length.to_bytes(8, "big"))
            masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
            proc.stdin.write(bytes(header) + mask + masked)
            proc.stdin.flush()

        def read_message(deadline: float) -> dict[str, Any]:
            while True:
                first, second = read_exact(2, deadline)
                opcode, length = first & 0x0F, second & 0x7F
                if length == 126:
                    length = int.from_bytes(read_exact(2, deadline), "big")
                elif length == 127:
                    length = int.from_bytes(read_exact(8, deadline), "big")
                if length > 2_000_000:
                    raise ValueError
                mask = read_exact(4, deadline) if second & 0x80 else b""
                data = read_exact(length, deadline)
                if mask:
                    data = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
                if opcode == 9:
                    proc.stdin.write(b"\x8a\x00")
                    proc.stdin.flush()
                    continue
                if opcode != 1:
                    continue
                value = json.loads(data.decode("utf-8"))
                if isinstance(value, dict):
                    return value

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        proc.stdin.write((
            "GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode("ascii"))
        proc.stdin.flush()
        deadline = time.monotonic() + 8
        header = read_until(b"\r\n\r\n", deadline).decode("utf-8", errors="replace")
        if not header.startswith("HTTP/1.1 101"):
            return {"count": None, "known": False}
        send_frame({"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "codex-fleet-sync", "title": "Codex Fleet Sync", "version": "0.1.0"}, "capabilities": {"experimentalApi": True}}})
        initialized = read_message(time.monotonic() + 8)
        if initialized.get("id") != 1 or "error" in initialized:
            return {"count": None, "known": False}
        send_frame({"method": "initialized", "params": {}})
        send_frame({"id": 2, "method": "thread/list", "params": {"limit": 100, "modelProviders": [], "includeTurns": False}})
        response: dict[str, Any] | None = None
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            message = read_message(deadline)
            if message.get("id") == 2:
                response = message
                break
        if not isinstance(response, dict) or "error" in response:
            return {"count": None, "known": False}
        result = response.get("result")
        rows = result.get("data", result.get("threads", [])) if isinstance(result, dict) else []
        if not isinstance(rows, list) or len(rows) >= 100:
            return {"count": None, "known": False}
        active = 0
        active_threads: list[tuple[str, dict[str, Any]]] = []
        for row in rows:
            if not isinstance(row, dict):
                return {"count": None, "known": False}
            status = row.get("status")
            if not isinstance(status, dict):
                return {"count": None, "known": False}
            status_type = status.get("type")
            if status_type in {"idle", "notLoaded", "not_loaded"}:
                continue
            if status_type != "active":
                return {"count": None, "known": False}
            thread_id = row.get("id") or row.get("threadId")
            if not isinstance(thread_id, str) or not thread_id:
                return {"count": None, "known": False}
            active_threads.append((thread_id, status))
        # An active thread can stay resident after its turn ends. Ask for its
        # latest turn metadata, never thread items or conversation content.
        for index, (thread_id, status) in enumerate(active_threads, start=3):
            request_id = index + 1
            send_frame({"id": request_id, "method": "thread/turns/list", "params": {"threadId": thread_id, "limit": 1}})
            turn_response = None
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                message = read_message(deadline)
                if message.get("id") == request_id:
                    turn_response = message
                    break
            if not isinstance(turn_response, dict) or "error" in turn_response:
                return {"count": None, "known": False}
            turn_result = turn_response.get("result")
            turns = turn_result.get("data", turn_result.get("turns", [])) if isinstance(turn_result, dict) else []
            if not isinstance(turns, list):
                return {"count": None, "known": False}
            if turns:
                latest_status = turns[0].get("status") if isinstance(turns[0], dict) else None
                if latest_status in {"inProgress", "in_progress"}:
                    active += 1
                elif latest_status not in {"completed", "interrupted", "failed", "completed_with_errors", "cancelled"}:
                    return {"count": None, "known": False}
            else:
                flags = status.get("activeFlags")
                if isinstance(flags, list) and any("approval" in str(flag).lower() or "userinput" in str(flag).lower() for flag in flags):
                    active += 1
                elif not isinstance(flags, list) or flags:
                    return {"count": None, "known": False}
        return {"count": active, "known": True}
    except Exception:
        return {"count": None, "known": False}
    finally:
        if proc is not None:
            try:
                if proc.stdin:
                    proc.stdin.close()
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


def inspect(codex_home: pathlib.Path, include_content: bool = False) -> dict[str, Any]:
    home = pathlib.Path.home().resolve()
    env = _codex_env(codex_home)
    codex = _codex_path(codex_home)
    cli_version = None
    runtime_version = None
    runtime_status = "unavailable"
    plugin_state: dict[str, Any] = {"available": False, "marketplaces": [], "plugins": [], "localPackages": {}, "hash": _hash("no-codex")}
    active_turns = {"count": None, "known": False}
    if codex:
        version_result = _run([codex, "--version"], env=env, timeout=12)
        if version_result.returncode == 0:
            cli_version = _version_from_output(version_result.stdout)
        runtime_result = _run([codex, "app-server", "daemon", "version"], env=env, timeout=12)
        try:
            runtime_json = json.loads(runtime_result.stdout)
            runtime_version = runtime_json.get("appServerVersion") or runtime_json.get("managedCodexVersion")
            runtime_status = runtime_json.get("status", "unknown")
        except (json.JSONDecodeError, AttributeError):
            runtime_status = "unknown" if runtime_result.returncode == 0 else "unavailable"
        plugin_state = _read_plugin_cli(codex, env, codex_home, include_content)
        if runtime_status == "running":
            active_turns = _active_turn_state(codex, env, codex_home)
    config = _toml_inventory(codex_home, home)
    skills = _skill_inventory(home, codex_home, include_content)
    if include_content:
        transfer_size = sum(
            (len(value) * 3) // 4
            for package in plugin_state.get("localPackages", {}).values()
            for value in package.values()
            if isinstance(value, str)
        ) + sum(
            (len(value) * 3) // 4
            for skill in skills["skills"].values()
            for value in skill["files"].values()
            if isinstance(value, str)
        )
        if transfer_size > MAX_TRANSFER_BYTES:
            for plugin in plugin_state.get("plugins", []):
                if plugin.get("marketplaceKind") == "local":
                    plugin["transferBlocked"] = True
            plugin_state["localPackages"] = {}
            for skill in skills["skills"].values():
                skill["files"] = {}
                skill["transferBlocked"] = True
            skills["blocked"].append("transfer-size-limit")
    public_marketplaces = [
        {key: value for key, value in item.items() if key not in {"root", "source"}}
        for item in plugin_state.get("marketplaces", [])
    ]
    public_plugins = [{key: value for key, value in item.items() if key not in {"transferBlocked", "packageHash"}} for item in plugin_state.get("plugins", [])]
    snapshot_hash = _hash({
        "cliVersion": cli_version,
        "runtimeVersion": runtime_version,
        "runtimeStatus": runtime_status,
        "configHash": config["hash"],
        "pluginHash": plugin_state["hash"],
        "skillHash": skills["hash"],
    })
    override = os.environ.get("CODEX_HOME")
    try:
        relative_home = codex_home.relative_to(home)
        display_home = "~" if str(relative_home) == "." else "~/" + relative_home.as_posix()
    except ValueError:
        display_home = "custom CODEX_HOME"
    home_status = {"configured": True, "exists": codex_home.is_dir(), "label": display_home, "source": "inventory" if override else "environment/default"}
    return {
        "cliVersion": cli_version,
        "runtimeVersion": runtime_version if isinstance(runtime_version, str) else None,
        "runtimeStatus": runtime_status,
        "activeTurns": active_turns,
        "codexHome": home_status,
        "config": config,
        "plugins": {"available": plugin_state.get("available", False), "error": plugin_state.get("error"), "marketplaces": plugin_state.get("marketplaces", []), "plugins": plugin_state.get("plugins", []), "localPackages": plugin_state.get("localPackages", {}), "hash": plugin_state.get("hash")},
        "skills": skills,
        "snapshotHash": snapshot_hash,
        "public": {
            "cliVersion": cli_version,
            "runtimeVersion": runtime_version if isinstance(runtime_version, str) else None,
            "runtimeStatus": runtime_status,
            "activeTurns": active_turns,
            "codexHome": home_status,
            "config": {"files": [{"name": row["name"], "exists": row["exists"], "portable": row["portable"], "unclassifiedKeys": sorted(row["unclassified"]), "invalid": row["invalid"]} for row in config["files"]], "profileNames": config["profileNames"]},
            "plugins": {"available": plugin_state.get("available", False), "marketplaces": public_marketplaces, "plugins": public_plugins},
            "skills": {"names": sorted(skills["skills"]), "blocked": skills["blocked"]},
            "snapshotHash": snapshot_hash,
        },
    }


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise SyncError("Only classified scalar Codex settings can be applied")


def _toml_value_lines_end(lines: list[str], start: int) -> int:
    """Find the last line of a TOML value, including multiline arrays/strings."""
    quote: str | None = None
    triple = False
    escaped = False
    depth = 0
    for index in range(start, len(lines)):
        line = lines[index]
        cursor = 0
        while cursor < len(line):
            char = line[cursor]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\" and quote == '"':
                    escaped = True
                elif triple and line.startswith(quote * 3, cursor):
                    quote = None
                    triple = False
                    cursor += 2
                elif not triple and char == quote:
                    quote = None
            else:
                if char == "#":
                    break
                if char in "\"'":
                    quote = char
                    triple = line.startswith(char * 3, cursor)
                    if triple:
                        cursor += 2
                elif char in "[{":
                    depth += 1
                elif char in "]}":
                    depth = max(0, depth - 1)
            cursor += 1
        if quote is None and depth == 0:
            return index + 1
    return len(lines)


def _patch_toml_key(text: str, section: str | None, key: str, value: Any | None) -> str:
    lines = text.splitlines(keepends=True)
    if not lines:
        lines = []
    target_header = f"[{section}]" if section else None
    section_start = 0
    section_end = len(lines)
    if section:
        section_start = -1
        for idx, line in enumerate(lines):
            if line.strip() == target_header:
                section_start = idx + 1
                section_end = len(lines)
                for next_idx in range(section_start, len(lines)):
                    if re.match(r"^\s*\[\[?", lines[next_idx]):
                        section_end = next_idx
                        break
                break
        if section_start < 0:
            if value is None:
                return text
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            if lines and lines[-1].strip():
                lines.append("\n")
            lines.extend([f"[{section}]\n", f"{key} = {_toml_scalar(value)}\n"])
            return "".join(lines)
    else:
        section_end = next((idx for idx, line in enumerate(lines) if re.match(r"^\s*\[\[?", line)), len(lines))

    assignment = re.compile(rf"^\s*{re.escape(key)}\s*=")
    found = None
    for idx in range(section_start, section_end):
        if assignment.match(lines[idx]):
            found = idx
            break
    if found is not None:
        end = _toml_value_lines_end(lines, found)
        replacement = [] if value is None else [f"{key} = {_toml_scalar(value)}\n"]
        lines[found:end] = replacement
        return "".join(lines)
    if value is None:
        return text
    insertion = section_end
    if not section:
        # Insert root keys before the first table. Keep all current table content.
        insertion = section_end
    line = f"{key} = {_toml_scalar(value)}\n"
    if insertion > 0 and lines[insertion - 1].strip():
        lines.insert(insertion, "\n")
        insertion += 1
    lines.insert(insertion, line)
    return "".join(lines)


def _setting_location(name: str) -> tuple[str | None, str]:
    if name.startswith("features."):
        key = name.split(".", 1)[1]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", key):
            raise SyncError("Invalid feature setting")
        return "features", key
    if name == "sandbox_workspace_write.network_access":
        return "sandbox_workspace_write", "network_access"
    if name in SAFE_STRING_VALUES:
        return None, name
    raise SyncError("Unclassified setting cannot be applied")


def _backup_file(path: pathlib.Path, backup_root: pathlib.Path, run_id: str, codex_home: pathlib.Path) -> pathlib.Path | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise SyncError("A Codex config path is not a regular file")
    backup_path = backup_root / f"{path.name}.{run_id}.bak"
    _private_directory(backup_path.parent, codex_home)
    shutil.copy2(path, backup_path)
    os.chmod(backup_path, 0o600)
    return backup_path


def _atomic_write(path: pathlib.Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode & 0o600)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _apply_configs(codex_home: pathlib.Path, actions: Any, run_id: str) -> dict[str, Any]:
    if not isinstance(actions, list):
        raise SyncError("Invalid Codex configuration actions")
    backup_root = codex_home / "fleet-sync-backups" / run_id / "config"
    changed: list[tuple[pathlib.Path, pathlib.Path | None, bytes | None]] = []
    changed_count = 0
    config_changed = 0
    profiles_changed = 0
    try:
        for action in actions:
            if not isinstance(action, dict):
                raise SyncError("Invalid Codex configuration action")
            filename = action.get("name")
            if filename != "config.toml" and (not isinstance(filename, str) or not SAFE_PROFILE.fullmatch(filename)):
                raise SyncError("Invalid Codex profile filename")
            values = action.get("values", {})
            removals = action.get("remove", [])
            if not isinstance(values, dict) or not isinstance(removals, list):
                raise SyncError("Invalid Codex settings map")
            path = codex_home / filename
            if path.is_symlink():
                raise SyncError("A Codex config path is a symbolic link")
            original = path.read_bytes() if path.exists() else b""
            updated = original.decode("utf-8")
            for name in removals:
                if not isinstance(name, str):
                    raise SyncError("Invalid setting removal")
                section, key = _setting_location(name)
                updated = _patch_toml_key(updated, section, key, None)
            for name, value in values.items():
                if not isinstance(name, str):
                    raise SyncError("Invalid setting name")
                section, key = _setting_location(name)
                if section == "features" or section == "sandbox_workspace_write":
                    if not isinstance(value, bool):
                        raise SyncError("Only boolean nested settings can be applied")
                elif not isinstance(value, str):
                    raise SyncError("Only portable string settings can be applied")
                # Re-run the allowlist before writing, even though the plan is
                # held in memory and came from the inspected source host.
                parsed_check = {"features": {key: value}} if section == "features" else ({"sandbox_workspace_write": {key: value}} if section else {key: value})
                candidate = _toml_state_from_dict(parsed_check)
                if name not in candidate:
                    raise SyncError("Unclassified setting cannot be applied")
                updated = _patch_toml_key(updated, section, key, value)
            if updated:
                try:
                    tomllib.loads(updated)
                except tomllib.TOMLDecodeError as error:
                    raise SyncError("The target Codex config is not valid TOML") from error
            if updated.encode("utf-8") == original:
                continue
            backup = _backup_file(path, backup_root, run_id, codex_home)
            changed.append((path, backup, original if path.exists() else None))
            _atomic_write(path, updated.encode("utf-8"), 0o600)
            changed_count += 1
            if filename == "config.toml":
                config_changed += 1
            else:
                profiles_changed += 1
        return {"status": "applied", "filesChanged": changed_count, "configFilesChanged": config_changed, "profilesChanged": profiles_changed, "backupCount": len(changed)}
    except Exception:
        for path, backup, original in reversed(changed):
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                elif backup and backup.exists():
                    _atomic_write(path, backup.read_bytes(), 0o600)
            except OSError:
                pass
        raise


def _toml_state_from_dict(value: dict[str, Any]) -> set[str]:
    portable: set[str] = set()
    for key, item in value.items():
        if key in SAFE_STRING_VALUES and isinstance(item, str):
            allowed = SAFE_STRING_VALUES[key]
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,119}", item) and not SECRET_CONTENT_RE.search(item) and (allowed is None or item in allowed):
                portable.add(key)
        elif key == "features" and isinstance(item, dict):
            portable.update(f"features.{feature}" for feature, flag in item.items() if isinstance(flag, bool) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", feature))
        elif key == "sandbox_workspace_write" and isinstance(item, dict) and isinstance(item.get("network_access"), bool):
            portable.add("sandbox_workspace_write.network_access")
    return portable


def _write_local_marketplace(codex_home: pathlib.Path, marketplace: dict[str, Any], packages: Any, run_id: str) -> pathlib.Path:
    name = marketplace.get("name")
    if not isinstance(name, str) or not SAFE_MARKETPLACE_NAME.fullmatch(name):
        raise SyncError("Invalid local marketplace name")
    if not isinstance(packages, dict) or not packages:
        raise SyncError("Local marketplace has no validated plugin packages")
    root = codex_home / "plugins" / "fleet-sync-sources" / name
    staging = root.with_name(f".{name}.staging.{run_id}")
    _assert_no_symlink_components(root, codex_home)
    _assert_no_symlink_components(staging, codex_home)
    _private_directory(root.parent, codex_home)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(mode=0o700, parents=True)
    entries = []
    for plugin_name, files in packages.items():
        if not isinstance(plugin_name, str) or not SAFE_PLUGIN_NAME.fullmatch(plugin_name) or not isinstance(files, dict):
            raise SyncError("Invalid local plugin package")
        package_dir = staging / "packages" / plugin_name
        package_dir.mkdir(mode=0o700, parents=True)
        for relative_name, encoded in files.items():
            relative = pathlib.PurePosixPath(relative_name)
            if relative.is_absolute() or ".." in relative.parts or not isinstance(encoded, str):
                raise SyncError("Invalid plugin package file path")
            try:
                content = base64.b64decode(encoded, validate=True)
            except ValueError as error:
                raise SyncError("Invalid plugin package encoding") from error
            if len(content) > MAX_FILE_BYTES or not _safe_file_content(content):
                raise SyncError("Plugin package failed the content safety check")
            destination = package_dir.joinpath(*relative.parts)
            _atomic_write(destination, content, 0o600)
        manifest_paths = [package_dir / "plugin.json", package_dir / ".codex-plugin/plugin.json"]
        manifests = []
        for manifest in manifest_paths:
            if manifest.is_file():
                manifests.append(json.loads(manifest.read_text(encoding="utf-8")))
        if not manifests or not any(isinstance(item, dict) and item.get("name") == plugin_name for item in manifests):
            raise SyncError("Transferred plugin manifest does not match its name")
        entries.append({
            "name": plugin_name,
            "source": {"source": "local", "path": f"./packages/{plugin_name}"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Productivity",
        })
    catalog = json.dumps({"name": name, "plugins": entries}, indent=2).encode("utf-8") + b"\n"
    manifest_path = staging / ".agents" / "plugins" / "marketplace.json"
    _atomic_write(manifest_path, catalog, 0o600)
    backup_root = codex_home / "fleet-sync-backups" / run_id / "plugins"
    backup = None
    if root.exists():
        _private_directory(backup_root, codex_home)
        backup = backup_root / name
        os.replace(root, backup)
    try:
        os.replace(staging, root)
    except Exception:
        if backup and backup.exists() and not root.exists():
            os.replace(backup, root)
        raise
    return root


def _plugin_command(codex: str, env: dict[str, str], args: list[str], timeout: int = 180) -> None:
    result = _run([codex, *args], env=env, timeout=timeout)
    if result.returncode != 0:
        raise SyncError("A Codex plugin marketplace command failed")


def _apply_plugins(codex_home: pathlib.Path, codex: str, env: dict[str, str], actions: Any, run_id: str) -> dict[str, Any]:
    if not isinstance(actions, dict):
        raise SyncError("Invalid plugin synchronization actions")
    markets = actions.get("marketplaces", [])
    if not isinstance(markets, list):
        raise SyncError("Invalid plugin marketplace list")
    local_packages = actions.get("localPackages", {})
    if not isinstance(local_packages, dict):
        raise SyncError("Invalid local plugin packages")
    removals = actions.get("remove", [])
    additions = actions.get("add", [])
    if not isinstance(removals, list) or not isinstance(additions, list):
        raise SyncError("Invalid plugin change list")
    changed = 0
    for item in removals:
        selector = _plugin_selector(item)
        _plugin_command(codex, env, ["plugin", "remove", selector, "--json"], 180)
        changed += 1
    for market in markets:
        if not isinstance(market, dict):
            continue
        name = market.get("name")
        kind = market.get("kind")
        if not isinstance(name, str) or not SAFE_MARKETPLACE_NAME.fullmatch(name):
            continue
        if kind == "local":
            package_map = local_packages.get(name)
            if not isinstance(package_map, dict) or not package_map:
                raise SyncError("A local plugin marketplace has no validated source packages")
            root = _write_local_marketplace(codex_home, market, package_map, run_id)
            # Replace only this named marketplace; Codex owns its config/cache.
            _run([codex, "plugin", "marketplace", "remove", name, "--json"], env=env, timeout=45)
            _plugin_command(codex, env, ["plugin", "marketplace", "add", str(root), "--json"])
            changed += 1
        elif kind == "git":
            source = market.get("source")
            if not isinstance(source, str) or not _safe_remote_source(source):
                raise SyncError("A marketplace source is not safe to install")
            replace = market.get("replace") is True
            exists = market.get("existing") is True
            if replace:
                _run([codex, "plugin", "marketplace", "remove", name, "--json"], env=env, timeout=45)
            add_args = ["plugin", "marketplace", "add", source]
            ref = market.get("ref")
            if isinstance(ref, str) and re.fullmatch(r"[A-Za-z0-9._/-]{1,160}", ref):
                add_args.extend(["--ref", ref])
            sparse = market.get("sparsePaths", [])
            if isinstance(sparse, list):
                for item in sparse[:20]:
                    if isinstance(item, str) and re.fullmatch(r"[A-Za-z0-9._/-]{1,180}", item) and ".." not in pathlib.PurePosixPath(item).parts:
                        add_args.extend(["--sparse", item])
            add_args.append("--json")
            if not exists or replace:
                result = _run([codex, *add_args], env=env, timeout=240)
                if result.returncode != 0:
                    raise SyncError("A Codex plugin marketplace could not be added")
            _plugin_command(codex, env, ["plugin", "marketplace", "upgrade", name, "--json"], 240)
            changed += 1
        else:
            raise SyncError("An unclassified marketplace cannot be synchronized")

    for item in additions:
        selector = _plugin_selector(item)
        _plugin_command(codex, env, ["plugin", "add", selector, "--json"], 240)
        changed += 1
    return {"status": "applied", "operations": changed}


def _plugin_selector(value: Any) -> str:
    if not isinstance(value, dict):
        raise SyncError("Invalid plugin selector")
    name, market = value.get("name"), value.get("marketplaceName")
    if not isinstance(name, str) or not SAFE_PLUGIN_NAME.fullmatch(name) or not isinstance(market, str) or not SAFE_MARKETPLACE_NAME.fullmatch(market):
        raise SyncError("Invalid plugin selector")
    return f"{name}@{market}"


def _apply_skills(home: pathlib.Path, codex_home: pathlib.Path, actions: Any, run_id: str) -> dict[str, Any]:
    if not isinstance(actions, dict) or not isinstance(actions.get("write", []), list) or not isinstance(actions.get("delete", []), list) or not isinstance(actions.get("deleteFiles", []), list):
        raise SyncError("Invalid user skill synchronization actions")
    roots = {"agents": home / ".agents/skills", "codex": codex_home / "skills"}
    anchors = {"agents": home, "codex": codex_home}
    backup_root = codex_home / "fleet-sync-backups" / run_id / "skills"
    changed = 0
    for item in actions.get("write", []):
        if not isinstance(item, dict) or item.get("root") not in roots:
            raise SyncError("Invalid skill destination")
        skill_name, relative_name = item.get("skill"), item.get("path")
        if not isinstance(skill_name, str) or not SAFE_SLUG.fullmatch(skill_name) or not isinstance(relative_name, str):
            raise SyncError("Invalid skill path")
        relative = pathlib.PurePosixPath(relative_name)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts or any(part in SKIP_DIRS for part in relative.parts) or "\\" in relative_name:
            raise SyncError("Unsafe skill path")
        try:
            content = base64.b64decode(item.get("content", ""), validate=True)
        except (ValueError, TypeError) as error:
            raise SyncError("Invalid skill file encoding") from error
        if len(content) > MAX_FILE_BYTES or not _safe_file_content(content):
            raise SyncError("Skill file failed the content safety check")
        destination = _assert_no_symlink_components(roots[item["root"]] / skill_name / pathlib.Path(*relative.parts), anchors[item["root"]])
        if destination.exists():
            backup_path = backup_root / item["root"] / skill_name / pathlib.Path(*relative.parts)
            _private_directory(backup_path.parent, codex_home)
            shutil.copy2(destination, backup_path)
            os.chmod(backup_path, 0o600)
        _atomic_write(destination, content, 0o600)
        changed += 1
    for item in actions.get("delete", []):
        if not isinstance(item, dict) or item.get("root") not in roots:
            raise SyncError("Invalid skill removal")
        skill_name = item.get("skill")
        if not isinstance(skill_name, str) or not SAFE_SLUG.fullmatch(skill_name):
            raise SyncError("Invalid skill removal")
        directory = _assert_no_symlink_components(roots[item["root"]] / skill_name, anchors[item["root"]])
        if not directory.exists():
            continue
        if directory.is_symlink() or not directory.is_dir():
            raise SyncError("Skill removal target is not a regular directory")
        _, unsafe = _collect_regular_tree(directory, require_skill=True)
        if unsafe:
            raise SyncError("Skill removal target contains unsafe files")
        destination = backup_root / item["root"] / skill_name
        _private_directory(destination.parent, codex_home)
        shutil.copytree(directory, destination, dirs_exist_ok=True, symlinks=False)
        shutil.rmtree(directory)
        changed += 1
    for item in actions.get("deleteFiles", []):
        if not isinstance(item, dict) or item.get("root") not in roots:
            raise SyncError("Invalid skill file removal")
        skill_name, relative_name = item.get("skill"), item.get("path")
        if not isinstance(skill_name, str) or not SAFE_SLUG.fullmatch(skill_name) or not isinstance(relative_name, str):
            raise SyncError("Invalid skill file removal")
        relative = pathlib.PurePosixPath(relative_name)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts or any(part in SKIP_DIRS for part in relative.parts) or "\\" in relative_name:
            raise SyncError("Unsafe skill file removal path")
        target = _assert_no_symlink_components(roots[item["root"]] / skill_name / pathlib.Path(*relative.parts), anchors[item["root"]])
        if not target.exists():
            continue
        if target.is_symlink() or not target.is_file():
            raise SyncError("Skill file removal target is not a regular file")
        backup_path = backup_root / item["root"] / skill_name / pathlib.Path(*relative.parts)
        _private_directory(backup_path.parent, codex_home)
        shutil.copy2(target, backup_path)
        os.chmod(backup_path, 0o600)
        target.unlink()
        changed += 1
    return {"status": "applied", "operations": changed}


def _install_cli_version(codex_home: pathlib.Path, target_version: Any) -> dict[str, Any]:
    if not isinstance(target_version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", target_version):
        raise SyncError("The source Codex CLI version is unavailable or invalid")
    env = _codex_env(codex_home)
    current = _codex_path(codex_home)
    if current:
        result = _run([current, "--version"], env=env, timeout=12)
        if result.returncode == 0 and _version_from_output(result.stdout) == target_version:
            return {"status": "unchanged", "version": target_version, "changed": False}
    try:
        with urllib.request.urlopen("https://chatgpt.com/codex/install.sh", timeout=20) as response:
            script = response.read(1024 * 1024 + 1)
    except Exception as error:
        raise SyncError("Could not fetch the official Codex installer") from error
    if len(script) > 1024 * 1024 or b"#!/bin/sh" not in script[:128]:
        raise SyncError("The official Codex installer response was invalid")
    installer_path = codex_home / "fleet-sync-staging" / "install.sh"
    _private_directory(installer_path.parent, codex_home)
    _atomic_write(installer_path, script, 0o600)
    env["CODEX_NON_INTERACTIVE"] = "1"
    env["CODEX_INSTALL_DIR"] = str(pathlib.Path.home() / ".local/bin")
    try:
        result = _run(["/bin/sh", str(installer_path), "--release", target_version], env=env, timeout=600)
        if result.returncode != 0:
            raise SyncError("The official installer could not install the pinned Codex CLI version")
        installed = _codex_path(codex_home)
        if not installed:
            raise SyncError("The official installer finished, but Codex CLI was not found")
        verify = _run([installed, "--version"], env=env, timeout=15)
        if verify.returncode != 0 or _version_from_output(verify.stdout) != target_version:
            raise SyncError("The installed Codex CLI version did not match the pinned source version")
        return {"status": "applied", "version": target_version, "changed": True}
    finally:
        try:
            installer_path.unlink(missing_ok=True)
        except OSError:
            pass


def apply(codex_home: pathlib.Path, request: dict[str, Any]) -> dict[str, Any]:
    run_id = request.get("runId")
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", run_id):
        raise SyncError("Invalid sync run ID")
    categories: dict[str, Any] = {}
    try:
        categories["cli"] = _install_cli_version(codex_home, request.get("targetVersion"))
    except SyncError:
        categories["cli"] = {"status": "failed", "message": "Pinned Codex CLI installation failed"}
    codex = _codex_path(codex_home)
    env = _codex_env(codex_home)
    try:
        config_result = _apply_configs(codex_home, request.get("config", []), run_id)
        categories["config"] = {"status": config_result["status"], "filesChanged": config_result["configFilesChanged"], "backupCount": config_result["backupCount"]}
        categories["profiles"] = {"status": config_result["status"], "filesChanged": config_result["profilesChanged"], "backupCount": config_result["backupCount"]}
    except Exception:
        categories["config"] = {"status": "failed", "message": "Config/profile changes failed and were rolled back"}
        categories["profiles"] = {"status": "failed", "message": "Config/profile changes failed and were rolled back"}
    if codex and categories["cli"]["status"] in {"applied", "unchanged"}:
        try:
            categories["plugins"] = _apply_plugins(codex_home, codex, env, request.get("plugins", {}), run_id)
        except Exception:
            categories["plugins"] = {"status": "failed", "message": "Codex plugin synchronization failed"}
    else:
        categories["plugins"] = {"status": "blocked", "message": "Plugin commands require the pinned Codex CLI"}
    try:
        categories["skills"] = _apply_skills(pathlib.Path.home(), codex_home, request.get("skills", {}), run_id)
    except Exception:
        categories["skills"] = {"status": "failed", "message": "User skill synchronization failed"}
    affected = categories.get("cli", {}).get("changed") is True or (
        categories.get("config", {}).get("status") == "applied" and categories.get("config", {}).get("filesChanged", 0) > 0
    ) or (
        categories.get("profiles", {}).get("status") == "applied" and categories.get("profiles", {}).get("filesChanged", 0) > 0
    ) or (
        categories.get("plugins", {}).get("status") == "applied" and categories.get("plugins", {}).get("operations", 0) > 0
    )
    return {"categories": categories, "restartRequired": affected, "versions": {"cli": request.get("targetVersion")}}


def _restart_managed_if_idle(codex_home: pathlib.Path) -> dict[str, Any]:
    """Restart only the known dashboard-managed service, and fail closed."""
    env = _codex_env(codex_home)
    codex = _codex_path(codex_home)
    if not codex:
        return {"status": "deferred", "reason": "Codex CLI is unavailable"}
    daemon = _run([codex, "app-server", "daemon", "version"], env=env, timeout=15)
    try:
        daemon_state = json.loads(daemon.stdout)
    except json.JSONDecodeError:
        return {"status": "deferred", "reason": "Daemon state is unknown"}
    if daemon_state.get("status") != "running":
        return {"status": "not-needed", "reason": "Daemon is not running"}
    active = _active_turn_state(codex, env, codex_home)
    if not active.get("known"):
        return {"status": "deferred", "reason": "Could not prove the daemon is idle"}
    if active.get("count", 0) > 0:
        return {"status": "deferred", "reason": "An active turn is running"}
    if sys.platform == "darwin":
        uid = os.getuid()
        label = "org.example.codex-app-server-ensure"
        check = _run(["launchctl", "print", f"gui/{uid}/{label}"], env=env, timeout=10)
        if check.returncode != 0:
            return {"status": "deferred", "reason": "Managed Codex LaunchAgent is not loaded"}
        result = _run(["launchctl", "kickstart", "-k", f"gui/{uid}/{label}"], env=env, timeout=60)
    elif sys.platform.startswith("linux"):
        check = _run(["systemctl", "--user", "is-enabled", "codex-app-server.service"], env=env, timeout=10)
        if check.returncode != 0:
            return {"status": "deferred", "reason": "Managed Codex user service is not enabled"}
        result = _run(["systemctl", "--user", "restart", "codex-app-server.service"], env=env, timeout=120)
    else:
        return {"status": "deferred", "reason": "Managed daemon restart is unsupported on this host"}
    if result.returncode != 0:
        return {"status": "failed", "reason": "Managed Codex daemon restart failed"}
    return {"status": "restarted", "reason": None}


def main() -> int:
    try:
        request = json.loads(sys.stdin.readline())
        if not isinstance(request, dict):
            raise SyncError("Invalid sync request")
        codex_home = _resolve_codex_home(request.get("codexHome"))
        operation = request.get("operation")
        if operation == "inspect":
            result = inspect(codex_home, request.get("includeContent") is True)
        elif operation == "apply":
            result = apply(codex_home, request)
        elif operation == "restart":
            result = _restart_managed_if_idle(codex_home)
        else:
            raise SyncError("Unsupported sync operation")
        _emit({"ok": True, "result": result})
        return 0
    except Exception as error:
        # Never print raw subprocess output, config values, paths, or exceptions.
        message = error.args[0] if isinstance(error, SyncError) and error.args else "Codex sync operation failed"
        _emit({"ok": False, "error": str(message)[:180]})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
