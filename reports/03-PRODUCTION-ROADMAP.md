# SwarmGuard AI — Production Roadmap

*Ordered by risk, not by effort. Every item below was verified against a running
system on 2026-09-20/21.*

---

## Implementation status — branch `fix/phase0-hardening`

Phase 0 and the documentation corrections are **done**, plus four blockers a
multi-agent audit surfaced after this roadmap was first written. Gates after
every change: **ruff clean, mypy clean, 388 passed / 48 skipped, single alembic
head.**

| Item | Status |
|---|---|
| 0.1 Ingest audit trail discarded | ✅ policy decided + implemented + tested |
| 0.2 Redis outage → 500 on login | ✅ fails open, surfaced on `/system/health` |
| 0.3 Live security suite never ran | ✅ new CI job; 6/6 pass; skips now fail in CI |
| 0.4 Audit table integrity | ✅ append-only trigger, duplicate index dropped |
| Docs corrections | ✅ all seven |
| `.dockerignore` build-context bloat | ✅ 634 MB → 12 kB |
| **New:** jamming alerts never broadcast | ✅ `broadcast_secure` did not exist |
| **New:** autogenerate would `DROP TABLE` ×9 | ✅ `env.py` never imported models |
| **New:** committed DB with 4 password hashes | ✅ untracked (history purge still owed) |
| **New:** `drone_id` globally unique | ✅ scoped per organization |
| **New:** CI ran on a branch that doesn't exist | ✅ `develop` → `development` |

**Phase 0b is also done** -- merged to `main` as PR #12 (`b5aed08`): eleven
commits, one per item plus the plan and a CI fix, each designed, independently
re-verified against the code and adversarially critiqued before it was written
(`04-PHASE0B-EXECUTION-PLAN.md`). Gates after every one: **ruff clean, mypy
clean, 506 passed / 48 skipped** (from 388), frontend 107/107, single alembic
head `j0e1f2a3b4c5`.

The CI fix was a Phase 0 defect, not a 0b one. Phase 0 made the live security
suite fail rather than skip when it cannot run, keyed on `CI=true` -- which
GitHub sets in *every* job. The unit-test job collects that file with no server,
so it failed six tests it was never meant to run and `main` stayed red from PR
#11 until PR #12. The requirement is now an explicit flag set only by the job
that starts a server, pinned by `tests/test_ci_workflow.py`.

**Phases 1-3 are planned in `05-PHASE1-3-EXECUTION-PLAN.md`**, which explains
each item in plain language, records what was found while planning (the 7-day
chunk interval that would have turned "3-day retention" into ten), and fixes
the order of work.

| Item | Status |
|---|---|
| 0b.1 Tier 1 divided by DB insert time | ✅ rates on the device sample clock; evidence records which clock |
| 0b.2 Rate limit defeated by `X-Forwarded-For` | ✅ API on loopback; uvicorn trusts only nginx's pinned address |
| 0b.3 Docker ignored every `.env` tuning variable | ✅ `env_file`, with `environment:` still winning for network URLs |
| 0b.4 Suppression race / resolved incidents / silent escalation | ✅ advisory lock, live-status filter, `INCIDENT_ESCALATED` broadcast |
| 0b.5a `system_settings` not unique per org | ✅ unique index + race-safe create |
| 0b.5b Email-collision account lockout | ✅ exact-username-first login + email validation |
| 0b.5c/e Token in nginx log; idle socket reconnect loop | ✅ pong keepalive with expiry re-check; token redacted in both logs |
| 0b.5f MAVLink blocked the event loop | ✅ persists via `asyncio.to_thread` |
| 0b.5g Unbounded `/latest` sort; `/stats` in Python | ✅ composite index + LATERAL; SQL aggregates, byte-identical JSON |
| 0b.5h `/ai/explain` attributed from NaN | ✅ refuses undefined vectors; `timestamp` now reaches the feature engineer |

**Phase 1 is done** — branch `feat/phase1-deployment-foundation`, one commit per
item, every procedure executed on the running stack before being written down.
Gates: **ruff clean, mypy clean, 679 passed / 48 skipped** (from 506).

