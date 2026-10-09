---
title: Configuration reference
description: Private fleet inventory, shared Codex profile, environment values, and storage locations.
---

## Fleet inventory

The dashboard loads hosts from `FLEET_CONFIG_PATH` when set, otherwise from the ignored `config/fleet.local.json` if present. `config/fleet.example.json` is an empty public template. Each host has a unique `slug`, display `name`, OS string, optional `localIp`, `tailscaleIp`, and `zerotierIp`, plus ordered `sshRoutes`.

An SSH route has a `transport` (`zerotier` or `tailscale`), a `target`, and `hostKeyAlias`. Route order controls failover; LAN values are display-only. Use a distinct, stable key alias per host and provision known-host entries before collection.

### `CODEX_HOME`

Each host may set an optional `codexHome` inventory value. It accepts `~`, a path under that host user's home such as `~/.codex-work`, or an absolute path. Relative paths and values containing `..` are rejected. Resolution order is:

1. The host's private inventory `codexHome` override, when present.
2. For the local host only, the dashboard process's `CODEX_HOME` environment variable.
3. The default `~/.codex`.

The dashboard passes the resolved host-specific home to its probe, control, recovery, and sync helpers. The macOS LaunchAgent installer reads the local host override from the same private inventory, before consulting the installer process environment. The Ansible inventory passes each remote host's override into its managed systemd units and Codex setup commands. Each host retains its own home path. Codex sync normalizes home-relative paths when comparing settings, and the browser receives only a safe path label rather than a private absolute override. Put live values only in the ignored fleet inventory or the local process environment.

## Shared Codex profile

`config/codex-fleet-profile.json` declares the synchronized model, reasoning effort, approval policy, sandbox mode, web search mode, and `sandbox_workspace_write` network and writable-root settings. The synchronizer resolves `$HOME` on each target and changes only these declared settings. It preserves authentication and unrelated MCP/plugin configuration. This profile synchronizer is separate from the on-demand [Codex fleet sync workflow](../../operators/codex-sync/), which reviews broader host state before applying changes.

The dashboard-managed profile preference is stored under the ignored `.dashboard-state/` directory. Local telemetry is written beneath ignored `logs/`. `LOG_INGEST_TOKEN` is optional and required only when enabling `POST /api/logs` ingestion. `CODEX_CLI_PATH` and `OPENCLAW_CLI` override command lookup when binaries are not on the dashboard process `PATH`.

## Public/private boundary

Never commit a live fleet inventory, private hostname, overlay IP, SSH key, Codex auth file, environment file, prompt, terminal capture, or host telemetry. The [public snapshot scanner](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/scripts/check_public_snapshot.py) scans tracked and non-ignored untracked files before publishing.
