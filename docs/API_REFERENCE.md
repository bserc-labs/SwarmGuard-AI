# SwarmGuard AI — API Reference Documentation

**Base URL:** `/` (Development: `http://localhost:8000`, Production: `/api/`)  
**Authentication:** Bearer JWT (`Authorization: Bearer <token>`). `/telemetry/ingest`
additionally requires an `x-drone-api-key` header — both, not either.  
**Timestamps:** every timestamp in a response is UTC and says so, with the ISO
8601 zone designator (`2026-09-22T17:13:19.336042Z`). A request that sends one
without a zone is read as UTC.

> **The generated OpenAPI schema at `/docs` is authoritative.** It is produced
> from the routers themselves and cannot drift. This file is a hand-written
> orientation guide covering the routes most people integrate against first;
> it describes a subset of the 40 routes the application actually serves.

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
| `POST` | `/telemetry/ingest` | JWT **and** API Key | `50/sec` | Ingest one telemetry packet |
| `GET` | `/telemetry/latest` | JWT | None | Latest packet per drone in the caller's organization |
| `GET` | `/telemetry/history` | JWT | None | Historical telemetry; `start_time` and `end_time` are **required**, with `limit`/`skip` pagination |
| `GET` | `/telemetry/{drone_id}` | JWT | None | Recent packets for one drone |
| `GET` | `/telemetry/{drone_id}/latest` | JWT | None | Latest packet for one drone |
| `GET` | `/telemetry/health/status` | None | None | MAVLink receiver status |

<!--
This table previously listed /telemetry/live, /telemetry/sensor-fusion/live and
/telemetry/swarm-formation. None of them exist in backend/routers/telemetry.py
and none ever did under those paths -- documentation that sends an integrator
down a dead end is worse than documentation that is merely incomplete. The
routes above were read off the router.
-->

### `POST /telemetry/ingest`
- **Headers:** `Authorization: Bearer <token>` (needs the `telemetry:ingest`
  permission) **and** `x-drone-api-key: <KEY>`. Missing or wrong key → `403`.
  `<KEY>` is the drone's own key (`sgd_...`, issued by
  `POST /drones/{drone_id}/credentials`, admin only), or the shared
  `DRONE_API_KEY` while `DEVICE_SHARED_KEY_ENABLED` is on. A drone's key is
  valid only for that `drone_id` in that organization.
- **Note:** `packet_sequence` is **required**. Omitting it yields a `422` whose
  body names the field but is easy to miss.
- **Optional:** `sample_time_ms` — the device's own sample clock in
  milliseconds (MAVLink `time_boot_ms`; monotonic is sufficient, wall-clock
  sync is not required). The kinematic guard rates motion over this interval
  when present and over server arrival time otherwise; the incident evidence
  records which (`"Time Base"`). Packets may arrive out of order: each is
  rated against its nearest neighbour on this clock, so send the time it was
  *sampled*, not the time it was sent.
- **Request Body:**
```json
{
  "drone_id": "drone_alpha",
  "latitude": 34.0522,
  "longitude": -118.2437,
  "altitude": 150.0,
  "speed": 18.5,
  "battery": 82.0,
  "packet_sequence": 1042,
  "sample_time_ms": 812345
}
```
- **Response `200 OK`:** the accepted packet, echoed. Detection runs in the
  background after the request returns; incidents arrive over the WebSocket and
  `GET /incidents/`, not in this response.
```json
{
  "status": "success",
  "data": {
    "drone_id": "drone_alpha",
    "latitude": 34.0522,
    "longitude": -118.2437,
    "altitude": 150.0,
    "speed": 18.5,
    "heading": null,
    "battery": 82.0,
    "flight_mode": null,
    "armed_status": null,
    "satellites": null,
    "packet_sequence": 1042,
    "sample_time_ms": 812345
  }
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
| `WebSocket` | `/ws/telemetry` | `?token=<JWT>` | Live telemetry frames and incident alerts (`AI_DETECTION`, `INCIDENT_ESCALATED`), scoped to the caller's organization. Clients send `{"type":"ping"}` every 15 s as an application-level keepalive and the server answers `{"type":"pong"}`; token expiry is re-checked on each ping and an expired session is closed with `1008`. All other client frames are ignored. |
