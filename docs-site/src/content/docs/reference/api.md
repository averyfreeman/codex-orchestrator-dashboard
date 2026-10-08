---
title: HTTP API reference
description: Read-only status endpoints and loopback-only dashboard control routes.
---

All routes are served by the self-hosted Next.js application. State-changing control routes require the dashboard’s local-origin check; this check is CSRF protection, not authentication. Some read-only routes do not check the origin, so keep the server bound to loopback. The browser does not receive SSH credentials. Do not expose these endpoints through a proxy without an authentication design.

## Observation

| Method and path | Purpose | Response / boundary |
| --- | --- | --- |
| `GET /api/overview` | Collect the configured fleet and append a bounded snapshot | `{ checkedAt, hosts }`; `no-store` |
| `GET /api/logs` | Read the bounded recent local event window | `{ events }`; `no-store` |
| `POST /api/logs` | Ingest one event | Requires `LOG_INGEST_TOKEN` bearer auth; body max 10 KB; validated shape |
| `GET /api/orchestrator` | Project local `openclaw status --json` | Sanitized gateway metadata; unavailable response on command/parse failure |

## Control

| Method and path | Request | Purpose |
| --- | --- | --- |
| `GET /api/control/profile` | — | Read current dashboard-managed profile settings |
| `PUT /api/control/profile` | `{ "networkAccess": boolean }` | Set command networking and web search mode for subsequent turns |
| `POST /api/control/codex/turn` | `{ "host": string, "prompt": string, "threadId"?: string }` | Start/resume a selected-host turn; returns Server-Sent Events |
| `POST /api/control/codex/interrupt` | `{ "host": string, "threadId": string, "turnId": string }` | Request interrupt of one specific turn |
| `POST /api/control/codex/recover` | `{ "host": string }` | Request fixed Codex daemon start only after server-side down check |
| `GET /api/control/herdr/sessions?host={slug}` | — | List sessions on one configured host |
| `POST /api/control/herdr/sessions` | `{ "host": string, "action": "start"\|"stop", "name": string }` | Start/stop one validated named session; `default` is protected |

Every host field must resolve against the private fleet inventory. Mutation routes reject non-local origins. The turn route caps prompt length at 40,000 characters and sends streaming events; interrupt success indicates acknowledgement, not final turn status. The app-server event stream supplies the terminal status.

Implementation links: [`src/app/api`](https://github.com/averyfreeman/codex-orchestrator-dashboard/tree/main/src/app/api), [`control security`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/src/lib/control-security.ts), [`telemetry schema`](https://github.com/averyfreeman/codex-orchestrator-dashboard/blob/main/src/lib/logging.ts).