| Item | Status |
|---|---|
| 1.4 Migrations raced across replicas | ✅ one-shot `migrate` job; advisory lock in Alembic (3 concurrent migrators: 1 survivor before, 3 after); API refuses a schema that is behind, warns on one that is ahead |
| 1.2 Secrets in the environment | ✅ files at `/run/secrets`; compose blanks the variables so `.env` leftovers cannot leak; `docker inspect` shows every secret EMPTY |
| 1.2 Key rotation | ✅ `SECRET_KEY_PREVIOUS`; a session from before a rotation stayed 200 until `--finish`, then 401 |
| 1.1 Plaintext everywhere | ✅ HTTPS only, TLS 1.2/1.3, HSTS; port 80 redirects; found and fixed: static assets were served with **no** security headers |
| 1.5 No resource limits | ✅ memory/CPU/pids on every service, sized from measurement; postgres settings pinned so `timescaledb-tune` cannot size it to the host |
| 1.3 No backups | ✅ 6-hourly `pg_dump` sidecar; TimescaleDB-aware restore; rehearsal compares every table and CI runs it on every push; live restore measured at 32 s |
| 1.5 Nothing published | ✅ `release` job: build → Trivy image scan (blocking) → GHCR, `sha-<commit>` tags; `deploy.sh` with smoke test and automatic rollback, proven against a broken release |

Two results worth more than the green: the image scan, run before it was made
a gate, found two HIGH findings in pip's vendored `msgpack` and `setuptools`,
so the runtime image no longer ships pip; and the first deploy proof used port
5000, which macOS AirPlay holds, so compose found the images locally and the
pull path went untested until the registry was moved.

What Phase 1 commits to: RPO 6 h, RTO about a minute at today's size. What it
does not pretend to: a real certificate (needs a domain), a server to deploy to
(the last hop is a script on the host), minute-level RPO (needs a bucket).

**Phase 2 is done** — branch `feat/phase2-observability`, one commit per item.
Gates: **ruff clean, mypy clean, 752 passed** (from 684 at the end of Phase 1),
frontend 107/107.

| Item | Status |
|---|---|
| 3.3 Deprecated `on_event` hooks | ✅ lifespan; shutdown cancels and awaits the loops, measured: container stops in 1 s, exit 0 |
| 2.2 `/health` lied about the database | ✅ `/ready` probes postgres, Redis and the loops with deadlines; repeated the experiment: 503 within 5 s of stopping postgres, container **unhealthy** at 30 s, back within 10 s, **0 restarts** |
| 2.3 Bare background tasks | ✅ supervisor: restart with backoff, recreate on any exit, tick timestamps; a stalled loop is a 503 on `/ready` |
| 2.1 Nothing measured | ✅ `/metrics`: requests by route template, ingest and detection outcomes, incidents by tier, pool, sockets, loops; the first live scrape caught a labelling bug the unit test had passed |
| 2.1 Nothing to scrape it | ✅ `--profile observability` Prometheus with seven alert rules, each with a next step; target up and rules loaded, verified live |
| 2.4 Errors vanish into a 500 | ✅ optional Sentry with credentials scrubbed before send; not verified against a real project (needs a DSN) |
| 2.4 Audit table grows forever | ✅ daily `audit-retention` loop through the append-only table's maintenance flag, one statement, `SET LOCAL` |

What Phase 2 does not pretend to: a Sentry project (needs a DSN), multi-worker
metrics (`PROMETHEUS_MULTIPROC_DIR` is a deliberate later step), and an
alerting *receiver* -- the rules fire inside Prometheus; where they go (email,
chat, pager) is the operator's choice and configuration.

Two results worth more than the green: the concurrency test was run with the
lock disabled and produced **2 rows instead of 1**, so it has teeth; and
`EXPLAIN` shows the planner doing an **Index Scan on the new composite index**
for `/telemetry/latest`, not a sort of the table.

Still deliberately open from 0b: moving the WebSocket token out of the URL
altogether; wiring MAVLink telemetry into the detection pipeline; routing
heartbeat-raised incidents through the incident engine. Each is a behaviour
change that did not belong inside the fix next to it.

