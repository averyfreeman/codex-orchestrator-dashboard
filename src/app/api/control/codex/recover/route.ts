import { spawn } from "node:child_process";
import { NextResponse } from "next/server";
import { collectHostReport, findHost } from "@/lib/collector";
import { isLocalDashboardRequest } from "@/lib/control-security";
import { appendEvent } from "@/lib/logging";

/** Request the fixed daemon start only after confirming the host is not responding. */
export async function POST(request: Request) {
  if (!isLocalDashboardRequest(request)) {
    return NextResponse.json({ error: "Codex controls are available from the local dashboard only." }, { status: 403 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid Codex recovery request." }, { status: 400 });
  }
  if (!body || typeof body !== "object") return NextResponse.json({ error: "Invalid Codex recovery request." }, { status: 400 });
  const hostSlug = (body as Record<string, unknown>).host;
  if (typeof hostSlug !== "string" || !/^[a-zA-Z0-9-]{1,80}$/.test(hostSlug)) {
    return NextResponse.json({ error: "A configured host is required." }, { status: 400 });
  }

  const host = findHost(hostSlug);
  if (!host) return NextResponse.json({ error: "The selected host is not in the private fleet inventory." }, { status: 404 });

  const current = await collectHostReport(host);
  if (current.reachable) {
    return NextResponse.json({ error: "The selected host's Codex app-server is already responding." }, { status: 409 });
  }

  const child = spawn("python3", ["scripts/codex_recovery.py"], {
    cwd: process.cwd(),
    stdio: ["pipe", "pipe", "ignore"],
  });
  const chunks: Buffer[] = [];
  let size = 0;
  const result = await new Promise<Record<string, unknown>>((resolve) => {
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      resolve({ type: "error", message: "Codex daemon recovery did not finish before the timeout." });
    }, 70_000);
    child.stdout.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size <= 8_000) chunks.push(chunk);
      else child.kill("SIGTERM");
    });
    child.on("error", () => {
      clearTimeout(timer);
      resolve({ type: "error", message: "Could not start the Codex recovery helper." });
    });
    child.on("close", () => {
      clearTimeout(timer);
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8").trim()) as Record<string, unknown>);
      } catch {
        resolve({ type: "error", message: "Codex daemon recovery returned no valid status." });
      }
    });
    child.stdin.end(JSON.stringify({ host }) + "\n");
  });

  if (result.type === "error") {
    try {
      await appendEvent({ source: "codex-control", host: host.slug, type: "codex.daemon.recovery_failed", stats: { message: result.message } });
    } catch {
      // Recovery status is authoritative; telemetry failure must not hide it.
    }
    return NextResponse.json({ error: result.message ?? "Could not start the Codex daemon." }, { status: 502 });
  }

  const transport = typeof result.transport === "string" ? result.transport : "unknown";
  try {
    await appendEvent({ source: "codex-control", host: host.slug, type: "codex.daemon.start_requested", stats: { transport } });
  } catch {
    // Recovery status is authoritative; telemetry failure must not hide it.
  }
  return NextResponse.json({
    status: "start_requested",
    transport,
    message: typeof result.message === "string" ? result.message : "Codex daemon start requested.",
  }, { headers: { "Cache-Control": "no-store" } });
}
