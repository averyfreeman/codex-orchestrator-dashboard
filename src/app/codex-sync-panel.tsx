"use client";

import { useEffect, useMemo, useState } from "react";
import type { HostReport } from "@/lib/hosts";
import type { CodexSyncPlanResponse, SyncCategory, SyncCategoryStatus, SyncDiff, SyncHostPlan } from "@/lib/codex-sync";

type RunSnapshot = {
  runId: string;
  sourceHostSlug: string;
  sourceCliVersion: string;
  createdAt: string;
  updatedAt: string;
  status: "queued" | "applying" | "completed" | "partial" | "failed";
  restartWhenFinished: boolean;
  hosts: Array<{
    hostSlug: string;
    hostName: string;
    status: "queued" | "applying" | "completed" | "partial" | "failed";
    categories: Partial<Record<SyncCategory, { status: SyncCategoryStatus; count?: number; message?: string }>>;
    versions: { cli: string | null; runtime: string | null };
    restart: { status: string; reason?: string };
  }>;
};

type Props = { hosts: HostReport[] };
function routeReachable(report: HostReport) {
  return report.connection.transport !== "unavailable";
}
const CATEGORY_LABELS: Record<SyncCategory, string> = {
  cli: "CLI version",
  runtime: "Running runtime",
  plugins: "Plugins",
  config: "Config",
  profiles: "Profiles",
  skills: "User skills",
  codexHome: "CODEX_HOME",
};

function statusLabel(status: SyncCategoryStatus) {
  const labels: Record<SyncCategoryStatus, string> = {
    "in-sync": "In sync", drift: "Drift", blocked: "Review", unavailable: "Unavailable", pending: "Queued", applying: "Applying",
    applied: "Applied", failed: "Failed", deferred: "Deferred", "not-requested": "Not requested",
  };
  return labels[status] ?? status;
}

function badgeClass(status: SyncCategoryStatus) {
  if (["in-sync", "applied"].includes(status)) return "badge-success";
  if (["drift", "applying", "pending", "deferred"].includes(status)) return "badge-warning";
  if (["failed", "unavailable"].includes(status)) return "badge-error";
  return "badge-ghost";
}

function CategoryBadge({ status }: { status: SyncCategoryStatus }) {
  return <span className={`badge badge-sm ${badgeClass(status)}`}>{statusLabel(status)}</span>;
}

function safeValue(value: SyncDiff["sourceValue"]) {
  if (value === null || value === undefined) return "(not set)";
  return typeof value === "boolean" ? String(value) : String(value);
}

function HostPlanDetails({ row }: { row: SyncHostPlan }) {
  const hasDetails = row.diffs.length > 0 || row.blockedItems.length > 0;
  return (
    <details className="collapse collapse-arrow codex-sync-details">
      <summary className="collapse-title">
        <span>{row.hostName}</span>
        <span className="codex-sync-detail-summary">
          {row.counts.changes ? `${row.counts.changes} changes` : "No classified changes"}
          {row.counts.blocked ? ` · ${row.counts.blocked} held for review` : ""}
        </span>
      </summary>
      <div className="collapse-content">
        {!hasDetails ? <p className="sync-muted">All classified settings match the reference host.</p> : null}
        {row.diffs.length > 0 && (
          <div className="sync-diff-list" aria-label={`${row.hostName} safe differences`}>
            {row.diffs.map((diff, index) => <DiffLine key={`${diff.category}:${diff.item}:${index}`} diff={diff} />)}
          </div>
        )}
        {row.blockedItems.length > 0 && (
          <div className="alert alert-warning codex-sync-blocked" role="note">
            <span aria-hidden="true">!</span>
            <div><strong>Kept on this host</strong><ul>{row.blockedItems.map((item) => <li key={item}>{item}</li>)}</ul></div>
          </div>
        )}
      </div>
    </details>
  );
}