Everything in Phases 1–3 below is still outstanding.

---

## Verdict

**The application is built. The system around it is not.**

SwarmGuard passes every gate its own CI defines, boots cleanly, and does what it
claims — I drove a GPS spoof through the live API and got a CRITICAL incident
with checkable arithmetic behind it, delivered over a WebSocket in under a
second. Then I ran the 12-drone simulator against the Docker stack: **315
packets, 13 drones, 3 incidents, zero false positives on nominal flight.** The
detector's central claim holds under test.

What is missing is not architecture. It is **operations**: there is no TLS
anywhere, no backup, no metrics, no resource limits, no deployment pipeline, and
no secrets management. Plus two genuine correctness blockers that need code.

Realistic timeline to a defensible production deployment: **5–7 weeks** for one
engineer, or **3 weeks** for two.

| Phase | Theme | Effort | Blocking? |
|---|---|---|---|
| **0** | Correctness blockers | 3–5 days | **Yes** |
| **1** | Deployment foundation | 1.5–2 weeks | **Yes** |
| **2** | Observability | 1 week | **Yes** |
| **3** | Hardening & scale | 1.5 weeks | Strongly advised |
| **4** | Research & product | ongoing | No |

---

## Phase 0 — Correctness blockers (3–5 days)

Nothing ships until these four are closed.

### 0.1 — The audit trail silently discards every ingest ⛔ **BLOCKER**

**Evidence.** On the production-shaped Docker stack, after the simulator run:

```
 telemetry_rows | ingest_audit_rows | all_audit_rows
----------------+-------------------+----------------
            315 |                 0 |              3
```

315 device-authenticated ingests. Zero audit records.

**Mechanism.** `backend/services/audit_service.py:50` adds the row and
deliberately does not commit:

```python
db.add(audit)
# We don't commit here. Let the calling transaction commit
# so that the incident creation and audit log are atomic.
```

That contract works for routers that commit afterwards. `routers/telemetry.py`
does not. `telemetry_service.process_telemetry()` commits the **packet** first
(`telemetry_service.py:44`), then `audit_service.log_from_context()` runs
(`routers/telemetry.py:69`), then the handler returns. `get_db`'s
`finally: db.close()` rolls the pending INSERT back.

**Why it matters.** `docs/SECURITY.md:35` names "Immutable `AuditLog` database
entries" as the mitigation for *Unauthorized Action Repudiation*. The highest-
volume, most security-relevant event in a defence product writes no record at
all. For a system whose value proposition is forensic defensibility, this is the
single most serious finding in this report.

**The trap.** Do *not* just add `db.commit()`. At the documented 50 req/s ingest
limit that becomes **~4.3 million audit rows per day** on a table with no
retention policy and — see 0.4 — a redundant duplicate index making every insert
more expensive. You would trade a silent failure for a disk-exhaustion outage.

**Recommended fix** — decide the policy first, then implement:

1. **Do not audit routine ingest per packet.** It is telemetry, not an
   administrative action, and `telemetry_logs` is already the record of it.
   Remove the call from the hot path.
2. **Do audit the security-relevant ingest events**: device-key rejections
   (currently only a log line at `routers/telemetry.py:44`), first-seen drones,
   and tenant mismatches. These are low-volume and genuinely forensic.
3. **Make the contract explicit** so this cannot recur. Either rename to
   `audit_service.stage()` to signal that the caller owns the commit, or add a
   `commit: bool = False` parameter. Silent no-ops are the failure mode here.
4. **Add a regression test**: ingest a packet, assert the expected audit rows
   exist. Nothing currently covers this — `test_audit` passes while the bug is
   live.

**Effort:** 1 day including the policy decision and tests.

---

### 0.2 — A Redis outage takes down authentication ⛔ **BLOCKER**

**Evidence.** Observed directly. With `REDIS_URL` configured and Redis stopped:

```
POST /auth/login -> 500
{"error":"Internal Server Error","detail":"An unexpected error occurred."}

redis.exceptions.ConnectionError: Error 61 connecting to localhost:6379.
Connection refused.
```

