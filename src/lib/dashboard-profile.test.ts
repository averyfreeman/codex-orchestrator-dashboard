import { afterEach, describe, expect, it } from "vitest";
import { mkdtemp, readFile, rm, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { readDashboardProfile, setDashboardNetworkAccess } from "@/lib/dashboard-profile";

const originalStateDir = process.env.DASHBOARD_STATE_DIR;
let testDirectory = "";

afterEach(async () => {
  if (originalStateDir === undefined) delete process.env.DASHBOARD_STATE_DIR;
  else process.env.DASHBOARD_STATE_DIR = originalStateDir;
  if (testDirectory) await rm(testDirectory, { recursive: true, force: true });
  testDirectory = "";
});

async function useTemporaryState() {
  testDirectory = await mkdtemp(path.join(os.tmpdir(), "codex-dashboard-profile-"));
  process.env.DASHBOARD_STATE_DIR = testDirectory;
}

describe("dashboard-managed Codex profile", () => {
  it("starts with network access enabled", async () => {
    await useTemporaryState();
    await expect(readDashboardProfile()).resolves.toMatchObject({ id: "dashboard-default", networkAccess: true });
  });

  it("persists the network switch privately for subsequent turns", async () => {
    await useTemporaryState();
    const profile = await setDashboardNetworkAccess(false);
    expect(profile.networkAccess).toBe(false);
    await expect(readDashboardProfile()).resolves.toMatchObject({ networkAccess: false });
    const file = path.join(testDirectory, "profiles.json");
    expect((await stat(file)).mode & 0o777).toBe(0o600);
    expect(JSON.parse(await readFile(file, "utf8"))).toMatchObject({ name: "Dashboard default", networkAccess: false });
  });
});
