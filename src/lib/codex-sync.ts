import { spawn } from "node:child_process";
import { chmod, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { configuredCodexHome, HOSTS, type HostDefinition } from "@/lib/hosts";
import { appendEvent } from "@/lib/logging";

const PLAN_TTL_MS = 10 * 60_000;
const HELPER_MAX_OUTPUT = 40 * 1024 * 1024;
const APPLY_TIMEOUT_MS = 12 * 60_000;
const helperSource = readFile(path.join(process.cwd(), "scripts/codex_sync.py"), "utf8");
const plans = new Map<string, StoredPlan>();
const runningHosts = new Set<string>();

export type SyncCategory = "cli" | "runtime" | "plugins" | "config" | "profiles" | "skills" | "codexHome";
export type SyncCategoryStatus = "in-sync" | "drift" | "blocked" | "unavailable" | "pending" | "applying" | "applied" | "failed" | "deferred" | "not-requested";
export type SyncDiff = {
  category: SyncCategory;
  item: string;
  kind: "add" | "update" | "remove" | "blocked" | "info";
  sourceValue?: string | number | boolean | null;
  targetValue?: string | number | boolean | null;
  message?: string;
};

export type SyncHostPlan = {
  hostSlug: string;
  hostName: string;
  reference?: boolean;
  included: boolean;
  reachable: boolean;
  categories: Record<SyncCategory, { status: SyncCategoryStatus; changes: number; blocked: number; source?: string | null; target?: string | null }>;
  diffs: SyncDiff[];
  blockedItems: string[];
  counts: { changes: number; blocked: number };
};

export type CodexSyncPlanResponse = {
  planId: string;
  createdAt: string;
  expiresAt: string;
  source: { slug: string; name: string; cliVersion: string; runtimeVersion: string | null };
  targetSlugs: string[];
  hosts: SyncHostPlan[];
  summary: { hosts: number; reachable: number; changes: number; blocked: number };
};

type HelperFile = { name: string; exists: boolean; hash: string | null; portable: Record<string, string | boolean>; unclassified: Record<string, string>; invalid: boolean };
type HelperSkill = { hash: string; files: Record<string, string>; fileNames: string[]; fileHashes: Record<string, string>; transferBlocked?: boolean };
type HelperPlugin = { name: string; marketplaceName: string; enabled: boolean; marketplaceKind: string; selector: string; version?: string; packageHash?: string; transferBlocked?: boolean };
type HelperMarketplace = { name: string; kind: string; source?: string | null; ref?: string | null; sparsePaths?: string[]; root?: string | null; replace?: boolean; existing?: boolean };
type HelperSnapshot = {
  cliVersion: string | null;
  runtimeVersion: string | null;
  runtimeStatus: string;
  activeTurns: { count: number | null; known: boolean };
  codexHome: { configured: boolean; label: string; source: string };
  config: { files: HelperFile[]; profileNames: string[]; hash: string };
  plugins: { available: boolean; error?: string | null; marketplaces: HelperMarketplace[]; plugins: HelperPlugin[]; localPackages: Record<string, Record<string, string>>; hash: string };
  skills: { skills: Record<string, HelperSkill>; blocked: string[]; hash: string };
  snapshotHash: string;
  public: {
    cliVersion: string | null;
    runtimeVersion: string | null;
    runtimeStatus: string;
    activeTurns: { count: number | null; known: boolean };
    codexHome: { configured: boolean; label: string; source: string };
    config: { files: Array<{ name: string; exists: boolean; portable: Record<string, string | boolean>; unclassifiedKeys: string[]; invalid: boolean }>; profileNames: string[] };
    plugins: { available: boolean; marketplaces: Array<{ name: string; kind: string; ref?: string | null; sparsePaths?: string[] }>; plugins: HelperPlugin[] };
    skills: { names: string[]; blocked: string[] };
    snapshotHash: string;
  };
};

type HostActions = {
  config: Array<{ name: string; values: Record<string, string | boolean>; remove: string[] }>;
  plugins: { marketplaces: HelperMarketplace[]; localPackages: Record<string, Record<string, Record<string, string>>>; add: Array<{ name: string; marketplaceName: string }>; remove: Array<{ name: string; marketplaceName: string }> };
  skills: { write: Array<{ root: string; skill: string; path: string; content: string }>; delete: Array<{ root: string; skill: string }>; deleteFiles: Array<{ root: string; skill: string; path: string }> };
};

type StoredPlan = {
  response: CodexSyncPlanResponse;
  sourceHost: HostDefinition;
  targetHosts: HostDefinition[];
  snapshots: Map<string, HelperSnapshot>;
  actions: Map<string, HostActions>;
  expiresAtMs: number;
};

type RunCategory = { status: SyncCategoryStatus; count?: number; message?: string };
type JsonRecord = Record<string, unknown>;
type PersistedRun = {
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
    categories: Partial<Record<SyncCategory, RunCategory>>;
    versions: { cli: string | null; runtime: string | null };
    restart: { status: "not-requested" | "not-needed" | "restarted" | "deferred" | "failed"; reason?: string };
  }>;
};

export class CodexSyncError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "CodexSyncError";
  }
}

export function assertPlanSnapshotHash(plannedHash: string, currentHash: string) {
  if (plannedHash !== currentHash) {
    throw new CodexSyncError("The sync plan is stale because host state changed after review. Create a new plan.", 409);
  }
}

