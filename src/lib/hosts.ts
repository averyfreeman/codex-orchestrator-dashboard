import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

export type HostDefinition = {
  slug: string;
  name: string;
  os: string;
  localIp: string | null;
  tailscaleIp: string | null;
  zerotierIp: string | null;
  sshRoutes?: SshRoute[];
  local?: boolean;
};

export type SshTransport = "zerotier" | "tailscale";
export type ConnectionTransport = SshTransport | "local" | "unavailable";

export type SshRoute = {
  transport: SshTransport;
  target: string;
  hostKeyAlias: string;
};

function loadHosts(): HostDefinition[] {
  const examplePath = path.join(process.cwd(), "config", "fleet.example.json");
  const configuredPath = process.env.FLEET_CONFIG_PATH
    ? path.resolve(process.env.FLEET_CONFIG_PATH)
    : path.join(process.cwd(), "config", "fleet.local.json");

  for (const file of [configuredPath, examplePath]) {
    try {
      if (!existsSync(/*turbopackIgnore: true*/ file)) continue;
      const value: unknown = JSON.parse(readFileSync(/*turbopackIgnore: true*/ file, "utf8"));
      if (Array.isArray(value) && value.every(isHostDefinition)) return value;
    } catch {
      // An invalid local inventory fails closed; it must not trigger SSH probes.
      if (file === configuredPath) return [];
    }
  }

  return [];
}

function isHostDefinition(value: unknown): value is HostDefinition {
  if (!value || typeof value !== "object") return false;
  const host = value as Record<string, unknown>;
  return typeof host.slug === "string" && typeof host.name === "string" &&
    typeof host.os === "string" &&
    (host.localIp === null || typeof host.localIp === "string") &&
    (host.tailscaleIp === null || typeof host.tailscaleIp === "string") &&
    (host.zerotierIp === null || typeof host.zerotierIp === "string") &&
    (host.sshRoutes === undefined || (Array.isArray(host.sshRoutes) && host.sshRoutes.every(isSshRoute))) &&
    (host.local === undefined || typeof host.local === "boolean");
}

function isSshRoute(value: unknown): value is SshRoute {
  if (!value || typeof value !== "object") return false;
  const route = value as Record<string, unknown>;
  return (route.transport === "zerotier" || route.transport === "tailscale") &&
    typeof route.target === "string" && typeof route.hostKeyAlias === "string";
}

export const HOSTS = loadHosts();

export type ProcessInfo = {
  pid: number;
  cpuPercent: number;
  memoryPercent: number;
  memoryMb: number;
  elapsed: string;
  command: string;
};

export type AgentInfo = {
  id: string;
  name: string;
  state: string;
  pid: number | null;
};

export type WorktreeInfo = {
  name: string;
  path: string;
  createdAt: string | null;
};

export type HostReport = {
  host: HostDefinition;
  checkedAt: string;
  reachable: boolean;
  connection: {
    transport: ConnectionTransport;
    target: string | null;
  };
  appServer: {
    status: string;
    version: string | null;
    remoteControlEnabled: boolean | null;
    remoteControlRuntime: string;
    loadedThreads: number | null;
    startup: string;
    error: string | null;
  };
  herdr: {
    status: string;
    version: string | null;
    startup: string;
    agents: AgentInfo[];
    workspaces: string[];
    error: string | null;
  };
  processes: ProcessInfo[];
  worktrees: WorktreeInfo[];
  error: string | null;
};

export function unavailableReport(
  host: HostDefinition,
  checkedAt = new Date().toISOString(),
): HostReport {
  const reason = "Host has not responded over its configured overlay routes.";
  return {
    host,
    checkedAt,
    reachable: false,
    connection: { transport: "unavailable", target: null },
    appServer: {
      status: "unavailable",
      version: null,
      remoteControlEnabled: null,
      remoteControlRuntime: "unavailable",
      loadedThreads: null,
      startup: "unknown",
      error: reason,
    },
    herdr: {
      status: "unavailable",
      version: null,
      startup: "unknown",
      agents: [],
      workspaces: [],
      error: reason,
    },
    processes: [],
    worktrees: [],
    error: reason,
  };
}
