# Codex fleet sync is reference, review, then apply

## Context

The operator wants the dashboard-controlled Codex hosts to converge on a selected host's CLI version, app-server runtime, plugin state, user config and profiles, user-owned skills, and resolved `CODEX_HOME` behavior. Host auth, MCP secrets, and machine-specific settings must remain independent. Existing control is intentionally narrow and loopback-only.

## Decision

Add an on-demand sync workflow with a reference host selected for every run. The dashboard inspects current source and target state, stores a ten-minute in-memory plan, shows safe classified diffs and blocked differences, then applies only the selected plan after explicit confirmation. Omitted API target lists select the other hosts that respond to inspection. Host health polling does not trigger sync inspection or writes.

Use a fixed Python helper over local execution or configured strict SSH routes. Resolve `CODEX_HOME` from the private host inventory, local environment, or `~/.codex`, and pass it explicitly to probes, control proxies, recovery, and sync. The macOS LaunchAgent installer reads the local override from the private inventory; Ansible expands each remote override against that host's home and passes it to Codex setup commands and managed daemon units. The browser receives no private path override.

Compare installed CLI and running app-server versions separately; `config.toml` and top-level `*.config.toml` profiles; Codex marketplace sources and enabled plugin selectors; and the user skill roots `~/.agents/skills` and `$CODEX_HOME/skills`. Keep repo-scoped and Codex-managed system skills out of host sync. Config transfer is limited to classified, portable scalar settings. Preserve credentials, auth files, MCP secret values, unclassified or machine-specific TOML values, and cache-only plugin sources. Transfer only bounded editable local plugin package sources whose paths, manifests, files, sizes, and content pass validation. Refresh Git marketplaces and install/remove Codex-owned OpenAI marketplace plugins through the Codex CLI; generated OpenAI marketplace snapshots are never transferred.

Apply config and profile edits with TOML validation, atomic replacement, and owner-only pre-change backups. Keep transfer payloads and plans in process memory. Persist only run IDs, host/category outcomes, versions, counts, and restart status; telemetry follows the same content-free rule. Reinspect source and target hashes immediately before apply and reject stale or expired plans.

Provide an opt-in “Auto-restart when finished” setting, off by default. Restart only the known dashboard-managed macOS LaunchAgent or Linux systemd user service, only when the app-server protocol confirms no active turn, and only after a sync changed CLI, config/profile, or plugin state. Unknown activity, active turns, or an unmanaged daemon defer the restart and report remaining runtime drift. This is a bounded exception to the normal down-only start recovery action, not a general service control surface.

Keep plan, apply, and run-status routes behind the existing local same-origin loopback guard. Only the plan/apply routes mutate remote state; run status exposes sanitized persisted metadata.

## Consequences

Every sync is operator-directed and reviewable, and routine polling remains read-only. A target may finish partially when a category is blocked or an individual host is unreachable; outcomes are recorded per host and category. Secret-bearing or unclassified values can differ across hosts without being copied. Per-host home paths may differ while dashboard-managed commands still use the correct explicitly resolved `CODEX_HOME`. Sync plans are intentionally process-local and must be recreated after a dashboard restart.