function quoteShell(value: string) {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function remoteCodexHome(host: HostDefinition) {
  const value = configuredCodexHome(host);
  if (value === "~") return 'CODEX_HOME="$HOME"; export CODEX_HOME; ';
  if (value.startsWith("~/")) return `CODEX_HOME="$HOME"/${quoteShell(value.slice(2))}; export CODEX_HOME; `;
  return `CODEX_HOME=${quoteShell(value)}; export CODEX_HOME; `;
}

function isJsonRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

async function invokeHelper(host: HostDefinition, request: Record<string, unknown>, timeoutMs = 30_000): Promise<JsonRecord> {
  const source = await helperSource;
  const payload = JSON.stringify({ ...request, codexHome: configuredCodexHome(host) }) + "\n";
  const runCommand = (command: string, args: string[]) => new Promise<{ stdout: string; code: number | null }>((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: process.cwd(),
      stdio: ["pipe", "pipe", "ignore"],
      env: host.local ? { ...process.env, CODEX_HOME: localCodexHome(host) } : process.env,
    });
    const chunks: Buffer[] = [];
    let size = 0;
    let settled = false;
    const finishError = (error: Error) => {
      if (settled) return;
      settled = true;
      child.kill("SIGTERM");
      reject(error);
    };
    const timer = setTimeout(() => finishError(new Error("Codex host did not respond to the sync request.")), timeoutMs);
    child.stdout.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size > HELPER_MAX_OUTPUT) {
        finishError(new Error("Codex sync inventory exceeded the transfer limit."));
        return;
      }
      chunks.push(chunk);
    });
    child.on("error", () => {
      clearTimeout(timer);
      finishError(new Error("Could not start the Codex sync helper."));
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (settled) return;
      settled = true;
      resolve({ stdout: Buffer.concat(chunks).toString("utf8"), code });
    });
    child.stdin.on("error", () => undefined);
    child.stdin.end(payload);
  });
  let result: { stdout: string; code: number | null };
  if (host.local) {
    result = await runCommand("python3", ["-c", source]);
  } else {
    let succeeded: { stdout: string; code: number | null } | null = null;
    for (const route of host.sshRoutes ?? []) {
      try {
        const attempt = await runCommand("ssh", [
          "-T", "-q",
          "-o", "BatchMode=yes",
          "-o", "ConnectTimeout=5",
          "-o", "ServerAliveInterval=8",
          "-o", "ServerAliveCountMax=2",
          "-o", "StrictHostKeyChecking=yes",
          "-o", `HostKeyAlias=${route.hostKeyAlias}`,
          "--", route.target,
          `${remoteCodexHome(host)}python3 -c ${quoteShell(source)}`,
        ]);
        if (attempt.code === 0) {
          succeeded = attempt;
          break;
        }
      } catch {
        // Try the next already-allowlisted strict route.
      }
    }
    if (!succeeded) throw new Error("Host did not respond over its configured strict SSH routes.");
    result = succeeded;
  }
  let envelope: JsonRecord;
  try {
    envelope = JSON.parse(result.stdout.trim()) as JsonRecord;
  } catch {
    throw new Error("Codex sync helper returned an invalid response.");
  }
  if (!envelope.ok || !isJsonRecord(envelope.result)) {
    throw new Error(typeof envelope.error === "string" ? envelope.error : "Codex sync operation failed.");
  }
  return envelope.result;
}

function localCodexHome(host: HostDefinition) {
  const value = configuredCodexHome(host);
  if (value === "~") return os.homedir();
  if (value.startsWith("~/")) return path.join(os.homedir(), value.slice(2));
  return value;
}

async function inspectHost(host: HostDefinition, includeContent: boolean) {
  const result = await invokeHelper(host, { operation: "inspect", includeContent });
  return result as HelperSnapshot;
}

function category(status: SyncCategoryStatus = "in-sync", changes = 0, blocked = 0, source?: string | null, target?: string | null) {
  return { status, changes, blocked, source, target };
}

function stableMarketEqual(source: HelperMarketplace | undefined, target: HelperMarketplace | undefined) {
  if (!source || !target || source.kind !== target.kind) return false;
  if (source.kind === "local" || source.kind === "managed") return true;
  return source.source === target.source && (source.ref ?? null) === (target.ref ?? null) && JSON.stringify(source.sparsePaths ?? []) === JSON.stringify(target.sparsePaths ?? []);
}

function keyLabel(key: string) {
  if (key === "mcp_servers") return "MCP server settings (secret values retained)";
  return /^[A-Za-z0-9_.-]{1,100}$/.test(key) ? key : "unclassified setting";
}

function configFileMap(snapshot: HelperSnapshot) {
  return new Map(snapshot.config.files.map((file) => [file.name, file]));
}

