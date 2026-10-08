# Codex defaults and dashboard-managed permissions are explicit

## Context

The operator requested permissive Codex defaults on local machines and dashboard-initiated work, with `$HOME` as the write boundary, command/web access enabled by default, and a dashboard switch to disable networking for subsequent turns.

## Decision

Set the shared Codex user defaults to `model = "gpt-6-luna"`, maximum reasoning effort, `approval_policy = "never"`, `sandbox_mode = "workspace-write"`, the current user's home directory as an additional writable root, command networking enabled, and `web_search = "live"`. Apply these values through the profile synchronizer on Maccauley and the configured Linux fleet. Preserve authentication, MCP/plugin configuration, and other machine-specific settings.

Dashboard-initiated turns use the same sandbox boundary and approval policy through request-scoped app-server settings. A dashboard-managed network switch starts on and controls both sandbox command networking and live web search for later turns without editing the user's config file.

## Consequences

The defaults reduce interruptions while retaining the configured sandbox. With networking enabled, sandboxed tools can reach external services and write anywhere under that host user's home directory. `approval_policy = "never"` does not turn off independent browser, connector, or operating-system permissions. The dashboard bridge grants only filesystem paths under `$HOME` and requested sandbox networking; it declines out-of-scope access and unsupported elicitation requests. A network switch change affects subsequent turns and cannot retract a request already in flight.
