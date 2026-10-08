import { connection, NextResponse } from "next/server";
import { collectOverview } from "@/lib/collector";
import { appendSnapshot } from "@/lib/logging";

export async function GET() {
  await connection();
  const hosts = await collectOverview();
  await appendSnapshot(hosts);
  return NextResponse.json({ checkedAt: new Date().toISOString(), hosts }, {
    headers: { "Cache-Control": "no-store" },
  });
}
