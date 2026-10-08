---
title: Use Codex and Herdr controls
description: Start selected-host Codex turns and manage named Herdr sessions safely.
---

## Codex conversation

The Control view requires an explicit host. Its first prompt creates a thread; later prompts in that view continue using the returned thread ID. The API also accepts an explicit `threadId` to resume a known thread. The view streams assistant text and activity updates and shows turn state and usage notifications. The browser’s connection is not the turn’s lifetime: if the page or SSH stream closes, the remote turn may continue. Reconnect and reconcile with app-server state before assuming the turn ended.

Interrupt targets one explicit thread and turn. The API reports that the request was acknowledged; the app-server’s terminal event is authoritative about whether the turn completed, failed, or was interrupted.

Prompts and replies are delivered to the selected host’s Codex thread. Telemetry records identifiers, policy, result, timing, and usage metadata, but does not include prompt or terminal contents.

## Herdr named sessions

Select a host to list its named sessions. Start and stop actions are scoped to a validated session name. The protected `default` session cannot be stopped through the dashboard. Stopping a named session ends that session’s panes and runtime; detaching a client does not.

## Separate integrations

The local OpenClaw gateway panel is observation-only. There is no implicit delegation from a Codex prompt to OpenClaw. If explicit OpenClaw delegation is added later, it should have its own destination label, task/session ID, status, and cancellation semantics.

The dashboard does not provide arbitrary SSH commands, general process termination, bulk session shutdown, or app-server daemon restart controls. This keeps actions specific to the selected host and documented API.

See the [HTTP route reference](../../reference/api/) for request shapes and local-origin requirements.
