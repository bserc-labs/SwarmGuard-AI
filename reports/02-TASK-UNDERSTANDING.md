# Task Understanding & Execution Report

*What was asked, how I read it, what I actually did, and what the evidence was.*

**Date:** 2026-09-20 / 21
**Target:** `SwarmGuard-AI` @ `main` (`06b21ca`), clean working tree at start

---

## 1. The request, as given

> "check run the project and build the roadmap how to build and fix the project
> to production and make two report one for task understanding and one report
> for me to understand the project better"

## 2. How I read it

I split this into four deliverables:

| # | Deliverable | Interpretation |
|---|---|---|
| 1 | **Check / run the project** | Actually execute it — not read the README and infer. Build both apps, run both test suites, boot the stack, drive real traffic through it. |
| 2 | **Roadmap to production** | An ordered, costed plan covering both *how to build/deploy it* and *what to fix first*. Ordered by risk, not by ease. |
| 3 | **Task-understanding report** | This document: what I understood, how I worked, and what evidence backs each claim. |
| 4 | **Project-understanding report** | An orientation guide so you can reason about the codebase without re-deriving it. |

**Judgement calls I made without asking:**

- **"Run the project" means prove it works, not prove it starts.** A health check
  passing proves very little. I drove an actual GPS-spoofing attack through the
  ingest API and confirmed a CRITICAL incident came out the other end with
  evidence an analyst could check by hand. That is the product's whole claim.
- **"To production" means a real deployment, not a better demo.** So TLS,
  backups, secrets management, observability and a deploy pipeline are in scope
  even though nothing in the repo mentions them.
- **I kept code changes to near zero.** You asked for a roadmap and reports, not
  a refactor. I changed exactly one file, and only because the Docker build could
  not complete without it (§6).

## 3. Method

Deliberately **empirical first, analytical second**. Reading a codebase tells you
what the authors intended; running it tells you what it does. The most valuable
finding in this whole exercise — a silently discarded audit-trail write — is
invisible on inspection and obvious after one `SELECT`.

Order of work:

1. **Survey** — layout, dependency manifests, CI definition, git history.
2. **Build** — frontend and backend from a cold start, on the pinned toolchain.
3. **Verify** — every gate CI runs, run locally: tests, lint, types, build.
4. **Operate** — boot the stack, authenticate, ingest telemetry, inject an
   attack, observe the incident, watch the WebSocket.
5. **Probe** — attack the things I had just seen work: bad tokens, missing
   device keys, cross-tenant reads, a dead Redis.
6. **Inspect** — read the hot paths, then cross-check documented claims against
   the artifacts that supposedly support them.
7. **Analyse in parallel** — a multi-agent audit across eight dimensions
   (security, correctness, ops, scale, frontend, infra, data, ML integrity),
   each finding put through adversarial verification before it was allowed to
   survive.

## 4. Environment

| | |
|---|---|
| Platform | macOS (darwin 25.6.0), Apple Silicon |
| Python | 3.12.12 via `uv` (system 3.14 is **too new** — `shap 0.52.0` has no wheels) |
| Node | 24.15.0 (CI uses 22) |
| Docker | 29.6.2, Docker Desktop |
| Postgres | `timescale/timescaledb:latest-pg16` on `:5433` |
| Redis | `redis:7-alpine` on `:6379` |

Secrets were generated locally into a gitignored `.env`. No real credentials
were used, created, or transmitted anywhere.

## 5. Evidence log

Everything below was executed. Nothing is inferred.

### Build & static gates

| Check | Result |
|---|---|
| `npm install` | ✅ 402 packages |
| `npm run lint` (eslint) | ✅ clean |
| `npm run typecheck` (tsc) | ✅ clean |
| `npm run build` (vite) | ✅ 816 modules, 213 ms |
| Backend deps on Python 3.12.12 | ✅ clean |
| `ruff check` | ✅ clean |
| `mypy` | ✅ clean, 30 files |
| `docker compose build` | ✅ after the `.dockerignore` fix (§6) |

### Database & tests

| Check | Result |
|---|---|
| `alembic heads` | ✅ single head `d4e5f6a7b8c9` — no branching |
| `alembic upgrade head` | ✅ all 7 migrations apply to an empty TimescaleDB |
| `pytest` | ✅ **366 passed, 50 skipped**, 1.13 s |
| `vitest` | ✅ **105 passed** (9 files), 1.25 s |
| Live security suite, run one-per-window | ✅ **6 / 6 pass** |

### Runtime behaviour

