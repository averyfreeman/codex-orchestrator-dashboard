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

## Data boundaries

- Host reports contain bounded health, version, counts, process usage, and worktree metadata.
- Prompts and assistant replies flow only through the selected Codex thread, not dashboard telemetry.
- Raw terminal output, process environment, credentials, and conversation files are not collected.
- Codex turn, Herdr session, OpenClaw delegation, and daemon lifecycle are distinct control domains.
- The dashboard exposes selected operations, not a general SSH terminal.

## Deployment boundary

GitHub Pages serves `docs-site/` as a static guide. It does not serve the Next.js dashboard or its APIs. Static export is not suitable for the current app: the app uses dynamic request-dependent route handlers, an SSE control response, subprocess bridges, and local filesystem telemetry. Next.js documents request-dependent Route Handlers and other runtime features as unsupported in static export; see [Next.js Static Exports](https://nextjs.org/docs/app/guides/static-exports).

Astro/Starlight builds the guide with the repository base path `/codex-orchestrator-dashboard/`. The Pages workflow checks out `main`, installs from the committed npm lockfile, builds `docs-site/dist`, and deploys only that artifact. The workflow grants read-only contents to build and Pages write plus OIDC deployment access to the deploy job. See [Astro’s GitHub Pages guide](https://docs.astro.build/en/guides/deploy/github/).
