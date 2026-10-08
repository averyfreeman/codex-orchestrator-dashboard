import { connection, NextRequest, NextResponse } from "next/server";
import { appendEvent, isLogEvent, readRecentEvents } from "@/lib/logging";

/** Return the bounded recent window of private local telemetry events. */
export async function GET() {
  await connection();
  return NextResponse.json({ events: await readRecentEvents() }, {
    headers: { "Cache-Control": "no-store" },
  });
}

/** Validate and append one bounded event using the configured bearer token. */
export async function POST(request: NextRequest) {
  const token = process.env.LOG_INGEST_TOKEN;
  if (!token) return NextResponse.json({ error: "Log ingestion is not configured" }, { status: 503 });
  if (request.headers.get("authorization") !== `Bearer ${token}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  const raw = await request.text();
  if (raw.length > 10_000) return NextResponse.json({ error: "Event too large" }, { status: 413 });
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }
  if (!isLogEvent(value)) return NextResponse.json({ error: "Invalid event shape" }, { status: 400 });
  await appendEvent(value);
  return NextResponse.json({ accepted: true }, { status: 202 });
}