| Probe | Result |
|---|---|
| Backend boot | ✅ starts; MAVLink correctly disabled by default |
| `POST /auth/login` (valid) | ✅ `200`, JWT carrying `{sub, role, org_id, tv, exp}` |
| `POST /auth/login` (wrong password) | ✅ `401` |
| `GET /system/health` (garbage bearer) | ✅ `401` |
| `POST /telemetry/ingest` (no device key) | ✅ `403` |
| `POST /telemetry/ingest` (wrong device key) | ✅ `403` |
| Ingest 2 benign + 1 spoofed packet | ✅ all `200` |
| **Incident raised** | ✅ `GPS_SPOOFING / CRITICAL / score 100`, with observed-vs-threshold evidence |
| WebSocket, garbage token | ✅ rejected `403` at handshake |
| WebSocket, valid token | ✅ 3 telemetry frames **+ the incident**, pushed live |
| Frontend → backend via vite `/api` proxy | ✅ login returns a JWT |
| Tenant-scoped reads (5 routes) | ✅ all `200`, org-scoped |

### The documented Docker path

`docker compose up --build -d` — all four services (`postgres`, `redis`,
`backend`, `frontend`) came up **healthy**, and the whole smoke sequence above
repeated against them:

| Probe | Result |
|---|---|
| Frontend on `:80` | ✅ `200` |
| OWASP headers | ✅ CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy all present |
| nginx → backend (`/api/health`) | ✅ proxied correctly |
| Login, RBAC, device-key gates | ✅ identical to native |
| GPS spoof end to end | ✅ `GPS_SPOOFING / CRITICAL / 100.0` |

### The documented demo (`simulate_attack.py`)

Ran the 12-drone swarm simulator against the Docker stack for 40 s:

```
 telemetry_rows | drones | incidents
            315 |     13 |         3

    drone_id    |     attack_type     | severity | count
 DRONE-ALPHA-01 | SIGNAL_JAMMING      | HIGH     |     1
 SMOKE-01       | GPS_SPOOFING        | CRITICAL |     1
 SMOKE-01       | SIGNAL_LOSS_JAMMING | CRITICAL |     1
```

The simulator injected `SIGNAL_JAMMING` into `DRONE-ALPHA-01`; the system caught
it. The other ~300 packets were nominal flight across 12 drones and produced
**zero false positives** — which is a direct empirical confirmation of the
project's central claim for Tier 1.

**Conclusion on "does it run": yes, comprehensively.** The product does the thing
it claims to do, and the security controls it advertises are real and enforced.

## 6. The one change I made

`backend/.dockerignore` did not exclude virtualenvs. The README's own local-dev
instruction is `python -m venv venv` **inside `backend/`** — so following the
documentation poisons every subsequent Docker build.

Measured, before and after:

| | Before | After |
|---|---|---|
| Build context | **634.32 MB** | **12.06 kB** |
| `chown -R /app` layer | **251.6 s** | negligible |
| Outcome | I/O error on image export (disk exhaustion) | builds clean |

Added: `venv/`, `.venv/`, `ENV/`, `.mypy_cache/`, `.ruff_cache/`. I deliberately
did **not** also exclude `tests/`, which would have been a behavioural change you
did not ask for.

## 7. Findings, in brief

Detail and remediation are in `03-PRODUCTION-ROADMAP.md`. Severity is *my*
assessment; each was verified first-hand.

| # | Finding | Severity | How found |
|---|---|---|---|
| 1 | **`TELEMETRY_INGEST` audit rows are silently discarded.** `audit_service.log()` never commits by design; the ingest route never commits after it; `get_db`'s `close()` rolls it back. | **Blocker** | Ran the system, then `SELECT`ed: 6 telemetry rows, **0** ingest audit rows |
| 2 | **A Redis outage returns `500` from `/auth/login`.** The limiter's `ConnectionError` propagates to the global handler. Redis down ⇒ nobody can log in. | **Blocker** | Observed directly with Redis stopped |
| 3 | **The live security suite never runs in CI.** All 6 tests skip when nothing is listening on `:8000`; CI never starts a server. Green, and testing nothing. | High | Read CI, reproduced the skip, then ran them properly — 6/6 pass |
| 4 | **That suite cannot pass as a suite.** Every test logs in; the limit is 5/min; tests 3–6 always skip. | High | Only 2 of 6 ran in one pass, even against a live server |
| 5 | **Stale headline ML metric in 3 files.** Authoritative is F1 **0.086** / FPR **0.862**; `.env.example`, `kinematic_guard.py` and `detection_pipeline.py` all say **0.041 / 0.813**. | Medium | Cross-checked every claim against `v2/evaluation.json` |
| 6 | **No immutability on `audit_logs`**, despite `docs/SECURITY.md` calling entries "Immutable". No triggers, no rules. | Medium | Queried `pg_trigger` on the live schema |
| 7 | **Duplicate index + redundant column on `audit_logs`** — `ix_audit_logs_actor` and `ix_audit_logs_username` are both `btree(actor)`; `created_at` and `timestamp` both default `now()`. | Low | `\d audit_logs` |
| 8 | **`.dockerignore` shipped the venv** (fixed, §6). | High | Build failed |
| 9 | **No TLS, no backups, no metrics, no resource limits** anywhere in the stack. | High | Grepped the whole repo — zero hits for each |
| 10 | **`docs/API_REFERENCE.md` documents 2 of 40 routes** in 98 lines, and the README calls it "full documentation". | Medium | Counted route decorators vs the doc |
| 11 | **Retention `DELETE` is unbatched** on a hypertable, hourly, instead of `drop_chunks`. | Medium | Read `main.py` |
| 12 | **`@app.on_event` is deprecated** in this FastAPI version. | Low | Read `main.py` |
| 13 | **The container healthcheck lies.** With Postgres stopped, the backend still reports `(healthy)` and `/health` returns `200` — while `/auth/login` returns `500`. The status never flips, even past the full retry window. | High | Stopped Postgres on the running Docker stack and probed |

