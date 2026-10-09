# Project vocabulary

Keep this file to definitions. Interface choices and implementation details live in the architecture record and ADRs.

- **Fleet:** the configured set of hosts visible to one dashboard installation.
- **Host:** one machine that runs Codex app-server, Herdr, or both.
- **Codex thread:** a durable conversation/session managed by Codex app-server.
- **Codex turn:** one unit of assistant work inside a thread, with a start, progress events, and a terminal state.
- **Herdr session:** a named persistent terminal workspace whose panes may continue running while detached.
- **Dashboard-managed profile:** a Codex configuration preset owned by the dashboard and applied only to work started through that profile.
- **OpenClaw delegation:** an explicit task sent to the OpenClaw gateway, with its own session identity and status.
- **Fleet snapshot:** one bounded, content-free collection of host and agent metadata at a point in time.
- **Codex sync plan:** a short-lived comparison of one reference host and selected peers, with reviewed changes and blocked differences.
- **CODEX_HOME:** the per-user Codex state directory resolved for a host and passed explicitly to dashboard-managed Codex commands.
