"use client";

import { useEffect, useState } from "react";
import type { HostReport } from "@/lib/hosts";

type HerdrHost = Pick<HostReport, "host" | "connection">;
type HerdrSession = { name: string; running: boolean; default: boolean };

/** List and manage validated named Herdr sessions on one selected host. */
export function HerdrSessionsPanel({ hosts }: { hosts: HerdrHost[] }) {
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("dashboard-work");
  const [sessions, setSessions] = useState<HerdrSession[]>([]);
  const [transport, setTransport] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshId, setRefreshId] = useState(0);
  const defaultHost = hosts[0];
  const hostSlug = selected || defaultHost?.host.slug || "";
  const currentHost = hosts.find((host) => host.host.slug === hostSlug);
  const routeAvailable = currentHost?.connection.transport !== "unavailable";

  useEffect(() => {
    if (!hostSlug) return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      void fetch(`/api/control/herdr/sessions?host=${encodeURIComponent(hostSlug)}`, { cache: "no-store", signal: controller.signal })
        .then(async (response) => {
          const result = await response.json();
          if (!response.ok) throw new Error(result.error ?? "Could not list Herdr sessions.");
          setSessions(Array.isArray(result.sessions) ? result.sessions : []);
          setTransport(typeof result.transport === "string" ? result.transport : "");
          setNotice("");
        })
        .catch((error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") return;
          setSessions([]);
          setNotice(error instanceof Error ? error.message : "Could not list Herdr sessions.");
        })
        .finally(() => setLoading(false));
    }, 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [hostSlug, refreshId]);

  async function changeSession(action: "start" | "stop", sessionName: string) {
    if (!hostSlug || busy) return;
    if (action === "stop" && !window.confirm(`Stop Herdr session “${sessionName}” on ${currentHost?.host.name}? All pane processes in that named session will end.`)) return;
    setBusy(`${action}:${sessionName}`);
    setNotice("");
    try {
      const response = await fetch("/api/control/herdr/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host: hostSlug, action, name: sessionName }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? `Herdr session ${action} failed.`);
      setNotice(result.state === "starting" || result.state === "stopping"
        ? `${sessionName} is ${result.state}; refresh to reconcile the host status.`
        : `Herdr session ${sessionName} is ${result.state}.`);
      setRefreshId((value) => value + 1);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `Herdr session ${action} failed.`);
    } finally {
      setBusy("");
    }
  }

  function startSession(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!/^[a-z][a-z0-9_-]{0,31}$/.test(name) || name === "default") {
      setNotice("Use a lowercase name starting with a letter, up to 32 characters. The default session is protected.");
      return;
    }
    void changeSession("start", name);
  }

  return (
    <section className="view-panel" aria-label="Herdr named sessions">
      <div className="panel-heading"><div><h2>Named Herdr sessions</h2><p>Start or stop an isolated Herdr server namespace on one selected host.</p></div><span className="panel-count">HERDR CONTROL</span></div>
      <div className="session-control-toolbar">
        <label>HOST<select className="select select-bordered select-sm" value={hostSlug} onChange={(event) => { setSelected(event.target.value); setSessions([]); setNotice(""); }} disabled={!hosts.length || !!busy}>
          {hosts.map((host) => <option key={host.host.slug} value={host.host.slug}>{host.host.name}</option>)}
        </select></label>
        <span className="session-transport">Via {transport || currentHost?.connection.transport || "—"}</span>
        <button type="button" className="btn btn-sm refresh-button" onClick={() => setRefreshId((value) => value + 1)} disabled={loading || !!busy}>{loading ? "Loading…" : "↻ Refresh"}</button>
      </div>
      <form className="session-create-form" onSubmit={startSession}>
        <label>Session name<input value={name} onChange={(event) => setName(event.target.value)} maxLength={32} pattern="[a-z][a-z0-9_-]{0,31}" disabled={!routeAvailable || !!busy} /></label>
        <button type="submit" className="btn btn-sm refresh-button" disabled={!routeAvailable || !name || !!busy}>{busy.startsWith("start:") ? "Starting…" : "Start named session"}</button>
        <span>New sessions run a headless Herdr server. The default session is protected.</span>
      </form>
      {notice && <div className="notice" role="status">{notice}<button type="button" onClick={() => setNotice("")} aria-label="Dismiss notice">×</button></div>}
      <div className="named-session-list">
        {loading && sessions.length === 0 ? <div className="activity-empty">Loading Herdr sessions…</div> : null}
        {!loading && sessions.length === 0 && !notice ? <div className="activity-empty">No Herdr session metadata was returned for this host.</div> : null}
        {sessions.map((session) => <div className="named-session-row" key={`${hostSlug}:${session.name}`}>
          <span className={`tiny-status ${session.running ? "on" : "off"}`} />
          <strong>{session.name}</strong>
          {session.default && <span className="default-session-badge">DEFAULT · PROTECTED</span>}
          <small>{session.running ? "Running" : "Stopped"}</small>
          {!session.default && (session.running
            ? <button type="button" className="btn btn-sm session-stop" disabled={!!busy} onClick={() => void changeSession("stop", session.name)}>{busy === `stop:${session.name}` ? "Stopping…" : "Stop"}</button>
            : <button type="button" className="btn btn-sm refresh-button" disabled={!!busy} onClick={() => void changeSession("start", session.name)}>{busy === `start:${session.name}` ? "Starting…" : "Start"}</button>)}
        </div>)}
      </div>
      <div className="table-note"><span className="info-mark">i</span> Stopping a named session ends its pane processes. The dashboard does not send terminal input or control arbitrary Herdr panes.</div>
    </section>
  );
}
