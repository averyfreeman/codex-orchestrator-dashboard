---
title: Set up the dashboard
description: Install the self-hosted dashboard and configure a private host inventory.
---

## Requirements

- Node.js 22.12 or newer and npm.
- Python 3 for the bounded probe and control helpers.
- Codex CLI on the gateway host; SSH on the gateway and managed hosts.
- Herdr or Treehouse only on hosts where those views are needed.
- Optional: Ansible for provisioning Linux services and synchronizing the shared Codex profile.

The dashboard does not require a model API key for observation. Interactive turns use the selected host’s Codex app-server and that host’s existing Codex authentication.

## Install and start

```sh
git clone https://github.com/averyfreeman/codex-orchestrator-dashboard.git
cd codex-orchestrator-dashboard
npm ci
npm run dev
```

Open `http://127.0.0.1:3000`. The application binds to loopback by default. To run a production build locally, use `npm run build` followed by `npm start`.

## Configure the fleet

Copy [`config/fleet.example.json`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/config/fleet.example.json) to the ignored `config/fleet.local.json`. Add only the hosts this dashboard should manage. `FLEET_CONFIG_PATH` can point to another private JSON inventory.

Each host has a stable slug, display name, operating system, optional display-only LAN/Tailscale/ZeroTier addresses, and an ordered list of SSH routes. Put ZeroTier first and Tailscale second to use ZeroTier as the preferred path with tailnet failover. SSH uses batch mode and strict host-key checking with a host-key alias; install the host key before relying on the route.

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

`codexHome` is optional. Omit it for the default `~/.codex`; set it on a host when Codex uses a different directory. It accepts `~`, a path under the host user's home (for example, `~/.codex-work`), or an absolute path. For the local host, the dashboard process's `CODEX_HOME` environment variable is used when the inventory has no override. See the [configuration reference](../../reference/configuration/) for resolution and privacy details.

Do not put private addresses, personal hostnames, emails, or credentials in tracked files. Keep `fleet.local.json`, SSH keys, and `.env.local` on the gateway. The public-data scan checks tracked and non-ignored files before publication.

## Host services and profile sync

For Linux, use the [dynamic inventory](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/ansible/inventory.py) and [`sync-linux-fleet.yml`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/ansible/playbooks/sync-linux-fleet.yml). The `codex_profile` tag updates the shared Codex defaults without changing service lifecycle. On macOS, the LaunchAgent installer supports check-only and explicit install modes; see the [service templates](https://github.com/averyfreeman/codex-orchestrator-dashboard/tree/main/macos/LaunchAgents).

Codex authentication remains local to each host. Profile synchronization preserves auth and unrelated MCP/plugin configuration; never copy auth files between hosts.

For a step-by-step Codex fleet sync walkthrough, including reference selection, review, apply, and restart results, see [Codex fleet sync](../codex-sync/).
