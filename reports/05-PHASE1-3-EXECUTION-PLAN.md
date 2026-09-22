# Phases 1–3: what is wrong, what the fix is, and the order of work

Phase 0 and 0b made the application *correct*. Phases 1–3 make it *operable*:
something you can put on a server, leave running, and trust to tell you when it
is broken.

| Phase | One-line meaning | Items |
|---|---|---|
| **1 — Deployment foundation** | Can it be deployed safely at all? | TLS, secrets, backups, migrations, limits, release pipeline |
| **2 — Observability** | When it breaks, will you know before a user tells you? | metrics, `/ready`, supervised tasks, error tracking, audit retention |
| **3 — Hardening and scale** | Will it hold under load, and survive one stolen key? | retention policy, per-device keys, lifespan, timestamptz, load test, CI gates |

Every item below was re-checked against the code on `main` at `b5aed08` before
this was written. Where the roadmap was incomplete, the difference is marked
**Found while planning**.

---

## Phase 1 — Deployment foundation

### 1.1 TLS everywhere

**What is wrong.** nginx listens on port 80 only. Login passwords, JWTs, the
device API key and every telemetry packet cross the network as plain text.
Anyone on the path can read them or change them. For a product whose whole
claim is "GPS data can be tampered with in transit", that is not defensible.

**The fix.**
- nginx listens on 443 with TLS 1.2/1.3. Port 80 answers only a health probe
  and otherwise redirects to `https://`.
- `Strict-Transport-Security` (HSTS) so a browser that has seen the site once
  refuses plain HTTP afterwards.
- `X-Forwarded-Proto` is passed to the backend so it knows the original scheme.
- The certificate is **mounted**, not baked into the image: put `tls.crt` and
  `tls.key` in `./certs/`. If none is mounted the container generates a
  self-signed one at start and says so loudly, so `docker compose up` still
  works on a laptop. A self-signed certificate encrypts but does not prove
  identity; production must mount a real one.
- The WebSocket needs no change: `frontend/src/config.ts` already picks `wss://`
  when the page is `https://`.

**Proof.** A config test on `nginx.conf`, `nginx -t` inside the built image, and
a live check: HTTP gets a 301, HTTPS gets a 200 with the HSTS header.

### 1.2 Secrets out of the environment

**What is wrong.** `SECRET_KEY`, `DRONE_API_KEY` and the database password are
environment variables. `docker inspect swarmguard-backend` prints all three to
anyone with Docker access, and they appear in crash dumps and process listings.

**The fix.**
- Docker **secrets**: each value lives in a file under `./secrets/` (gitignored)
  and is mounted read-only at `/run/secrets/<name>`. The backend reads them from
  there; postgres uses its native `POSTGRES_PASSWORD_FILE`.
- The compose file sets `SECRET_KEY: ""` and `DRONE_API_KEY: ""` on purpose. An
  empty value means "unset" to the app, and `environment:` beats `env_file:`, so
  even a `.env` that still contains the secrets cannot leak them into the
  container's environment.
- `DATABASE_URL` no longer carries the password; it is supplied separately as
  `DATABASE_PASSWORD` from a secret file and joined in memory.
- `scripts/init-secrets.sh` creates the files, reusing the values already in
  `.env` so an existing database volume and existing logins keep working.
- **Rotation without an outage.** `SECRET_KEY_PREVIOUS` (optional): tokens are
  signed with the new key but still *verified* against the previous one until
  they expire. Without this, rotating the key logs every user out at once, which
  in practice means nobody ever rotates it.

Environment variables still work and still win, so native runs, CI and the test
suite are unchanged.

**Proof.** Tests for file loading, URL assembly, precedence, and both keys in
rotation; a compose test that fails if a secret reappears under `environment:`;
`docker inspect` on the live container showing empty values.

### 1.3 Backups and a rehearsed restore

**What is wrong.** There is no backup of any kind. One `docker volume rm`, one
disk failure, one bad migration, and every incident record is gone for good.

**The fix.**
- A `backup` service takes a compressed `pg_dump` on a schedule (default every
  6 hours), writes it to a volume or a directory you choose, and prunes old
  dumps (default 14 days).
- `scripts/restore.sh` does the restore **the TimescaleDB way**
  (`timescaledb_pre_restore()` → `pg_restore` → `timescaledb_post_restore()`).
  A plain `pg_restore` into a hypertable database fails or silently produces a
  broken catalogue, which is exactly the kind of thing you discover at 3 a.m.
- `scripts/rehearse-restore.sh` restores the newest dump into a scratch
  database, compares row counts table by table against the source, checks the
  hypertable is still a hypertable, and drops the scratch database. CI runs it
  on every push, because **an untested backup is a hypothesis**.