function settingDiffs(
  source: HelperFile,
  target: HelperFile | undefined,
  categoryName: "config" | "profiles",
  action: HostActions,
  diffs: SyncDiff[],
  blocked: string[],
) {
  if (!source.exists) {
    if (target?.exists) blocked.push(`${source.name}: source file is absent; target file was retained.`);
    return 0;
  }
  if (source.invalid || target?.invalid) {
    blocked.push(`${source.name}: invalid TOML must be reviewed on the host before syncing.`);
    return 0;
  }
  const targetValues = target?.portable ?? {};
  const sourceValues = source.portable ?? {};
  const valueNames = new Set([...Object.keys(sourceValues), ...Object.keys(targetValues)]);
  const values: Record<string, string | boolean> = {};
  const remove: string[] = [];
  let changed = 0;
  for (const name of [...valueNames].sort()) {
    if (sourceValues[name] === targetValues[name] && Object.hasOwn(sourceValues, name) === Object.hasOwn(targetValues, name)) continue;
    if (Object.hasOwn(sourceValues, name)) values[name] = sourceValues[name];
    else remove.push(name);
    diffs.push({
      category: categoryName,
      item: `${source.name} · ${name}`,
      kind: Object.hasOwn(sourceValues, name) ? (Object.hasOwn(targetValues, name) ? "update" : "add") : "remove",
      sourceValue: sourceValues[name] ?? null,
      targetValue: targetValues[name] ?? null,
    });
    changed++;
  }
  if (changed) action.config.push({ name: source.name, values, remove });
  const sourceUnknown = source.unclassified ?? {};
  const targetUnknown = target?.unclassified ?? {};
  const unknownNames = new Set([...Object.keys(sourceUnknown), ...Object.keys(targetUnknown)]);
  const unknownDiffs = [...unknownNames].filter((name) => sourceUnknown[name] !== targetUnknown[name]);
  if (unknownDiffs.length) {
    const labels = unknownDiffs.slice(0, 5).map(keyLabel).join(", ");
    blocked.push(`${source.name}: ${unknownDiffs.length} unclassified setting difference${unknownDiffs.length === 1 ? "" : "s"} retained (${labels}).`);
  }
  if (target && !target.exists && !Object.keys(sourceValues).length && Object.keys(sourceUnknown).length) {
    blocked.push(`${source.name}: no portable settings were eligible to create the file.`);
  }
  return changed;
}

