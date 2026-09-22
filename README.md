# SwarmGuard AI

Real-time anomaly detection for autonomous UAV swarms. SwarmGuard ingests MAVLink
telemetry, scores it against a model trained on real PX4 flight logs, and raises
explainable incidents to an operator dashboard.

The detection target is **GPS spoofing** — an attack where a UAV's reported
position is manipulated while the airframe's own sensors continue reporting
normally. The system catches it by deriving ground speed from successive
position fixes and comparing it against the speed the airframe reports; a
spoofed position jumps, so the two diverge.

---

## Status

| Subsystem | State |
|---|---|
| Telemetry ingest (REST + MAVLink) | Working |
| Tier 1 detection — kinematic guard | Working, **live** |
| Tier 2 detection — ML anomaly model | Trained, **disabled** — see Results |
| Explainable incidents | Working |
| WebSocket live feed | Working |
| Multi-tenant isolation (RBAC + org scoping) | Working |
| Operator dashboard (11 screens) | Working |
| Ping DoS / jamming classification | Not implemented — see Scope |

---

## Detection: two tiers

### Tier 1 — kinematic guard (authoritative)

Deterministic physical-plausibility checks. A UAV cannot travel 5 km in 1.5
seconds, cannot climb at 200 m/s, and its GNSS-derived ground speed cannot
disagree with its airframe-reported speed by two orders of magnitude unless one
of them is lying — and the accelerometers are far harder to spoof than the GNSS
receiver.

| Check | Default limit |
|---|---|
| `gps_implied_speed` | 60 m/s |
| `gps_airframe_speed_mismatch` | 25 m/s |
| `vertical_speed` | 25 m/s |
| `satellite_loss` | below 6, having previously held lock |

Thresholds come from the airframe's envelope with margin, not from a dataset.
Every alert carries the observed value, the threshold crossed, and the
exceedance factor, so an analyst can verify the arithmetic:

> *GPS track implies 3,706 m/s but the airframe reports 18.0 m/s — a 3,688 m/s
> disagreement.*

This is the floor, not the ceiling: it catches gross manipulation, not subtle
drift. But it is deterministic, has no false positives on physically valid
flight, requires no training data, and does not degrade when deployed somewhere
that looks nothing like the training set.

### Tier 2 — ML anomaly model (disabled by default)

Trained on the **Live GPS Spoofing and Jamming** dataset — real PX4 ULog flight
recordings, not simulation. It is shipped but `AI_INCIDENTS_ENABLED=false`,
because it does not generalize. The numbers are below.

---

## Model results

### Validation protocol

The headline number is **leave-one-flight-out (LOFO)**: the model is trained on
every flight but one and tested on the held-out flight, repeated across all
flights.

This matters because in this dataset `attack_type` is 1:1 with `flight_id` —
each flight is entirely one attack type. A conventional random row split puts
rows from the *same flight* in both train and test, so the model can memorise
flight identity instead of learning attack behaviour, and the reported score
becomes meaningless.

### The result: it does not generalize

Binary GPS Spoofing vs Normal, 39,441 rows across 9 flights, RandomForest:

| Validation | Precision | Recall | F1 | FPR |
|---|---|---|---|---|
| **LOFO (honest)** | 0.074 | 0.102 | **0.086** | **0.862** |
| Row-level stratified (leaky) | 0.562 | 0.841 | 0.673 | — |

Mean per-flight accuracy: **12.7%** (std 12.2%). An **8× gap** between the
number a naive split reports and the number that survives honest validation.

Read the failure mode, not just the number: the model flags 86% of *normal*
rows as attacks while catching 10% of *actual* attacks. It is systematically
inverted — it learned flight-specific idiosyncrasies that anti-correlate on
unseen flights. Per-flight accuracy ranges from 0.3% to 35.5%, so it is not
uniformly weak; it is confidently wrong in a flight-dependent way.

Two interventions were measured, and both point the same direction:

| Change | LOFO F1 | Row-level F1 |
|---|---|---|
| Baseline (unbounded trees, 9 features) | 0.041 | 0.586 |
| + depth cap at 12 | 0.086 | 0.673 |
| + drop absolute features (`altitude`, `yaw`) | **0.145** | 0.612 |

Depth-capping matters because unbounded trees split until every leaf is pure,
which *is* memorisation — the mechanism behind the collapse. It also shrank the
artifact from 327 MB to 7.8 MB.

Dropping `altitude` and `yaw` matters more. Both cleared the ICC screen
individually, but ICC is a *per-feature* test: two weakly flight-specific
features can still encode flight identity jointly. Removing them lifted LOFO F1
by 69% while *lowering* the leaky ceiling — exactly the signature of removing a
shortcut rather than removing signal.

