# Interactive control and telemetry options

**Status:** Architecture research for the dashboard; no implementation change. Sources below are upstream product documentation, protocol specifications, or source schemas, reviewed 2026-10-07.

## Recommendation

Add an authenticated control plane behind the existing dashboard API. The browser selects a host and an existing/new Codex thread, then the dashboard backend connects to that host’s Codex app-server, starts or steers a turn, and streams the app-server’s events back to the browser. Make chat host-scoped by default; require a separate, explicit route when the operator wants OpenClaw to handle a task.

Use the native Codex app-server protocol for Codex work, and Herdr’s own session interface for Herdr lifecycle controls. A2A and ACP solve other integration problems; neither is a better replacement for direct control of these existing runtimes.

Keep dashboard start/stop controls to **Codex turns** and **Herdr sessions**. Do not expose app-server daemon lifecycle or arbitrary remote shell/process controls in this dashboard.

## Interaction model

### Codex chat and turn controls

Codex app-server is already a bidirectional JSON-RPC interface for rich clients. Its primitives are threads, turns, and turn items; the app-server emits notifications while a turn runs. The current protocol includes thread start/resume/list/read and turn start/steer/interrupt operations, so a per-host chat composer and live progress view are a natural fit. [Codex app-server protocol](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md) · [protocol method map](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/common.rs)

Use one stable app-server connection for a host/profile and multiplex its thread activity through the dashboard API. The turn/interrupt request is tied to a specific thread and turn; show the active turn and target clearly before stopping it. Model turn states explicitly (inProgress, completed, interrupted, failed). [Turn API and status types](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/v2/turn.rs)

