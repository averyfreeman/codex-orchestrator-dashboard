import { chmod, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";

/** Local profile state applied to new dashboard-managed Codex turns. */
export type DashboardProfile = {
  id: "dashboard-default";
  name: "Dashboard default";
  networkAccess: boolean;
};

const DEFAULT_PROFILE: DashboardProfile = {
  id: "dashboard-default",
  name: "Dashboard default",
  networkAccess: true,
};

let updateQueue: Promise<unknown> = Promise.resolve();

function statePath() {
  const directory = process.env.DASHBOARD_STATE_DIR
    ? path.resolve(process.env.DASHBOARD_STATE_DIR)
    : path.join(process.cwd(), ".dashboard-state");
  return { directory, file: path.join(directory, "profiles.json") };
}

/** Read the owner-only local profile, falling back to the network-enabled default. */
export async function readDashboardProfile(): Promise<DashboardProfile> {
  const { file } = statePath();
  try {
    const value: unknown = JSON.parse(await readFile(/*turbopackIgnore: true*/ file, "utf8"));
    if (value && typeof value === "object" && typeof (value as Record<string, unknown>).networkAccess === "boolean") {
      return { ...DEFAULT_PROFILE, networkAccess: (value as Record<string, boolean>).networkAccess };
    }
  } catch {
    // First run or malformed private state: restore the documented safe default.
  }
  return { ...DEFAULT_PROFILE };
}

/** Atomically persist the profile's command-network and web-search setting. */
export function setDashboardNetworkAccess(networkAccess: boolean): Promise<DashboardProfile> {
  const update = updateQueue.then(async () => {
    const { directory, file } = statePath();
    await mkdir(directory, { recursive: true, mode: 0o700 });
    await chmod(directory, 0o700);
    const profile = { ...DEFAULT_PROFILE, networkAccess };
    const temporary = `${file}.${process.pid}.${Date.now()}.tmp`;
    await writeFile(/*turbopackIgnore: true*/ temporary, `${JSON.stringify(profile, null, 2)}\n`, { mode: 0o600 });
    await chmod(temporary, 0o600);
    await rename(/*turbopackIgnore: true*/ temporary, /*turbopackIgnore: true*/ file);
    await chmod(file, 0o600);
    return profile;
  });
  updateQueue = update.catch(() => undefined);
  return update;
}