**Mechanism.** `utils/limiter.py` correctly falls back to in-memory storage when
`REDIS_URL` is *unset* — but there is no handling for it being *set and
unreachable*. slowapi's storage backend raises, and `main.py`'s catch-all
handler turns it into a 500. Every rate-limited route fails: login, ingest,
everything.

Compose's `depends_on: redis: condition: service_healthy` only covers **start**.
A Redis restart, failover, or network blip at any point afterwards locks every
operator out of the product.

**Fix.** Rate limiting must fail **open**, loudly:

```python
# main.py — ahead of the generic Exception handler
@app.exception_handler(redis.exceptions.RedisError)
async def _limiter_storage_down(request, exc):
    logger.error(f"Rate limiter storage unavailable, failing open: {exc}")
    return await call_next(request)   # serve the request; alert on the log
```

Pair it with `slowapi`'s `swallow_errors=True`, a Redis health signal on
`/system/health`, and an alert. A brief window of unlimited login attempts is a
smaller risk than a total authentication outage — but only if you *know* it is
happening, hence the alert.

**Effort:** half a day.

---

### 0.3 — The live security suite never runs, anywhere ⛔ **BLOCKER**

**Evidence.** All six tests in `tests/test_sprint7_security.py` skip when nothing
is listening on `:8000`:

```
SKIPPED [6] No server reachable at http://localhost:8000
```

`.github/workflows/ci.yml` never starts a server. **CI has been green while this
entire suite — auth, RBAC, tenant isolation, audit, rate limiting, the command
framework — has never executed.**

Worse, it cannot pass as a suite even with a live server. Every test logs in; the
limit is 5/minute; tests 3–6 always skip. I reproduced exactly that: **2 of 6
ran.** Running them one per rate-limit window, **all 6 pass** — so the code is
fine. The *test harness* is broken, and it is broken in the silent direction.

**Fix.**
1. Add a CI job that boots the stack (`docker compose up -d --wait`) and runs
   this file against it.
2. Make the skip **fail** in CI: `if os.getenv("CI"): pytest.fail(...)`. A skip
   that means "we never checked" must not read as green.
3. Give the suite its own rate-limit budget — a dedicated test user per test, a
   raised limit under a test flag, or a fixture that resets the counter.

**Effort:** 1 day.

---

### 0.4 — Audit table: no immutability, duplicate index, redundant column

Three defects in one table, all verified against the live schema.

**No immutability.** `docs/SECURITY.md:35` says "Immutable". There are zero
triggers or rules on `audit_logs`:

```sql
SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
 WHERE c.relname='audit_logs' AND NOT tgisinternal;
-- (0 rows)
```

Any `UPDATE` or `DELETE` succeeds. Either enforce it — a `BEFORE UPDATE OR
DELETE` trigger that raises, plus revoking those grants from the app role — or
correct the claim in the docs. Claiming a control you do not have is worse than
not having it.

**Duplicate index.** `ix_audit_logs_actor` and `ix_audit_logs_username` are both
`btree(actor)`. Two identical indexes, paid for on every insert. Drop one.

**Redundant column.** The table carries both `created_at` and `timestamp`, each
defaulting to `now()`. Pick one; migrate the other away.

**Effort:** 1 day including the migration.

---

## Phase 0b — Blockers found by the audit (✅ all fixed)

A 126-agent audit ran across eight dimensions with adversarial verification
after Phase 0 was implemented. Four of its blockers were fixed with Phase 0; the
rest are below, each verified by reading the cited code, ordered by how badly
they hurt. **All are now fixed** — see the status table at the top. The
descriptions are kept as the record of what was wrong.

### 0b.1 — Tier 1 measures network arrival, not flight ⛔

`kinematic_guard._interval_seconds` (`kinematic_guard.py:295`) reads
`created_at`, which is the **database insert time** — a server default, set when
the row lands, not when the airframe sampled. Every rate the guard computes
(implied ground speed, climb rate, GNSS/airframe mismatch) is therefore divided
by *packet arrival cadence*.

