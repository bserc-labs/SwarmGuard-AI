# SwarmGuard AI — Project Orientation

*A guide to what this codebase is, how it actually works, and what is real versus
aspirational. Written from a full build-and-run of the system on 2026-09-20/21,
not from reading the README.*

---

## 1. What the product does, in one paragraph

SwarmGuard AI watches the telemetry stream coming off a fleet of UAVs and raises
explainable security incidents to a human operator's dashboard. The specific
threat it is built to catch is **GPS spoofing**: an attacker manipulates the
position a drone reports while the airframe's own inertial sensors keep telling
the truth. SwarmGuard catches this by deriving ground speed from successive
position fixes and comparing it against the speed the airframe itself reports.
A spoofed position jumps; the two numbers diverge; the system fires.

I verified this end to end. Feeding three packets — two benign, then one with a
~60 km position jump two seconds later — produced this incident:

```
#2 drone=SMOKE-01 type=GPS_SPOOFING sev=CRITICAL score=100.0 prio=100
   action  : Verify GNSS integrity. Cross-check position against INS/visual
             odometry before trusting any waypoint command.
   evidence: gps_airframe_speed_mismatch observed=42620.913 threshold=25.0 m/s
   evidence: gps_implied_speed          observed=42638.913 threshold=60.0 m/s
```

That is the product working. The evidence line is the important part: an analyst
can check the arithmetic by hand.

I then ran the project's own 12-drone simulator against the Docker stack:

```
 telemetry_rows | drones | incidents
            315 |     13 |         3
```

The simulator injected a jamming attack into `DRONE-ALPHA-01`; the system caught
it (`SIGNAL_JAMMING / HIGH`). The remaining ~300 packets were nominal flight and
produced **zero false positives**. The central claim of the detector — "no false
positives on physically valid flight" — holds under test.

---

## 2. The one thing to understand before anything else

**There are two detection tiers, and only the dumb one is turned on.**

| Tier | What it is | Status |
|---|---|---|
| **Tier 1 — kinematic guard** | Deterministic physics checks | **Live, authoritative** |
| **Tier 1b — geofence** | Deterministic zone breach | Live |
| **Tier 2 — ML anomaly model** | RandomForest on real PX4 flights | **Shipped but disabled** |

Tier 2 is disabled — `AI_INCIDENTS_ENABLED=false` — and this is the most
intellectually honest decision in the repository. The team validated the model
**leave-one-flight-out** (train on every flight but one, test on the held-out
flight) and got:

```
F1 0.086   precision 0.074   recall 0.102   false-positive rate 0.862
```

(Source: `backend/models_ml/v2/evaluation.json`, which I read directly.)

At an 86% false-positive rate, roughly six of every seven alerts would be noise.
An operator who learns to ignore the dashboard is worse off than one who never
had it. So the model ships, documented, switched off — and a deterministic
physics layer that *cannot* false-positive on a physically achievable manoeuvre
does the actual work.

**Why this matters to you:** if someone asks "where's the AI?", the honest
answer is "measured, found wanting, and disabled on purpose — the detection you
see running is physics." That is a stronger position than a demo that looks
impressive and does not generalise. Do not let anyone flip that flag to make a
demo look better without re-reading `backend/models_ml/v2/evaluation.json`.

---

## 3. Architecture — how a packet becomes an alert

```
MAVLink / REST  ─▶  POST /telemetry/ingest  ─▶  TimescaleDB (commit)
                            │
                            └─▶ background task: detection_pipeline
                                     │
                                     ├─▶ Tier 1  KinematicGuard    ── fires ──┐
                                     ├─▶ Tier 1b GeofenceEngine    ── fires ──┤
                                     ├─▶ Tier 2  AIInferenceService (disabled) │
                                     │                                         ▼
                                     ├─▶ IncidentEngine (severity, priority,
                                     │                   duplicate suppression)
                                     └─▶ WebSocket broadcast, scoped to one org
```

Three design decisions here are worth internalising:

1. **Detection runs after the ingest transaction commits, and off the request
   path.** Rolling features are defined against *preceding* packets, so the
   detector reads its window back out of the database rather than scoring a
   packet in isolation. It needs the packet to already be there.

2. **Inference is sync CPU work; broadcast is async I/O.** The pipeline splits
   them — `asyncio.to_thread` for the sklearn/DB work, the event loop itself for
   socket delivery. Getting this backwards would stall the event loop under load.