Reproduce the ablation:
```bash
SWARMGUARD_FEATURE_SET=deltas python model_train/scripts/train_deployable_v2.py
```

The trend is real and the direction is clear, but 0.145 is still not a
detector. The conclusion holds: **the features computable from live telemetry
do not support cross-flight generalization on this dataset.** What the ablation
tells us is *where to push next* — removing flight-identity leakage helps, so
per-flight normalisation is the highest-value next experiment.

That is why Tier 1 is the live detector and Tier 2 ships disabled. A detector
with a 0.862 false-positive rate does not degrade gracefully — it trains
operators to ignore the dashboard, which is worse than having no dashboard.

### Why the honest number is so much lower

An ICC (intraclass correlation) analysis on flight identity found several
features acting as flight-identity shortcuts:

| Feature | ICC | Action |
|---|---|---|
| `battery` | 0.77 | Dropped |
| `link_data_rate` | 0.67 | Dropped |
| `pitch` | 0.65 | Dropped (`pitch_change` retained, ICC ≈ 0) |
| `speed` | 0.54 | Dropped (`speed_change` retained, ICC ≈ 0) |
| `heartbeat_time` | 0.26 | Dropped (`heartbeat_gap` retained) |

Per-flight *differences* of the same signals came back at ICC ≈ 0 — they
describe instantaneous behaviour rather than which flight you are looking at,
so they are what the deployed model uses.

Reproduce:
```bash
python model_train/diagnostics/15_icc_confound_check.py   # confound analysis
python model_train/diagnostics/16_apply_confound_fixes.py # produces v2 dataset
python model_train/scripts/train_deployable_v2.py         # LOFO + train + register
```

### Features

The deployed model uses only features that are **both** confound-clean **and**
computable from a live `TelemetryPacket`:

```
altitude              yaw                    speed_change
yaw_change            time_delta             vertical_speed
gps_acceleration      gps_speed_error_abs    gps_speed_error_ratio
```

Feature definitions are shared between training
(`model_train/scripts/feature_engineering.py`) and serving
(`backend/models_ml/preprocess.py`) — including an identical haversine
implementation — so there is no train/serve skew.

### Scope

**Ping DoS and jamming are deliberately out of scope for this model version.**
Their signal lives entirely in MAVLink link statistics — `heartbeat_gap`,
`heartbeat_lost`, `link_data_rate` — which the current ingest schema does not
carry. Training on them would produce a model that scores well offline and
cannot run on the live feed at all. Extending `TelemetryPacket` to carry link
telemetry is the next milestone.

`latitude` / `longitude` are also excluded. Their ICC was low, but they are
absolute position: a model trained only on flights near (43.94, −78.89) would
carry that geography into its decision boundary.

---

## Architecture

```
MAVLink / REST  ─▶  /telemetry/ingest  ─▶  TimescaleDB
                            │
                            └─▶ detection_pipeline (background)
                                     │
                                     ├─▶ Tier 1: KinematicGuard      ── fires ──┐
                                     │      (deterministic physics)             │
                                     │                                          │
                                     ├─▶ Tier 2: AIInferenceService             │
                                     │      + ExplainabilityEngine (TreeSHAP)   │
                                     │      [disabled by default]               │
                                     │                                          ▼
                                     ├─▶ IncidentEngine (severity, priority, suppression)
                                     └─▶ WebSocket broadcast (org-scoped)
```

Detection runs **after** the ingest transaction commits and **off** the request
path. Rolling features are defined against preceding packets, so the detector
reads its window back from the database rather than scoring a packet in
isolation.

