export type OpenClawReport = {
  status: "available" | "unavailable";
  gateway: {
    mode: string | null;
    url: string | null;
    reachable: boolean;
    latencyMs: number | null;
  };
  agents: Array<{ id: string; sessions: number }>;
  totalSessions: number;
};

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function sanitizeOpenClawStatus(value: unknown): OpenClawReport {
  const root = record(value);
  const gateway = record(root.gateway);
  const agentState = record(root.agents);
  const rawAgents = Array.isArray(agentState.agents) ? agentState.agents : [];
  const agents = rawAgents.flatMap((item) => {
    const agent = record(item);
    if (typeof agent.id !== "string") return [];
    return [{
      id: agent.id.slice(0, 80),
      sessions: typeof agent.sessionsCount === "number" && Number.isFinite(agent.sessionsCount)
        ? Math.max(0, agent.sessionsCount)
        : 0,
    }];
  });

  return {
    status: typeof gateway.reachable === "boolean" ? "available" : "unavailable",
    gateway: {
      mode: typeof gateway.mode === "string" ? gateway.mode : null,
      url: typeof gateway.url === "string" ? gateway.url : null,
      reachable: gateway.reachable === true,
      latencyMs: typeof gateway.connectLatencyMs === "number" && Number.isFinite(gateway.connectLatencyMs)
        ? Math.max(0, gateway.connectLatencyMs)
        : null,
    },
    agents,
    totalSessions: typeof agentState.totalSessions === "number" && Number.isFinite(agentState.totalSessions)
      ? Math.max(0, agentState.totalSessions)
      : agents.reduce((sum, agent) => sum + agent.sessions, 0),
  };
}
