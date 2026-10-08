import { describe, expect, it } from "vitest";
import { isLocalDashboardRequest } from "@/lib/control-security";

describe("local dashboard control origin", () => {
  it("accepts same-origin loopback requests", () => {
    expect(isLocalDashboardRequest(new Request("http://localhost:3000/api/control", {
      method: "POST",
      headers: { host: "localhost:3000", origin: "http://localhost:3000" },
    }))).toBe(true);
  });

  it("rejects missing, cross-origin, and non-loopback origins", () => {
    expect(isLocalDashboardRequest(new Request("http://localhost:3000/api/control", { method: "POST" }))).toBe(false);
    expect(isLocalDashboardRequest(new Request("http://localhost:3000/api/control", {
      method: "POST",
      headers: { host: "localhost:3000", origin: "https://attacker.example" },
    }))).toBe(false);
    expect(isLocalDashboardRequest(new Request("http://dashboard.example.test:3000/api/control", {
      method: "POST",
      headers: { host: "dashboard.example.test:3000", origin: "http://dashboard.example.test:3000" },
    }))).toBe(false);
  });
});
