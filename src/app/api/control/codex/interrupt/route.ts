import { spawn } from "node:child_process";
import { NextResponse } from "next/server";
import { findHost } from "@/lib/collector";
import { isLocalDashboardRequest } from "@/lib/control-security";
import { appendEvent } from "@/lib/logging";

/** Request interruption of one allowlisted host's explicit thread and turn. */
export async function POST(request: Request) {
  if (!isLocalDashboardRequest(request)) {
    return NextResponse.json({ error: "Codex controls are available from the local dashboard only." }, { status: 403 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid interrupt request." }, { status: 400 });
  }
  if (!body || typeof body !== "object") return NextResponse.json({ error: "Invalid interrupt request." }, { status: 400 });
  const value = body as Record<string, unknown>;
  if (typeof value.host !== "string" || typeof value.threadId !== "string" || typeof value.turnId !== "string" || value.threadId.length > 160 || value.turnId.length > 160) {
    return NextResponse.json({ error: "A host, thread, and turn are required." }, { status: 400 });
  }
  const host = findHost(value.host);
  if (!host) return NextResponse.json({ error: "The selected host is not in the private fleet inventory." }, { status: 404 });

  const child = spawn("python3", ["scripts/codex_control.py"], { cwd: process.cwd(), stdio: ["pipe", "pipe", "ignore"] });
  const chunks: Buffer[] = [];
  let size = 0;
  const result = await new Promise<Record<string, unknown>>((resolve) => {
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      resolve({ type: "error", message: "The selected host did not confirm the interrupt request." });
    }, 20_000);
    child.stdout.on("data", (chunk: Buffer) => {
      size += chunk.length;
      if (size <= 16_000) chunks.push(chunk);
      else child.kill("SIGTERM");
    });
    child.on("error", () => {
      clearTimeout(timer);
      resolve({ type: "error", message: "Could not start the Codex control bridge." });
    });
    child.on("close", () => {
      clearTimeout(timer);
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8").trim()) as Record<string, unknown>);
      } catch {
        resolve({ type: "error", message: "The selected host did not confirm the interrupt request." });
      }
    });
    child.stdin.end(JSON.stringify({ mode: "interrupt", host, threadId: value.threadId, turnId: value.turnId }) + "\n");
  });
  if (result.type === "error") return NextResponse.json({ error: result.message }, { status: 502 });
  try {
    await appendEvent({ source: "codex-control", host: host.slug, type: "codex.turn.interrupt_requested", stats: { threadId: value.threadId, turnId: value.turnId, transport: result.transport } });
  } catch {
    // The interrupt result is authoritative; audit storage is best-effort.
  }
  return NextResponse.json({ ...result, message: "Interrupt request acknowledged. The app-server will report the terminal turn status." }, { headers: { "Cache-Control": "no-store" } });
}
