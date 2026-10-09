---
title: Architecture and deployment boundary
description: Understand the observation plane, control plane, SSH bridge, and static docs deployment.
---

import Mermaid from "../../../components/Mermaid.astro";

## Two planes

The dashboard separates **observation** from **control**. Observation gathers bounded host metadata and writes sanitized local snapshots. Control is a loopback-only Next.js API that invokes a host-scoped Codex bridge or Herdr session helper after an explicit operator action.

<Mermaid caption="Observation flow from the operator browser through the bounded collector to sanitized reports and private snapshots." code={`flowchart LR
    Browser[Operator browser] -->|loopback HTTP| Gateway[Next.js gateway]
    Gateway --> Collector[Bounded collector]
    Collector -->|local probe| Local[Gateway host]
    Collector -->|ZeroTier, then Tailscale over strict SSH| Fleet[Configured remote hosts]
    Local --> Snapshot[Sanitized report]
    Fleet --> Snapshot
    Gateway -->|aggregate status only| OpenClaw[Optional OpenClaw gateway]
    Snapshot --> Gateway
    Gateway -->|metadata only| JSONL[Private JSONL snapshots]
`} />

The request-time routes and local JSONL store are why the live Next.js app stays on a trusted gateway. The same-origin control API needs a server runtime and a private inventory. Static hosting would also expose compiled client assets publicly.

## Selected-host control flow

<Mermaid caption="Selected-host Codex turn lifecycle from submission through app-server events and interruption." code={`sequenceDiagram
    participant Operator
    participant UI as Dashboard UI
    participant Gateway as Loopback Next.js API
    participant SSH as Strict SSH route
    participant App as Host Codex app-server
    Operator->>UI: Select host/profile and submit prompt
    UI->>Gateway: POST selected host, prompt, optional thread
    Gateway->>SSH: Start host-local proxy (ZeroTier first)
    SSH->>App: Carry app-server RPC stream
    App-->>UI: Projected output, state, usage
    Operator->>UI: Interrupt selected turn
    UI->>Gateway: POST host + threadId + turnId
    Gateway->>App: Native turn/interrupt
    App-->>UI: Terminal turn status
`} />

The dashboard tunnels the host’s app-server control channel over strict SSH. The transport is bidirectional; stdio frames the proxy stream and does not mean the feature is one-way. See [protocol choices](../protocols-telemetry/) and the canonical [architecture record](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/docs/architecture.md).

## Codex fleet sync

Codex sync is a separate, operator-started control flow. Health polling stays read-only. The operator selects one reference host and peers, receives a short-lived plan of safe differences and blocked items, and explicitly applies that plan.

<Mermaid caption="Codex fleet sync inspects selected hosts on demand, validates the reviewed plan again before apply, and reports sanitized outcomes." code={`sequenceDiagram
    participant Operator
    participant UI as Codex sync view
    participant API as Loopback Next.js API
    participant Source as Reference host helper
    participant Peers as Target host helpers
    Operator->>UI: Select reference and targets; compare
    UI->>API: POST /api/control/codex-sync/plan
    API->>Source: Inspect with source CODEX_HOME
    API->>Peers: Inspect over local or strict SSH routes
    Source-->>API: Bounded source snapshot
    Peers-->>API: Bounded target snapshots
    API-->>UI: Ten-minute plan with safe diffs and blocked items
    Operator->>UI: Review and apply
    UI->>API: POST /api/control/codex-sync/apply
    API->>Source: Recheck reference state
    API->>Peers: Recheck targets, then apply validated actions
    Peers-->>API: Per-category results and restart outcome
    UI->>API: GET /api/control/codex-sync/runs/{runId}
    API-->>UI: Sanitized per-host progress
`} />

The `CODEX_HOME` value is resolved per host from its private inventory override, the dashboard process environment for the local host, or `~/.codex`. The resolved value is supplied explicitly to probes, control, recovery, and sync. The macOS LaunchAgent installer reads its local override from the private inventory, and Ansible expands each remote override against that host's home before configuring Codex commands and managed systemd units. Host-relative paths are normalized for comparison; a target keeps its own home path, and browser responses contain a safe label rather than its absolute override.

The plan compares installed CLI and running app-server versions separately, supported marketplace/plugin state, portable settings in `config.toml` and top-level `*.config.toml` profiles, and user-owned skills. When CLI versions differ, the fixed helper invokes the official Codex installer pinned to the reference release and verifies the installed version. Unsafe or unclassified config, secrets, auth, machine-specific values, repo/system skills, and generated plugin caches stay local. Local plugin sources must pass bounded path and content validation. Apply rechecks state and rejects expired or stale plans. Config/profile edits are validated and atomic with private backups; durable run data and telemetry contain only IDs, versions, category outcomes, restart status, and counts. The optional post-apply restart is attempted once for an affected managed daemon when it can be proven idle; otherwise runtime drift is reported as deferred. See the canonical [Codex sync architecture](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/docs/architecture.md#codex-fleet-sync), [operator walkthrough](../operators/codex-sync/), and [ADR 0006](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/docs/adr/0006-codex-fleet-sync.md).

## Data boundaries

- Host reports contain bounded health, version, counts, process usage, and worktree metadata.
- Prompts and assistant replies flow only through the selected Codex thread, not dashboard telemetry.
- Raw terminal output, process environment, credentials, and conversation files are not collected.
- Codex turn, Herdr session, OpenClaw delegation, and daemon lifecycle are distinct control domains.
- The dashboard exposes selected operations, not a general SSH terminal.

## Deployment boundary

GitHub Pages serves `docs-site/` as a static guide. It does not serve the Next.js dashboard or its APIs. Static export is not suitable for the current app: the app uses dynamic request-dependent route handlers, an SSE control response, subprocess bridges, and local filesystem telemetry. Next.js documents request-dependent Route Handlers and other runtime features as unsupported in static export; see [Next.js Static Exports](https://nextjs.org/docs/app/guides/static-exports).

Astro/Starlight builds the guide with the repository base path `/codex-orchestrator-dashboard/`. The Pages workflow checks out `main`, installs from the committed npm lockfile, builds `docs-site/dist`, and deploys only that artifact. The workflow grants read-only contents to build and Pages write plus OIDC deployment access to the deploy job. See [Astro’s GitHub Pages guide](https://docs.astro.build/en/guides/deploy/github/).
