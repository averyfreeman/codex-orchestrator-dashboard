import { afterEach, describe, expect, it } from "vitest";
import { assertPlanSnapshotHash, CodexSyncError, createCodexSyncPlan, makeActionsAndView, startCodexSyncApply } from "@/lib/codex-sync";
import { HOSTS, type HostDefinition } from "@/lib/hosts";

const originalHosts = [...HOSTS];
const fixtures: HostDefinition[] = [
  { slug: "reference", name: "Reference", os: "macOS", localIp: null, tailscaleIp: null, zerotierIp: null, local: true },
  { slug: "peer", name: "Peer", os: "Linux", localIp: null, tailscaleIp: null, zerotierIp: null, sshRoutes: [] },
];

afterEach(() => {
  HOSTS.splice(0, HOSTS.length, ...originalHosts);
});

describe("Codex sync request validation", () => {
  it("requires an inventory source and rejects a source selected as its own target", async () => {
    HOSTS.splice(0, HOSTS.length, ...fixtures);
    await expect(createCodexSyncPlan({ sourceHostSlug: "missing" })).rejects.toMatchObject({ status: 404 });
    await expect(createCodexSyncPlan({ sourceHostSlug: "reference", targetHostSlugs: ["reference"] })).rejects.toMatchObject({ status: 400 });
  });

  it("rejects targets outside the configured host inventory", async () => {
    HOSTS.splice(0, HOSTS.length, ...fixtures);
    await expect(createCodexSyncPlan({ sourceHostSlug: "reference", targetHostSlugs: ["unknown"] })).rejects.toMatchObject({ status: 404 });
  });

  it("rejects a missing or stale apply plan", async () => {
    await expect(startCodexSyncApply("not-a-plan", false)).rejects.toBeInstanceOf(CodexSyncError);
    expect(() => assertPlanSnapshotHash("reviewed-hash", "changed-hash")).toThrowError(CodexSyncError);
    expect(() => assertPlanSnapshotHash("same-hash", "same-hash")).not.toThrow();
  });
});

describe("Codex-managed marketplace plugin planning", () => {
  const marketplace: { name: string; kind: string; source: string | null; ref: string | null; sparsePaths: string[]; root: string | null } = { name: "openai-curated-remote", kind: "managed", source: null, ref: null, sparsePaths: [], root: null };
  const plugin: { name: string; marketplaceName: string; enabled: boolean; marketplaceKind: string; selector: string; version: string } = { name: "fixture-plugin", marketplaceName: marketplace.name, enabled: true, marketplaceKind: "managed", selector: `fixture-plugin@${marketplace.name}`, version: "1.2.3" };

  function snapshot(marketplaces: Array<typeof marketplace>, plugins: Array<typeof plugin>) {
    const base = {
      cliVersion: "0.161.0",
      runtimeVersion: "0.162.0",
      runtimeStatus: "running",
      activeTurns: { count: 0, known: true },
      codexHome: { configured: true, label: "~/.codex", source: "environment/default" },
      config: { files: [{ name: "config.toml", exists: true, hash: "same", portable: {}, unclassified: {}, invalid: false }], profileNames: [], hash: "same" },
      plugins: { available: true, marketplaces, plugins, localPackages: {}, hash: "plugins" },
      skills: { skills: {}, blocked: [], hash: "skills" },
      snapshotHash: "snapshot",
    };
    return {
      ...base,
      public: {
        cliVersion: base.cliVersion,
        runtimeVersion: base.runtimeVersion,
        runtimeStatus: base.runtimeStatus,
        activeTurns: base.activeTurns,
        codexHome: base.codexHome,
        config: { files: [], profileNames: [] },
        plugins: { available: true, marketplaces, plugins },
        skills: { names: [], blocked: [] },
        snapshotHash: base.snapshotHash,
      },
    };
  }

  it("installs enabled OpenAI marketplace plugins with Codex commands without copying marketplace caches", () => {
    const planned = makeActionsAndView(fixtures[1], snapshot([marketplace], [plugin]), snapshot([], []), true);
    expect(planned.actions.plugins.marketplaces).toEqual([]);
    expect(planned.actions.plugins.localPackages).toEqual({});
    expect(planned.actions.plugins.add).toEqual([{ name: plugin.name, marketplaceName: marketplace.name }]);
    expect(planned.view.categories.plugins).toMatchObject({ status: "drift", changes: 1, blocked: 0 });
  });

  it("keeps an already-enabled managed marketplace plugin in sync on repeat runs", () => {
    const inventory = snapshot([marketplace], [plugin]);
    const planned = makeActionsAndView(fixtures[1], inventory, inventory, true);
    expect(planned.actions.plugins.add).toEqual([]);
    expect(planned.actions.plugins.remove).toEqual([]);
    expect(planned.actions.plugins.marketplaces).toEqual([]);
    expect(planned.view.categories.plugins).toMatchObject({ status: "in-sync", changes: 0, blocked: 0 });
  });

  it("reinstalls a present but disabled plugin to restore the reference enabled state", () => {
    const disabled = { ...plugin, enabled: false };
    const planned = makeActionsAndView(fixtures[1], snapshot([marketplace], [plugin]), snapshot([marketplace], [disabled]), true);
    expect(planned.actions.plugins.remove).toEqual([{ name: plugin.name, marketplaceName: marketplace.name }]);
    expect(planned.actions.plugins.add).toEqual([{ name: plugin.name, marketplaceName: marketplace.name }]);
  });

  it("blocks a managed plugin when the target has a same-named custom marketplace", () => {
    const customMarketplace = { ...marketplace, kind: "local", root: "/tmp/custom-marketplace" };
    const planned = makeActionsAndView(fixtures[1], snapshot([marketplace], [plugin]), snapshot([customMarketplace], []), true);
    expect(planned.actions.plugins.add).toEqual([]);
    expect(planned.view.blockedItems).toContain(`${plugin.selector}: a same-named non-Codex marketplace exists on the target; the plugin was left unchanged.`);
  });
});