**What this commits to.** RPO (how much data you can lose) = the backup
interval, 6 h by default. RTO (how long a restore takes) = measured by the
rehearsal and recorded in `docs/OPERATIONS.md`. Minute-level RPO needs WAL
archiving (WAL-G or pgBackRest) to object storage, which needs a bucket this
project does not have yet. That is written down as the next step, not pretended.

### 1.4 Migrations must run once

**What is wrong.** Every container start runs `alembic upgrade head`. With one
replica that is fine. Start two together and both run the same DDL against the
same database at the same time: one crashes, or worse, both half-succeed.

**The fix, in three layers.**
1. A one-shot `migrate` service runs migrations and admin provisioning. The
   backend waits for it to finish successfully (`service_completed_successfully`).
2. Alembic takes a PostgreSQL **advisory lock** for the length of a run. Two
   migrators that do overlap (a rolling deploy, a human at a terminal) queue up
   instead of racing.
3. The API **refuses to start** if the database is not at the head revision the
   code was built with. New code on an old schema fails at boot, clearly,
   instead of failing on some request an hour later.

**Proof.** Two concurrent `alembic upgrade head` against an empty database both
succeed (today one fails); the API exits non-zero against a schema that is
behind.

### 1.5 Resource limits and a release pipeline

**What is wrong.** No container has a memory or CPU limit, and logs grow without
bound. The backend loads sklearn, SHAP and pandas; one runaway request can take
the host down with it. Separately, CI tests the code but never publishes an
image: there is nothing to deploy and nothing to roll back to.

**The fix.**
- Limits on every service, sized from measurement (backend idles at ~285 MiB,
  postgres ~110 MiB, redis and nginx ~10 MiB), plus log rotation and
  `no-new-privileges`.
- CI job, on `main` only and only after every other job is green: build both
  images → scan with Trivy → push to GHCR tagged with the **commit SHA**. A SHA
  tag is immutable: "what is running" always maps to one exact commit.
- `docker-compose.prod.yml` runs published images instead of building.
  `scripts/deploy.sh <tag>` pulls, migrates, starts, smoke-tests over HTTPS, and
  **rolls back to the previous tag automatically** if the smoke test fails.

**Honest limit.** There is no server to deploy *to* yet, so the last hop is a
script you run on the host rather than a button. Rolling an image back does not
roll a migration back; `docs/OPERATIONS.md` states the rule that makes that safe
(migrations must be backward compatible for one release).

---

## Phase 2 — Observability

### 2.1 Metrics

**What is wrong.** Nothing is measured. You cannot answer "how many packets per
second?", "how long does detection take?", "is the connection pool full?".

**The fix.** A Prometheus `/metrics` endpoint: request rate, latency and errors
per route; ingest accepted/rejected; detection duration and failures; incidents
by tier and severity; **database pool utilisation** (the pool was sized by
reasoning and never measured); WebSocket connections and broadcast latency;
last-tick time of each background task.

`/metrics` is not public: nginx returns 404 for `/api/metrics`, the backend port
is loopback-only, and an optional bearer token can be required.

### 2.2 `/ready` separate from `/health`

**What is wrong.** Verified by experiment earlier: stop postgres and `/health`
still says `ok`, the container stays "healthy" forever, and login returns 500.
The health check checks nothing.

**The fix.** `/health` stays as *liveness* ("the process is up"). New
unauthenticated `/ready` is *readiness*: it checks the database and Redis with
short timeouts and returns **503** when a dependency is down. The compose health
check points at `/ready`. The experiment is repeated to show the container now
flips to unhealthy.

**A judgement call, made explicit.** Redis down means no live alerts reach an
operator's screen, so by default it makes the instance not ready. With several
replicas behind a load balancer that choice can turn a partial outage into a
total one, so `READINESS_REQUIRES_REDIS=false` turns it into a reported warning.

### 2.3 Supervised background tasks

**What is wrong.** The heartbeat monitor is what notices a jammed, silent drone.
It runs as a bare `asyncio` task. If it ever exits, nothing restarts it and
nothing reports it, and "monitor is dead" looks exactly like "no drone is
jammed". For this product that is the worst possible silent failure.

**The fix.** A supervisor restarts a task that exits or raises, with backoff,
records each tick, and shuts down cleanly. A stalled monitor shows in `/metrics`
and fails `/ready`.

Includes roadmap **3.3**: the deprecated `@app.on_event` hooks move to a
`lifespan` context manager, which is where supervised start and graceful stop
belong.