export function makeActionsAndView(
  targetHost: HostDefinition,
  source: HelperSnapshot,
  target: HelperSnapshot,
  included: boolean,
): { view: SyncHostPlan; actions: HostActions } {
  const actions: HostActions = { config: [], plugins: { marketplaces: [], localPackages: {}, add: [], remove: [] }, skills: { write: [], delete: [], deleteFiles: [] } };
  const diffs: SyncDiff[] = [];
  const blocked: string[] = [];
  const categories: SyncHostPlan["categories"] = {
    cli: category(), runtime: category(), plugins: category(), config: category(), profiles: category(), skills: category(), codexHome: category(),
  };

  if (source.cliVersion !== target.cliVersion) {
    categories.cli = category("drift", 1, 0, source.cliVersion, target.cliVersion);
    diffs.push({ category: "cli", item: "Codex CLI", kind: target.cliVersion ? "update" : "add", sourceValue: source.cliVersion, targetValue: target.cliVersion });
  }
  if (source.runtimeVersion !== target.runtimeVersion || source.runtimeStatus !== target.runtimeStatus) {
    categories.runtime = category("drift", 1, 0, source.runtimeVersion, target.runtimeVersion);
    diffs.push({ category: "runtime", item: "Running app-server", kind: "info", sourceValue: source.runtimeVersion, targetValue: target.runtimeVersion, message: "Runtime changes take effect only after an eligible managed-daemon restart." });
  }
  if (!target.codexHome.configured) {
    categories.codexHome = category("blocked", 0, 1, source.codexHome.label, target.codexHome.label);
    blocked.push("CODEX_HOME is not present on the target host; the sync helper will use the inventory/default path.");
  } else {
    categories.codexHome = category("in-sync", 0, 0, source.codexHome.label, target.codexHome.label);
  }

  const sourceFiles = configFileMap(source);
  const targetFiles = configFileMap(target);
  let configChanges = 0;
  let profileChanges = 0;
  for (const name of new Set([...sourceFiles.keys(), ...targetFiles.keys()])) {
    const sourceFile = sourceFiles.get(name) ?? { name, exists: false, hash: null, portable: {}, unclassified: {}, invalid: false };
    const targetFile = targetFiles.get(name);
    const currentCategory = name === "config.toml" ? "config" : "profiles";
    const changed = settingDiffs(sourceFile, targetFile, currentCategory, actions, diffs, blocked);
    if (name === "config.toml") configChanges += changed;
    else profileChanges += changed;
  }
  const configBlocked = blocked.filter((item) => item.startsWith("config.toml:")).length;
  const profileBlocked = blocked.filter((item) => item.includes(".config.toml:")).length;
  categories.config = category(configBlocked ? "blocked" : configChanges ? "drift" : "in-sync", configChanges, configBlocked);
  categories.profiles = category(profileBlocked ? "blocked" : profileChanges ? "drift" : "in-sync", profileChanges, profileBlocked);

  if (!source.plugins.available) {
    blocked.push("Source plugin inventory is unavailable.");
    categories.plugins = category("blocked", 0, 1);
  } else if (!target.plugins.available) {
    blocked.push("Target plugin inventory is unavailable; marketplace/plugin state was left unchanged.");
    categories.plugins = category("blocked", 0, 1);
  } else {
    const sourceMarkets = new Map(source.plugins.marketplaces.map((market) => [market.name, market]));
    const targetMarkets = new Map(target.plugins.marketplaces.map((market) => [market.name, market]));
    const sourcePlugins = new Map(source.plugins.plugins.filter((plugin) => plugin.enabled).map((plugin) => [plugin.selector, plugin]));
    const targetPlugins = new Map(target.plugins.plugins.map((plugin) => [plugin.selector, plugin]));
    const targetEnabled = new Set(target.plugins.plugins.filter((plugin) => plugin.enabled).map((plugin) => plugin.selector));
    const desired = new Set(sourcePlugins.keys());
    const marketNeedsSync = new Set<string>();
    const pluginIssues = new Set<string>();
    const enabledByMarket = new Set([...sourcePlugins.values()].map((plugin) => plugin.marketplaceName));
    let pluginChanges = 0;

    for (const market of sourceMarkets.values()) {
      if (!['git', 'local', 'managed'].includes(market.kind)) {
        blocked.push(`Marketplace ${market.name} has an unsupported source type and was left unchanged.`);
        continue;
      }
      if (market.kind === "managed") continue;
      if (enabledByMarket.has(market.name)) continue;
      const targetMarket = targetMarkets.get(market.name);
      if (market.kind === "git" && !stableMarketEqual(market, targetMarket)) {
        marketNeedsSync.add(market.name);
        diffs.push({ category: "plugins", item: `Marketplace ${market.name}`, kind: targetMarket ? "update" : "add", message: "The reference Git marketplace source or ref differs." });
        pluginChanges++;
      } else if (market.kind === "local" && !targetMarket) {
        blocked.push(`Local marketplace ${market.name} has no enabled plugin with a validated source package; it was not copied.`);
      }
    }

    for (const [selector, plugin] of sourcePlugins) {
      const market = sourceMarkets.get(plugin.marketplaceName);
      if (!market || !["git", "local", "managed"].includes(market.kind)) {
        blocked.push(`${selector}: source marketplace type is not supported for automatic sync.`);
        pluginIssues.add(selector);
        continue;
      }
      const targetMarket = targetMarkets.get(plugin.marketplaceName);
      if (market.kind === "managed" && targetMarket && targetMarket.kind !== "managed") {
        blocked.push(`${selector}: a same-named non-Codex marketplace exists on the target; the plugin was left unchanged.`);
        pluginIssues.add(selector);
        continue;
      }
      if (plugin.transferBlocked) {
        blocked.push(`${selector}: validated local package transfer is blocked.`);
        pluginIssues.add(selector);
        continue;
      }
      const prior = targetPlugins.get(selector);
      const packageChanged = market.kind === "local" && Boolean(prior?.enabled) && prior?.packageHash !== plugin.packageHash;
      const versionChanged = Boolean(prior?.enabled && plugin.version && prior.version && prior.version !== plugin.version);
      if (market.kind !== "managed" && (!prior?.enabled || packageChanged || versionChanged || !stableMarketEqual(market, targetMarket))) {
        marketNeedsSync.add(plugin.marketplaceName);
      }
    }

    for (const marketName of marketNeedsSync) {
      const market = sourceMarkets.get(marketName)!;
      const priorMarket = targetMarkets.get(marketName);
      const replace = Boolean(priorMarket && !stableMarketEqual(market, priorMarket));
      const cleanMarket: HelperMarketplace = { name: market.name, kind: market.kind, source: market.source ?? null, ref: market.ref ?? null, sparsePaths: market.sparsePaths ?? [], replace, existing: Boolean(priorMarket) };
      actions.plugins.marketplaces.push(cleanMarket);
      if (market.kind === "local") {
        const packages: Record<string, Record<string, string>> = {};
        for (const plugin of sourcePlugins.values()) {
          if (plugin.marketplaceName !== marketName || pluginIssues.has(plugin.selector)) continue;
          const files = source.plugins.localPackages[plugin.selector];
          if (!files) {
            blocked.push(`${plugin.selector}: validated local package source is unavailable.`);
            pluginIssues.add(plugin.selector);
            continue;
          }
          packages[plugin.name] = files;
        }
        if (Object.keys(packages).length) actions.plugins.localPackages[marketName] = packages;
      }
    }

    for (const selector of targetEnabled) {
      if (desired.has(selector)) continue;
      const plugin = targetPlugins.get(selector)!;
      const market = targetMarkets.get(plugin.marketplaceName);
      const sourceMarket = sourceMarkets.get(plugin.marketplaceName);
      if (sourceMarket?.kind === "managed" && market?.kind !== "managed") {
        blocked.push(`${selector}: a same-named non-Codex marketplace exists on the target; the plugin was left unchanged.`);
        continue;
      }
      if (!market || !["git", "local", "managed"].includes(market.kind) || !["git", "local", "managed"].includes(plugin.marketplaceKind)) {
        blocked.push(`${selector}: target plugin source is not supported for automatic sync; the plugin remains enabled.`);
        continue;
      }
      actions.plugins.remove.push({ name: plugin.name, marketplaceName: plugin.marketplaceName });
      diffs.push({ category: "plugins", item: selector, kind: "remove" });
      pluginChanges++;
    }
    for (const [selector, plugin] of sourcePlugins) {
      if (pluginIssues.has(selector)) continue;
      const prior = targetPlugins.get(selector);
      const market = sourceMarkets.get(plugin.marketplaceName)!;
      const targetMarket = targetMarkets.get(plugin.marketplaceName);
      const packageChanged = market.kind === "local" && Boolean(prior?.enabled) && prior?.packageHash !== plugin.packageHash;
      const versionChanged = Boolean(prior?.enabled && plugin.version && prior.version && prior.version !== plugin.version);
      const needsMarketSync = market.kind !== "managed" && marketNeedsSync.has(plugin.marketplaceName);
      const needsInstall = !prior?.enabled || packageChanged || versionChanged || needsMarketSync;
      const marketMatches = market.kind === "managed" || stableMarketEqual(market, targetMarket);
      if (!needsInstall && marketMatches) continue;
      if (prior) actions.plugins.remove.push({ name: plugin.name, marketplaceName: plugin.marketplaceName });
      actions.plugins.add.push({ name: plugin.name, marketplaceName: plugin.marketplaceName });
      diffs.push({ category: "plugins", item: selector, kind: prior?.enabled ? "update" : "add", sourceValue: plugin.version ?? null, targetValue: prior?.version ?? null });
      pluginChanges++;
    }
    for (const market of target.plugins.marketplaces) {
      if (!sourceMarkets.has(market.name)) {
        blocked.push(`Additional marketplace ${market.name} is kept on the target host.`);
      }
    }
    const pluginBlocked = new Set(blocked.filter((item) => item.toLowerCase().includes("marketplace") || item.toLowerCase().includes("plugin") || item.toLowerCase().includes("package") || item.toLowerCase().includes("selector"))).size;
    categories.plugins = category(pluginBlocked ? "blocked" : pluginChanges ? "drift" : "in-sync", pluginChanges, pluginBlocked);
  }

  const sourceSkills = source.skills.skills;
  const targetSkills = target.skills.skills;
  const sourceBlocked = new Set(source.skills.blocked);
  const targetBlocked = new Set(target.skills.blocked);
  let skillChanges = 0;
  for (const [key, skill] of Object.entries(sourceSkills)) {
    const [root, skillName] = key.split("/", 2);
    const prior = targetSkills[key];
    if (targetBlocked.has(key) || skill.transferBlocked || !Object.keys(skill.files).length) {
      blocked.push(`${key}: skill content failed a transfer safety or size check.`);
      continue;
    }
    if (!prior) {
      diffs.push({ category: "skills", item: key, kind: "add", sourceValue: skill.fileNames.length, targetValue: 0 });
    }
    const targetHashes = prior?.fileHashes ?? {};
    for (const [filePath, content] of Object.entries(skill.files)) {
      if (skill.fileHashes[filePath] === targetHashes[filePath]) continue;
      actions.skills.write.push({ root, skill: skillName, path: filePath, content });
      if (prior) diffs.push({ category: "skills", item: `${key}/${filePath}`, kind: "update" });
      skillChanges++;
    }
    for (const filePath of prior?.fileNames ?? []) {
      if (Object.hasOwn(skill.fileHashes, filePath)) continue;
      actions.skills.deleteFiles.push({ root, skill: skillName, path: filePath });
      diffs.push({ category: "skills", item: `${key}/${filePath}`, kind: "remove" });
      skillChanges++;
    }
    if (!prior && skill.fileNames.length) skillChanges++;
  }
  for (const key of Object.keys(targetSkills)) {
    if (sourceSkills[key] || sourceBlocked.has(key)) continue;
    const [root, skillName] = key.split("/", 2);
    actions.skills.delete.push({ root, skill: skillName });
    diffs.push({ category: "skills", item: key, kind: "remove", message: "Target-only user skill will be backed up before removal." });
    skillChanges++;
  }
  for (const key of sourceBlocked) blocked.push(`${key}: excluded from transfer by the user-skill safety boundary.`);
  for (const key of targetBlocked) if (!sourceBlocked.has(key)) blocked.push(`${key}: target skill was excluded from transfer by the safety boundary.`);
  const skillBlocked = blocked.filter((item) => item.includes("skill") || item.includes("transfer safety") || item.includes("transfer size")).length;
  categories.skills = category(skillBlocked ? "blocked" : skillChanges ? "drift" : "in-sync", skillChanges, skillBlocked);

  const changes = Object.values(categories).reduce((sum, item) => sum + item.changes, 0);
  const blockedCount = Object.values(categories).reduce((sum, item) => sum + item.blocked, 0);
  return {
    view: {
      hostSlug: targetHost.slug,
      hostName: targetHost.name,
      included,
      reachable: true,
      categories,
      diffs,
      blockedItems: [...new Set(blocked)],
      counts: { changes, blocked: blockedCount },
    },
    actions,
  };
}

