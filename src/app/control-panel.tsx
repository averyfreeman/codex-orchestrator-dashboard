"use client";

import { useEffect, useRef, useState } from "react";
import type { HostReport } from "@/lib/hosts";
import styles from "./control-panel.module.css";

type ControlHost = Pick<HostReport, "host" | "reachable" | "connection">;
type Message = { role: "you" | "codex"; text: string };
type Usage = { inputTokens: number | null; outputTokens: number | null; totalTokens: number | null };

function parseEventStream(text: string) {
  return text.split("\n\n").flatMap((block) => {
    const data = block.split("\n").find((line) => line.startsWith("data: "))?.slice(6);
    if (!data) return [];
    try {
      const value: unknown = JSON.parse(data);
      return value && typeof value === "object" ? [value as Record<string, unknown>] : [];
    } catch {
      return [];
    }
  });
}

/** Provide selected-host Codex thread controls and projected turn events. */
export function ControlPanel({ hosts }: { hosts: ControlHost[] }) {
  const [selectedHost, setSelectedHost] = useState("");
  const [networkAccess, setNetworkAccess] = useState(true);
  const [profileLoading, setProfileLoading] = useState(true);
  const [savingProfile, setSavingProfile] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [threadId, setThreadId] = useState("");
  const [turnId, setTurnId] = useState("");
  const [transport, setTransport] = useState("");
  const [activity, setActivity] = useState("");
  const [usage, setUsage] = useState<Usage | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const streamAbort = useRef<AbortController | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const profileRequest = window.setTimeout(() => {
      void fetch("/api/control/profile", { cache: "no-store" })
        .then(async (response) => {
          if (!response.ok) throw new Error("Could not load the dashboard profile.");
          const profile = await response.json();
          setNetworkAccess(profile.networkAccess === true);
        })
        .catch((error: unknown) => setNotice(error instanceof Error ? error.message : "Could not load the dashboard profile."))
        .finally(() => setProfileLoading(false));
    }, 0);
    return () => window.clearTimeout(profileRequest);
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [messages, activity]);

  useEffect(() => () => streamAbort.current?.abort(), []);

  async function toggleNetwork() {
    if (savingProfile || profileLoading) return;
    setSavingProfile(true);
    setNotice("");
    try {
      const response = await fetch("/api/control/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ networkAccess: !networkAccess }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not update the dashboard profile.");
      setNetworkAccess(result.networkAccess === true);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not update the dashboard profile.");
    } finally {
      setSavingProfile(false);
    }
  }

  async function sendPrompt(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prompt = draft.trim();
    if (!prompt || busy || !activeHostSlug) return;
    setDraft("");
    setNotice("");
    setActivity("");
    setUsage(null);
    setMessages((current) => [...current, { role: "you", text: prompt }, { role: "codex", text: "" }]);
    setBusy(true);
    const abort = new AbortController();
    streamAbort.current = abort;
    try {
      const response = await fetch("/api/control/codex/turn", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host: activeHostSlug, prompt, ...(threadId ? { threadId } : {}) }),
        signal: abort.signal,
      });
      if (!response.ok) {
        const result = await response.json().catch(() => ({}));
        throw new Error(result.error ?? "The Codex turn could not be started.");
      }
      if (!response.body) throw new Error("The Codex event stream was unavailable.");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffered = "";
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        buffered += decoder.decode(part.value, { stream: true });
        const blocks = buffered.split("\n\n");
        buffered = blocks.pop() ?? "";
        for (const item of parseEventStream(blocks.join("\n\n"))) handleEvent(item);
      }
      buffered += decoder.decode();
      for (const item of parseEventStream(buffered)) handleEvent(item);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      setNotice(error instanceof Error ? error.message : "Codex connection failed.");
      setBusy(false);
    } finally {
      streamAbort.current = null;
    }
  }

  function handleEvent(event: Record<string, unknown>) {
    if (event.type === "started") {
      if (typeof event.threadId === "string") setThreadId(event.threadId);
      if (typeof event.turnId === "string") setTurnId(event.turnId);
      if (typeof event.transport === "string") setTransport(event.transport);
      setActivity("Codex is working");
    } else if (event.type === "delta" && typeof event.delta === "string") {
      setMessages((current) => {
        const next = [...current];
        const last = next.at(-1);
        if (last?.role === "codex") next[next.length - 1] = { ...last, text: last.text + event.delta };
        return next;
      });
    } else if (event.type === "message" && typeof event.text === "string") {
      setMessages((current) => {
        const next = [...current];
        const last = next.at(-1);
        if (last?.role === "codex" && !last.text) next[next.length - 1] = { ...last, text: event.text as string };
        return next;
      });
    } else if (event.type === "activity" && typeof event.kind === "string") {
      setActivity(event.status === "completed" ? "Codex is thinking" : `${event.kind} in progress`);
    } else if (event.type === "usage") {
      setUsage({
        inputTokens: typeof event.inputTokens === "number" ? event.inputTokens : null,
        outputTokens: typeof event.outputTokens === "number" ? event.outputTokens : null,
        totalTokens: typeof event.totalTokens === "number" ? event.totalTokens : null,
      });
    } else if (event.type === "completed") {
      setBusy(false);
      setActivity(typeof event.status === "string" ? `Turn ${event.status}` : "Turn complete");
      if (event.failed) setNotice("Codex reported that this turn failed. The turn status is authoritative; the error detail is kept out of dashboard telemetry.");
    } else if (event.type === "streamEnded") {
      setBusy(false);
    } else if (event.type === "error") {
      setBusy(false);
      setNotice(typeof event.message === "string" ? event.message : "Codex connection failed.");
    }
  }

  async function interruptTurn() {
    if (!activeHostSlug || !threadId || !turnId) return;
    setNotice("");
    try {
      const response = await fetch("/api/control/codex/interrupt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host: activeHostSlug, threadId, turnId }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Interrupt request failed.");
      setNotice(result.message ?? "Interrupt request acknowledged.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Interrupt request failed.");
    }
  }

  function changeHost(slug: string) {
    if (slug === activeHostSlug) return;
    setSelectedHost(slug);
    setThreadId("");
    setTurnId("");
    setTransport("");
    setMessages([]);
    setActivity("");
    setUsage(null);
    setNotice("");
  }

  function startNewThread() {
    if (busy) return;
    setThreadId("");
    setTurnId("");
    setTransport("");
    setMessages([]);
    setActivity("");
    setUsage(null);
    setNotice("");
  }

  const defaultHost = hosts.find((host) => host.reachable) ?? hosts[0];
  const activeHostSlug = selectedHost || defaultHost?.host.slug || "";
  const selected = hosts.find((host) => host.host.slug === activeHostSlug);

  return (
    <section className={styles.panel} aria-label="Codex host control">
      <div className={styles.heading}>
        <div><div className={styles.eyebrow}>INTERACTIVE CONTROL</div><h2>Talk to a host’s Codex</h2><p>Each thread runs on the selected host’s app-server.</p></div>
        <button type="button" className={styles.newThread} disabled={busy} onClick={startNewThread}>New thread</button>
      </div>
      <div className={styles.controls}>
        <label className={styles.hostPicker}>HOST<select value={activeHostSlug} onChange={(event) => changeHost(event.target.value)} disabled={!hosts.length || busy}>
          {hosts.map((host) => <option key={host.host.slug} value={host.host.slug}>{host.host.name}{host.reachable ? " · online" : " · unavailable"}</option>)}
        </select></label>
        <div className={styles.profile}>
          <div><small>MANAGED PROFILE</small><strong>Dashboard default</strong><span>Eligible Codex tools auto-approved · writes bounded to $HOME</span></div>
          <button type="button" role="switch" aria-checked={networkAccess} aria-label="Network access" className={`${styles.switch} ${networkAccess ? styles.switchOn : ""}`} disabled={profileLoading || savingProfile} onClick={() => void toggleNetwork()}><i /></button>
          <div className={styles.networkStatus}><b>{profileLoading ? "Loading" : networkAccess ? "Network on" : "Network off"}</b><span>{networkAccess ? "Command networking + live web search" : "Command networking + live web search disabled"}</span></div>
        </div>
      </div>
      <div className={styles.conversation} ref={logRef} role="log" aria-live="polite" aria-label="Codex conversation">
        {messages.length === 0 ? <div className={styles.empty}><span>✳</span><strong>Start a Codex thread</strong><p>Prompts and replies stay in the selected host’s Codex thread. Dashboard telemetry stores only host, thread/turn IDs, state, policy, and token counts.</p></div> : messages.map((message, index) => <article className={message.role === "you" ? styles.userMessage : styles.codexMessage} key={`${index}:${message.role}`}><small>{message.role === "you" ? "YOU" : "CODEX"}</small><div>{message.text || (busy && message.role === "codex" ? <span className={styles.thinking}>Working…</span> : "")}</div></article>)}
      </div>
      <div className={styles.statusBar}>
        <span>{selected?.reachable ? "Connected" : selected ? "Host unavailable" : "No host selected"}{transport ? ` via ${transport}` : ""}</span>
        {activity && <span>{activity}</span>}
        {usage?.totalTokens !== null && usage?.totalTokens !== undefined && <span>{usage.totalTokens.toLocaleString()} tokens · {usage.inputTokens?.toLocaleString() ?? "—"} in / {usage.outputTokens?.toLocaleString() ?? "—"} out</span>}
        {threadId && <code>Thread {threadId.slice(0, 12)}</code>}
      </div>
      {notice && <div className={styles.notice} role="status">{notice}<button type="button" onClick={() => setNotice("")} aria-label="Dismiss message">×</button></div>}
      <form className={styles.composer} onSubmit={sendPrompt}>
        <textarea value={draft} onChange={(event) => setDraft(event.target.value)} placeholder={selected?.reachable ? `Message Codex on ${selected.host.name}…` : "Select an available host to start"} aria-label="Message Codex" disabled={!selected?.reachable || busy || profileLoading} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
        <div><span>Enter to send · Shift+Enter for a new line · No terminal output is shown</span><div>{busy && threadId && turnId && <button type="button" className={styles.interrupt} onClick={() => void interruptTurn()}>Interrupt turn</button>}<button type="submit" className={styles.send} disabled={!draft.trim() || busy || profileLoading || !selected?.reachable}>{busy ? "Working…" : "Send ↗"}</button></div></div>
      </form>
    </section>
  );
}