function DiffLine({ diff }: { diff: SyncDiff }) {
  const targetOnlyRemoval = diff.kind === "remove" && diff.sourceValue === undefined && diff.targetValue === undefined;
  const removalMessage = diff.category === "skills"
    ? "This target-only user skill file will be backed up before removal."
    : diff.category === "plugins"
      ? "This target-only plugin will be removed from the host."
      : "This target-only item will be removed from the host.";
  return (
    <article className="sync-diff-row">
      <div className="sync-diff-label"><span>{CATEGORY_LABELS[diff.category]}</span><strong>{diff.item}</strong></div>
      {diff.kind === "info" || diff.kind === "blocked" || targetOnlyRemoval ? (
        <p>{diff.message ?? (targetOnlyRemoval ? removalMessage : "This item needs review before it can be synchronized.")}</p>
      ) : (
        <div className="sync-diff-values">
          <span><small>Reference</small><code>{safeValue(diff.sourceValue)}</code></span>
          <span aria-hidden="true" className="sync-diff-arrow">→</span>
          <span><small>Target</small><code>{safeValue(diff.targetValue)}</code></span>
        </div>
      )}
      <span className={`badge badge-xs ${diff.kind === "remove" ? "badge-warning" : "badge-ghost"}`}>{diff.kind}</span>
    </article>
  );
}

