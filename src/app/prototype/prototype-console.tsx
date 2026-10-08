"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import styles from "./prototype.module.css";

export type PrototypeVariant = "A" | "B" | "C";
type Target = "codex" | "openclaw";
type Message = { role: "operator" | "codex"; text: string; stamp: string };

const VARIANTS: Array<{ key: PrototypeVariant; name: string }> = [
  { key: "A", name: "Operations desk" },
  { key: "B", name: "Conversation canvas" },
  { key: "C", name: "Run ledger" },
];
const HOSTS = ["build-a", "compute-b", "worker-c"];

export function isPrototypeVariant(value: unknown): value is PrototypeVariant {
  return value === "A" || value === "B" || value === "C";
}

function HealthDot({ active }: { active: boolean }) {
  return <i className={`${styles.healthDot} ${active ? styles.healthOn : styles.healthOff}`} />;
}

function HostSelect({ selected, onSelect }: { selected: string; onSelect: (host: string) => void }) {
  return (
    <label className={styles.hostSelect}>
      <span>SELECTED HOST</span>
      <select value={selected} onChange={(event) => onSelect(event.target.value)} aria-label="Selected host">
        {HOSTS.map((host) => <option key={host} value={host}>{host}</option>)}
      </select>
    </label>
  );
}

function HostRail({ selected, onSelect }: { selected: string; onSelect: (host: string) => void }) {
  return (
    <div className={styles.hostRail}>
      {HOSTS.map((host) => (
        <button key={host} className={`${styles.hostRailItem} ${selected === host ? styles.hostRailSelected : ""}`} onClick={() => onSelect(host)}>
          <HealthDot active />
          <span>{host}</span>
          <small>{host === selected ? "selected" : "online"}</small>
        </button>
      ))}
    </div>
  );
}

