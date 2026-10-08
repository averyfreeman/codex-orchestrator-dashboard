---
title: Python helper reference
description: Documented CLI boundaries for local profile sync, collection, Codex, Herdr, and recovery helpers.
---

The control, recovery, and Herdr bridge scripts accept one JSON request on stdin and emit a bounded result on stdout. The probe source emits the host report directly; the profile and LaunchAgent utilities expose explicit CLI flags. The Next.js control routes validate their requests before starting a helper and suppress stderr where command details could expose private state.

| Script | Entrypoint | Contract |
| --- | --- | --- |
| [`scripts/probe.py`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/scripts/probe.py) | Probe CLI | Collect bounded host, Codex, Herdr, process, and Treehouse metadata for the local host. |
| [`scripts/codex_control.py`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/scripts/codex_control.py) | JSON stdin, `mode=turn` or `mode=interrupt` | Bridge selected-host Codex app-server RPC over local/strict SSH transport; project events without persisting conversation content. |
| [`scripts/herdr_sessions.py`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/scripts/herdr_sessions.py) | JSON stdin with `action=list\|start\|stop` | List or mutate one validated named Herdr session; refuses the protected default session for stop. |
| [`scripts/codex_recovery.py`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/scripts/codex_recovery.py) | JSON stdin containing one configured host | Request the fixed Codex daemon start operation after the API has verified the host is not responding. |
| [`scripts/sync_codex_profile.py`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/scripts/sync_codex_profile.py) | `--check` or `--write` | Merge the declared profile keys into `config.toml`, resolving `$HOME` roots and preserving unrelated settings. |
| [`scripts/install_macos_launchagents.py`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/scripts/install_macos_launchagents.py) | `--check` or `--install` | Verify or install the current user’s Codex and Herdr LaunchAgents. |

`--check` modes are the safe default for inspecting profile and LaunchAgent drift. `--write` and `--install` mutate local configuration and should be invoked deliberately. The dashboard control routes constrain request shape before calling the bridge; do not turn these helper scripts into an arbitrary command interface.
