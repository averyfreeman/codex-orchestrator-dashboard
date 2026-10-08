"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { HostReport } from "@/lib/hosts";
import type { OpenClawReport } from "@/lib/orchestrator";
import { ControlPanel } from "./control-panel";
import { HerdrSessionsPanel } from "./herdr-sessions-panel";

type View = "app-server" | "herdr" | "treehouse" | "orchestrator" | "control";
type LogItem = { at: string; source: string; host: string; type: string; stats?: Record<string, unknown> };

function timeAgo(value?: string) {
  if (!value) return "—";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ago`;
}

function Kpi({ label, value, hint, tone = "neutral" }: { label: string; value: string | number; hint: string; tone?: string }) {
  return <article className="kpi"><div className="kpi-label">{label}</div><div className={`kpi-value ${tone}`}>{value}</div><div className="kpi-hint">{hint}</div></article>;
}

function Health({ online, label }: { online: boolean; label: string }) {
  return <span className={`health ${online ? "healthy" : "offline"}`}><i />{label}</span>;
}

function HostCard({ report, recovering, onRecover }: { report: HostReport; recovering: boolean; onRecover: () => void }) {
  const online = report.reachable;
  return (
    <article className={`host-card ${online ? "" : "host-card-offline"}`}>
      <div className="host-card-top">
        <div><span className={`host-mark ${online ? "up" : "down"}`}>{report.host.name.slice(0, 1).toUpperCase()}</span></div>
        <div className="host-title"><h3>{report.host.name}</h3><p>{report.host.os}</p></div>
        <Health online={online} label={online ? "Responding" : "Unavailable"} />
      </div>
      <div className="host-addresses">
        <div><span>LAN</span><code>{report.host.localIp ?? "—"}</code></div>
        <div><span>TAILSCALE</span><code>{report.host.tailscaleIp ?? "—"}</code></div>
        <div><span>ZEROTIER</span><code>{report.host.zerotierIp ?? "—"}</code></div>
      </div>
      <div className="host-card-bottom">
        <span className="minor">Codex {report.appServer.version ?? "—"}</span>
        <span className="minor">RC {report.appServer.remoteControlEnabled === null ? "unknown" : report.appServer.remoteControlEnabled ? "enabled" : "off"} · {report.appServer.remoteControlRuntime}</span>
        <span className="minor">{report.appServer.loadedThreads === null ? "threads —" : `${report.appServer.loadedThreads} loaded`}</span>
        <span className="minor transport-note">Via {report.connection.transport === "unavailable" ? "—" : report.connection.transport === "local" ? "Local" : report.connection.transport === "zerotier" ? "ZeroTier" : "Tailscale"}</span>
        {!online && <button type="button" className="recovery-button" disabled={recovering} onClick={onRecover}>{recovering ? "Starting…" : "Start daemon"}</button>}
      </div>
      {report.error && <p className="host-error">{report.error}</p>}
    </article>
  );
}

function OpenClawPanel({ report }: { report: OpenClawReport | null }) {
  return (
    <section className="view-panel" aria-label="OpenClaw orchestrator">
      <div className="panel-heading">
        <div><h2>Local OpenClaw gateway</h2><p>Read-only health and aggregate agent session counts.</p></div>
        <span className="panel-count">ORCHESTRATOR</span>
      </div>
      {!report || report.status === "unavailable" ? (
        <div className="empty-state"><div className="empty-graphic">⌘</div><strong>OpenClaw status unavailable</strong><p>The local CLI did not return a gateway status. Fleet monitoring remains available.</p></div>
      ) : (
        <div className="orchestrator-grid">
          <article className="orchestrator-card">
            <div className="orchestrator-label">GATEWAY</div>
            <Health online={report.gateway.reachable} label={report.gateway.reachable ? "reachable" : "unreachable"} />
            <strong>{report.gateway.mode ?? "mode unknown"}</strong>
            <code>{report.gateway.url ?? "URL unavailable"}</code>
            <small>{report.gateway.latencyMs === null ? "latency —" : `${report.gateway.latencyMs} ms connect latency`}</small>
          </article>
          <article className="orchestrator-card orchestrator-total">
            <div className="orchestrator-label">OPEN SESSIONS</div>
            <strong>{report.totalSessions}</strong>
            <small>Aggregate count reported by OpenClaw</small>
          </article>
          {report.agents.map((agent) => (
            <article className="orchestrator-card" key={agent.id}>
              <div className="orchestrator-label">AGENT</div>
              <strong>{agent.id}</strong>
              <small>{agent.sessions} sessions</small>
            </article>
          ))}
        </div>
      )}
      <div className="table-note"><span className="info-mark">i</span> The dashboard reads gateway and aggregate session metadata only. It does not read session files, messages, credentials, or call agent tools.</div>
    </section>
  );
}

/** Render the polling fleet overview and switchable operational views. */
export default function Home() {
  const [view, setView] = useState<View>("app-server");
  const [hosts, setHosts] = useState<HostReport[]>([]);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [openClaw, setOpenClaw] = useState<OpenClawReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [recoveringHost, setRecoveringHost] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [lastChecked, setLastChecked] = useState<string>();
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async (quiet = false) => {
    if (quiet) setRefreshing(true);
    else setLoading(true);
    try {
      const [overviewResponse, logResponse, openClawResponse] = await Promise.all([
        fetch("/api/overview", { cache: "no-store" }),
        fetch("/api/logs", { cache: "no-store" }),
        fetch("/api/orchestrator", { cache: "no-store" }),
      ]);
      if (!overviewResponse.ok) throw new Error("Could not read fleet status");
      const overview = await overviewResponse.json();
      const activity = await logResponse.json();
      const orchestrator = openClawResponse.ok ? await openClawResponse.json() : null;
      setHosts(overview.hosts);
      setLogs(activity.events ?? []);
      setOpenClaw(orchestrator);
      setLastChecked(overview.checkedAt);
      setNotice("");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Refresh failed");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(true), 30_000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [refresh]);

  async function recoverCodex(host: HostReport["host"]) {
    if (recoveringHost) return;
    let statusRefreshPending = false;
    setRecoveringHost(host.slug);
    setNotice("");
    try {
      const response = await fetch("/api/control/codex/recover", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host: host.slug }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not start the Codex daemon.");
      setNotice(`${host.name}: ${result.message ?? "Codex daemon start requested."} Checking fleet status shortly.`);
      statusRefreshPending = true;
      window.setTimeout(() => {
        void refresh(true).finally(() => setRecoveringHost(null));
      }, 2_000);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Codex daemon recovery failed.");
    } finally {
      if (!statusRefreshPending) setRecoveringHost(null);
    }
  }

  const counts = useMemo(() => ({
    online: hosts.filter((host) => host.reachable).length,
    agents: hosts.reduce((sum, host) => sum + host.herdr.agents.length, 0),
    worktrees: hosts.reduce((sum, host) => sum + host.worktrees.length, 0),
  }), [hosts]);

  const visibleHosts = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return hosts;
    return hosts.filter((report) => [report.host.name, report.host.os, report.host.localIp, report.host.tailscaleIp, report.host.zerotierIp].join(" ").toLowerCase().includes(q));
  }, [hosts, query]);

  const viewLabel = view === "app-server" ? "App-server fleet" : view === "herdr" ? "Herdr sessions" : view === "treehouse" ? "Treehouse worktrees" : view === "orchestrator" ? "OpenClaw gateway" : "Interactive control";

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-icon"><span /><span /><span /></div><div><strong>FIELDNOTE</strong><small>CODEX FLEET</small></div></div>
        <div className="side-label">WORKSPACE</div>
        <button className="workspace-switch"><span className="workspace-dot" /> Orchestrator <span className="chevron">⌄</span></button>
        <div className="side-label side-label-spaced">VIEWS</div>
        <nav className="side-nav" aria-label="Dashboard views">
          <button className={view === "app-server" ? "selected" : ""} onClick={() => setView("app-server")}><span className="nav-icon">◉</span> App-server fleet <b>{hosts.filter((host) => host.reachable).length}</b></button>
          <button className={view === "herdr" ? "selected" : ""} onClick={() => setView("herdr")}><span className="nav-icon">▦</span> Herdr sessions <b>{counts.agents}</b></button>
          <button className={view === "treehouse" ? "selected" : ""} onClick={() => setView("treehouse")}><span className="nav-icon">⌘</span> Treehouse <b>{counts.worktrees}</b></button>
          <button className={view === "orchestrator" ? "selected" : ""} onClick={() => setView("orchestrator")}><span className="nav-icon">◎</span> OpenClaw <b>{openClaw?.totalSessions ?? "—"}</b></button>
          <button className={view === "control" ? "selected" : ""} onClick={() => setView("control")}><span className="nav-icon">✳</span> Control <b>Codex</b></button>
        </nav>
        <div className="sidebar-spacer" />
        <div className="sidebar-foot"><span className="pulse-dot" /> Polling every 30 sec <small>ZeroTier first · Tailscale fallback</small></div>
        <div className="user-chip"><div className="avatar">O</div><div><strong>Operator</strong><small>fleet admin</small></div><span className="more">···</span></div>
      </aside>

      <section className="main-area">
        <header className="topbar"><div className="breadcrumbs"><span>Fleet</span><span>/</span><strong>{viewLabel}</strong></div><div className="top-actions"><span className="updated">Updated {timeAgo(lastChecked)}</span><button className="refresh-button" onClick={() => void refresh(true)} disabled={refreshing}>{refreshing ? "Refreshing…" : "↻ Refresh"}</button><div className="top-avatar">O</div></div></header>
        <div className="content">
          <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> OPERATIONS OVERVIEW</div><h1>{viewLabel}</h1><p>One place to see the machines, sessions, and worktrees behind your Codex fleet.</p></div><div className="heading-meta"><span className="live-indicator"><i /> LIVE</span><span>Last sync {lastChecked ? new Date(lastChecked).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "—"}</span></div></div>

          <div className="kpi-grid">
            <Kpi label="APP-SERVERS ONLINE" value={`${counts.online} / ${hosts.length}`} hint="Managed daemon responses" tone="mint" />
            <Kpi label="ACTIVE AGENTS" value={counts.agents} hint="Reported by Herdr" tone="lavender" />
            <Kpi label="WORKTREES" value={counts.worktrees} hint="Recorded by Treehouse" tone="amber" />
            <Kpi label="TRANSPORTS" value="3" hint="Tailscale · ZeroTier · LAN" tone="blue" />
          </div>

          <div className="section-bar"><div className="tabs" role="tablist" aria-label="Fleet view">
            <button role="tab" aria-selected={view === "app-server"} className={view === "app-server" ? "active" : ""} onClick={() => setView("app-server")}>App-server</button>
            <button role="tab" aria-selected={view === "herdr"} className={view === "herdr" ? "active" : ""} onClick={() => setView("herdr")}>Herdr</button>
            <button role="tab" aria-selected={view === "treehouse"} className={view === "treehouse" ? "active" : ""} onClick={() => setView("treehouse")}>Treehouse / worktrees</button>
            <button role="tab" aria-selected={view === "orchestrator"} className={view === "orchestrator" ? "active" : ""} onClick={() => setView("orchestrator")}>OpenClaw</button>
            <button role="tab" aria-selected={view === "control"} className={view === "control" ? "active" : ""} onClick={() => setView("control")}>Interactive control</button>
          </div><label className="search-box"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter hosts" aria-label="Filter hosts" /><kbd>⌘ K</kbd></label></div>

          {notice && <div className="notice" role="status"><span>ⓘ</span>{notice}<button onClick={() => setNotice("")} aria-label="Dismiss notice">×</button></div>}
          {loading && hosts.length === 0 ? <div className="loading-panel"><span className="loader" /> Connecting to configured hosts…</div> : null}

          {view === "app-server" && <section className="view-panel" aria-label="App-server hosts">
            <div className="panel-heading"><div><h2>Machines</h2><p>Daemon health, Remote Control configuration, and address paths.</p></div><span className="panel-count">{visibleHosts.length} HOSTS</span></div>
            <div className="host-grid">{visibleHosts.map((report) => <HostCard key={report.host.slug} report={report} recovering={recoveringHost === report.host.slug} onRecover={() => void recoverCodex(report.host)} />)}</div>
            <div className="table-note"><span className="info-mark">i</span> “Responding” means the managed app-server control socket answered. SSH tries ZeroTier first, then Tailscale, with strict host-key checking on both paths. Remote Control runtime and loaded-thread count come from read-only status/list RPCs; no conversation content is read.</div>
          </section>}

          {view === "herdr" && <><HerdrSessionsPanel hosts={hosts.map(({ host, connection }) => ({ host, connection }))} /><section className="view-panel" aria-label="Herdr sessions">
            <div className="panel-heading"><div><h2>Herdr machines &amp; agents</h2><p>Persistent terminal sessions and agent metadata reported by each Herdr server.</p></div><span className="panel-count">{counts.agents} AGENTS</span></div>
            <div className="agent-table-wrap"><table><thead><tr><th>MACHINE</th><th>SERVER</th><th>WORKSPACES</th><th>AGENTS</th><th>DAEMON PID / USAGE</th></tr></thead><tbody>{visibleHosts.map((report) => <tr key={report.host.slug}><td><div className="machine-cell"><span className={`tiny-status ${report.herdr.status === "running" ? "on" : "off"}`} /> <strong>{report.host.name}</strong><small>{report.connection.transport === "unavailable" ? "no SSH route" : `via ${report.connection.transport}`}</small></div></td><td><Health online={report.herdr.status === "running"} label={report.herdr.status} /><small className="version-note">{report.herdr.version ? `v${report.herdr.version}` : ""}</small><small className="version-note">Auto-start: {report.herdr.startup}</small></td><td>{report.herdr.workspaces.length || "—"}{report.herdr.workspaces.length > 0 && <small className="subline">{report.herdr.workspaces.join(", ")}</small>}</td><td>{report.herdr.agents.length ? report.herdr.agents.map((agent) => <div className="agent-pill" key={agent.id}><span className="tiny-status on" />{agent.name}<small>{agent.state}{agent.pid ? ` · PID ${agent.pid}` : ""}</small></div>) : <span className="muted">No active agents</span>}</td><td>{report.processes.length ? report.processes.map((proc) => <div className="process-cell" key={proc.pid}><strong>PID {proc.pid} · {proc.command}</strong><small>{proc.cpuPercent.toFixed(1)}% CPU · {proc.memoryMb} MB · {proc.elapsed}</small></div>) : <span className="muted">No daemon process</span>}</td></tr>)}</tbody></table></div>
            <div className="table-note"><span className="info-mark">i</span> Herdr agent names/states and daemon process usage are metadata only; terminal contents are never collected.</div>
          </section></>}

          {view === "treehouse" && <section className="view-panel" aria-label="Treehouse worktrees">
            <div className="panel-heading"><div><h2>Worktree inventory</h2><p>Treehouse state files across each user account. No terminal output is read.</p></div><span className="panel-count">{counts.worktrees} WORKTREES</span></div>
            <div className="agent-table-wrap"><table><thead><tr><th>WORKTREE</th><th>MACHINE</th><th>PATH</th><th>CREATED</th><th>STATE</th></tr></thead><tbody>{visibleHosts.flatMap((report) => report.worktrees.map((worktree) => <tr key={`${report.host.slug}:${worktree.path}`}><td><strong>{worktree.name}</strong></td><td>{report.host.name}</td><td><code className="path-cell">{worktree.path}</code></td><td>{worktree.createdAt ? new Date(worktree.createdAt).toLocaleDateString() : "—"}</td><td><span className="worktree-state">Registered</span></td></tr>))}</tbody></table>{counts.worktrees === 0 && <div className="empty-state"><div className="empty-graphic">⌘</div><strong>No Treehouse worktrees registered yet</strong><p>Treehouse is installed on the reachable hosts. Worktrees appear here after a repository creates them.</p></div>}</div>
            <div className="table-note"><span className="info-mark">i</span> Treehouse provides repo-scoped worktree context; an empty list means no state files were found, not that the binaries are missing.</div>
          </section>}

          {view === "orchestrator" && <OpenClawPanel report={openClaw} />}

          {view === "control" && <ControlPanel hosts={hosts.map(({ host, reachable, connection }) => ({ host, reachable, connection }))} />}

          {view !== "control" && <section className="activity-section"><div className="activity-heading"><div><h2>Recent telemetry</h2><p>Plaintext JSONL snapshots · local file-backed stub</p></div><a href="/api/logs" target="_blank" rel="noreferrer">View API ↗</a></div><div className="activity-list">{logs.slice(-5).reverse().map((item, index) => <div className="activity-row" key={`${item.at}-${index}`}><span className="activity-dot" /><div><strong>{item.type === "snapshot" ? "Fleet snapshot collected" : item.type}</strong><p>{item.host} · {item.at ? new Date(item.at).toLocaleTimeString() : ""}</p></div><span className="activity-source">{item.source}</span></div>)}{logs.length === 0 && <div className="activity-empty">No snapshots yet. Refresh to collect the first one.</div>}</div></section>}
          <footer className="footer"><span>FIELDNOTE · PRIVATE FLEET VIEW</span><span>SSH host-key checking enabled</span></footer>
        </div>
      </section>
    </main>
  );
}
