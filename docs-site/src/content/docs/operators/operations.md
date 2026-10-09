---
title: Operate fleet views
description: Interpret host health, Herdr, Treehouse, OpenClaw, and telemetry views.
---

## App-server fleet

The overview reports whether a host responds, Codex version and Remote Control state, loaded thread count, selected SSH transport, and the configured LAN, Tailscale, and ZeroTier address fields. An unavailable host means the configured probes did not establish that the app-server is responding; it is not proof that the operating system is powered off.

The fleet collector polls every 30 seconds. Manual refresh runs the same bounded collection. SSH output is parsed into a sanitized report; raw command output, environment variables, prompts, transcripts, and terminal content are not returned to the browser.

Codex sync is a separate on-demand workflow. It reads the selected source and targets only when you request a plan; fleet polling never creates a plan or changes host state. See the [Codex sync walkthrough](../codex-sync/) for the review and apply steps.

## Herdr and Treehouse

The Herdr view summarizes daemon state, version, startup state, workspaces, agent metadata, and process CPU/RSS when the operating system reports it. These are process and agent metadata only; the dashboard does not read pane terminal output.

The Treehouse view lists registered worktree names, paths, and creation times from state files. A zero count means no registered state files were found; it does not establish whether Treehouse is installed.

## OpenClaw and logs

OpenClaw is optional and read-only in the current dashboard. The local CLI status projection reports gateway reachability, mode, latency, and aggregate agent session counts. It does not inspect OpenClaw session files or read messages.

Telemetry is stored as bounded JSONL snapshots in the ignored `logs/` directory. The dashboard API exposes a bounded recent window. Treat this directory as private operational data, use a short retention period, and do not add prompt or tool-output logging.

## Read failures carefully

When a host is unavailable, inspect the reported transport and then validate SSH reachability and host-key setup from the gateway host. The dashboard does not offer a general SSH terminal or arbitrary service-manager commands. See [recovery behavior](../recovery/) before using the daemon start action.

Source: [`src/lib/collector.ts`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/src/lib/collector.ts), [`scripts/probe.py`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/scripts/probe.py).