Tier 2 is disabled, so this guard is the entire detection capability. The
consequence cuts both ways: a spoofer who paces their packets widens `dt` and
suppresses the alert, while ordinary network delay or a retry burst narrows it
and manufactures one. The demo works because packets arrive promptly on a
loopback; a real link is not that.

**Fix:** add a device-supplied sample time to `TelemetryPacket`, persist it, and
divide by that — falling back to `created_at` only when absent, and saying so in
the incident evidence. This is the single most important correctness item left.

### 0b.2 — The rate limiter is trivially defeated ⛔

`docker-compose.yml` publishes the backend on `8000:8000`, so nginx is not the
only ingress, and `entrypoint.sh:24` passes `--forwarded-allow-ips "*"`. uvicorn
therefore trusts `X-Forwarded-For` from any peer. The `5/minute` login limit
keys on that header, so rotating it per request gives unlimited password
attempts. The same header is what the audit trail records as the source IP.

**Fix:** `expose: 8000` instead of `ports:`, and pin `FORWARDED_ALLOW_IPS` to the
frontend container's address.

### 0b.3 — Docker ignores every documented tuning variable ⛔

`docker-compose.yml:48-59` enumerates the environment it passes and has no
`env_file:`. The README tells operators to raise `GUARD_MAX_SPEED_MPS` for
fixed-wing; set it in `.env`, restart, and the container silently keeps the
60 m/s multirotor default. The safety-relevant Tier 1 thresholds are
unreachable under the recommended deployment.

**Fix:** add `env_file: .env` to the backend service.

### 0b.4 — Alert suppression is a check-then-insert race

`alert_service.py:155` checks for a recent incident, then inserts. Two
concurrent detections for one drone both find nothing and both insert. Related:
suppression matches against *resolved* incidents too, so an operator who
resolves a still-active spoof gets no further alert for 60 s; and an escalation
from MEDIUM to CRITICAL inside the window updates the database without
broadcasting, so the dashboard keeps showing the lower severity.

**Fix:** a partial unique index on `(organization_id, drone_id)` for live
statuses, catching `IntegrityError` as "suppressed"; scope the suppression query
to live statuses; broadcast on severity change.

### 0b.5 — Smaller, but real

| Finding | Location |
|---|---|
| `system_settings.organization_id` declares UNIQUE in the model; no migration creates it, so duplicate rows per tenant are possible | `models.py:158` |
| Any user can set their email to another tenant's **username**, and login resolves either — an account-lockout vector | `routers/users.py:72` |
| The JWT is passed in the WebSocket query string and written to the nginx access log in cleartext | `websocket.ts:75`, `nginx.conf:46` |
| Healthchecks declare no `start_period`, so a slow first migration marks the backend permanently unhealthy | `docker-compose.yml:63` |
| WebSocket reconnects every ~31 s on an idle feed — the backend never answers the client's ping | `websocket.ts:88` |
| MAVLink ingest runs a blocking `psycopg2` INSERT on the asyncio event loop | `mavlink_receiver.py:148` |
| `/telemetry/latest` sorts the whole org-scoped hypertable with no LIMIT; `/incidents/stats` loads every incident into Python | `telemetry.py:93`, `incidents.py:114` |
| `/ai/explain` returns a high-confidence attack attribution computed from NaN features during warm-up | `explanation_service.py:155` |

---

## Phase 1 — Deployment foundation (✅ done)

Nothing here existed when this was written; the descriptions below are kept as
the record of what was missing. Status, evidence and what was found on the way
are in the Phase 1 table near the top of this document and in
`05-PHASE1-3-EXECUTION-PLAN.md`; the operating procedures are in
`docs/OPERATIONS.md`.

### 1.1 — TLS everywhere ⛔

`frontend/nginx.conf` has no `listen 443`, no `ssl_certificate`. The stack
publishes **port 80, plaintext**. JWTs, telemetry and the device API key all
cross the wire in the clear.

For a system whose entire premise is that GPS data can be tampered with in
transit, shipping its own control plane unencrypted is not a defensible position.

