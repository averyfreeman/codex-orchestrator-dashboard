---
title: Configuration reference
description: Private fleet inventory, shared Codex profile, environment values, and storage locations.
---

## Fleet inventory

The dashboard loads hosts from `FLEET_CONFIG_PATH` when set, otherwise from the ignored `config/fleet.local.json` if present. `config/fleet.example.json` is an empty public template. Each host has a unique `slug`, display `name`, OS string, optional `localIp`, `tailscaleIp`, and `zerotierIp`, plus ordered `sshRoutes`.

An SSH route has a `transport` (`zerotier` or `tailscale`), a `target`, and `hostKeyAlias`. Route order controls failover; LAN values are display-only. Use a distinct, stable key alias per host and provision known-host entries before collection.

## Shared Codex profile

`config/codex-fleet-profile.json` declares the synchronized model, reasoning effort, approval policy, sandbox mode, web search mode, and `sandbox_workspace_write` network and writable-root settings. The synchronizer resolves `$HOME` on each target and changes only these declared settings. It preserves authentication and unrelated MCP/plugin configuration.

The dashboard-managed profile preference is stored under the ignored `.dashboard-state/` directory. Local telemetry is written beneath ignored `logs/`. `LOG_INGEST_TOKEN` is optional and required only when enabling `POST /api/logs` ingestion. `CODEX_CLI_PATH` and `OPENCLAW_CLI` override command lookup when binaries are not on the dashboard process `PATH`.

## Public/private boundary

Never commit a live fleet inventory, private hostname, overlay IP, SSH key, Codex auth file, environment file, prompt, terminal capture, or host telemetry. The [public snapshot scanner](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/scripts/check_public_snapshot.py) scans tracked and non-ignored untracked files before publishing.
