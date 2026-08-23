/**
 * Single source of truth for backend endpoints.
 *
 * Previously auth.ts hardcoded http://localhost:8000 while api.ts used the
 * relative /api proxy, so authentication broke on any real hostname. Both now
 * read from here, and here reads from the environment.
 *
 * Defaults target the nginx reverse proxy defined in frontend/nginx.conf, which
 * serves the app and proxies /api and /ws to the backend on the same origin.
 */

function readEnv(key: string): string | undefined {
  const value = (import.meta.env as Record<string, string | undefined>)[key];
  return value && value.trim() !== "" ? value.trim() : undefined;
}

/** Strip trailing slashes so path joins never produce a double slash. */
function normalizeBase(value: string): string {
  return value.replace(/\/+$/, "");
}

/** REST base path. Same-origin by default; override for split deployments. */
export const API_BASE_URL = normalizeBase(readEnv("VITE_API_BASE_URL") ?? "/api");

/**
 * WebSocket origin. When unset we derive it from the page origin so the app
 * works on localhost, a LAN address, and a TLS domain without reconfiguration.
 */
export function resolveWebSocketBase(): string {
  const configured = readEnv("VITE_WS_BASE_URL");
  if (configured) return normalizeBase(configured);

  if (typeof window === "undefined") return "";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}`;
}

/** Full URL of the telemetry socket, excluding the token query parameter. */
export function telemetrySocketUrl(): string {
  return `${resolveWebSocketBase()}/ws/telemetry`;
}

/** Storage keys, centralised so logout cannot miss one. */
export const STORAGE_KEYS = {
  token: "swarmguard_token",
  role: "swarmguard_role",
} as const;

/** How long telemetry may go without an update before the UI calls it stale. */
export const TELEMETRY_STALE_AFTER_MS = 15_000;

/** Poll intervals, in one place so they can be tuned coherently. */
export const POLL_INTERVALS = {
  incidents: 15_000,
  fleet: 15_000,
  health: 20_000,
  stats: 30_000,
} as const;
