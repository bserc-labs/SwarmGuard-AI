import { getToken, logout } from "./auth";

const API_BASE = "/api";

function getAuthHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function fetchWithAuth<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      ...getAuthHeaders(),
      ...options?.headers,
    },
  });

  if (res.status === 401) {
    logout();
    window.location.href = "/login";
    throw new Error("Unauthorized");
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || `HTTP ${res.status}`);
  }

  return res.json();
}

// === API Methods ===

export interface TelemetryPacket {
  drone_id: string;
  latitude: number;
  longitude: number;
  altitude: number;
  speed: number;
  battery: number;
  packet_sequence: number;
}

export interface Incident {
  id: number;
  drone_id: string;
  attack_type: string;
  threat_level: number;
  severity: string;
  shap_values: Array<{ feature: string; value: number }> | null;
  explanation: string;
  created_at: string;
  status: string;
}

export interface DetectionResult {
  is_anomaly: boolean;
  anomaly_score: number;
  drone_id?: string;
  attack_type: string | null;
  threat_level: number | null;
  severity: string | null;
  shap_top3: Array<{ feature: string; value: number }> | null;
  explanation: string | null;
}

export interface UserInfo {
  id: number;
  username: string;
  email: string | null;
  role: string;
  created_at: string;
}

export interface HealthResponse {
  status: string;
  service: string;
}

export interface Drone {
  id: number;
  drone_id: string;
  status: string;
  last_seen: string;
  last_command: string | null;
}

export interface DroneCommand {
  id: number;
  drone_id: string;
  command_type: string;
  reason: string | null;
  issued_by: string;
  status: string;
  created_at: string;
}

export interface SystemSettings {
  critical_threshold: number;
  high_threshold: number;
  refresh_rate: string;
  ui_sound: boolean;
  push_notif: boolean;
  webhooks: boolean;
}

export const api = {
  getHealth: (): Promise<HealthResponse> =>
    fetch(`${API_BASE}/health`).then((r) => r.json()),

  getTelemetryLive: (): Promise<TelemetryPacket[]> =>
    fetchWithAuth("/telemetry/live"),

  getIncidents: (severity?: string, limit = 50): Promise<Incident[]> => {
    const params = new URLSearchParams();
    if (severity) params.set("severity", severity);
    params.set("limit", String(limit));
    return fetchWithAuth(`/incidents/?${params.toString()}`);
  },

  getIncident: (id: number): Promise<Incident> =>
    fetchWithAuth(`/incidents/${id}`),

  getMe: (): Promise<UserInfo> =>
    fetchWithAuth("/users/me"),

  updateMe: (payload: { email?: string }): Promise<UserInfo> =>
    fetch(`${API_BASE}/users/me`, {
      method: "PATCH",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }).then(async (res) => {
      if (res.status === 401) {
        logout();
        window.location.href = "/login";
        throw new Error("Unauthorized");
      }

      if (res.status === 404 || res.status === 405) {
        throw new Error("PROFILE_UPDATE_UNSUPPORTED");
      }

      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: "Request failed" }));
        throw new Error(error.detail || `HTTP ${res.status}`);
      }

      return res.json();
    }),

  getDrones: (): Promise<Drone[]> =>
    fetchWithAuth("/drones"),

  issueCommand: (droneId: string, commandType: string, reason?: string): Promise<DroneCommand> =>
    fetchWithAuth(`/drones/${droneId}/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command_type: commandType, reason }),
    }),

  getDroneCommands: (droneId: string): Promise<DroneCommand[]> =>
    fetchWithAuth(`/drones/${droneId}/commands`),

  checkHeartbeats: (): Promise<{ status: string; silent_drones_detected: number }> =>
    fetchWithAuth("/drones/check-heartbeats", { method: "POST" }),

  updateIncidentStatus: (id: number, status: string): Promise<Incident> =>
    fetchWithAuth(`/incidents/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status }),
    }),

  changePassword: (currentPassword: string, newPassword: string): Promise<{ message: string }> =>
    fetchWithAuth("/users/me/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

  getSettings: (): Promise<SystemSettings> =>
    fetchWithAuth("/settings"),

  updateSettings: (payload: Partial<SystemSettings>): Promise<SystemSettings> =>
    fetchWithAuth("/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  getSwarmFormation: (): Promise<{
    formation_type: string;
    confidence: number;
    active_swarm_count: number;
    cluster_drone_ids: string[];
    centroid: { lat: number; lng: number } | null;
    formation_lines: number[][][];
    description: string;
  }> => fetchWithAuth("/telemetry/swarm-formation"),

  getGeofences: (): Promise<any[]> => fetchWithAuth("/geofence/zones"),
  
  getTelemetryHistory: (startTime: string, endTime: string): Promise<TelemetryPacket[]> => {
    const params = new URLSearchParams();
    params.set("start_time", startTime);
    params.set("end_time", endTime);
    return fetchWithAuth(`/telemetry/history?${params.toString()}`);
  },

  createGeofence: (payload: {
    name: string;
    zone_type: string;
    coordinates: any;
    severity?: string;
  }): Promise<any> =>
    fetchWithAuth("/geofence/zones", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
};

