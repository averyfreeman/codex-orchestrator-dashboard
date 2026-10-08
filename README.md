# Codex Orchestrator Dashboard

A self-hosted dashboard for Codex app-server health, Herdr sessions, Treehouse worktrees, and an optional local OpenClaw gateway. The Next.js app collects bounded metadata through local probes and SSH; it does not collect prompts, terminal output, credentials, or conversation contents.

## Run locally

```bash
npm install
npm run dev
```

The example inventory is empty, so the dashboard makes no remote connections until a private inventory is configured. Copy `config/fleet.example.json` to the ignored `config/fleet.local.json`, then add the hosts you intend to monitor. `FLEET_CONFIG_PATH` can point to another private inventory file.

An inventory host has this shape:

```json
{
  "slug": "node-a",
  "name": "Node A",
  "os": "Linux",
  "localIp": null,
  "tailscaleIp": null,
  "zerotierIp": null,
  "sshRoutes": [
    { "transport": "zerotier", "target": "operator@node-a.example.test", "hostKeyAlias": "fleet-node-a" },
    { "transport": "tailscale", "target": "operator@node-a.example.test", "hostKeyAlias": "fleet-node-a" }
  ]
}
```

Routes are tried in listed order; use ZeroTier first and Tailscale as failover. Each SSH call requires batch mode and strict host-key checking with the configured alias. LAN addresses are displayed only and are not SSH routes. Keep the local inventory and SSH private keys outside the public repository.

## Current dashboard surface

- **App-server fleet** — health, version, Remote Control state, startup status, and the route used to reach each host.
- **Herdr** — daemon state, workspaces, agent metadata, and process CPU/RSS.
- **Treehouse** — registered worktree names and paths.
- **OpenClaw** — optional local gateway health and aggregate session counts, projected from `openclaw status --json`.
- **Telemetry** — bounded JSONL snapshots in the ignored `logs/` directory.

The current application is an observation dashboard. Interactive control is designed around the selected host’s Codex app-server for Codex threads and turns, and Herdr’s named-session interface for Herdr sessions. OpenClaw is an explicit delegation option; it is not the default path. The dashboard does not expose arbitrary SSH, service-manager controls, or Codex daemon restarts.

Dashboard-managed Codex profiles are a separate policy from the shared fleet sync profile in `config/codex-fleet-profile.json`. The managed-profile design uses `approval_policy = "never"`, a `workspace-write` sandbox with the host’s `$HOME` as its writable root, and network access enabled by default. Its per-profile dashboard switch is designed to turn command networking and live web search off together for subsequent turns. It does not edit unrelated local Codex profiles. Treat this as a high-trust profile: while enabled, commands can access the network and write anywhere under the selected user’s home directory.

## Telemetry and retention

The collector returns status, versions, aggregate counts, process CPU/RSS, and worktree metadata. It polls every 30 seconds in the UI. Collection and rendering make no model calls, so the observer itself has no token cost. Resource use depends on SSH latency and host count; the research note gives a sizing heuristic and benchmark plan. Local JSONL files should be treated as private operational data. Keep retention short and never add prompts, tool output, environment variables, or auth material.

`POST /api/logs` accepts events only when `LOG_INGEST_TOKEN` is set. The logs route returns bounded recent snapshots. Keep `.env.local` private; it is ignored by Git.

## Host setup

`ansible/inventory.py` builds a dynamic inventory from the private fleet file and selects the first responding route in the configured order. The Linux playbook installs or reconciles Codex and Herdr user services and applies the shared fleet profile. That profile sync is intentionally conservative and does not overwrite local MCP/plugin configuration or auth files.

The macOS LaunchAgent templates under `macos/LaunchAgents` use a generic label for new installs. The installer detects an already-loaded matching Codex or Herdr label by suffix and preserves that label. LaunchAgents run in a GUI user session; Linux services use the user systemd manager.

Use `CODEX_CLI_PATH` and `OPENCLAW_CLI` if the relevant binaries are not on the dashboard process `PATH`.

## Architecture and research

See [`docs/architecture.md`](docs/architecture.md) for the system model and Mermaid flows, [`docs/research/interactive-control-options.md`](docs/research/interactive-control-options.md) for protocol/telemetry research with primary-source links, and [`CONTEXT.md`](CONTEXT.md) for the project vocabulary. Decisions are recorded in [`docs/adr/`](docs/adr/).

## Git workflow

`.githabits.yaml` records the allowed Git actions. The project Stop hook runs the public-snapshot scanner and repository checks, then stages, commits, creates a patch tag, and pushes to `main`. Codex’s Stop event does not expose an authoritative turn status, so exact completed-versus-failed gating requires the dashboard’s app-server event stream. Prototype work stays on its own branch. Codex requires local review and trust for project hooks; open `/hooks` in the Codex app to activate this workflow after reviewing the hook definition.

## Development checks

```bash
npm test
npm run lint
npx tsc --noEmit
npm run build
python3 scripts/test_sync_codex_profile.py
python3 -m unittest scripts/test_macos_launchagents.py
python3 -m py_compile scripts/probe.py scripts/sync_codex_profile.py ansible/inventory.py
python3 scripts/check_public_snapshot.py
cd ansible && ansible-playbook -i inventory.py --syntax-check playbooks/sync-linux-fleet.yml
```
