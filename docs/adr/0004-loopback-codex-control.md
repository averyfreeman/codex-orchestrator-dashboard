# Codex control uses a loopback-only dashboard bridge

## Context

The observation dashboard needs a real chat/control path to each selected host's Codex app-server, including streaming output, interruption, token usage, ZeroTier-first SSH, and a default-on network switch. The request must not expose a general remote shell or change the host's unrelated Codex configuration.

## Decision

The dashboard launches a narrow local Python bridge that connects to the host's existing managed app-server through `codex app-server proxy`. Remote connections use only configured SSH routes in inventory order with batch mode and strict host-key checking. The browser selects a host and sends a prompt through a loopback-only, same-origin API. The bridge issues only initialize, thread start/resume, turn start, interrupt, and request responses needed by those flows.

Each dashboard thread/turn receives explicit settings: `gpt-6-luna`, maximum reasoning effort, `approvalPolicy = never`, `workspace-write`, and the selected host user's `$HOME` as the only writable root. `Dashboard default` network access begins enabled; one persisted toggle controls both sandbox command networking and live web search for subsequent turns. Shared host `config.toml`, authentication, and fleet-synced profiles are untouched. Unexpected permission expansions beyond `$HOME` or beyond the network switch are denied.

The API binds to loopback by default and rejects control mutations without a same-origin loopback request. No user-authentication layer exists yet, so the dashboard must not be exposed through a network interface or reverse proxy.

## Consequences

The selected host's persistent app-server owns thread and turn history; the dashboard stores only profile preference and bounded metadata. The gateway streams assistant text and limited activity/usage events but never writes prompts, transcripts, or terminal output to JSONL telemetry. Closing the browser or SSH stream is not treated as turn cancellation; the operator must use the explicit interrupt action and reconcile terminal state. OpenClaw delegation and Herdr named-session control remain separate paths.