function makeUnavailableView(host: HostDefinition, included: boolean, message: string): SyncHostPlan {
  const blockedItems = [message];
  const categories = {
    cli: category("unavailable", 0, 1), runtime: category("unavailable", 0, 1), plugins: category("unavailable", 0, 1),
    config: category("unavailable", 0, 1), profiles: category("unavailable", 0, 1), skills: category("unavailable", 0, 1), codexHome: category("unavailable", 0, 1),
  } satisfies SyncHostPlan["categories"];
  return { hostSlug: host.slug, hostName: host.name, included, reachable: false, categories, diffs: [{ category: "runtime", item: "Host inspection", kind: "blocked", message }], blockedItems, counts: { changes: 0, blocked: 7 } };
}

function makeReferenceView(host: HostDefinition, snapshot: HelperSnapshot): SyncHostPlan {
  const invalidFiles = snapshot.config.files.filter((file) => file.invalid).length;
  const pluginBlocked = snapshot.plugins.available ? 0 : 1;
  const skillBlocked = snapshot.skills.blocked.length;
  const categories: SyncHostPlan["categories"] = {
    cli: category(snapshot.cliVersion ? "in-sync" : "unavailable", 0, snapshot.cliVersion ? 0 : 1, snapshot.cliVersion, snapshot.cliVersion),
    runtime: category(snapshot.runtimeVersion ? "in-sync" : "unavailable", 0, snapshot.runtimeVersion ? 0 : 1, snapshot.runtimeVersion, snapshot.runtimeVersion),
    plugins: category(snapshot.plugins.available ? "in-sync" : "blocked", 0, pluginBlocked),
    config: category(invalidFiles ? "blocked" : "in-sync", 0, invalidFiles),
    profiles: category(invalidFiles ? "blocked" : "in-sync", 0, invalidFiles),
    skills: category(skillBlocked ? "blocked" : "in-sync", 0, skillBlocked),
    codexHome: category("in-sync", 0, 0, snapshot.codexHome.label, snapshot.codexHome.label),
  };
  const blockedItems = [
    ...(!snapshot.plugins.available ? ["Reference plugin inventory is unavailable."] : []),
    ...(invalidFiles ? ["One or more reference config/profile files are invalid TOML."] : []),
    ...snapshot.skills.blocked.map((item) => `${item}: excluded by the user-skill safety boundary.`),
  ];
  return {
    hostSlug: host.slug,
    hostName: host.name,
    reference: true,
    included: false,
    reachable: true,
    categories,
    diffs: [],
    blockedItems,
    counts: { changes: 0, blocked: blockedItems.length },
  };
}

