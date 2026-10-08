# Selected-host control uses native runtime interfaces

## Context

The dashboard needs to move from observation to controlling Codex and Herdr work without turning into a general remote shell. Codex app-server owns Codex threads and turns; Herdr owns persistent named terminal sessions. OpenClaw is useful for a different, delegated task path.

## Decision

Use the selected host’s Codex app-server protocol for Codex thread/turn start, streaming, and interruption. Use Herdr’s named-session interface for Herdr session lifecycle actions. Keep OpenClaw delegation explicit and separate through its client bridge. Treat A2A as a future inter-agent task protocol, not as a replacement for native host control. Tunnel host-local app-server transport over verified SSH, trying ZeroTier before Tailscale.

## Consequences

The dashboard can present native thread and turn state and can interrupt a specific turn. The selected host and profile remain visible for each operation. Loss of a browser or SSH connection is reconciled from runtime state rather than treated as cancellation. Arbitrary SSH, host service controls, and Codex daemon restarts remain outside the control interface. OpenClaw cancellation is reported only when its selected interface confirms it.