Finding 1 is the one to act on today. The product advertises "defence-grade
traceability" and its highest-volume, most security-relevant event — device-
authenticated data ingestion — writes no audit record at all. Note the tangle:
if you simply fix the commit, you get the *opposite* problem, because at the
documented 50 req/s ingest limit that is ~4.3 M audit rows per day against a
table with no retention policy. The fix is a decision, not a one-liner. See the
roadmap.

## 8. What I did not do

Stated plainly so you can judge the coverage:

- **No code fixes beyond `.dockerignore`.** You asked for a roadmap; the fixes
  are specified there, not applied.
- **No load or soak testing.** Pool sizing, the 10 Hz broadcast fan-out and the
  50 req/s rate limit are reasoned about from the code, not measured under load.
- **Only two failure modes injected** — Redis down and Postgres down. I did not
  test network partitions, slow dependencies, partial writes, or clock skew.
- **No browser-driven UI testing.** I verified the frontend builds, its 105 unit
  tests pass, it serves, and it authenticates against the real backend through
  the proxy. I did not click through all 13 screens.
- **No model retraining.** I read the evaluation artifacts and cross-checked the
  claims; I did not re-run LOFO validation.
- **No penetration testing.** I probed the specific controls listed in §5.
- **`simulate_attack.py` not exercised**, because it needs the full Docker stack
  on `:8000` and I used a native backend for most of the run.

## 9. Caveats on the environment

- **Your disk was full** — 202 GB of 228 GB, 844 MB free. The first Docker image
  export failed with an I/O error because of it. It later freed to 41 GB on its
  own. This is a machine condition, not a project defect, but it is why the
  Docker path took several attempts.
- **Node 24 locally vs 22 in CI.** Everything passed on 24; the delta is untested.
- **Python 3.14 is on your `PATH` and will not work.** `shap 0.52.0` has no wheels
  for it. Use 3.12.

## 10. How to reproduce any of this

```bash
# static gates
cd frontend && npm ci && npm run lint && npm run typecheck && npm run test && npm run build
cd ../backend && ruff check . && mypy

# database + suite
docker run -d --name sg-db -p 5433:5432 -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=password -e POSTGRES_DB=swarmguard_test \
  timescale/timescaledb:latest-pg16
export DATABASE_URL=postgresql://postgres:password@localhost:5433/swarmguard_test
export TEST_DATABASE_URL=$DATABASE_URL
export SECRET_KEY=$(openssl rand -hex 32) DRONE_API_KEY=$(openssl rand -hex 32)
alembic upgrade head && pytest

# finding 1, the audit-trail defect — the whole reproduction
#   1. boot the backend, log in, POST a few packets to /telemetry/ingest
#   2. then:
psql -h localhost -p 5433 -U postgres -d swarmguard_test \
  -c "SELECT count(*) FROM telemetry_logs;" \
  -c "SELECT action, count(*) FROM audit_logs GROUP BY action;"
#   telemetry rows: non-zero.  TELEMETRY_INGEST audit rows: zero.
```

## 11. Bottom line

The project **builds, runs, passes every gate its CI defines, and does what it
claims** — including catching a real GPS-spoofing pattern and pushing an
explainable incident to a live socket in under a second.

It is not production-ready, but the gap is narrower than it first looks and it is
mostly *operational* rather than *architectural*: TLS, backups, observability,
secrets management, a deploy pipeline. Those are absent, not wrong. Against that,
there are two genuine correctness blockers (findings 1 and 2) that need code.

The engineering judgement on display — particularly shipping the ML model
**disabled** because leave-one-flight-out validation said it does not generalise
— is better than most projects at this stage manage. The production discipline
has not caught up with it yet. That is what the roadmap addresses.
