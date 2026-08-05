# SwarmGuard AI — API Reference Documentation

**Base URL:** `/` (Development: `http://localhost:8000`, Production: `/api/`)  
**Authentication:** Bearer JWT Token (`Authorization: Bearer <token>`) or `x-drone-api-key` header.

---

## 1. Authentication Endpoints (`/auth`)

| Method | Endpoint | Auth | Rate Limit | Description |
|:---|:---|:---:|:---:|:---|
| `POST` | `/auth/login` | None | `5/min` | Authenticate user credentials and return JWT bearer token |

### `POST /auth/login`
- **Request Body (Form Data):** `username`, `password`
- **Response `200 OK`:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1Ni...",
  "token_type": "bearer",
  "role": "commander"
}
```

---

## 2. Drone Telemetry Endpoints (`/telemetry`)

| Method | Endpoint | Auth | Rate Limit | Description |
|:---|:---|:---:|:---:|:---|
| `POST` | `/telemetry/ingest` | API Key | `50/sec` | Ingest real-time drone telemetry JSON |
| `GET` | `/telemetry/live` | JWT | None | Fetch latest 500 telemetry logs |
| `GET` | `/telemetry/history` | JWT | None | Fetch historical telemetry with time window & `limit`/`skip` pagination |
| `GET` | `/telemetry/sensor-fusion/live` | JWT | None | Fetch live 5-sensor fusion matrix across active drones |
| `GET` | `/telemetry/swarm-formation` | JWT | None | Fetch real-time drone spatial formation classification |

### `POST /telemetry/ingest`
- **Headers:** `x-drone-api-key: <KEY>`
- **Request Body:**
```json
{
  "drone_id": "drone_alpha",
  "latitude": 34.0522,
  "longitude": -118.2437,
  "altitude": 150.0,
  "speed": 18.5,
  "battery": 82.0,
  "packet_sequence": 1042
}
```
- **Response `200 OK`:**
```json
{
  "is_anomaly": true,
  "anomaly_score": 0.88,
  "attack_type": "GPS_SPOOFING",
  "threat_level": 92,
  "severity": "CRITICAL",
  "explanation": "CRITICAL severity alert: Drone is reporting geographically impossible movements.",
  "shap_top3": [
    { "feature": "speed", "importance": 0.48 },
    { "feature": "altitude", "importance": 0.32 },
    { "feature": "battery_drain_rate", "importance": 0.20 }
  ]
}
```

---

## 3. Incident Management Endpoints (`/incidents`)

| Method | Endpoint | Auth | Rate Limit | Description |
|:---|:---|:---:|:---:|:---|
| `GET` | `/incidents/` | JWT | None | Fetch all security incidents with severity/status filtering & pagination |
| `GET` | `/incidents/stats` | JWT | None | Fetch aggregated incident statistics for dashboard widgets |
| `GET` | `/incidents/export` | JWT | None | Export incident logs as downloadable CSV report |
| `GET` | `/incidents/{id}` | JWT | None | Fetch details for a specific incident by ID |
| `PATCH` | `/incidents/{id}` | JWT | None | Update incident status (`ACKNOWLEDGED`, `RESOLVED`, `FALSE_POSITIVE`) |
| `GET` | `/incidents/audit/logs` | Admin | None | Fetch system audit trail logs |

---

## 4. Tactical Command Endpoints (`/drones`)

| Method | Endpoint | Auth | Rate Limit | Description |
|:---|:---|:---:|:---:|:---|
| `GET` | `/drones` | JWT | None | List registered drones and active operational status |
| `POST` | `/drones/{id}/command` | Commander | None | Issue tactical command (`HARD_KILL`, `RETURN_TO_HOME`, `EMERGENCY_LAND`) |
| `GET` | `/drones/{id}/commands` | JWT | None | Fetch command execution history for a drone |
| `POST` | `/drones/check-heartbeats` | JWT | None | Trigger silent drone heartbeat check |

---

## 5. Real-Time Streaming (`/ws`)

| Type | Endpoint | Query Param | Description |
|:---|:---|:---:|:---|
| `WebSocket` | `/ws/telemetry` | `?token=<JWT>` | Stream real-time telemetry alerts, threat updates, and kill-chain actions |
