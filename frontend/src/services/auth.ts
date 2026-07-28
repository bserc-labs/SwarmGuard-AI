const API_BASE = "http://localhost:8000";

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: string;
}

let inMemoryToken: string | null = localStorage.getItem("swarmguard_token");
let inMemoryRole: string | null = localStorage.getItem("swarmguard_role");

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
  localStorage.setItem("swarmguard_token", data.access_token);
  localStorage.setItem("swarmguard_role", data.role);
  return data;
}

export function logout(): void {
  inMemoryToken = null;
  inMemoryRole = null;
  localStorage.removeItem("swarmguard_token");
  localStorage.removeItem("swarmguard_role");
}

export function getToken(): string | null {
  return inMemoryToken || localStorage.getItem("swarmguard_token");
}

export function getRole(): string | null {
  return inMemoryRole || localStorage.getItem("swarmguard_role");
}

export function isAuthenticated(): boolean {
  return !!getToken();
}
