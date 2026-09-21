/**
 * API client.
 *
 * Every method below maps to a route that exists in the FastAPI application.
 * Four previously-declared methods were removed because the backend has no such
 * route and they returned 404 at runtime:
 *
 *   getTelemetryLive()      GET  /telemetry/live            -> use /telemetry/latest
 *   getSwarmFormation()     GET  /telemetry/swarm-formation -> no equivalent
 *   checkHeartbeats()       POST /drones/check-heartbeats   -> server-side task only
 *   updateIncidentStatus()  PATCH /incidents/{id}           -> use the transition routes
 *
 * Response shapes mirror backend/schemas.py. Where the backend types a field as
 * `list[dict]`, it is typed loosely here and narrowed at the point of use rather
 * than asserted, because the payload contents are not guaranteed.
 */

import { API_BASE_URL } from "@/config";
import { getToken, logout } from "./auth";

/* ------------------------------------------------------------------ errors */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** The caller lacks the permission this route requires. */
  get isForbidden(): boolean {
    return this.status === 403;
  }

  /** The route or record does not exist. */
  get isNotFound(): boolean {
    return this.status === 404;
  }

  /** The server could not be reached at all. */
  get isNetwork(): boolean {
    return this.status === 0;
  }
}

/* ---------------------------------------------------------------- transport */

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let res: Response;

  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: { ...authHeaders(), ...options?.headers },
    });
  } catch {
    throw new ApiError("Cannot reach the server.", 0);
  }

  if (res.status === 401) {
    // The token is absent, expired, or was signed with a rotated key.
    logout();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.assign("/login");
    }
    throw new ApiError("Your session has ended. Sign in again.", 401);
  }

  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    throw new ApiError(payload?.detail || `Request failed (${res.status})`, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

function jsonBody(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

/* ------------------------------------------------------------------- types */

/** POST /telemetry/ingest body and the shape broadcast over the socket. */
export interface TelemetryPacket {
  drone_id: string;
  latitude: number;
  longitude: number;
  altitude: number;
  speed: number;
  heading?: number | null;
  battery: number;
  flight_mode?: string | null;
  armed_status?: boolean | null;
  satellites?: number | null;
  packet_sequence: number;
  /** Device sample clock in ms (MAVLink time_boot_ms). Absent when the source does not report one. */
  sample_time_ms?: number | null;
}

/** Rows from GET /telemetry/* also carry storage metadata. */
export interface TelemetryRecord extends TelemetryPacket {
  id?: number;
  organization_id?: number | null;
  created_at?: string;
}

/**
 * Feature attribution entry. The backend types shap_values as list[dict] and
 * three producers disagree on the magnitude key, so all are optional and
 * `attributionMagnitude()` picks whichever is present.
 *
 *   kinematic_guard   feature, shap_value, magnitude, observed, threshold, unit
 *   explainability    feature, shap_value, magnitude
 *   heartbeat / ws    feature, importance
 *
 * The trailing three fields are unique to Tier 1: because the guard is
 * deterministic, it can report the number it measured and the limit it crossed,
 * which SHAP over a learned model cannot.
 */
export interface FeatureAttribution {
  feature?: string;
  importance?: number;
  magnitude?: number;
  shap_value?: number;
  value?: number;
  /** Measured value that tripped the check. Tier 1 only. */
  observed?: number;
  /** Limit it was measured against. Tier 1 only. */
  threshold?: number;
  /** Unit for observed and threshold, e.g. "m/s". Tier 1 only. */
  unit?: string;
}

export interface ExplanationSummary {
  primary_cause?: string;
  secondary_cause?: string;
  supporting_indicators?: string[];
  recommended_action?: string;
  model_version?: string;
  explanation_strength?: number;
}

/** Mirrors schemas.IncidentOut. */
export interface Incident {
  id: number;
  drone_id: string;
  organization_id?: number | null;
  mission_id?: string | null;
  attack_type: string;
  threat_score: number;
  anomaly_score: number;
  threat_level: number;
  severity: string;
  priority: number;
  shap_values: FeatureAttribution[] | null;
  explanation: string;
  explanation_summary?: ExplanationSummary | null;
  recommended_action?: string | null;
  model_version?: string | null;
  feature_version?: string | null;
  status: string;
  assigned_analyst?: string | null;
  detection_time: string;
  resolution_time?: string | null;
  created_at: string;
  updated_at: string;
}

/** Mirrors schemas.DetectionResult — the WebSocket alert payload. */
export interface DetectionResult {
  is_anomaly: boolean;
  anomaly_score: number;
  attack_type: string | null;
  threat_level: number | null;
  severity: string | null;
  shap_top3: FeatureAttribution[] | null;
  explanation: string | null;
  /** Present on heartbeat alerts, absent on the base schema. */
  drone_id?: string;
  event_type?: string;
  timestamp?: string;
}

/** Mirrors schemas.UserOut. */
export interface UserInfo {
  id: number;
  username: string;
  email: string | null;
  role: string;
  organization_id?: number | null;
  created_at: string;
}

/** Mirrors schemas.DroneOut. */
export interface Drone {
  id: number;
  drone_id: string;
  organization_id?: number | null;
  status: string;
  last_seen: string;
  last_command: string | null;
}

/**
 * Mirrors schemas.CommandRequestOut. The primary key is command_id, not id, and
 * the requester field is requested_by — both differed from the previous types,
 * so these rendered blank in the UI.
 */
export interface CommandRequest {
  command_id: number;
  organization_id?: number | null;
  drone_id: string;
  requested_by: string;
  command_type: string;
  reason: string | null;
  status: string;
  created_at: string;
  approved_by?: string | null;
  approved_at?: string | null;
}

/** Mirrors schemas.AuditLogOut. Note previous_state / new_state, not *_status. */
export interface AuditLog {
  id: number;
  actor: string;
  organization_id?: number | null;
  action: string;
  resource?: string | null;
  resource_id?: string | null;
  target?: string | null;
  previous_state?: string | null;
  new_state?: string | null;
  reason?: string | null;
  details?: string | null;
  ip_address?: string | null;
  correlation_id?: string | null;
  timestamp?: string | null;
  created_at: string;
}

/** GET /system/health. Fields beyond status are absent in the degraded branch. */
export interface SystemHealth {
  status: string;
  db_connected?: boolean;
  system_health_pct?: number;
  signal_fidelity_pct?: number;
  active_drones?: number;
  total_drones?: number;
  silent_drones?: number;
  total_incidents?: number;
  critical_incidents?: number;
  timestamp?: string;
}

export interface IncidentStats {
  total: number;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
  by_threat_type: Record<string, number>;
  by_drone: Record<string, number>;
  avg_resolution_time_seconds: number;
}

export interface SystemSettings {
  critical_threshold: number;
  high_threshold: number;
  refresh_rate: string;
  ui_sound: boolean;
  push_notif: boolean;
  webhooks: boolean;
}

export interface GeofenceZone {
  id: number;
  name: string;
  zone_type: string;
  coordinates: unknown;
  severity: string;
  is_active: boolean;
  organization_id?: number | null;
}

/** One physical check the kinematic guard performs. GET /ai/detection/status. */
export interface GuardCheck {
  check: string;
  unit: string;
  threshold: number;
  description: string;
  lower_is_worse?: boolean;
}

/**
 * Measured performance of the ML tier. Every field is nullable because the
 * evaluation record is read from the model artifact directory and may be absent
 * — in which case the console must say so rather than show a zero.
 */
export interface TierValidation {
  protocol: string;
  precision?: number | null;
  recall?: number | null;
  f1_score?: number | null;
  false_positive_rate?: number | null;
  n_folds?: number | null;
  mean_flight_accuracy?: number | null;
}

/** One attempt at fixing the ML tier, and what it measured. */
export interface Intervention {
  id: string;
  name: string;
  description?: string;
  lofo?: {
    f1_score?: number | null;
    precision?: number | null;
    recall?: number | null;
    false_positive_rate?: number | null;
  };
  verdict: string;
  reason: string;
}

export interface Investigations {
  task?: string;
  trivial_baselines?: {
    note?: string;
    always_say_attack?: { f1_score?: number | null };
  };
  interventions?: Intervention[];
  root_cause?: { finding?: string; evidence?: string[]; implication?: string };
  decision?: { tier_2_enabled?: boolean; statement?: string };
}

export interface DetectionTier {
  tier: number;
  name: string;
  detector: string;
  method: string;
  enabled: boolean;
  raises_incidents: boolean;
  deterministic: boolean;
  requires_training_data: boolean;
  /** Tier 1 only. */
  checks?: GuardCheck[];
  /** Tier 2 only. */
  model_version?: string;
  artifact_status?: string;
  feature_list?: string[];
  validation?: TierValidation;
  contrast?: { protocol: string; f1_score?: number | null; caveat?: string | null };
  investigations?: Investigations;
  disabled_reason?: string | null;
}

export interface GeofenceCreate {
  name: string;
  zone_type: string;
  coordinates: unknown;
  severity?: string;
  is_active?: boolean;
}

/** Command types the backend regex actually accepts. */
export const COMMAND_TYPES = [
  "RETURN_TO_HOME",
  "LAND",
  "HOLD",
  "EMERGENCY_LAND",
  "SWITCH_SAFE_MODE",
  "RESUME_MISSION",
] as const;
export type CommandType = (typeof COMMAND_TYPES)[number];

/** Incident statuses the backend regex accepts. */
export const INCIDENT_STATUSES = [
  "NEW",
  "OPEN",
  "ACKNOWLEDGED",
  "INVESTIGATING",
  "CONTAINED",
  "RESOLVED",
  "CLOSED",
] as const;

/* ----------------------------------------------------------------- methods */

export const api = {
  /* --- system ---------------------------------------------------------- */

  /** GET /system/health — requires an authenticated operator or above. */
  getSystemHealth: (): Promise<SystemHealth> => request("/system/health"),

  /** GET /telemetry/health/status — MAVLink receiver state. Unauthenticated. */
  getIngestHealth: (): Promise<{
    status: string;
    mavlink_connected: boolean;
    packets_processed: number;
  }> => request("/telemetry/health/status"),

  /**
   * GET /ai/detection/status — which tiers are live, their thresholds, and the
   * ML tier's measured performance. Requires ai.explain, so observers cannot
   * read the guard thresholds.
   */
  getDetectionStatus: (): Promise<{ tiers: DetectionTier[] }> =>
    request("/ai/detection/status"),

  /* --- telemetry ------------------------------------------------------- */

  /** GET /telemetry/latest — newest packet per drone for this organization. */
  getLatestTelemetry: (): Promise<TelemetryRecord[]> => request("/telemetry/latest"),

  /** GET /telemetry/{drone_id} — recent packets for one drone. */
  getDroneTelemetry: (droneId: string, limit = 100): Promise<TelemetryRecord[]> =>
    request(`/telemetry/${encodeURIComponent(droneId)}?limit=${limit}`),

  /** GET /telemetry/{drone_id}/latest — single newest packet for one drone. */
  getDroneLatestTelemetry: (droneId: string): Promise<TelemetryRecord> =>
    request(`/telemetry/${encodeURIComponent(droneId)}/latest`),

  /** GET /telemetry/history — bounded window for DVR playback. Backend caps limit at 2000. */
  getTelemetryHistory: (
    startTime: string,
    endTime: string,
    opts?: { limit?: number; skip?: number },
  ): Promise<TelemetryRecord[]> => {
    const params = new URLSearchParams({ start_time: startTime, end_time: endTime });
    if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
    if (opts?.skip !== undefined) params.set("skip", String(opts.skip));
    return request(`/telemetry/history?${params}`);
  },

  /* --- incidents ------------------------------------------------------- */

  /** GET /incidents/ — the trailing slash is required; the backend does not alias it. */
  getIncidents: (severity?: string, limit = 50): Promise<Incident[]> => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (severity) params.set("severity", severity);
    return request(`/incidents/?${params}`);
  },

  getOpenIncidents: (): Promise<Incident[]> => request("/incidents/open"),

  getIncidentStats: (): Promise<IncidentStats> => request("/incidents/stats"),

  getIncident: (id: number): Promise<Incident> => request(`/incidents/${id}`),

  /**
   * Lifecycle transitions. Each names a destination; the backend walks any
   * intermediate states and writes an audit row per hop, so the stored history
   * is a complete path even when the operator clicked one button.
   */
  acknowledgeIncident: (id: number, reason?: string): Promise<Incident> =>
    request(`/incidents/${id}/acknowledge`, jsonBody("POST", { reason })),

  investigateIncident: (id: number, reason?: string): Promise<Incident> =>
    request(`/incidents/${id}/investigate`, jsonBody("POST", { reason })),

  containIncident: (id: number, reason?: string): Promise<Incident> =>
    request(`/incidents/${id}/contain`, jsonBody("POST", { reason })),

  assignIncident: (id: number, username: string): Promise<Incident> =>
    request(`/incidents/${id}/assign`, jsonBody("POST", { username })),

  resolveIncident: (id: number, reason?: string): Promise<Incident> =>
    request(`/incidents/${id}/resolve`, jsonBody("POST", { reason })),

  closeIncident: (id: number, reason?: string): Promise<Incident> =>
    request(`/incidents/${id}/close`, jsonBody("POST", { reason })),

  /** GET /incidents/audit/logs — requires the audit.read permission. */
  getAuditLogs: (): Promise<AuditLog[]> => request("/incidents/audit/logs"),

  /* --- fleet & commands ------------------------------------------------ */

  getDrones: (): Promise<Drone[]> => request("/drones"),

  /**
   * POST /drones/{id}/command — requests a command. This does NOT actuate:
   * the backend records it as PENDING and logs a dry-run entry. It becomes
   * effective only after approveCommand() by a second, authorised user.
   */
  requestCommand: (
    droneId: string,
    commandType: CommandType,
    reason?: string,
  ): Promise<CommandRequest> =>
    request(
      `/drones/${encodeURIComponent(droneId)}/command`,
      jsonBody("POST", { command_type: commandType, reason }),
    ),

  /** POST /drones/{id}/command/{command_id}/approve — the second person in the two-person rule. */
  approveCommand: (
    droneId: string,
    commandId: number,
    approved: boolean,
    reason?: string,
  ): Promise<CommandRequest> =>
    request(
      `/drones/${encodeURIComponent(droneId)}/command/${commandId}/approve`,
      jsonBody("POST", { approved, reason }),
    ),

  getDroneCommands: (droneId: string): Promise<CommandRequest[]> =>
    request(`/drones/${encodeURIComponent(droneId)}/commands`),

  /* --- users ----------------------------------------------------------- */

  getMe: (): Promise<UserInfo> => request("/users/me"),

  updateMe: (payload: { email?: string }): Promise<UserInfo> =>
    request("/users/me", jsonBody("PATCH", payload)),

  changePassword: (
    currentPassword: string,
    newPassword: string,
  ): Promise<{ message: string }> =>
    request(
      "/users/me/password",
      jsonBody("POST", { current_password: currentPassword, new_password: newPassword }),
    ),

  /** GET /users/ — requires user.manage. Scoped to the caller's organization. */
  getUsers: (): Promise<UserInfo[]> => request("/users/"),

  /** POST /users/ — requires user.manage. Creates within the caller's organization. */
  createUser: (payload: {
    username: string;
    password: string;
    email?: string;
    role?: string;
  }): Promise<UserInfo> => request("/users/", jsonBody("POST", payload)),

  /* --- settings -------------------------------------------------------- */

  /** GET /settings/ — trailing slash avoids a 307 that can drop the method. */
  getSettings: (): Promise<SystemSettings> => request("/settings/"),

  updateSettings: (payload: Partial<SystemSettings>): Promise<SystemSettings> =>
    request("/settings/", jsonBody("PATCH", payload)),

  /* --- geofence -------------------------------------------------------- */

  getGeofences: (): Promise<GeofenceZone[]> => request("/geofence/zones"),

  createGeofence: (payload: GeofenceCreate): Promise<GeofenceZone> =>
    request("/geofence/zones", jsonBody("POST", payload)),

  /** DELETE /geofence/zones/{id} — deactivates rather than deleting. */
  deleteGeofence: (zoneId: number): Promise<{ status: string; message: string }> =>
    request(`/geofence/zones/${zoneId}`, { method: "DELETE" }),
};
