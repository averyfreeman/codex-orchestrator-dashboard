import { describe, expect, it } from "vitest";
import { sanitizeOpenClawStatus } from "@/lib/orchestrator";

describe("OpenClaw status projection", () => {
  it("keeps gateway and aggregate session metadata while dropping private paths and auth fields", () => {
    const report = sanitizeOpenClawStatus({
      gateway: { mode: "local", url: "ws://127.0.0.1:18789", reachable: true, connectLatencyMs: 1162, authWarning: "private" },
      agents: {
        totalSessions: 3,
        agents: [{ id: "main", sessionsCount: 3, sessionsPath: "/private/session.jsonl", token: "secret" }],
      },
      token: "secret",
    });

    expect(report).toEqual({
      status: "available",
      gateway: { mode: "local", url: "ws://127.0.0.1:18789", reachable: true, latencyMs: 1162 },
      agents: [{ id: "main", sessions: 3 }],
      totalSessions: 3,
    });
    expect(JSON.stringify(report)).not.toContain("private");
    expect(JSON.stringify(report)).not.toContain("secret");
  });

  it("returns a bounded unavailable report for malformed status", () => {
    expect(sanitizeOpenClawStatus(null).status).toBe("unavailable");
  });
});