Full documentation: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md),
[`docs/API_REFERENCE.md`](docs/API_REFERENCE.md),
[`docs/SECURITY.md`](docs/SECURITY.md),
[`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md).

## Tech Stack

- **Frontend**: React 19, TypeScript, Vite, TanStack Router/Query, Tailwind 4, Leaflet, Recharts
- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2, Pydantic v2, Alembic
- **ML**: scikit-learn, SHAP, pandas, NumPy
- **Data**: TimescaleDB (PostgreSQL 16), Redis
- **Infra**: Docker Compose, GitHub Actions

---

## Security

- **Multi-tenant isolation** — `organization_id` on every table; tenant identity
  is derived server-side from the JWT and never read from client input
- **RBAC** — five roles, permission checks declared at router level
- **Session revocation** — a `token_version` claim is embedded in each JWT and
  compared per request, so a password or role change invalidates every
  outstanding session with a single `UPDATE`
- **Device authentication** — `/telemetry/ingest` requires both an operator
  bearer token and a device API key
- **Secret validation** — startup fails on absent, short, or publicly-known
  secrets (`backend/config.py`)
- **CI gates** — Trivy secret scanning blocks merges; `pip-audit`, `npm audit`,
  Ruff and Mypy run on every PR

---

## Setup

### Docker (recommended)

```bash
cp .env.example .env      # then fill in the required values
docker compose up --build -d
```

Required in `.env` — the backend refuses to start without them:

```bash
POSTGRES_USER, POSTGRES_PASSWORD
SECRET_KEY=$(openssl rand -hex 32)
DRONE_API_KEY=$(openssl rand -hex 32)
ADMIN_USERNAME, ADMIN_PASSWORD   # optional: provisions the first admin
```

`docker compose up` first runs a one-shot **`migrate`** job (schema migrations,
then the optional admin) and starts the API only once it has exited 0. The API
itself never migrates: it checks that the database is at the revision the build
ships and refuses to start if it is behind, because two replicas migrating on
start ran the same DDL at the same time. To migrate by hand:
`docker compose run --rm migrate`.

Frontend on `:80`. The API is published on loopback only —
`http://localhost:8000` (OpenAPI docs at `/docs`) — for the local demo and
scripts; everything else reaches it through nginx at `/api`. Every variable in
`.env` is passed to the backend container; the compose file overrides
`DATABASE_URL` and `REDIS_URL` with the in-network values.

### Local development

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

## Demo

With the stack running, drive 12 simulated drones and inject attacks:

```bash
export SWARMGUARD_USER=admin
export SWARMGUARD_PASSWORD=...      # the ADMIN_PASSWORD you configured
export DRONE_API_KEY=...            # must match the backend's
python simulate_attack.py
```

The simulator authenticates, streams nominal telemetry, and every 20 seconds
injects a GPS spoof or jamming event into a random drone. Incidents appear on
the dashboard in real time via WebSocket.

## Testing

```bash
cd backend && pytest                 # requires a running TimescaleDB
cd frontend && npm run test
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GUARD_ENABLED` | `true` | Tier 1 kinematic guard |
| `GUARD_MAX_SPEED_MPS` | `60` | Airframe speed envelope |
| `GUARD_MAX_CLIMB_MPS` | `25` | Airframe climb/descent envelope |
| `GUARD_GPS_SPEED_ERROR_MPS` | `25` | Tolerated GNSS/airframe speed disagreement |
| `GUARD_MIN_SATELLITES` | `6` | Satellite-loss floor |
| `GUARD_DEVICE_CLOCK_MAX_LEAD_S` | `10` | How far the device sample clock (`sample_time_ms`) may exceed packet arrival spacing before it is disbelieved for that pair |
| `AI_INCIDENTS_ENABLED` | `false` | Let Tier 2 raise incidents — see Model results before enabling |
| `MODEL_VERSION` | `v2` | Active model in the registry |
| `MAVLINK_ENABLED` | `false` | Enable the MAVLink receiver |
| `MAVLINK_ORGANIZATION_ID` | — | Required when MAVLink is enabled; telemetry without it is invisible to every tenant |
| `WEBSOCKET_INTERVAL` | `0.1` | Broadcast interval (10 Hz) |
| `REDIS_URL` | — | Required for multi-worker deployments |
| `LOGIN_RATE_LIMIT` | `5/minute` | Login attempts per client address; raise only for an ephemeral test deployment |
| `REQUIRE_SCHEMA_AT_HEAD` | `true` | The API refuses to start against a database that is behind the build's migrations. A database that is *ahead* (a rollback) only warns |
| `RUN_MIGRATIONS_ON_START` | `false` | Image only: migrate before serving, for a single container run by hand. Under compose the `migrate` job does this once |
| `SWARMGUARD_TAG` | `local` | Tag of the backend image shared by the `migrate` job and the API |
| `FORWARDED_ALLOW_IPS` | nginx container (compose) / `127.0.0.1` (image) | Peers whose `X-Forwarded-For` uvicorn honours. Set by compose; not overridable from `.env` |
| `SWARMGUARD_SUBNET` / `SWARMGUARD_PROXY_IP` | `172.28.0.0/24` / `172.28.0.10` | Compose network and the frontend's static address. Change only on a subnet collision, then `docker compose down` once |

## Roadmap

Ordered by what the measurements say matters:

1. **Per-flight normalisation.** The LOFO collapse is the central open problem.
   Normalising each feature against the flight's own early-window baseline is
   the most direct attack on flight-identity leakage.
2. **More flights.** Nine flights is thin for flight-level cross-validation;
   with `attack_type` 1:1 with `flight_id`, every fold is single-class.
3. **Extend `TelemetryPacket` with MAVLink link statistics**, then retrain to
   cover jamming and Ping DoS.
4. Widen the kinematic guard: IMU/GNSS cross-checks, geofence-rate limits.
5. Model drift monitoring and scheduled retraining.
6. Approval workflow for outbound drone commands (schema exists, UI pending).

## License

See [LICENSE](LICENSE).
