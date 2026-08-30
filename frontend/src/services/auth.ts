import { API_BASE_URL, STORAGE_KEYS } from "@/config";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: string;
}

/**
 * Token storage.
 *
 * localStorage is XSS-exfiltratable and is a known limitation tracked for the
 * cookie migration. It is used here because the token must also be readable to
 * build the WebSocket URL. Do not add new persisted keys without adding them to
 * STORAGE_KEYS so clearSession() stays exhaustive.
 */
function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // Safari private mode and similar
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage unavailable — session lasts for this tab only */
  }
}

export function getToken(): string | null {
  return read(STORAGE_KEYS.token);
}

export function getRole(): string | null {
  return read(STORAGE_KEYS.role);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

export function clearSession(): void {
  for (const key of Object.values(STORAGE_KEYS)) {
    try {
      localStorage.removeItem(key);
    } catch {
      /* nothing to clear */
    }
  }
}

/** POST /auth/login — OAuth2 password flow, form-encoded per the backend. */
export async function login(username: string, password: string): Promise<LoginResponse> {
  const body = new URLSearchParams();
  body.append("username", username);
  body.append("password", password);

  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
    });
  } catch {
    throw new Error("Cannot reach the server. Check your connection and try again.");
  }

  if (res.status === 429) {
    throw new Error("Too many sign-in attempts. Wait a minute and try again.");
  }

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new Error(payload?.detail || "Incorrect username or password.");
  }

  const data = (await res.json()) as LoginResponse;
  write(STORAGE_KEYS.token, data.access_token);
  write(STORAGE_KEYS.role, data.role);
  return data;
}

/**
 * The backend issues stateless JWTs with no revocation, so signing out can only
 * discard the local copy. The token stays valid server-side until it expires.
 */
export function logout(): void {
  clearSession();
}