Do not treat closing a browser tab or losing SSH as proof that a turn stopped. Reconnect and read the authoritative app-server thread/turn state. Avoid starting a separate app-server for every chat request: independently launched app-server processes have separate live status and approval state, as the OpenClaw transport reference also documents. [OpenClaw Codex app-server transport](https://docs.openclaw.ai/plugins/codex-harness-reference/app-server-transport)

For remote transport, use the verified SSH route (ZeroTier first, Tailscale fallback, strict host-key checking), keep app-server on the host, and carry its local stdio stream over SSH or forward its local Unix control socket. This bridge choice is an engineering inference from the documented local transports and the existing SSH path. Codex app-server’s default stdio transport carries newline-delimited JSON-RPC; Codex and OpenClaw both classify the app-server WebSocket listener as experimental/unsupported for production. Keep it off public interfaces. [Codex app-server protocol and transports](https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md) · [OpenClaw transport guidance](https://docs.openclaw.ai/plugins/codex-harness-reference/app-server-transport)

Dashboard-managed Codex profiles should apply the settled operator policy: auto-approve eligible dashboard-initiated tool actions, set $HOME as the writable root, and enable command network access by default with a per-profile dashboard off switch. Codex command networking (`sandbox_workspace_write.network_access`) and built-in web search (`web_search`) are separate controls. The dashboard switch should set both together: on means command networking plus live web search; off disables command networking and web search. Approval policy and sandbox/network policy are also separate: `approval_policy = "never"` suppresses eligible command approval prompts while retaining the configured sandbox. It does not grant access to unrelated apps, MCP servers, browser traffic, or operating-system permission prompts. Apply changes to subsequent turns; an already-sent network request cannot be recalled. This is an operational recommendation; exact live-update behavior depends on how the dashboard applies the profile. [Codex sandbox configuration](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/v2/config.rs) · [Codex approval and sandbox definitions](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs) · [Codex approvals and web-search configuration](https://learn.chatgpt.com/docs/agent-approvals-security)

This is an unattended, high-trust profile: an approved Codex tool can act on files under $HOME and use outbound network access while enabled. Keep that profile distinct from read-only observation, display the selected host/profile and current network setting in the composer, and log actor, host alias, thread/turn IDs, policy, timestamps, result, and token counts. Keep prompts, terminal output, environment values, and credentials out of dashboard logs by default.

### Herdr sessions

Use Herdr’s named-session lifecycle rather than treating each pane or foreground process as a dashboard job. Its CLI supports listing, attaching, starting/attaching a named session, and stopping a named session; the CLI communicates with the running server through Herdr’s local socket API and supports JSON output. [Herdr CLI reference](https://github.com/herdrdev/herdr/blob/master/docs/next/website/src/content/docs/cli-reference.mdx)

For richer status, subscribe to Herdr events and bootstrap/recover with session.snapshot. Events cover live workspace/tab/pane/agent changes; the snapshot is authoritative current state, not durable history. If an events_lost notification arrives, resubscribe and reconcile from a fresh snapshot. pane.process_info can report shell PID, foreground process group, and foreground process PID/name/arguments/cwd when the platform exposes them; it does not report CPU or RSS. [Herdr socket API](https://github.com/herdrdev/herdr/blob/master/docs/next/website/src/content/docs/socket-api.mdx)

A Herdr “stop” is materially different from detaching a client: detached panes keep running, while a stopped named session ends that session’s panes and runtime. Show the selected session name and its pane count before stopping; don’t offer a bulk “stop all” action. [Herdr CLI reference](https://github.com/herdrdev/herdr/blob/master/docs/next/website/src/content/docs/cli-reference.mdx) · [Herdr named session lifecycle](https://herdr.dev/docs/persistence-remote/)

The socket API also exposes pane input and agent prompt/start operations, but they broaden the surface into arbitrary terminal interaction. Keep those out of the initial control scope; start/stop named Herdr sessions and observe their event/status state first.

## Metrics and operating cost

| Signal | Collection path | What it adds | Cost profile |
| --- | --- | --- | --- |
| Host health | Bounded SSH probes: CPU/load, memory, disk, uptime, process count, OS/runtime versions | Capacity and “host is alive” context beyond app status | No model tokens. One short remote command per host per interval; CPU, RAM, and network use should be small, but measure on the actual hosts. |
| Codex activity | App-server events/thread reads: thread, turn, state, model/profile, timestamps, approval events | Live turn progress and stale/running/failed distinction | No model call to observe; one persistent RPC stream plus small event payloads. Do not poll full transcripts. |
| Codex usage | ThreadTokenUsageUpdatedNotification: last/total input, cached input, cache-write input, output, reasoning output, total, and context window | Usage per turn/thread and trend reporting | Reading usage adds no inference tokens. Chat/delegation do. Convert tokens to money only when the provider’s billing mode and model price are known; the OpenAI API pricing table is not a reliable estimate for a ChatGPT plan. [Usage schema](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/json/v2/ThreadTokenUsageUpdatedNotification.json) · [API pricing](https://developers.openai.com/api/docs/pricing) |
| Herdr activity | Event subscription + periodic/reconnect snapshot; pane process metadata | Agent state, workspace/pane counts, foreground process identity | Event-driven status avoids frequent polling. Snapshot recovery is bounded work; no model tokens. |
| OpenClaw gateway | Existing local status/aggregate session probe | Gateway health and aggregate session counts | No model tokens. Add turn/token detail only if a supported OpenClaw interface exposes it. |
| Agent work | Codex or explicit OpenClaw task | Actual code/agent execution | This is the token and remote CPU/RAM cost center. Token usage can be best-effort or unknown; cost depends on the model, provider, and billing arrangement. [OpenAI usage observability](https://developers.openai.com/api/docs/guides/agents-api/observability) |

As a planning heuristic (not a vendor limit), interval polling produces approximately **host_count × 60 / interval_seconds** probes per minute. Prefer 30–60 second health probes plus event streams for live app state; stagger probes and cap command output/timeouts. Each remote process doing actual work can use much more CPU/RAM than the collector, and Herdr panes intentionally keep detached processes running. Vendor docs do not publish a transferable CPU or memory benchmark for this deployment; capture a baseline, then compare gateway and host CPU/RSS with telemetry disabled and enabled at the intended interval.

Codex’s optional server/diagnostics method is marked experimental and described as content-free, process-local diagnostics. It could enrich Codex health later, but don’t make the dashboard depend on it until its schema/support level is stable. [Codex experimental diagnostics method](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/common.rs)

## Protocol fit: stdio, A2A, and ACP

| Interface | Best fit | Fit for this dashboard |
| --- | --- | --- |
| **Codex app-server (stdio / Unix socket)** | A client controlling native Codex threads and turns, including streaming updates and interruption | **Primary.** Stdio is a transport for a full JSON-RPC control protocol, not a limitation to one-way output. Keep the connection local to the host and tunnel it over SSH. |
| **A2A (Agent2Agent)** | Task-oriented communication between independently operated agents, with Agent Cards/discovery and task results | Better for formal agent-to-agent task exchange or federation. It does not expose the selected host’s native Codex thread controls. While the A2A spec defines CancelTask, OpenClaw’s current A2A channel refuses it because it has no abort seam; don’t promise cancellation through this integration. [A2A specification](https://github.com/a2aproject/A2A/blob/main/docs/specification.md) · [OpenClaw A2A limitations](https://docs.openclaw.ai/channels/a2a) |
| **ACP (Agent Client Protocol)** | A client creating an agent session, sending prompts, receiving updates, and cancellation; local agents commonly use JSON-RPC over stdio, with remote HTTP/WebSocket options | The closer optional OpenClaw delegation path for a dashboard acting as a client: OpenClaw’s ACP bridge routes a client session through the Gateway. It is not a direct Codex app-server connection and uses OpenClaw session/runtime semantics. Keep delegation explicit and separate from per-host Codex chat. [ACP protocol overview](https://agentclientprotocol.com/protocol/v1/overview) · [OpenClaw ACP bridge](https://docs.openclaw.ai/cli/acp) · [OpenClaw ACP agents](https://docs.openclaw.ai/tools/acp-agents) |

For OpenClaw delegation, make the destination and consequence explicit in the composer (for example, “Send to this host’s Codex” versus “Delegate to OpenClaw”). Give the delegation its own task/session identifier and report its status. Because dashboard start/stop scope is Codex turns and Herdr sessions, do not make the dashboard stop control claim to cancel an OpenClaw task.

## Rollout and limits

1. Start with Codex thread/turn start, streaming state, interrupt, and per-turn usage; keep the selected host visible throughout.
2. Add Herdr named-session start/stop and event-driven state with snapshot recovery.
3. Add host health probes with staggered intervals and output/timeout limits.
4. Add explicit OpenClaw delegation only behind a separate route and honest cancellation/status semantics.
5. Benchmark resource use under idle monitoring and one representative active turn/session. Track gateway RSS/CPU, remote collector RSS/CPU, probe duration, event volume, and actual agent token usage.

The Codex managed app-server daemon is a separate, explicitly experimental lifecycle interface; restarting/stopping it can interrupt active or queued work. It is intentionally outside the dashboard’s start/stop surface. [Codex app-server daemon lifecycle](https://github.com/openai/codex/blob/main/codex-rs/app-server-daemon/README.md)
