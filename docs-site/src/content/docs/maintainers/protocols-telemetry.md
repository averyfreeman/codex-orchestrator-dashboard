---
title: Protocols and telemetry
description: Choose native app-server, ACP, and A2A interfaces and size bounded monitoring.
---

## Protocol selection

Use Codex app-server for native Codex threads and turns on a selected host. The protocol supports newline-delimited JSON-RPC over stdio; this dashboard uses the managed daemon’s host-local WebSocket control socket through `codex app-server proxy --sock`, carrying the bidirectional framed stream over strict SSH stdio. It does not expose the control socket on the network. Review the [Codex app-server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md) and [method map](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/common.rs) when updating the bridge.

Use **ACP** for an optional explicit client-to-agent delegation path through OpenClaw. It is closer to the dashboard acting as an agent client but uses OpenClaw session semantics, not the selected Codex app-server thread. Use **A2A** for task exchange or federation between independent agents, not as a replacement for native Codex controls. Do not promise cancellation unless the chosen endpoint supports it. Sources: [ACP overview](https://agentclientprotocol.com/protocol/v1/overview), [OpenClaw ACP bridge](https://docs.openclaw.ai/cli/acp), [A2A specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md).

## Metrics to consider

| Signal | Collection method | Token cost | Main resource cost |
| --- | --- | --- | --- |
| Host availability | One bounded probe per host and interval | None | SSH setup and a short remote command |
| CPU/load, memory, disk, uptime | Bounded OS commands; report aggregate values | None | Small remote CPU, output, and network transfer |
| Codex turn state | App-server events and targeted thread reads | None to observe | One persistent proxy stream per actively observed turn |
| Token usage | App-server usage notifications | None to read | Small event parsing and metadata storage |
| Herdr workspace/agent state | Event subscription plus snapshot on reconnect | None to observe | Event processing; bounded snapshot/reconciliation work |
| Process CPU/RSS | OS process table for reported Herdr/agent PIDs | None | Short remote process query |
| OpenClaw gateway health | Existing bounded local status call | None | One local CLI invocation per refresh |
| Agent work | Existing Codex or explicit OpenClaw task | Model-dependent | Usually the dominant CPU, RAM, and token cost |

At a polling interval of `I` seconds, the rough probe rate is `host_count × 60 / I` probes per minute. Five hosts polled every 30 seconds produce about 10 probes/minute. Stagger probes, bound their timeout/output, and use event streams for live turn/session state rather than polling full transcripts.

There is no portable vendor benchmark for this gateway and host mix. Measure gateway and remote CPU/RSS with monitoring disabled and enabled at the target interval, then measure again during one representative active turn. Include probe duration, timeouts, event volume, and actual turn token usage. Observation itself does not invoke a model; only the underlying agent work incurs model usage.

For longer retention, define privacy and disk bounds first. The existing collector excludes prompts, transcripts, terminal output, credentials, and process environment variables. A reasonable initial target is 30 days of aggregate metadata and 7 days of operational snapshots with owner-only file permissions.