3. **Physics wins ties.** If both the guard and the model would fire, the
   operator sees the explanation with checkable numbers behind it. Geofence runs
   only when the guard stayed silent, because a geofence verdict is only as good
   as the position it is handed — and the guard has just declared that position a
   lie.

---

## 4. The codebase, by the numbers

| | |
|---|---|
| Backend Python | ~12,500 lines |
| Frontend TypeScript/TSX | ~11,100 lines |
| ML training code | ~5,500 lines |
| Backend tests | 416 (366 pass, 50 skip) |
| Frontend tests | 105, all passing |
| API surface | 38 paths / 42 operations |
| Alembic migrations | 7, single linear head |
| Frontend pages | 13 |

### Where things live

| Path | What it is |
|---|---|
| `backend/routers/` | HTTP surface — 10 routers, all RBAC-gated |
| `backend/services/` | The real logic. Start with `detection_pipeline.py` |
| `backend/services/kinematic_guard.py` | **Tier 1. Read this first.** |
| `backend/middleware/` | Auth + RBAC + tenant context derivation |
| `backend/models.py` | 9 tables, all carrying `organization_id` |
| `backend/models_ml/` | Serving-side ML: registry, preprocess, artifacts |
| `model_train/` | Offline training, diagnostics, confound analysis |
| `backend/experimental/` | **Dead code, deliberately kept.** Not on any live path |
| `frontend/src/pages/` | 13 operator screens |
| `frontend/src/services/` | API client, auth, WebSocket |

---

## 5. The security model (this part is genuinely good)

Multi-tenancy is the backbone, and it is enforced in depth rather than by
convention:

- **`organization_id` on every table**, `NOT NULL` at the schema level. There is
  a migration whose entire job is "make an unowned row impossible at the
  database level" (`d4e5f6a7b8c9`). I confirmed the constraints exist in a live
  Postgres instance.
- **Tenant identity comes from the JWT, server-side, never from client input.**
  The decoded token carries `{sub, role, org_id, tv}`.
- **Session revocation** via a `token_version` (`tv`) claim compared on every
  request — a password or role change invalidates every outstanding session with
  one `UPDATE`.
- **`/telemetry/ingest` needs two credentials**: an operator bearer token *and* a
  device API key. I verified: valid token + missing key → `403`; valid token +
  wrong key → `403`.
- **WebSocket fan-out is per-organization channels**, not a shared channel with
  filtering — so a worker never even receives another tenant's payloads. Garbage
  token on the WS handshake → `403`, verified.
- **Startup refuses known-public secrets.** `backend/config.py` keeps a
  `KNOWN_PUBLIC_SECRETS` set and fails to boot on any of them.

There is a test file, `tests/test_route_tenancy.py`, that walks every registered
route and asserts it filters on `organization_id` — with a maintained list of
explicit exemptions and tests that the checker itself detects violations. That
is a notably mature piece of test engineering.

---

## 6. What actually runs — verified, not assumed

Everything below I executed.

| Check | Result |
|---|---|
| `npm install` | 402 packages, clean |
| `npm run lint` | clean |
| `npm run typecheck` | clean |
| `npm run test` | **105 passed** (9 files, 1.25 s) |
| `npm run build` | 816 modules, 213 ms |
| Backend deps (Python 3.12.12) | install clean |
| `alembic upgrade head` | 7 migrations, single head `d4e5f6a7b8c9` |
| `pytest` | **366 passed, 50 skipped** (1.13 s) |
| `ruff check` | clean |
| `mypy` | clean, 30 files |
| Backend boot | starts; MAVLink correctly disabled by default |
| Login / bad password / bad token | `200` / `401` / `401` |
| Device API key enforcement | missing → `403`, wrong → `403` |
| **GPS spoof, end to end** | **CRITICAL incident with checkable evidence** |
| **WebSocket live feed** | telemetry frames + incident push received |
| Frontend ↔ backend via proxy | `/api/auth/login` returns a JWT |
| Live security suite (run properly) | **6 / 6 pass** |
| `docker compose up --build -d` | all 4 services **healthy**; full smoke repeats |
| OWASP headers via nginx | CSP + 4 others, all present |
| `simulate_attack.py`, 12 drones | attack caught, **0 false positives** on ~300 nominal packets |

