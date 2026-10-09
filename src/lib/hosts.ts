import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

/** One allowlisted local or SSH-reachable machine in the private fleet inventory. */
export type HostDefinition = {
  /** Stable, URL-safe key used by control requests. */
  slug: string;
  /** Human-readable dashboard label. */
  name: string;
  /** Display-only operating system label. */
  os: string;
  /** Optional LAN address shown in the UI; never used as an SSH route. */
  localIp: string | null;
  /** Optional Tailscale address shown in the UI. */
  tailscaleIp: string | null;
  /** Optional ZeroTier address shown in the UI. */
  zerotierIp: string | null;
  /** Strict SSH routes tried in order, normally ZeroTier before Tailscale. */
  sshRoutes?: SshRoute[];
  /** Marks the gateway host so the collector probes it without SSH. */
  local?: boolean;
  /** Optional per-host CODEX_HOME override, absolute or relative to $HOME. */
  codexHome?: string;
};

/** Supported overlay transports for SSH routes. */
export type SshTransport = "zerotier" | "tailscale";
/** Selected transport reported by a local, remote, or failed probe. */
export type ConnectionTransport = SshTransport | "local" | "unavailable";

/** One strict SSH destination and its stable known-hosts alias. */
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
    (host.local === undefined || typeof host.local === "boolean") &&
    (host.codexHome === undefined || isCodexHomeOverride(host.codexHome));
}

function isCodexHomeOverride(value: unknown): value is string {
  if (typeof value !== "string" || !value.trim() || /[\0\r\n]/.test(value)) return false;
  if (value === "~") return true;
  if (value.startsWith("~/")) return !value.slice(2).split(/[\\/]+/).includes("..");
  return path.isAbsolute(value) && !value.split(path.sep).includes("..");
}

/** Resolve an inventory's Codex home without exposing it in browser reports. */
export function configuredCodexHome(host: HostDefinition) {
  const raw = host.codexHome ?? (host.local ? process.env.CODEX_HOME : undefined) ?? "~/.codex";
  if (raw === "~") return raw;
  if (raw.startsWith("~/")) return raw;
  return raw;
}

function publicHost(host: HostDefinition): HostDefinition {
  const safeHost = { ...host };
  delete safeHost.codexHome;
  return safeHost;
}

function isSshRoute(value: unknown): value is SshRoute {
  if (!value || typeof value !== "object") return false;
  const route = value as Record<string, unknown>;
  return (route.transport === "zerotier" || route.transport === "tailscale") &&
    typeof route.target === "string" && typeof route.hostKeyAlias === "string";
}

/** Hosts validated from the private inventory, or an empty list on invalid input. */
export const HOSTS = loadHosts();

/** CPU, memory, elapsed time, and command metadata for one observed process. */
export type ProcessInfo = {
  pid: number;
  cpuPercent: number;
  memoryPercent: number;
  memoryMb: number;
  elapsed: string;
  command: string;
};

/** Bounded Herdr agent metadata associated with a host. */
export type AgentInfo = {
  id: string;
  name: string;
  state: string;
  pid: number | null;
};

/** A registered Treehouse worktree discovered from local state metadata. */
export type WorktreeInfo = {
  name: string;
  path: string;
  createdAt: string | null;
};

/** Sanitized observation result for one configured host. */
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
    cliVersion: string | null;
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

/** Build the consistent unavailable-state report used when a probe cannot respond. */
export function unavailableReport(
  host: HostDefinition,
  checkedAt = new Date().toISOString(),
): HostReport {
  const reason = "Host has not responded over its configured overlay routes.";
  return {
    host: publicHost(host),
    checkedAt,
    reachable: false,
    connection: { transport: "unavailable", target: null },
    appServer: {
      status: "unavailable",
      cliVersion: null,
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
