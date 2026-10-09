import { NextResponse } from "next/server";
import { CodexSyncError, createCodexSyncPlan } from "@/lib/codex-sync";
import { isLocalDashboardRequest } from "@/lib/control-security";

/** Inspect the selected reference host and build a short-lived review plan. */
export async function POST(request: Request) {
  if (!isLocalDashboardRequest(request)) {
    return NextResponse.json({ error: "Codex sync is available from the local dashboard only." }, { status: 403 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid Codex sync plan request." }, { status: 400 });
  }
  if (!body || typeof body !== "object" || Array.isArray(body)) {
    return NextResponse.json({ error: "Invalid Codex sync plan request." }, { status: 400 });
  }
  const input = body as Record<string, unknown>;
  if (typeof input.sourceHostSlug !== "string" || !/^[A-Za-z0-9-]{1,80}$/.test(input.sourceHostSlug)) {
    return NextResponse.json({ error: "A configured source host is required." }, { status: 400 });
  }
  if (input.targetHostSlugs !== undefined && (!Array.isArray(input.targetHostSlugs) || input.targetHostSlugs.length > 20 || input.targetHostSlugs.some((slug) => typeof slug !== "string"))) {
    return NextResponse.json({ error: "Target host slugs must be an array of configured hosts." }, { status: 400 });
  }
  try {
    const plan = await createCodexSyncPlan({
      sourceHostSlug: input.sourceHostSlug,
      targetHostSlugs: input.targetHostSlugs as string[] | undefined,
    });
    return NextResponse.json(plan, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (error instanceof CodexSyncError) return NextResponse.json({ error: error.message }, { status: error.status });
    return NextResponse.json({ error: "Could not inspect Codex hosts for a sync plan." }, { status: 502 });
  }
}