### 2.4 Error tracking and audit retention

**What is wrong.** Unhandled exceptions become an anonymous 500 and a log line
nobody reads. And `audit_logs` grows forever.

**The fix.** Optional Sentry: set `SENTRY_DSN` and errors are grouped and
reported, with tokens and passwords scrubbed; unset, nothing changes. A daily
supervised task deletes audit rows older than `AUDIT_RETENTION_DAYS` (default
365, `0` = keep forever) through the maintenance flag the Phase 0 trigger
already requires, so immutability is untouched.

---

## Phase 3 — Hardening and scale

### 3.1 Retention by dropping chunks, not deleting rows

**What is wrong.** Every hour the app runs one huge `DELETE` on the telemetry
hypertable: a long transaction, locks, and millions of dead rows for vacuum.

**Found while planning.** The hypertable uses TimescaleDB's default **7-day
chunks**. A retention policy only drops a chunk when *all* of it is old enough,
so "3-day retention" on 7-day chunks really keeps up to **10 days**. The chunk
interval has to change too.

**The fix.** One migration: 1-day chunks, `add_retention_policy(3 days)`, and the
Python delete loop is removed. Dropping a chunk is a metadata operation: near
instant, no dead rows. Compression is deliberately **not** enabled: with 3-day
retention the saving is small, and compressed hypertables restrict future
schema changes.

### 3.2 Per-device credentials

**What is wrong.** Every drone holds the same `DRONE_API_KEY`. Steal one drone
and you can impersonate the whole fleet, and the only remedy is re-keying every
aircraft at once.

**The fix.** A `device_credentials` table: one random key per drone, stored only
as a hash, bound to its organization and drone id, individually revocable, with
last-used tracking. Admin API to issue (shown once), list and revoke. Ingest
accepts a per-device key and rejects it for any other drone id. The shared key
keeps working behind `DEVICE_SHARED_KEY_ENABLED` (default on) so nothing breaks
on upgrade; turn it off once the fleet is migrated. mTLS remains the long-term
answer and is noted as such.

### 3.4 Timezone-aware timestamps

**What is wrong.** Every timestamp column is "naive": it stores `12:00` without
saying *which* 12:00. The code assumes UTC everywhere, but the database does not
know that, and neither would a court reading an incident record.

**The fix.** Migrate every column to `timestamptz`, replace `datetime.utcnow()`
with an aware clock, and turn the two lint rules that were disabled for this
back on. This is last because it touches the most code; the frontend formatter
already handles zoned values.

### 3.5 Load test

**What is wrong.** Pool size, the 50 req/s limit and the 10 Hz broadcast are all
carefully argued in comments and have never been measured.

**The fix.** `scripts/loadtest.py` drives the documented rate with a realistic
fleet and live WebSocket listeners, and reads the new pool metrics while it
runs. Results, including whatever breaks, go in `reports/06-LOAD-TEST-RESULTS.md`.

### 3.6 Make the security gates real

**What is wrong.** `pip-audit` and `npm audit` run with `continue-on-error`. A
gate that cannot fail is a gate nobody reads.

**The fix.** Triage the current findings (upgrade, or ignore with a written
reason), then make both jobs blocking.

---

## Order of work

Three pull requests, one per phase, each a series of small commits.

| PR | Commits, in order |
|---|---|
| **Phase 1** | plan + roadmap correction → 1.4 migrations → 1.2 secrets → 1.2 key rotation → 1.1 TLS → 1.5 limits → 1.3 backups → 1.3 restore rehearsal in CI → 1.5 release pipeline → 1.5 deploy + rollback → operations guide |
| **Phase 2** | 3.3 lifespan → 2.2 `/ready` → 2.3 supervisor → 2.1 metrics (core, then pool/socket/task gauges) → 2.4 Sentry → 2.4 audit retention |
| **Phase 3** | 3.1 retention → 3.2 device credentials (schema, API, ingest) → 3.6 CI gates → 3.5 load test → 3.4 timestamptz |

1.4 goes first because TLS, secrets and backups all change how the stack starts,
and they should build on the final start-up sequence rather than the old one.

## What needs you, not code

| Needed | For | Until then |
|---|---|---|
| A domain name and a real certificate (Let's Encrypt or your PKI) | 1.1 | self-signed certificate, browser warning |
| A server | 1.5 | `deploy.sh` is tested locally and in CI only |
| An object-storage bucket | 1.3 minute-level RPO | 6-hour dumps on a volume |
| A Sentry project DSN | 2.4 | error tracking stays off |
| Re-keying real drones | 3.2 | shared key stays enabled |