function expirePlans() {
  const now = Date.now();
  for (const [id, plan] of plans) if (plan.expiresAtMs <= now) plans.delete(id);
}

export async function createCodexSyncPlan(input: { sourceHostSlug: string; targetHostSlugs?: string[] }): Promise<CodexSyncPlanResponse> {
  expirePlans();
  const sourceHost = HOSTS.find((host) => host.slug === input.sourceHostSlug);
  if (!sourceHost) throw new CodexSyncError("The selected source host is not in the private fleet inventory.", 404);
  if (input.targetHostSlugs !== undefined && (!Array.isArray(input.targetHostSlugs) || input.targetHostSlugs.length === 0)) {
    throw new CodexSyncError("Select at least one target host.", 400);
  }
  const selectedSlugs = input.targetHostSlugs ? [...new Set(input.targetHostSlugs)] : undefined;
  if (selectedSlugs?.some((slug) => typeof slug !== "string" || !/^[A-Za-z0-9-]{1,80}$/.test(slug))) {
    throw new CodexSyncError("Target host slugs are invalid.", 400);
  }
  if (selectedSlugs?.includes(sourceHost.slug)) throw new CodexSyncError("The source host cannot also be a target.", 400);
  const peerHosts = HOSTS.filter((host) => host.slug !== sourceHost.slug);
  if (selectedSlugs?.some((slug) => !peerHosts.some((host) => host.slug === slug))) {
    throw new CodexSyncError("A selected target is not in the private fleet inventory.", 404);
  }
  let source: HelperSnapshot;
  try {
    source = await inspectHost(sourceHost, true);
  } catch {
    throw new CodexSyncError("The selected source host could not be inspected over its configured route.", 502);
  }
  if (!source.cliVersion) throw new CodexSyncError("The selected source host does not report an installed Codex CLI version.", 409);
  const inspectedPeers = await Promise.all(peerHosts.map(async (host) => {
    try {
      return { host, snapshot: await inspectHost(host, false), error: null as string | null };
    } catch {
      return { host, snapshot: null, error: "Host did not respond to the on-demand sync inspection." };
    }
  }));
  const reachableSlugs = new Set(inspectedPeers.filter((item) => item.snapshot).map((item) => item.host.slug));
  const chosenSlugs = selectedSlugs ?? [...reachableSlugs];
  const snapshots = new Map<string, HelperSnapshot>([[sourceHost.slug, source]]);
  const actions = new Map<string, HostActions>();
  const hostViews: SyncHostPlan[] = [makeReferenceView(sourceHost, source)];
  for (const item of inspectedPeers) {
    const included = chosenSlugs.includes(item.host.slug);
    if (!item.snapshot) {
      hostViews.push(makeUnavailableView(item.host, included, item.error ?? "Host did not respond to inspection."));
      continue;
    }
    if (included) snapshots.set(item.host.slug, item.snapshot);
    const result = makeActionsAndView(item.host, source, item.snapshot, included);
    hostViews.push(result.view);
    if (included) actions.set(item.host.slug, result.actions);
  }
  const reachableSelected = chosenSlugs.filter((slug) => reachableSlugs.has(slug));
  const createdAt = new Date().toISOString();
  const expiresAtMs = Date.now() + PLAN_TTL_MS;
  const response: CodexSyncPlanResponse = {
    planId: randomUUID(),
    createdAt,
    expiresAt: new Date(expiresAtMs).toISOString(),
    source: { slug: sourceHost.slug, name: sourceHost.name, cliVersion: source.cliVersion, runtimeVersion: source.runtimeVersion },
    targetSlugs: chosenSlugs,
    hosts: hostViews,
    summary: {
      hosts: chosenSlugs.length,
      reachable: reachableSelected.length,
      changes: hostViews.filter((view) => view.included).reduce((sum, view) => sum + view.counts.changes, 0),
      blocked: hostViews.filter((view) => view.included).reduce((sum, view) => sum + view.counts.blocked, 0),
    },
  };
  plans.set(response.planId, { response, sourceHost, targetHosts: peerHosts.filter((host) => chosenSlugs.includes(host.slug)), snapshots, actions, expiresAtMs });
  void appendEvent({ source: "codex-sync", host: sourceHost.slug, type: "codex.sync.plan_created", stats: { targetCount: response.summary.hosts, reachableCount: response.summary.reachable, changeCount: response.summary.changes, blockedCount: response.summary.blocked, cliVersion: source.cliVersion } }).catch(() => undefined);
  return response;
}

