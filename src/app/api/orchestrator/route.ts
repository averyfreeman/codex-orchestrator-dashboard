import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { NextResponse } from "next/server";
import { sanitizeOpenClawStatus } from "@/lib/orchestrator";

const execFileAsync = promisify(execFile);

/** Return a sanitized projection of local OpenClaw gateway status. */
export async function GET() {
  try {
    const result = await execFileAsync(
      process.env.OPENCLAW_CLI ?? "openclaw",
      ["status", "--json"],
      { timeout: 8_000, maxBuffer: 200_000, encoding: "utf8" },
    );
    return NextResponse.json(sanitizeOpenClawStatus(JSON.parse(result.stdout)), {
      headers: { "Cache-Control": "no-store" },
    });
  } catch {
    return NextResponse.json({
      status: "unavailable",
      gateway: { mode: null, url: null, reachable: false, latencyMs: null },
      agents: [],
      totalSessions: 0,
    }, { headers: { "Cache-Control": "no-store" } });
  }
}
