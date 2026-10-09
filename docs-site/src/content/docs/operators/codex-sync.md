---
title: Sync Codex hosts
description: Compare a reference host with selected peers, review safe differences, and apply a Codex sync plan.
---

Codex sync uses a **reference, review, apply** workflow. Every run reads current state on demand. The normal 30-second fleet health poll does not create sync plans or write to hosts.

## Before you start

- Add the local and remote Codex hosts to the private fleet inventory. Configure SSH routes and install each host key before using a remote host.
- Make sure the reference host has an installed Codex CLI version. It must appear in the dashboard's CLI version report to be selectable as a reference.
- Set `codexHome` for any host that uses a non-default Codex home. See [fleet configuration](../../reference/configuration/#codex_home); a target keeps its own resolved home path.
- Start the dashboard on its trusted gateway and open `http://127.0.0.1:3000`.

## Configure `CODEX_HOME`

The dashboard resolves a home path independently for every host. An inventory value takes priority. For the local host, the dashboard process's `CODEX_HOME` environment variable is the fallback; otherwise the default is `~/.codex`. Remote hosts use their inventory override or the default.

Add an optional value to the host object in the ignored `config/fleet.local.json` (or the file named by `FLEET_CONFIG_PATH`):

```json
{
  "slug": "node-a",
  "name": "Node A",
  "os": "Linux",
  "localIp": null,
  "tailscaleIp": null,
  "zerotierIp": null,
  "codexHome": "~/.codex-work",
  "sshRoutes": [
    { "transport": "zerotier", "target": "operator@node-a.example.test", "hostKeyAlias": "fleet-node-a" },
    { "transport": "tailscale", "target": "operator@node-a.example.test", "hostKeyAlias": "fleet-node-a" }
  ]
}
```

Use `~`, a path under the host user's home such as `~/.codex-work`, or an absolute path. Do not use a relative path or `..`. Remove `codexHome` to use the default. Keep the inventory private: the browser receives a safe path label, not the full absolute override. Restart the dashboard after changing the local process environment.

Changing an inventory override does not rewrite a launcher's existing service definition. Re-run the Linux fleet playbook to update its systemd units. On macOS, unload the managed Codex LaunchAgent before running `python3 scripts/install_macos_launchagents.py --install`; the installer refuses to replace a changed plist while that agent is loaded.

## Run a sync

1. **Open Codex sync.** Review the host table first. It shows the latest health snapshot, including installed CLI version, running app-server version, and the resolved `CODEX_HOME` label. Detailed sync inspection happens only after you request a comparison.
2. **Choose a reference host.** Select a host with a reported Codex CLI version. The reference is chosen for this run; it is not saved as a permanent fleet leader.
3. **Choose targets.** The dashboard initially selects the other currently reachable hosts. Unreachable hosts are shown as offline and cannot be selected in the UI. Remove peers you want to leave unchanged; at least one target is required.
4. **Create the plan.** Select **Compare & review**. The dashboard inspects the reference and targets through local execution or their configured strict SSH routes. This reads host state but does not apply changes. The plan expires after ten minutes.
5. **Review every target.** Compare CLI and app-server runtime versions, plugins, `config.toml`, profile files, user skills, and `CODEX_HOME` status. Expand each host to inspect its safe differences and blocked items. Review removals as carefully as additions: target-only enabled plugins and user skills can be removed. Replaced or removed config/profile files, user-skill files, and local plugin source files receive run-scoped backups.
6. **Resolve anything held for review.** A blocked item means the value or source failed a safety or classification rule and will stay on that host. Credentials, MCP secret values, machine-specific or unclassified settings, repo skills, Codex system skills, and generated plugin caches are outside host sync. Fix the underlying issue or accept that the hosts will retain that difference.
7. **Choose restart behavior.** **Auto-restart when finished** is off by default. Turn it on only when an affected dashboard-managed Codex daemon may be restarted after apply. The dashboard attempts a restart only when it can verify the service is managed and idle. An active turn, unknown activity, or unmanaged service produces a deferred result; the dashboard does not queue an automatic retry.
8. **Apply the reviewed plan.** Select **Apply to N targets**. The server checks the reference and targets again. If state changed, the plan expired, or the dashboard restarted and discarded its in-memory plan, apply is rejected; create a new plan and review it before applying.
9. **Read the run results.** Follow each host's category outcomes. A completed host has applied its eligible changes. Partial or failed outcomes identify categories that need attention; an unreachable host may require an SSH or route repair before a new plan. If runtime drift remains after a deferred restart, wait until active turns finish and use the host's normal service procedure when appropriate.

## What the plan means

`CODEX_HOME` is resolved per target and explicitly passed to its probe, control, recovery, sync helper, and dashboard-managed launcher. The sync compares host settings with paths normalized to each user's home. Different `CODEX_HOME` paths across machines are expected; the dashboard reports a safe label for each host instead of sending the private absolute override to the browser.

The installed `codex --version` and running app-server version are separate categories. When needed, the helper uses the official Codex installer to install the reference CLI release. An already-running app-server can continue to report its prior runtime until an eligible managed-daemon restart. Leave restart off when you do not want an automatic attempt.

The helper applies only classified, portable settings. It preserves unrelated TOML and local auth, and uses Codex commands to reconcile supported plugin marketplaces and enabled plugin state. Validated editable local plugin packages may be transferred; generated caches are not. Config/profile changes are validated, written atomically, and backed up under the host's resolved Codex home. Run records and telemetry contain versions, category outcomes, IDs, and counts rather than raw config, file contents, or credentials.

For request shapes and the local-origin boundary, see the [HTTP API reference](../../reference/api/). The full control boundary is in the [architecture guide](../../maintainers/architecture/) and [ADR 0006](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/docs/adr/0006-codex-fleet-sync.md).
