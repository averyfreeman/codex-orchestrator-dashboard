import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { HOSTS, unavailableReport, type HostDefinition, type HostReport, type SshRoute } from "@/lib/hosts";

const execFileAsync = promisify(execFile);
const probe = readFile(path.join(process.cwd(), "scripts/probe.py"), "utf8");

function shellQuote(value: string) {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/** Try strict SSH routes sequentially and return the first successful result. */
export async function sshWithFailover<T>(
  /** Ordered routes; the collector honors the configured preference. */
  routes: SshRoute[],
  /** One route attempt, usually an SSH probe with bounded execution time. */
  runRoute: (route: SshRoute) => Promise<T>,
): Promise<{ route: SshRoute; result: T }> {
  const failures: string[] = [];
  for (const route of routes) {
    try {
      return { route, result: await runRoute(route) };
    } catch (error) {
      const message = error instanceof Error ? error.message : "SSH attempt failed";
      failures.push(`${route.transport}: ${message.slice(0, 180)}`);
    }
  }
  throw new Error(failures.length ? failures.join("; ") : "No SSH routes are configured");
}

async function collectOne(host: HostDefinition): Promise<HostReport> {
  try {
    const script = await probe;
    const options = { timeout: 14_000, maxBuffer: 1_000_000, encoding: "utf8" as const };
    let result;
    let connection: HostReport["connection"];
    if (host.local) {
      result = await execFileAsync("python3", ["-c", script], options);
      connection = { transport: "local", target: null };
    } else {
      const attempt = await sshWithFailover(host.sshRoutes ?? [], (route) =>
        execFileAsync(
          "ssh",
          [
            "-T",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=yes",
            "-o", `HostKeyAlias=${route.hostKeyAlias}`,
            route.target,
            `python3 -c ${shellQuote(script)}`,
          ],
          options,
        ),
      );
      result = attempt.result;
      connection = { transport: attempt.route.transport, target: attempt.route.target.split("@").at(-1) ?? null };
    }
    const data = JSON.parse(result.stdout) as {
      appServer: HostReport["appServer"];
      herdr: HostReport["herdr"];
      processes: HostReport["processes"];
      worktrees: HostReport["worktrees"];
      ips?: { localIp?: string | null; tailscaleIp?: string | null; zerotierIp?: string | null };
    };
    return {
      host: {
        ...host,
        localIp: data.ips?.localIp ?? host.localIp,
        tailscaleIp: data.ips?.tailscaleIp ?? host.tailscaleIp,
        zerotierIp: data.ips?.zerotierIp ?? host.zerotierIp,
      },
      checkedAt: new Date().toISOString(),
      reachable: data.appServer.status === "running",
      connection,
      appServer: data.appServer,
      herdr: data.herdr,
      processes: data.processes,
      worktrees: data.worktrees,
      error: data.appServer.error,
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : "Probe failed";
    return {
      ...unavailableReport(host),
      error: message.slice(0, 400),
    };
  }
}

/** Collect a sanitized report for every configured host concurrently. */
export async function collectOverview() {
  return Promise.all(HOSTS.map(collectOne));
}

/** Collect one configured host report for the guarded recovery recheck. */
export async function collectHostReport(host: HostDefinition) {
  return collectOne(host);
}

/** Resolve a request-supplied host slug against the private allowlist. */
export function findHost(slug: string) {
  return HOSTS.find((host) => host.slug === slug);
}

/** Return whether a report says the Codex app-server is responding. */
export function appServerHealthy(report: Pick<HostReport, "appServer">) {
  return report.appServer.status === "running";
}
