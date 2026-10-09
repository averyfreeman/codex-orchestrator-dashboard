import { NextResponse } from "next/server";
import { CodexSyncError, startCodexSyncApply } from "@/lib/codex-sync";
import { isLocalDashboardRequest } from "@/lib/control-security";

/** Start applying a reviewed, unexpired Codex sync plan. */
export async function POST(request: Request) {
  if (!isLocalDashboardRequest(request)) {
    return NextResponse.json({ error: "Codex sync is available from the local dashboard only." }, { status: 403 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid Codex sync apply request." }, { status: 400 });
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return NextResponse.json({ error: "Invalid Codex sync apply request." }, { status: 400 });
  }
  const input = body as Record<string, unknown>;
  if (typeof input.planId !== "string" || !/^[a-f0-9-]{36}$/.test(input.planId) || typeof input.restartWhenFinished !== "boolean") {
    return NextResponse.json({ error: "A valid plan ID and restart preference are required." }, { status: 400 });
  }
  try {
    const result = await startCodexSyncApply(input.planId, input.restartWhenFinished);
    return NextResponse.json(result, { status: 202, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof CodexSyncError) return NextResponse.json({ error: error.message }, { status: error.status });
    return NextResponse.json({ error: "Could not start the Codex sync run." }, { status: 502 });
  }
}
