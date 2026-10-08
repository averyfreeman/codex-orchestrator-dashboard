import { appendFile, chmod, mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import type { HostReport } from "@/lib/hosts";

/** Bounded event metadata persisted to the private JSONL telemetry file. */
export type LogEvent = {
  at?: string;
  source: string;
  host: string;
  type: string;
  stats?: Record<string, unknown>;
};

/** Validate the public event envelope before writing an ingested event. */
export function isLogEvent(value: unknown): value is LogEvent {
  if (!value || typeof value !== "object") return false;
  const event = value as Record<string, unknown>;
  return (
    typeof event.source === "string" && event.source.length > 0 && event.source.length <= 80 &&
    typeof event.host === "string" && event.host.length > 0 && event.host.length <= 120 &&
    typeof event.type === "string" && event.type.length > 0 && event.type.length <= 80 &&
    (event.stats === undefined || (typeof event.stats === "object" && event.stats !== null && !Array.isArray(event.stats)))
  );
}

const logPath = () => path.join(process.cwd(), "logs", "events.jsonl");

/** Append one event with an owner-only file and directory mode. */
export async function appendEvent(event: LogEvent) {
  const file = logPath();
  await mkdir(path.dirname(file), { recursive: true });
  await chmod(path.dirname(file), 0o700);
  const line = JSON.stringify({ at: event.at ?? new Date().toISOString(), ...event });
  await appendFile(file, `${line}\n`, { mode: 0o600 });
  await chmod(file, 0o600);
}

/** Project host reports into a content-free fleet snapshot and persist it. */
export async function appendSnapshot(reports: HostReport[]) {
  await appendEvent({
    source: "dashboard",
    host: "fleet",
    type: "snapshot",
    stats: {
      reachable: reports.filter((report) => report.reachable).length,
      total: reports.length,
      appServers: reports.map((report) => ({
        host: report.host.slug,
        status: report.appServer.status,
        transport: report.connection.transport,
        version: report.appServer.version,
        remoteControlEnabled: report.appServer.remoteControlEnabled,
        processCount: report.processes.length,
        agentCount: report.herdr.agents.length,
        worktreeCount: report.worktrees.length,
      })),
    },
  });
}

/** Read the newest bounded events, returning an empty list when no log exists. */
export async function readRecentEvents(limit = 100) {
  try {
    const body = await readFile(logPath(), "utf8");
    return body
      .split("\n")
      .filter(Boolean)
      .slice(-Math.max(1, Math.min(limit, 500)))
      .map((line) => JSON.parse(line));
  } catch {
    return [];
  }
}
