function isLoopback(hostname: string) {
  const normalized = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "::1";
}

/** CSRF guard for the loopback-only deployment; this is not network authentication. */
/** Check same-origin loopback requests for CSRF defense; this does not authenticate users. */
export function isLocalDashboardRequest(request: Request) {
  const origin = request.headers.get("origin");
  const host = request.headers.get("host");
  if (!origin || !host) return false;
  try {
    const originUrl = new URL(origin);
    const hostUrl = new URL(`${originUrl.protocol}//${host}`);
    return originUrl.host === hostUrl.host && isLoopback(originUrl.hostname) && isLoopback(hostUrl.hostname);
  } catch {
    return false;
  }
}
