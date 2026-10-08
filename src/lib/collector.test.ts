import { describe, expect, it } from "vitest";
import { sshWithFailover } from "@/lib/collector";
import type { SshRoute } from "@/lib/hosts";

const routes: SshRoute[] = [
  { transport: "zerotier", target: "operator@node-a.example.test", hostKeyAlias: "fleet-node-a" },
  { transport: "tailscale", target: "operator@node-a.example.test", hostKeyAlias: "fleet-node-a" },
];

describe("SSH route failover", () => {
  it("starts with ZeroTier and returns the route that answered", async () => {
    const tried: string[] = [];
    const result = await sshWithFailover(routes, async (route) => {
      tried.push(route.transport);
      if (route.transport === "zerotier") throw new Error("connection timed out");
      return "ok";
    });

    expect(tried).toEqual(["zerotier", "tailscale"]);
    expect(result.route.transport).toBe("tailscale");
    expect(result.result).toBe("ok");
  });

  it("reports errors after every route fails", async () => {
    await expect(sshWithFailover(routes, async (route) => {
      throw new Error(`${route.transport} unavailable`);
    })).rejects.toThrow("zerotier: zerotier unavailable; tailscale: tailscale unavailable");
  });
});
