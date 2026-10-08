import { describe, expect, it } from "vitest";
import { unavailableReport, type HostDefinition } from "@/lib/hosts";
import { isLogEvent } from "@/lib/logging";

const nodeA: HostDefinition = {
  slug: "node-a",
  name: "Node A",
  os: "Linux",
  localIp: null,
  tailscaleIp: null,
  zerotierIp: null,
  sshRoutes: [
    { transport: "zerotier", target: "operator@node-a.example.test", hostKeyAlias: "fleet-node-a" },
    { transport: "tailscale", target: "operator@node-a.example.test", hostKeyAlias: "fleet-node-a" },
  ],
};

describe("fleet metadata", () => {
  it("keeps the first configured route as the preferred route", () => {
    expect(nodeA.sshRoutes?.map((route) => route.transport)).toEqual(["zerotier", "tailscale"]);
    expect(unavailableReport(nodeA).connection.transport).toBe("unavailable");
  });

  it("accepts bounded structured telemetry and rejects malformed events", () => {
    expect(isLogEvent({ source: "collector", host: "node-a", type: "snapshot", stats: { cpu: 2.1 } })).toBe(true);
    expect(isLogEvent({ source: "", host: "node-a", type: "snapshot" })).toBe(false);
    expect(isLogEvent({ source: "collector", host: "node-a", type: "snapshot", stats: [] })).toBe(false);
    expect(isLogEvent(null)).toBe(false);
  });
});
