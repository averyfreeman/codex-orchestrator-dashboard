---
title: Recovery and reconnects
description: Recover from reachability failures without confusing a dropped connection with stopped work.
---

## Route failover

SSH routes are attempted in configured order. A typical inventory lists ZeroTier first and Tailscale second, with strict host-key checking and a fixed alias on both routes. The dashboard reports which transport succeeded. It does not silently weaken SSH host-key checks or turn display-only LAN addresses into routes.

Before changing a route, verify from the gateway host that the target is reachable on that overlay and that its host key matches the configured alias. Keep route ordering in the private fleet inventory so collection and control agree.

## Codex daemon recovery

The **Start daemon** action appears only when the selected host is unavailable. The server rechecks status and returns a conflict if the app-server is already responding. If still down, the fixed recovery helper requests `codex app-server daemon start`; it does not accept arbitrary command text or restart a responding daemon.

After the request, refresh the fleet view and inspect the reported transport and status. Automatic service retry belongs to the configured systemd user service/ensure timer on Linux or LaunchAgent on macOS. The dashboard action is a bounded manual recovery path, not a replacement for service supervision.

Codex sync has a separate opt-in restart attempt after it applies changes that affect a managed daemon. It runs only when the dashboard can verify the daemon is managed and idle. If activity is unknown, a turn is active, or the daemon is unmanaged, the result is marked deferred and runtime drift remains visible. The dashboard does not queue an automatic retry; use the host's normal service procedure when it is safe. See the [Codex sync walkthrough](../codex-sync/).

## Interrupted control connections

A dropped browser stream or SSH proxy does not prove that Codex stopped its turn. Reconnect to the same host and thread, read authoritative app-server state, and interrupt only the specific active turn if appropriate. An interrupt acknowledgement is not itself a terminal-state confirmation.

Herdr sessions can outlive a detached client. Stop only the intended named session; the protected default session and bulk stop are excluded from dashboard controls.