function NetworkSwitch({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) {
  return (
    <div className={styles.networkControl}>
      <div className={styles.networkText}>
        <div className={styles.eyebrow}>PROFILE PERMISSION</div>
        <h3>Network access</h3>
        <p>Controls sandboxed commands and live web search for later turns.</p>
        <div className={styles.networkScopes}>
          <span>COMMAND NETWORK</span><span>LIVE WEB SEARCH</span>
        </div>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={enabled}
        aria-label="Network access for the selected profile"
        className={`${styles.switch} ${enabled ? styles.switchEnabled : styles.switchDisabled}`}
        onClick={onToggle}
      ><span /></button>
      <strong className={enabled ? styles.enabledLabel : styles.disabledLabel}>{enabled ? "ON" : "OFF"}</strong>
    </div>
  );
}

function StateStrip({
  host,
  networkEnabled,
  target,
  turnStatus,
  herdrActive,
  lastAction,
}: {
  host: string;
  networkEnabled: boolean;
  target: Target;
  turnStatus: string;
  herdrActive: boolean;
  lastAction: string;
}) {
  return (
    <div className={styles.stateStrip} role="status" aria-live="polite">
      <div><span>HOST</span><strong>{host}</strong></div>
      <div><span>PROFILE</span><strong>Default · home writable</strong></div>
      <div><span>NETWORK</span><strong className={networkEnabled ? styles.enabledLabel : styles.disabledLabel}>{networkEnabled ? "On · commands + live search" : "Off · commands + search"}</strong></div>
      <div><span>DESTINATION</span><strong>{target === "codex" ? "Host Codex" : "OpenClaw · explicit"}</strong></div>
      <div><span>CODEX TURN</span><strong>{turnStatus}</strong></div>
      <div><span>HERDR SESSION</span><strong>{herdrActive ? "Running" : "Stopped"}</strong></div>
      <p>{lastAction}</p>
    </div>
  );
}

function ThreadMessages({ messages }: { messages: Message[] }) {
  return (
    <div className={styles.messageList}>
      {messages.map((message, index) => (
        <article className={`${styles.message} ${message.role === "operator" ? styles.operatorMessage : styles.codexMessage}`} key={`${message.stamp}-${index}`}>
          <div className={styles.messageMeta}><strong>{message.role === "operator" ? "YOU" : "CODEX"}</strong><time>{message.stamp}</time></div>
          <p>{message.text}</p>
        </article>
      ))}
    </div>
  );
}

function Composer({
  draft,
  target,
  onDraft,
  onTarget,
  onSubmit,
}: {
  draft: string;
  target: Target;
  onDraft: (value: string) => void;
  onTarget: (value: Target) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form className={styles.composer} onSubmit={onSubmit}>
      <textarea value={draft} onChange={(event) => onDraft(event.target.value)} placeholder="Message the selected host’s Codex…" aria-label="Message the selected agent" rows={3} />
      <div className={styles.composerFooter}>
        <label className={styles.targetPicker}><span>ROUTE TO</span>
          <select value={target} onChange={(event) => onTarget(event.target.value as Target)} aria-label="Message destination">
            <option value="codex">Selected host · Codex</option>
            <option value="openclaw">OpenClaw · explicit delegation</option>
          </select>
        </label>
        <button className={styles.primaryButton} type="submit">{target === "codex" ? "Send to Codex" : "Delegate to OpenClaw"}<span>↗</span></button>
      </div>
    </form>
  );
}

function PermissionSummary({ enabled, onToggle }: { enabled: boolean; onToggle: () => void }) {
  return (
    <section className={styles.permissionSummary}>
      <div className={styles.profileHeading}><div><div className={styles.eyebrow}>DASHBOARD-MANAGED PROFILE</div><h3>Default</h3></div><span className={styles.profileBadge}>ACTIVE</span></div>
      <NetworkSwitch enabled={enabled} onToggle={onToggle} />
      <div className={styles.policyLines}>
        <div><span>APPROVALS</span><strong>Auto-approve tools</strong></div>
        <div><span>WRITABLE ROOT</span><strong>$HOME</strong></div>
        <div><span>APPLIES</span><strong>Subsequent turns</strong></div>
      </div>
      <p className={styles.profileHint}>High-trust profile. Network access starts on for new dashboard-managed profiles.</p>
    </section>
  );
}

function HerdrControl({ active, onToggle }: { active: boolean; onToggle: () => void }) {
  return (
    <section className={styles.herdrControl}>
      <div className={styles.eyebrow}>HERDR NAMED SESSION</div>
      <div className={styles.herdrRow}><div><strong>workspace / review</strong><small>{active ? "3 panes · detached-safe" : "Session stopped"}</small></div><button onClick={onToggle}>{active ? "Stop session" : "Start session"}</button></div>
    </section>
  );
}

function ActionButton({ active, onClick }: { active: boolean; onClick: () => void }) {
  return <button className={styles.interruptButton} onClick={onClick} disabled={!active}>{active ? "■  Interrupt turn" : "✓  Turn ended"}</button>;
}

function Timeline({ messages }: { messages: Message[] }) {
  return (
    <div className={styles.timeline}>
      <div className={styles.timelineHeading}><div><div className={styles.eyebrow}>LIVE THREAD</div><h2>Review retry behavior</h2></div><span className={styles.runningPill}><i /> TURN RUNNING</span></div>
      {messages.map((message, index) => (
        <div className={styles.timelineItem} key={`${message.stamp}-${index}`}>
          <div className={styles.timelineMarker}>{message.role === "operator" ? "↗" : "✳"}</div>
          <div className={styles.timelineBody}><div><strong>{message.role === "operator" ? "Operator" : "Codex"}</strong><time>{message.stamp}</time></div><p>{message.text}</p></div>
        </div>
      ))}
      <div className={styles.toolActivity}><span className={styles.toolGlyph}>⌘</span><div><strong>Inspecting collector behavior</strong><small>Read-only action · changes require turn tools</small></div><span className={styles.toolStatus}>RUNNING</span></div>
    </div>
  );
}

function VariantA(props: SharedProps) {
  return (
    <div className={`${styles.console} ${styles.variantA}`}>
      <header className={styles.topbar}><div className={styles.brand}><span className={styles.brandGlyph}>✳</span><div><strong>CODEX CONTROL</strong><small>HOST CONSOLE</small></div></div><span className={styles.prototypeMark}>PROTOTYPE · LOCAL STATE ONLY</span><div className={styles.topbarRight}><span className={styles.secureMark}>● PRIVATE FLEET</span><span className={styles.operatorMark}>OF</span></div></header>
      <div className={styles.triPane}>
        <aside className={styles.leftPane}><div className={styles.paneLabel}>FLEET <span>03</span></div><HostRail selected={props.host} onSelect={props.onHost} /><div className={styles.leftDivider} /><div className={styles.paneLabel}>ACTIVE WORK</div><div className={styles.workChip}><i /><div><strong>Review retry behavior</strong><small>{props.host} · Codex turn</small></div></div><div className={styles.workChipMuted}><span>⌘</span><div><strong>Herdr workspace</strong><small>{props.herdrActive ? "1 active session" : "No active session"}</small></div></div><p className={styles.leftFoot}>Only Codex turns and named Herdr sessions have controls.</p></aside>
        <main className={styles.centerPane}><div className={styles.threadToolbar}><div><div className={styles.eyebrow}>CODEX THREAD · {props.host.toUpperCase()}</div><h1>Review retry behavior</h1><span className={styles.subtleLine}>thread_01 · started 4 minutes ago</span></div><ActionButton active={props.turnStatus === "Running"} onClick={props.onInterrupt} /></div><StateStrip {...props} /><ThreadMessages messages={props.messages} /><Composer {...props.composerProps} /></main>
        <aside className={styles.rightPane}><PermissionSummary enabled={props.networkEnabled} onToggle={props.onNetwork} /><HerdrControl active={props.herdrActive} onToggle={props.onHerdr} /><div className={styles.rightNote}><span>i</span><p>Switching network access updates the profile used for later turns. In-flight requests are not recalled.</p></div></aside>
      </div>
    </div>
  );
}

function VariantB(props: SharedProps) {
  return (
    <div className={`${styles.console} ${styles.variantB}`}>
      <header className={styles.canvasHeader}><div className={styles.brand}><span className={styles.brandGlyph}>✳</span><div><strong>HOST CONSOLE</strong><small>CODEX SESSION</small></div></div><span className={styles.prototypeMark}>PROTOTYPE · LOCAL STATE ONLY</span><div className={styles.canvasHeaderControls}><HostSelect selected={props.host} onSelect={props.onHost} /><button className={styles.headerProfile}>◈ Default profile</button><span className={styles.operatorMark}>OF</span></div></header>
      <main className={styles.canvasMain}>
        <div className={styles.canvasContext}><span className={styles.contextDot} /> CONNECTED OVER ZEROTIER <span className={styles.contextDivider}>/</span> {props.host} <span className={styles.contextDivider}>/</span> CODEX APP-SERVER</div>
        <section className={styles.canvasConversation}><div className={styles.canvasTitle}><div><div className={styles.eyebrow}>THREAD · ACTIVE TURN</div><h1>Review retry behavior</h1><p>Codex is tracing timeout and failover paths for this host.</p></div><ActionButton active={props.turnStatus === "Running"} onClick={props.onInterrupt} /></div><StateStrip {...props} /><ThreadMessages messages={props.messages} /></section>
        <section className={styles.canvasActionDock}><div className={styles.permissionInline}><div><span className={styles.eyebrow}>DEFAULT PROFILE · HIGH TRUST</span><strong>Network access {props.networkEnabled ? "on" : "off"}</strong><small>$HOME writable · tools auto-approved</small></div><NetworkSwitch enabled={props.networkEnabled} onToggle={props.onNetwork} /></div><Composer {...props.composerProps} /><div className={styles.dockFoot}><HerdrControl active={props.herdrActive} onToggle={props.onHerdr} /><span>Codex thread is host-scoped. OpenClaw requires explicit selection.</span></div></section>
      </main>
    </div>
  );
}

function VariantC(props: SharedProps) {
  return (
    <div className={`${styles.console} ${styles.variantC}`}>
      <header className={styles.ledgerHeader}><div className={styles.brand}><span className={styles.brandGlyph}>✳</span><div><strong>OPERATIONS LEDGER</strong><small>CODEX + HERDR</small></div></div><span className={styles.prototypeMark}>PROTOTYPE · LOCAL STATE ONLY</span><div className={styles.ledgerHeaderRight}><HostSelect selected={props.host} onSelect={props.onHost} /><span className={styles.operatorMark}>OF</span></div></header>
      <main className={styles.ledgerMain}>
        <div className={styles.ledgerTitle}><div><div className={styles.eyebrow}>HOST ACTIVITY</div><h1>{props.host}<span> / RUN LEDGER</span></h1></div><div className={styles.ledgerStatus}><HealthDot active /><span>APP-SERVER CONNECTED</span><span className={styles.ledgerStatusDivider}>·</span><span>SSH ROUTE VERIFIED</span></div></div>
        <StateStrip {...props} />
        <div className={styles.ledgerGrid}>
          <section className={styles.runTable}><div className={styles.runTableHead}><div><div className={styles.eyebrow}>CURRENT ACTIVITY</div><h2>Runs &amp; sessions</h2></div><span className={styles.tableCount}>02 ACTIVE</span></div><div className={styles.tableColumns}><span>TYPE / NAME</span><span>STATE</span><span>CONTROL</span></div><div className={styles.runRow}><div className={styles.runName}><span className={styles.runIcon}>✳</span><div><strong>Review retry behavior</strong><small>Codex turn · thread_01 · 4m</small></div></div><span className={styles.runState}><i />{props.turnStatus}</span><ActionButton active={props.turnStatus === "Running"} onClick={props.onInterrupt} /></div><div className={styles.runRow}><div className={styles.runName}><span className={styles.runIconMuted}>⌘</span><div><strong>workspace / review</strong><small>Herdr named session · 3 panes</small></div></div><span className={styles.runState}><i className={props.herdrActive ? "" : styles.stateStopped} />{props.herdrActive ? "Running" : "Stopped"}</span><button className={styles.secondaryButton} onClick={props.onHerdr}>{props.herdrActive ? "Stop" : "Start"}</button></div><div className={styles.ledgerBoundary}><span>BOUNDARY</span><p>Codex and Herdr controls only · no shell or host-service actions.</p></div><Timeline messages={props.messages} /></section>
          <aside className={styles.policyColumn}><div className={styles.policyColumnTitle}><span>PROFILE</span><b>DEFAULT</b></div><PermissionSummary enabled={props.networkEnabled} onToggle={props.onNetwork} /><div className={styles.policyAction}><div className={styles.eyebrow}>NEW ACTION</div><p>Start from the selected host’s Codex, or choose explicit OpenClaw delegation.</p><Composer {...props.composerProps} /></div></aside>
        </div>
      </main>
    </div>
  );
}

type ComposerProps = {
  draft: string;
  target: Target;
  onDraft: (value: string) => void;
  onTarget: (value: Target) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

type SharedProps = {
  host: string;
  networkEnabled: boolean;
  target: Target;
  turnStatus: string;
  herdrActive: boolean;
  lastAction: string;
  messages: Message[];
  onHost: (host: string) => void;
  onNetwork: () => void;
  onInterrupt: () => void;
  onHerdr: () => void;
  composerProps: ComposerProps;
};

function PrototypeSwitcher({ variant, onChange }: { variant: PrototypeVariant; onChange: (variant: PrototypeVariant) => void }) {
  const index = VARIANTS.findIndex((item) => item.key === variant);
  const cycle = useCallback((delta: number) => onChange(VARIANTS[(index + delta + VARIANTS.length) % VARIANTS.length].key), [index, onChange]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target;
      if (target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable='true']")) return;
      if (event.key === "ArrowLeft") { event.preventDefault(); cycle(-1); }
      if (event.key === "ArrowRight") { event.preventDefault(); cycle(1); }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [cycle]);

  if (process.env.NODE_ENV === "production") return null;
  const current = VARIANTS[index];
  return (
    <nav className={styles.prototypeSwitcher} aria-label="Prototype variants">
      <button onClick={() => cycle(-1)} aria-label="Previous variant">←</button>
      <span><strong>{current.key}</strong><i />{current.name}</span>
      <button onClick={() => cycle(1)} aria-label="Next variant">→</button>
    </nav>
  );
}

export default function PrototypeConsole({ initialVariant }: { initialVariant: PrototypeVariant }) {
  const [variant, setVariant] = useState(initialVariant);
  const [host, setHost] = useState(HOSTS[0]);
  const [networkEnabled, setNetworkEnabled] = useState(true);
  const [target, setTarget] = useState<Target>("codex");
  const [turnStatus, setTurnStatus] = useState("Running");
  const [herdrActive, setHerdrActive] = useState(true);
  const [draft, setDraft] = useState("");
  const [lastAction, setLastAction] = useState("Connected · ready for a host-scoped action.");
  const [messages, setMessages] = useState<Message[]>([
    { role: "operator", text: "Trace the timeout and failover path. Keep the change scoped to the collector.", stamp: "10:42:08" },
    { role: "codex", text: "I’m checking the collector route order and the probe timeout boundary before suggesting a change.", stamp: "10:42:12" },
  ]);

  const changeVariant = useCallback((next: PrototypeVariant) => {
    setVariant(next);
    setLastAction(`Prototype variant changed to ${next}.`);
    const params = new URLSearchParams(window.location.search);
    params.set("variant", next);
    window.history.replaceState(null, "", `${window.location.pathname}?${params.toString()}`);
  }, []);

  function selectHost(next: string) {
    setHost(next);
    setLastAction(`Selected host changed to ${next}.`);
  }

  function toggleNetwork() {
    const next = !networkEnabled;
    setNetworkEnabled(next);
    setLastAction(`Network access ${next ? "enabled" : "disabled"} for subsequent turns on the Default profile.`);
  }

  function interruptTurn() {
    setTurnStatus("Interrupted");
    setLastAction(`Codex turn interrupted on ${host}.`);
  }

  function toggleHerdr() {
    const next = !herdrActive;
    setHerdrActive(next);
    setLastAction(`Herdr named session ${next ? "started" : "stopped"}.`);
  }

  function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setMessages((current) => [...current, { role: "operator", text, stamp: "now" }]);
    if (target === "codex") setTurnStatus("Running");
    setLastAction(target === "codex" ? `Message sent to Codex on ${host}.` : "Task delegated to OpenClaw explicitly.");
    setDraft("");
  }

  const shared: SharedProps = {
    host,
    networkEnabled,
    target,
    turnStatus,
    herdrActive,
    lastAction,
    messages,
    onHost: selectHost,
    onNetwork: toggleNetwork,
    onInterrupt: interruptTurn,
    onHerdr: toggleHerdr,
    composerProps: { draft, target, onDraft: setDraft, onTarget: setTarget, onSubmit: submitMessage },
  };

  return (
    <div className={styles.prototypeRoot}>
      {variant === "A" ? <VariantA {...shared} /> : null}
      {variant === "B" ? <VariantB {...shared} /> : null}
      {variant === "C" ? <VariantC {...shared} /> : null}
      <PrototypeSwitcher variant={variant} onChange={changeVariant} />
    </div>
  );
}
