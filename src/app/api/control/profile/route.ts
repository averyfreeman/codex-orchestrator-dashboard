import { NextResponse } from "next/server";
import { isLocalDashboardRequest } from "@/lib/control-security";
import { readDashboardProfile, setDashboardNetworkAccess } from "@/lib/dashboard-profile";

/** Return the current local dashboard-managed profile. */
export async function GET() {
  return NextResponse.json(await readDashboardProfile(), {
    headers: { "Cache-Control": "no-store" },
  });
}

/** Persist the profile network switch for command networking and web search. */
export async function PUT(request: Request) {
  if (!isLocalDashboardRequest(request)) {
    return NextResponse.json({ error: "Profile changes are available from the local dashboard only." }, { status: 403 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid profile update." }, { status: 400 });
  }
  if (!body || typeof body !== "object" || typeof (body as Record<string, unknown>).networkAccess !== "boolean") {
    return NextResponse.json({ error: "networkAccess must be true or false." }, { status: 400 });
  }
  const profile = await setDashboardNetworkAccess((body as Record<string, boolean>).networkAccess);
  return NextResponse.json(profile, { headers: { "Cache-Control": "no-store" } });
}