- Terminate TLS at nginx or an ingress; cert-manager/Let's Encrypt or your PKI.
- Redirect 80 → 443; add HSTS.
- `wss://` for the socket — `frontend/src/config.ts` already derives this from
  `window.location.protocol`, so it needs no code change.

### 1.2 — Secrets out of the compose file ⛔

`SECRET_KEY` and `DRONE_API_KEY` are plain environment variables in
`docker-compose.yml`, readable via `docker inspect` and every process listing.

Move to Docker secrets, Vault, or your cloud's secret manager. Then add **key
rotation** — note that rotating `SECRET_KEY` invalidates every JWT, and
`DRONE_API_KEY` is a single shared secret for the entire fleet (see 3.2).

### 1.3 — Backups and restore ⛔

Zero hits for `pg_dump`, `pgbackrest`, `wal-g` anywhere in the repo. There is no
backup, and therefore no tested restore.

- Continuous archiving (WAL-G / pgBackRest) against TimescaleDB.
- **Rehearse the restore.** An untested backup is a hypothesis.
- Define and document the RPO/RTO you are actually committing to.

### 1.4 — Migrations must not race

`backend/entrypoint.sh` runs `alembic upgrade head` on **every container start**.
One replica: fine. Two or more starting together: concurrent DDL on the same
database.

Move migrations to a dedicated job/init-container that runs once, and have the
app container refuse to start if the schema is behind.

### 1.5 — Resource limits and a real deploy pipeline

`docker-compose.yml` sets no `mem_limit`, no `cpus`, no `deploy.resources`. The
backend image is **1.59 GB** and loads sklearn, shap, pandas and numba — an
unbounded memory profile with nothing to contain it.

CI today builds and tests but **never publishes an image**. There is no registry
push, no tagging, no environment promotion, no rollback. Add: build → scan → push
with an immutable tag → deploy → smoke-test → automatic rollback.

**Effort:** 1.5–2 weeks.

---

## Phase 2 — Observability (✅ done)

The descriptions below are kept as the record of what was missing; status and
evidence are in the Phase 2 table near the top.

Zero hits for `prometheus`, `opentelemetry`, or `statsd` in the backend. Logging
is structured JSON (good), but that is the whole of it. Today you would learn the
system is down from a user.

### 2.1 — Metrics

Instrument, at minimum:

- ingest rate, latency, error rate
- detection-pipeline duration and failure count
- incidents raised, by tier and severity
- DB pool utilisation — the pool is tuned to exactly `2 × 50 req/s` in
  `backend/database.py`, and that reasoning is untested under load
- WebSocket connections and broadcast fan-out latency
- background-task liveness (see 2.3)

### 2.2 — Split liveness from readiness ⚠️ **verified by experiment**

`/health` returns `{"status":"ok"}` unconditionally — it does not touch the
database. The compose healthcheck uses exactly that endpoint.

I tested this on the running stack by stopping Postgres:

```
--- BASELINE (postgres up) ---
postgres container : 1 running
backend status     : Up 16 minutes (healthy)
/health            : HTTP 200
/auth/login        : HTTP 200

--- POSTGRES STOPPED (t+8s) ---
postgres container : 0 running
backend status     : Up 17 minutes (healthy)   <-- still healthy
/health            : HTTP 200                  <-- still green
/auth/login        : HTTP 500                  <-- actually dead

--- POSTGRES STOPPED (t+53s, past the 30s x 3 healthcheck window) ---
postgres container : 0 running
backend status     : Up 17 minutes (healthy)   <-- never flips
/health            : HTTP 200
/auth/login        : HTTP 500

--- POSTGRES RESTARTED ---
/auth/login        : HTTP 200                  <-- recovers cleanly
```

**The container advertises itself as healthy while the product is completely
non-functional, and it never stops doing so** — I waited past the full
`interval: 10s × retries: 3` window and the status never changed. Docker will not
restart it; a load balancer will keep routing to it; an orchestrator will happily
scale it. The only signal is user complaints.

The good news from the same experiment: once Postgres returns, the backend
recovers on its own with no restart. `pool_pre_ping=True` in
`backend/database.py` is doing its job. The defect is purely the *signal*, not
the resilience.