function runsDirectory() {
  return path.join(process.cwd(), ".dashboard-state", "codex-sync", "runs");
}

async function persistRun(run: PersistedRun) {
  const directory = runsDirectory();
  await mkdir(directory, { recursive: true, mode: 0o700 });
  await chmod(path.dirname(directory), 0o700).catch(() => undefined);
  await chmod(directory, 0o700);
  const destination = path.join(directory, `${run.runId}.json`);
  const temporary = `${destination}.${randomUUID()}.tmp`;
  await writeFile(temporary, JSON.stringify(run, null, 2), { mode: 0o600 });
  await chmod(temporary, 0o600);
  await rename(temporary, destination);
}

export async function readCodexSyncRun(runId: string): Promise<PersistedRun | null> {
  if (!/^[a-f0-9-]{36}$/.test(runId)) return null;
  try {
    const run = JSON.parse(await readFile(path.join(runsDirectory(), `${runId}.json`), "utf8")) as PersistedRun;
    return run;
  } catch {
    return null;
  }
}

function helperCategory(result: JsonRecord | undefined): RunCategory {
  const status = result?.status;
  const normalized: SyncCategoryStatus = status === "applied" || status === "unchanged" ? "applied" : status === "deferred" ? "deferred" : status === "not-needed" ? "in-sync" : status === "blocked" ? "blocked" : "failed";
  const count = Number(result?.filesChanged ?? result?.operations ?? (result?.changed ? 1 : 0));
  return { status: normalized, count: Number.isFinite(count) ? count : 0, message: typeof result?.message === "string" ? result.message : undefined };
}

function publicCategoryOutcome(value: JsonRecord | undefined, status: SyncCategoryStatus = "failed"): RunCategory {
  return { status: value ? helperCategory(value).status : status, count: Number(value?.filesChanged ?? value?.operations ?? 0), message: typeof value?.message === "string" ? value.message : undefined };
}

async function verifyFresh(plan: StoredPlan) {
  for (const [slug, prior] of plan.snapshots) {
    const host = slug === plan.sourceHost.slug ? plan.sourceHost : plan.targetHosts.find((entry) => entry.slug === slug);
    if (!host) throw new CodexSyncError("The sync plan no longer matches the host inventory.", 409);
    let current: HelperSnapshot;
    try {
      current = await inspectHost(host, false);
    } catch {
      throw new CodexSyncError("The sync plan is stale because a host is no longer reachable. Create a new plan.", 409);
    }
    assertPlanSnapshotHash(prior.snapshotHash, current.snapshotHash);
  }
}

export async function startCodexSyncApply(planId: string, restartWhenFinished: boolean) {
  expirePlans();
  const plan = plans.get(planId);
  if (!plan || plan.expiresAtMs <= Date.now()) throw new CodexSyncError("This sync plan expired. Create a fresh plan to continue.", 409);
  if (plan.response.summary.reachable === 0) throw new CodexSyncError("No selected target host is reachable. Create a plan with at least one reachable peer.", 409);
  const locks = [plan.sourceHost.slug, ...plan.response.targetSlugs];
  if (locks.some((slug) => runningHosts.has(slug))) throw new CodexSyncError("A Codex sync run is already using one of the selected hosts.", 409);
  locks.forEach((slug) => runningHosts.add(slug));
  try {
    await verifyFresh(plan);
  } catch (error) {
    locks.forEach((slug) => runningHosts.delete(slug));
    plans.delete(planId);
    throw error;
  }
  plans.delete(planId);
  const runId = randomUUID();
  const now = new Date().toISOString();
  const run: PersistedRun = {
    runId,
    sourceHostSlug: plan.sourceHost.slug,
    sourceCliVersion: plan.response.source.cliVersion,
    createdAt: now,
    updatedAt: now,
    status: "queued",
    restartWhenFinished,
    hosts: plan.response.targetSlugs.map((slug) => {
      const host = plan.targetHosts.find((item) => item.slug === slug)!;
      const initial = plan.response.hosts.find((item) => item.hostSlug === slug);
      const pending = Object.fromEntries((Object.keys(initial?.categories ?? {}) as SyncCategory[]).map((item) => [item, { status: initial?.reachable ? "pending" : "failed" as SyncCategoryStatus }])) as Partial<Record<SyncCategory, RunCategory>>;
      return { hostSlug: slug, hostName: host.name, status: initial?.reachable ? "queued" : "failed", categories: pending, versions: { cli: initial?.categories.cli.target ?? null, runtime: initial?.categories.runtime.target ?? null }, restart: { status: restartWhenFinished ? "not-needed" : "not-requested" } };
    }),
  };
  try {
    await persistRun(run);
  } catch (error) {
    locks.forEach((slug) => runningHosts.delete(slug));
    throw error;
  }
  void appendEvent({ source: "codex-sync", host: plan.sourceHost.slug, type: "codex.sync.apply_started", stats: { runId, targetCount: run.hosts.length, restartRequested: restartWhenFinished, cliVersion: run.sourceCliVersion } }).catch(() => undefined);
  void executeRun(plan, run)
    .catch(async () => {
      run.status = "failed";
      run.updatedAt = new Date().toISOString();
      run.hosts = run.hosts.map((host) => host.status === "completed" || host.status === "partial" || host.status === "failed"
        ? host
        : { ...host, status: "failed", categories: Object.fromEntries((Object.keys(host.categories) as SyncCategory[]).map((key) => [key, { status: "failed", message: "Sync run stopped before this host completed." }])) as Partial<Record<SyncCategory, RunCategory>> });
      await persistRun(run).catch(() => undefined);
    })
    .finally(() => locks.forEach((slug) => runningHosts.delete(slug)));
  return { runId };
}

