# Herdr controls operate on named sessions only

## Context

The dashboard needs a small way to start and stop workspaces managed by Herdr without becoming a general remote terminal or process manager. Stopping a Herdr session also ends the processes running in its panes.

## Decision

Use Herdr's session list/start/stop CLI through the local machine or an allowlisted, strict-SSH route. Try ZeroTier first and Tailscale only when the read-only session listing cannot connect. Send a start/stop request once, then reconcile the result with a fresh listing. Accept only validated lowercase named-session identifiers and protect `default` from dashboard mutations. Set `HERDR_ENV=1` only for dashboard-initiated Herdr subprocesses.

## Consequences

The dashboard can list sessions and start or stop one named session at a time. Stopping can end every process in that session's panes, so the UI names the session and asks for confirmation. The dashboard does not attach to sessions, send pane input, stop every session, or manage host services. Read-only session metadata and bounded lifecycle outcomes may be logged; terminal content is not collected.