**The project builds, runs, and does what it says.** That is not a given for a
project of this shape, and it is the most important finding in this report.

---

## 7. How to run it yourself

### The fast path (native, no Docker)

```bash
# 1. A TimescaleDB to talk to
docker run -d --name sg-db -p 5433:5432 \
  -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=swarmguard_test timescale/timescaledb:latest-pg16
docker run -d --name sg-redis -p 6379:6379 redis:7-alpine

# 2. Backend
cd backend
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DATABASE_URL="postgresql://postgres:password@localhost:5433/swarmguard_test"
export SECRET_KEY=$(openssl rand -hex 32)
export DRONE_API_KEY=$(openssl rand -hex 32)
export ADMIN_USERNAME=admin ADMIN_PASSWORD='ChooseSomethingLong123'
.venv/bin/alembic upgrade head
.venv/bin/python bootstrap.py          # creates org + admin
.venv/bin/uvicorn main:app --port 8000

# 3. Frontend (separate shell)
cd frontend && npm install && npm run dev   # http://localhost:5173
```

### The Docker path

```bash
cp .env.example .env    # fill in POSTGRES_PASSWORD, SECRET_KEY, DRONE_API_KEY
docker compose up --build -d
```

Frontend on `:80`, API on `:8000`, OpenAPI at `/docs`.

> ⚠️ **Gotcha I hit:** if you followed the README's local-dev step and made a
> `venv/` inside `backend/`, the Docker build used to ship it — a 634 MB build
> context and a four-minute `chown`. I added `venv/` and `.venv/` to
> `backend/.dockerignore`; context dropped to **12 kB**. This is the one file I
> changed.

### Gotchas worth knowing

- `packet_sequence` is **required** on ingest. Omitting it gives a `422` that
  does not obviously say so.
- Vite 8 binds IPv6-first here: `curl 127.0.0.1:5173` is refused, `localhost` works.
- The login rate limit is **5/minute**. It is easy to lock yourself out while testing.
- Python **3.12**, not newer — `shap 0.52.0` has no wheels above it.

---

## 8. What is *not* built (and is honest about it)

- **Ping DoS and jamming detection.** Their signal lives in MAVLink link
  statistics (`heartbeat_gap`, `link_data_rate`) that `TelemetryPacket` does not
  carry. Training on them would produce a model that scores well offline and
  cannot run on the live feed at all. Correctly scoped out.
- **A generalising ML model.** Nine flights, and `attack_type` is 1:1 with
  `flight_id`, so every cross-validation fold is single-class. This is the
  central open research problem, and the README says so.
- **Command approval workflow.** Schema exists, UI does not.
- **TLS, backups, metrics, resource limits.** See the roadmap — none of these
  exist anywhere in the stack.

---

## 9. How to read the codebase in an hour

In this order:

1. `README.md` — the "Model results" section. It is unusually honest; the
   posture there explains most of the design.
2. `backend/services/kinematic_guard.py` — the detector that actually runs. The
   module docstring is the clearest statement of the project's thesis.
3. `backend/services/detection_pipeline.py` — how a packet becomes an incident,
   and why the ordering and threading are what they are.
4. `backend/middleware/auth_middleware.py` + `backend/models.py` — the tenancy model.
5. `backend/tests/test_route_tenancy.py` — how they *prove* the tenancy model.
6. `frontend/src/services/api.ts` + `frontend/src/config.ts` — the client contract.

The comments in this codebase are unusually good. Several of them explain a past
bug and why the current shape prevents it. Read them; they are load-bearing.

---

## 10. Honest overall assessment

This is a **strong engineering project with a production gap, not a demo with a
thin veneer**. The distinction matters.

**What is genuinely impressive:**
- Measurement honesty about the ML tier, at the cost of the more impressive story.
- Defence-in-depth multi-tenancy, proven by a route-walking test.
- Comments that explain *why*, including past failures.
- A green CI that actually gates on lint and types, not just tests.

**What it is not yet:**
- There is no TLS, no backup story, no metrics, no resource limits, and no
  deployment pipeline. Every one of those is a prerequisite for production, and
  none of them is hard — they are just absent.
- A small number of real defects exist, the most serious being an audit-trail
  write that is silently discarded. See the roadmap.

The codebase has earned the right to be taken seriously. It has not yet been
operated.
