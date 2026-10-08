import { spawn } from "node:child_process";
import { NextResponse } from "next/server";
import { findHost } from "@/lib/collector";
import { isLocalDashboardRequest } from "@/lib/control-security";
import { appendEvent } from "@/lib/logging";

type HerdrAction = "list" | "start" | "stop";

async function runHerdr(host: NonNullable<ReturnType<typeof findHost>>, action: HerdrAction, name?: string) {
  const child = spawn("python3", ["scripts/herdr_sessions.py"], { cwd: process.cwd(), stdio: ["pipe", "pipe", "ignore"] });
  const chunks: Buffer[] = [];
  let size = 0;
  return new Promise<Record<string, unknown>>((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error("Herdr did not return a session status in time."));
    }, 45_000);
    child.stdout.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size <= 64_000) chunks.push(chunk);
      else child.kill("SIGTERM");
    });
    child.on("error", () => {
      clearTimeout(timer);
      reject(new Error("Could not start the Herdr control bridge."));
    });
    child.on("close", () => {
      clearTimeout(timer);
      try {
        const result = JSON.parse(Buffer.concat(chunks).toString("utf8").trim()) as Record<string, unknown>;
        if (result.ok !== true) reject(new Error(typeof result.error === "string" ? result.error : "Herdr session operation failed."));
        else resolve(result);
      } catch {
        reject(new Error("Herdr did not return a valid session response."));
      }
    });
    child.stdin.end(JSON.stringify({ action, host, ...(name ? { name } : {}) }) + "\n");
  });
}

/** List named Herdr sessions on one host from the private fleet allowlist. */
export async function GET(request: Request) {
  if (!isLocalDashboardRequest(request)) {
    return NextResponse.json({ error: "Herdr sessions are available from the local dashboard only." }, { status: 403 });
  }
  const slug = new URL(request.url).searchParams.get("host");
  const host = slug ? findHost(slug) : undefined;
  if (!host) return NextResponse.json({ error: "Select a host from the private fleet inventory." }, { status: 404 });
  try {
    const result = await runHerdr(host, "list");
    return NextResponse.json({ sessions: result.sessions, transport: result.transport }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Herdr session list failed." }, { status: 502 });
  }
}

/** Start or stop one validated named Herdr session on the selected host. */
export async function POST(request: Request) {
  if (!isLocalDashboardRequest(request)) {
    return NextResponse.json({ error: "Herdr controls are available from the local dashboard only." }, { status: 403 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid Herdr session request." }, { status: 400 });
  }
  if (!body || typeof body !== "object") return NextResponse.json({ error: "Invalid Herdr session request." }, { status: 400 });
  const value = body as Record<string, unknown>;
  if (typeof value.host !== "string" || !/^[a-zA-Z0-9-]{1,80}$/.test(value.host) || (value.action !== "start" && value.action !== "stop") || typeof value.name !== "string" || !/^[a-z][a-z0-9_-]{0,31}$/.test(value.name) || value.name === "default") {
    return NextResponse.json({ error: "Use a named Herdr session; the default session is protected." }, { status: 400 });
  }
  const host = findHost(value.host);
  if (!host) return NextResponse.json({ error: "The selected host is not in the private fleet inventory." }, { status: 404 });
  try {
    const result = await runHerdr(host, value.action, value.name);
    try {
      if (!result.alreadyRunning && !result.alreadyStopped) {
        await appendEvent({
          source: "herdr-control",
          host: host.slug,
          type: `herdr.session.${value.action}`,
          stats: { name: value.name, state: result.state, transport: result.transport },
        });
      }
    } catch {
      // An audit write failure must not change the named-session result.
    }
    return NextResponse.json(result, { status: result.state === "starting" || result.state === "stopping" ? 202 : 200, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Herdr session action failed." }, { status: 502 });
  }
}