async function executeRun(plan: StoredPlan, run: PersistedRun) {
  run.status = "applying";
  run.updatedAt = new Date().toISOString();
  await persistRun(run);
  for (const row of run.hosts) {
    const host = plan.targetHosts.find((item) => item.slug === row.hostSlug)!;
    const source = plan.snapshots.get(plan.sourceHost.slug)!;
    const target = plan.snapshots.get(host.slug);
    const actions = plan.actions.get(host.slug);
    if (!target || !actions) {
      row.status = "failed";
      row.categories = Object.fromEntries((Object.keys(row.categories) as SyncCategory[]).map((key) => [key, { status: "failed", message: "Host was unreachable during planning." }])) as Partial<Record<SyncCategory, RunCategory>>;
      run.updatedAt = new Date().toISOString();
      await persistRun(run);
      continue;
    }
    row.status = "applying";
    run.updatedAt = new Date().toISOString();
    await persistRun(run);
    try {
      const result = await invokeHelper(host, {
        operation: "apply",
        runId: run.runId,
        targetVersion: source.cliVersion,
        config: actions.config,
        plugins: actions.plugins,
        skills: actions.skills,
      }, APPLY_TIMEOUT_MS);
      const categories = isJsonRecord(result.categories) ? result.categories : {};
      row.categories = {
        cli: publicCategoryOutcome(isJsonRecord(categories.cli) ? categories.cli : undefined),
        runtime: { status: result.restartRequired === true ? (run.restartWhenFinished ? "pending" : "deferred") : "in-sync", count: 0, message: result.restartRequired === true && !run.restartWhenFinished ? "Automatic restart was not requested; the running daemon may still use its previous CLI, config, or plugin state." : undefined },
        plugins: publicCategoryOutcome(isJsonRecord(categories.plugins) ? categories.plugins : undefined),
        config: publicCategoryOutcome(isJsonRecord(categories.config) ? categories.config : undefined),
        profiles: publicCategoryOutcome(isJsonRecord(categories.profiles) ? categories.profiles : undefined),
        skills: publicCategoryOutcome(isJsonRecord(categories.skills) ? categories.skills : undefined),
        codexHome: { status: "applied", count: 0 },
      };
      if (run.restartWhenFinished && result.restartRequired === true) {
        const restart = await invokeHelper(host, { operation: "restart" }, 45_000);
        if (restart.status === "restarted") {
          row.restart = { status: "restarted" };
          row.categories.runtime = { status: "applied", count: 1 };
        } else if (restart.status === "failed") {
          row.restart = { status: "failed", reason: "Managed daemon restart failed." };
          row.categories.runtime = { status: "failed", message: "Managed daemon restart failed." };
        } else {
          row.restart = { status: restart.status === "not-needed" ? "not-needed" : "deferred", reason: typeof restart.reason === "string" ? restart.reason : undefined };
          row.categories.runtime = { status: restart.status === "not-needed" ? "in-sync" : "deferred", message: restart.status === "not-needed" ? undefined : "Restart deferred; runtime-version drift remains." };
        }
      }
      try {
        const latest = await inspectHost(host, false);
        row.versions = { cli: latest.cliVersion, runtime: latest.runtimeVersion };
        if (latest.runtimeVersion !== source.runtimeVersion) {
          row.categories.runtime = { status: "deferred", count: 0, message: `Runtime version ${latest.runtimeVersion ?? "unavailable"} still differs from reference ${source.runtimeVersion ?? "unavailable"}.` };
        } else if (row.categories.runtime?.status === "deferred") {
          row.categories.runtime.message = "A managed-daemon restart was deferred; the running server may not reflect newly applied config or plugin state.";
        }
      } catch {
        // The category outcomes remain authoritative if the post-apply readback
        // cannot reach the host.
      }
      const failed = Object.values(row.categories).some((outcome) => outcome.status === "failed" || outcome.status === "blocked");
      const deferred = Object.values(row.categories).some((outcome) => outcome.status === "deferred");
      row.status = failed ? "partial" : deferred ? "partial" : "completed";
    } catch {
      row.status = "failed";
      row.categories = Object.fromEntries((Object.keys(row.categories) as SyncCategory[]).map((key) => [key, { status: "failed", message: "Host apply did not complete." }])) as Partial<Record<SyncCategory, RunCategory>>;
      row.restart = run.restartWhenFinished ? { status: "deferred", reason: "Apply did not complete; restart was skipped." } : { status: "not-requested" };
    }
    run.updatedAt = new Date().toISOString();
    await persistRun(run);
    void appendEvent({ source: "codex-sync", host: row.hostSlug, type: `codex.sync.host_${row.status}`, stats: { runId: run.runId, categories: Object.fromEntries(Object.entries(row.categories).map(([name, outcome]) => [name, { status: outcome?.status, count: outcome?.count ?? 0 }])), cliVersion: row.versions.cli, runtimeVersion: row.versions.runtime, restartStatus: row.restart.status } }).catch(() => undefined);
  }
  const failures = run.hosts.filter((host) => host.status === "failed" || host.status === "partial").length;
  run.status = failures === 0 ? "completed" : failures === run.hosts.length ? "failed" : "partial";
  run.updatedAt = new Date().toISOString();
  await persistRun(run);
}