function PlanTable({ rows }: { rows: SyncHostPlan[] }) {
  const categories: SyncCategory[] = ["cli", "runtime", "plugins", "config", "profiles", "skills", "codexHome"];
  return (
    <div className="overflow-x-auto codex-sync-table-wrap">
      <table className="table table-sm table-zebra codex-sync-table">
        <thead><tr><th>HOST</th>{categories.map((key) => <th key={key}>{CATEGORY_LABELS[key]}</th>)}</tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.hostSlug}>
              <th>
                <span className="sync-host-cell">{row.hostName}{row.reference && <span className="badge badge-xs badge-secondary">Reference</span>}{row.included && <span className="badge badge-xs badge-primary">Target</span>}</span>
                <small>{row.reachable ? (row.counts.changes ? `${row.counts.changes} planned changes` : "Ready to compare") : "Not reachable"}</small>
              </th>
              {categories.map((key) => <td key={key}><CategoryBadge status={row.categories[key].status} /></td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InventoryTable({ hosts }: Props) {
  return (
    <div className="overflow-x-auto codex-sync-table-wrap codex-sync-inventory">
      <table className="table table-sm codex-sync-table">
        <caption>Latest health snapshot. Detailed configuration is inspected only when a sync plan is created.</caption>
        <thead><tr><th>HOST</th><th>CLI</th><th>APP-SERVER</th><th>PLUGINS</th><th>CONFIG</th><th>PROFILES</th><th>SKILLS</th><th>CODEX_HOME</th></tr></thead>
        <tbody>{hosts.map((report) => (
          <tr key={report.host.slug}>
            <th><span className="sync-host-cell">{report.host.name}</span><small>{report.host.os}</small></th>
            <td>{report.appServer.cliVersion ? <code>{report.appServer.cliVersion}</code> : <CategoryBadge status="unavailable" />}</td>
            <td><span className="sync-runtime-cell"><CategoryBadge status={report.appServer.status === "running" ? "in-sync" : "unavailable"} /><small>{report.appServer.version ?? report.appServer.status}</small></span></td>
            <td><span className="badge badge-sm badge-outline">On demand</span></td>
            <td><span className="badge badge-sm badge-outline">On demand</span></td>
            <td><span className="badge badge-sm badge-outline">On demand</span></td>
            <td><span className="badge badge-sm badge-outline">On demand</span></td>
            <td><span className="badge badge-sm badge-ghost">Resolved per host</span></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function RunStatus({ run }: { run: RunSnapshot }) {
  const finished = ["completed", "partial", "failed"].includes(run.status);
  return (
    <section className="view-panel codex-sync-run" aria-live="polite" aria-label="Codex sync run status">
      <div className="panel-heading"><div><h2>{finished ? "Sync run result" : "Applying reviewed changes"}</h2><p>Run <code>{run.runId}</code> · Reference CLI {run.sourceCliVersion}</p></div><span className={`badge ${run.status === "completed" ? "badge-success" : run.status === "failed" ? "badge-error" : "badge-warning"}`}>{run.status}</span></div>
      <div className="codex-sync-run-hosts">
        {run.hosts.map((host) => (
          <details className="collapse collapse-arrow codex-sync-details" key={host.hostSlug} open={host.status === "applying" || host.status === "partial" || host.status === "failed"}>
            <summary className="collapse-title"><span>{host.hostName}</span><span className="codex-sync-detail-summary">CLI {host.versions.cli ?? "—"} · Runtime {host.versions.runtime ?? "—"} · {host.status}</span></summary>
            <div className="collapse-content">
              <div className="sync-run-categories">
                {(Object.keys(CATEGORY_LABELS) as SyncCategory[]).map((key) => {
                  const result = host.categories[key];
                  if (!result) return null;
                  return <div key={key}><span>{CATEGORY_LABELS[key]}</span><CategoryBadge status={result.status} /><small>{result.count ? `${result.count} item${result.count === 1 ? "" : "s"}` : result.message ?? ""}</small></div>;
                })}
              </div>
              {host.restart.status === "deferred" && <div className="alert alert-warning codex-sync-blocked"><span aria-hidden="true">!</span><div><strong>Restart deferred</strong><p>{host.restart.reason ?? "An active turn may be running or the managed daemon could not be verified idle."} {host.categories.runtime?.message ?? "The running server may not reflect newly applied state yet."}</p></div></div>}
              {host.restart.status === "restarted" && <p className="sync-success-note">The affected managed Codex daemon restarted.</p>}
            </div>
          </details>
        ))}
      </div>
    </section>
  );
}

/** On-demand Codex fleet sync: compare, review, apply, and follow one run. */
export function CodexSyncPanel({ hosts }: Props) {
  const [sourceSlug, setSourceSlug] = useState("");
  const [targetSlugs, setTargetSlugs] = useState<string[]>([]);
  const [plan, setPlan] = useState<CodexSyncPlanResponse | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [restartWhenFinished, setRestartWhenFinished] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState("");

  const sourceOptions = useMemo(() => hosts.filter((report) => Boolean(report.appServer.cliVersion)), [hosts]);
  const peerOptions = useMemo(() => hosts.filter((report) => report.host.slug !== sourceSlug && routeReachable(report)), [hosts, sourceSlug]);

  function chooseSource(slug: string) {
    setSourceSlug(slug);
    setTargetSlugs(hosts.filter((report) => report.host.slug !== slug && routeReachable(report)).map((report) => report.host.slug));
    setPlan(null);
    setError("");
  }

  function toggleTarget(slug: string) {
    setTargetSlugs((current) => current.includes(slug) ? current.filter((item) => item !== slug) : [...current, slug]);
    setPlan(null);
  }

  function clearPlanSelection() {
    setPlan(null);
    setSourceSlug("");
    setTargetSlugs([]);
    setRestartWhenFinished(false);
  }

  function startAnotherRun() {
    setRun(null);
    clearPlanSelection();
    setError("");
  }

  async function createPlan() {
    if (!sourceSlug || targetSlugs.length === 0 || planning) return;
    setPlanning(true);
    setError("");
    setPlan(null);
    try {
      const response = await fetch("/api/control/codex-sync/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sourceHostSlug: sourceSlug, targetHostSlugs: targetSlugs }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not create a sync plan.");
      setPlan(result as CodexSyncPlanResponse);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not create a sync plan.");
    } finally {
      setPlanning(false);
    }
  }

  async function applyPlan() {
    if (!plan || applying) return;
    setApplying(true);
    setError("");
    try {
      const response = await fetch("/api/control/codex-sync/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ planId: plan.planId, restartWhenFinished }),
      });
      const result = await response.json();
      if (!response.ok) {
        if (response.status === 409) clearPlanSelection();
        throw new Error(result.error ?? "Could not start the sync run.");
      }
      setPlan(null);
      setSourceSlug("");
      setTargetSlugs([]);
      setRun({ runId: result.runId, sourceHostSlug: plan.source.slug, sourceCliVersion: plan.source.cliVersion, createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), status: "queued", restartWhenFinished, hosts: plan.hosts.filter((host) => host.included).map((host) => ({ hostSlug: host.hostSlug, hostName: host.hostName, status: host.reachable ? "queued" : "failed", categories: {}, versions: { cli: host.categories.cli.target ?? null, runtime: host.categories.runtime.target ?? null }, restart: { status: restartWhenFinished ? "not-needed" : "not-requested" } })) });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not start the sync run.");
    } finally {
      setApplying(false);
    }
  }

  useEffect(() => {
    const runId = run?.runId;
    const runStatus = run?.status;
    if (!runId || ["completed", "partial", "failed"].includes(runStatus ?? "")) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const response = await fetch(`/api/control/codex-sync/runs/${runId}`, { cache: "no-store" });
        const result = await response.json();
        if (response.ok && !cancelled) {
          setRun(result as RunSnapshot);
          if (!["completed", "partial", "failed"].includes(result.status)) timer = window.setTimeout(poll, 1_500);
        } else if (!cancelled) {
          setError(result.error ?? "Could not read sync run status.");
        }
      } catch {
        if (!cancelled) timer = window.setTimeout(poll, 2_500);
      }
    };
    timer = window.setTimeout(poll, 400);
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); };
  }, [run?.runId, run?.status]);

  return (
    <section className="view-panel codex-sync-panel" aria-label="Codex fleet sync">
      <div className="panel-heading codex-sync-intro">
        <div><h2>Reference, review, apply</h2><p>Compare host state on demand, review safe differences, then apply to selected peers. Health polling never writes host state.</p></div>
        <span className="badge badge-outline">ON-DEMAND</span>
      </div>

      {hosts.length === 0 && <div className="empty-state"><div className="empty-graphic">⌘</div><strong>No Codex hosts are configured</strong><p>Add hosts to the private fleet inventory before creating a sync plan.</p></div>}

      {hosts.length > 0 && (
        <>
          <div className="stats stats-vertical sm:stats-horizontal codex-sync-overview-stats">
            <div className="stat"><div className="stat-title">Hosts in fleet</div><div className="stat-value">{hosts.length}</div><div className="stat-desc">Listed in the private inventory</div></div>
            <div className="stat"><div className="stat-title">CLI versions known</div><div className="stat-value">{sourceOptions.length}</div><div className="stat-desc">Available as reference hosts</div></div>
            <div className="stat"><div className="stat-title">App-servers running</div><div className="stat-value">{hosts.filter((host) => host.appServer.status === "running").length}</div><div className="stat-desc">Health snapshot · no writes</div></div>
          </div>
          <InventoryTable hosts={hosts} />
        </>
      )}

      {hosts.length > 0 && !run && (
        <div className="codex-sync-setup">
          <div className="codex-sync-controls">
            <div className="sync-field">
              <label htmlFor="codex-sync-source">Reference host</label>
              <select id="codex-sync-source" className="select select-bordered select-sm" value={sourceSlug} onChange={(event) => chooseSource(event.target.value)}>
                <option value="">Choose a source for this run…</option>
                {sourceOptions.map((host) => <option key={host.host.slug} value={host.host.slug}>{host.host.name} · CLI {host.appServer.cliVersion}</option>)}
              </select>
              <small>Reads current settings from this host when you create the plan.</small>
              {sourceOptions.length === 0 && <small role="status">No host currently reports an installed Codex CLI.</small>}
            </div>
            <fieldset className="codex-sync-targets" disabled={!sourceSlug || planning}>
              <legend>Targets <span>{targetSlugs.length} selected</span></legend>
              {hosts.filter((report) => report.host.slug !== sourceSlug).map((report) => {
                const canReach = routeReachable(report);
                const checked = targetSlugs.includes(report.host.slug);
                return <label className={`sync-target-option ${!canReach ? "target-unreachable" : ""}`} key={report.host.slug}>
                  <input className="checkbox checkbox-primary checkbox-sm" type="checkbox" checked={checked} disabled={!canReach} onChange={() => toggleTarget(report.host.slug)} />
                  <span>{report.host.name}<small>{canReach ? `CLI ${report.appServer.cliVersion ?? "unknown"} · app-server ${report.appServer.status}` : "Host route unavailable · excluded from default targets"}</small></span>
                  {!canReach && <span className="badge badge-xs badge-ghost">Offline</span>}
                </label>;
              })}
              {peerOptions.length === 0 && <p className="sync-muted">No other reachable Codex hosts are available.</p>}
            </fieldset>
          </div>
          <div className="codex-sync-actions">
            <div className="sync-privacy-note"><strong>Protected on every target</strong><span>Credentials, MCP secret values, unclassified settings, repo skills, and Codex system skills stay local.</span></div>
            <button type="button" className="btn btn-primary btn-sm" onClick={() => void createPlan()} disabled={!sourceSlug || targetSlugs.length === 0 || planning}>
              {planning ? <><span className="loading loading-spinner loading-xs" /> Checking hosts…</> : "Compare & review"}
            </button>
          </div>
        </div>
      )}

      {planning && <div className="loading-panel" role="status"><span className="loader" /> Inspecting the selected hosts…</div>}
      {error && <div className="alert alert-error codex-sync-error" role="alert"><span>{error}</span><button type="button" className="btn btn-ghost btn-xs" onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}

      {plan && (
        <section className="codex-sync-review" aria-label="Review Codex sync plan">
          <div className="codex-sync-review-heading"><div><div className="eyebrow"><span className="eyebrow-line" /> REVIEW BEFORE APPLY</div><h3>{plan.source.name} <span>→</span> selected hosts</h3><p>Plan expires {new Date(plan.expiresAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}. Only the listed safe values and validated files can be written.</p></div><button type="button" className="btn btn-ghost btn-sm" onClick={() => setPlan(null)}>Back to setup</button></div>
          <div className="stats stats-vertical sm:stats-horizontal codex-sync-stats">
            <div className="stat"><div className="stat-title">Targets selected</div><div className="stat-value">{plan.summary.hosts}</div><div className="stat-desc">{plan.summary.reachable} reachable for sync</div></div>
            <div className="stat"><div className="stat-title">Classified changes</div><div className="stat-value">{plan.summary.changes}</div><div className="stat-desc">CLI, config, plugin, and skill actions</div></div>
            <div className="stat"><div className="stat-title">Held for review</div><div className="stat-value">{plan.summary.blocked}</div><div className="stat-desc">Unclassified or unreachable state</div></div>
          </div>
          <PlanTable rows={plan.hosts} />
          <div className="codex-sync-host-details">{plan.hosts.filter((host) => host.included).map((host) => <HostPlanDetails key={host.hostSlug} row={host} />)}</div>
          <div className="codex-sync-apply-row">
            <label className="sync-restart-choice"><input className="checkbox checkbox-primary checkbox-sm" type="checkbox" checked={restartWhenFinished} onChange={(event) => setRestartWhenFinished(event.target.checked)} /><span><strong>Auto-restart when finished</strong><small>Off by default. Only affected dashboard-managed Codex daemons are eligible. Active turns defer the restart.</small></span></label>
            <div className="sync-apply-buttons"><button type="button" className="btn btn-ghost btn-sm" onClick={clearPlanSelection}>Cancel</button><button type="button" className="btn btn-primary btn-sm" onClick={() => void applyPlan()} disabled={applying || plan.summary.reachable === 0}>{applying ? "Starting…" : `Apply to ${plan.summary.hosts} target${plan.summary.hosts === 1 ? "" : "s"}`}</button></div>
          </div>
        </section>
      )}

      {run && <><RunStatus run={run} />{["completed", "partial", "failed"].includes(run.status) && <div className="codex-sync-new-run"><button type="button" className="btn btn-primary btn-sm" onClick={startAnotherRun}>Start another sync</button></div>}</>}
    </section>
  );
}
