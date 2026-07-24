const API_BASE = "http://localhost:8000";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: string;
}

let inMemoryToken: string | null = null;
let inMemoryRole: string | null = null;

export async function login(username: string, password: string): Promise<LoginResponse> {
  const formData = new URLSearchParams();
  formData.append("username", username);
  formData.append("password", password);

  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(err.detail || "Invalid credentials");
  }

  const data: LoginResponse = await res.json();
  inMemoryToken = data.access_token;
  inMemoryRole = data.role;
  return data;
}

export function logout(): void {
  inMemoryToken = null;
  inMemoryRole = null;
}

export function getToken(): string | null {
  return inMemoryToken;
}

export function getRole(): string | null {
  return inMemoryRole;
}

export function isAuthenticated(): boolean {
  return !!inMemoryToken;
}
