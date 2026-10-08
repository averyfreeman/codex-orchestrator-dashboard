# Dashboard-managed Codex profiles carry explicit permissions

## Context

Dashboard-initiated work needs predictable permissions without changing every local Codex configuration or the conservative shared fleet sync profile. The operator chose auto-approval, a `$HOME` writable root, and network access for dashboard-managed profiles, while keeping profiles separately controllable.

## Decision

Create dashboard-managed profiles with `approval_policy = "never"`, `sandbox_mode = "workspace-write"`, and the selected host user’s home directory as the writable root. Enable command networking and live web search by default. Provide one per-profile network switch that turns both settings off or on for subsequent turns. Keep this policy scoped to dashboard-managed profiles; do not change unrelated local or shared fleet profiles.

## Consequences

The profile reduces interruptions while retaining the configured sandbox. With networking enabled, tools can reach external services and write anywhere under that host user’s home directory. A switch change cannot retract a request already in flight. The UI must show the selected host and profile, record policy changes, and explain that browser, connector, MCP, and model traffic use separate controls. The shared fleet profile remains unchanged.