`/system/health` *does* check the DB, but it requires authentication and returns
`DEGRADED` with HTTP **200**, so no orchestrator can act on it either.

Add an unauthenticated `/ready` that checks DB + Redis and returns a non-2xx
when either is down. Point the compose and orchestrator readiness probes at it.

### 2.3 — Supervise the background tasks

`main.py` starts `periodic_heartbeat_check` and `periodic_database_cleanup` with
`asyncio.create_task`. Both loops catch `Exception` and continue — but an
unexpected exit, cancellation, or a `BaseException` kills the loop silently. The
heartbeat monitor is what detects silent (possibly jammed) drones. Its death is
indistinguishable from "no drones are jammed".

Add a supervisor that restarts them and a metric that alerts if a loop has not
ticked.

### 2.4 — Error tracking and audit retention

Wire Sentry or equivalent — `main.py`'s catch-all currently converts every
unhandled exception into an opaque 500 with no aggregation. And once 0.1 is
fixed, `audit_logs` needs the retention policy `telemetry_logs` already has.

**Effort:** 1 week.

---

## Phase 3 — Hardening and scale (1.5 weeks)

### 3.1 — Replace the retention DELETE with `drop_chunks`

`main.py:96` runs, hourly and unbatched:

```python
db.query(models.TelemetryLog).filter(
    models.TelemetryLog.created_at < cutoff).delete()
```

On a TimescaleDB hypertable at 50 req/s, that is a long transaction holding locks
and generating dead tuples for autovacuum to chase. Use a native retention
policy:

```sql
SELECT add_retention_policy('telemetry_logs', INTERVAL '3 days');
```

Then verify the hypertable and compression policy are actually configured — the
initial migration creates the hypertable, but nothing sets compression.

### 3.2 — One shared device API key for the entire fleet

`DRONE_API_KEY` is a single global secret (`config.py`). Every drone holds the
same one. One compromised airframe compromises fleet-wide ingest, and there is no
revocation short of rotating the key for everyone simultaneously.

Move to per-device credentials with individual revocation. mTLS is the right
long-term answer for airborne assets.

### 3.3 — Migrate off deprecated APIs

`@app.on_event("startup")` / `("shutdown")` are deprecated in this FastAPI
version. Move to the `lifespan` context manager — this also gives you a clean
place to implement graceful shutdown (drain in-flight detections, close sockets).

### 3.4 — Timezone-aware datetimes

`pyproject.toml` disables `DTZ003`/`DTZ005` with a note that it is a schema
decision. It is, and it is a real one: every column is naive, and
`datetime.utcnow()` is used throughout. For a forensic system whose incidents may
be evidence, ambiguous timestamps are a liability. Migrate to `timestamptz`.

### 3.5 — Load-test the assumptions

The pool sizing, the 50 req/s limit, and the 10 Hz broadcast fan-out are all
carefully *reasoned* in comments and **never measured**. Run a real load test at
the documented rate with a realistic fleet size and see what actually breaks.

### 3.6 — Turn the advisory CI gates on

`pip-audit` and `npm audit` both run with `continue-on-error: true`. The comment
says this is deliberate until the first triage pass. Do the triage pass and flip
them — an advisory security gate is a gate nobody reads.

**Effort:** 1.5 weeks.

---

## Phase 4 — Research and product (ongoing, not blocking)

Taken from the README's own roadmap, which is well reasoned. Do not let this
compete with Phases 0–2.

1. **Per-flight normalisation.** The LOFO collapse is the central open problem.
   Normalising each feature against the flight's own early-window baseline is the
   most direct attack on flight-identity leakage.
2. **More flights.** Nine is thin, and with `attack_type` 1:1 with `flight_id`
   every fold is single-class. This may be the binding constraint, not the model.
3. **Extend `TelemetryPacket` with MAVLink link statistics**
   (`heartbeat_gap`, `link_data_rate`), then retrain to cover jamming and Ping
   DoS properly. Currently out of scope for the correct reason.
4. **Widen Tier 1** — IMU/GNSS cross-checks, geofence rate limits. Given Tier 1
   is carrying the product and measurably produces no false positives, this is
   likely a better return than Tier 2 work.
5. **Drift monitoring and scheduled retraining.**
6. **Command approval workflow** — schema exists, UI does not.

**Guard rail:** `AI_INCIDENTS_ENABLED` stays `false` until LOFO F1 and false-
positive rate are defensible. Write that threshold down now, before anyone is
tempted to flip it for a demo.

---

## Documentation corrections (half a day, do them now)

Cheap, and they protect the project's most valuable asset — its credibility.

| Issue | Location | Correction |
|---|---|---|
| **Stale headline ML metric** | `.env.example:57`, `services/kinematic_guard.py:6`, `services/detection_pipeline.py:105` | All three say **F1 0.041 / FPR 0.813**. The authoritative `models_ml/v2/evaluation.json` says **F1 0.086 / FPR 0.862**. README, `config.py` and `AI_ARCHITECTURE.md` already have it right. |
| **"Full documentation"** | `README.md` → `docs/API_REFERENCE.md` | 98 lines covering **2 of 40** routes. Either finish it or point at the OpenAPI schema at `/docs`. |
| **"Immutable" audit log** | `docs/SECURITY.md:35` | Not enforced (see 0.4). Enforce it or reword it. |
| **`packet_sequence` is required** | `docs/API_REFERENCE.md` | Undocumented; omitting it yields an unhelpful 422. |
| **Frontend env example contradicts the design** | `frontend/.env.example` | `VITE_API_BASE_URL=http://localhost:8000` breaks the `connect-src 'self'` CSP in `nginx.conf`. The same-origin default is correct — the example teaches the wrong thing. |
| **Empty CHANGELOG** | `CHANGELOG.md` | Still says "Initial project structure" after 20+ substantive commits. |
| **v1 model is non-functional** | `models_ml/v1/evaluation.json` | Pooled F1 is **0.0**. It ships in the registry. Delete it or mark it clearly. |

**Repository hygiene:** `dump.py`, `dump_filtered.py`, `dump_clean.py`,
`test_main.py` and `scratch/` are at the repo root and are not part of the
product. `backend/swarmguard.db` is a committed SQLite file in a codebase that
refuses to run on SQLite. `backend/utils/incident_generator.py` is imported only
by a test.

---

## Definition of done

Production-ready when every box is ticked:

**Correctness**
- [ ] Ingest audit policy decided, implemented, and covered by a test
- [ ] Rate limiter fails open on a Redis outage, with an alert
- [ ] Live security suite runs in CI and **fails** rather than skips
- [ ] Audit table: immutability enforced (or claim withdrawn), duplicate index dropped

**Infrastructure**
- [x] TLS end to end; HTTP redirects; HSTS
- [x] Secrets in a manager, with a documented rotation procedure
- [x] Automated backups with a **rehearsed** restore
- [x] Migrations run once, not per replica
- [x] Resource limits on every container
- [x] Deploy pipeline with immutable tags and rollback

**Observability**
- [x] Metrics on ingest, detection, incidents, pool, sockets
- [x] `/ready` separate from `/health`, returning non-2xx when degraded
- [x] Background tasks supervised and alerting
- [x] Error tracking wired up

**Operations**
- [ ] Load test at the documented ingest rate
- [ ] Runbook: what each alert means and what to do
- [ ] Incident-response process for the security product itself

---

## Closing note

The reason this roadmap is mostly infrastructure rather than rewriting is that
**the hard part is already done and done well.** The tenancy model is enforced in
depth and proven by a route-walking test. The detector works and — measurably, on
~300 packets of simulated nominal flight — does not false-positive. The team
measured their own ML model, found it did not generalise, and shipped it
**disabled**, which is the correct call and a rarer one than it should be.

What has not happened yet is that nobody has had to *operate* this. Phases 0–2
are the cost of that, and they are ordinary, well-understood work.

Do Phase 0 this week. Item 0.1 in particular: a security product that silently
discards its own audit trail is a credibility problem long before it is a
technical one.
