# Phase 0b — Execution Plan

*Nine verified blockers, fixed one at a time, one small commit each, gates green
after every commit. Built from a design pass in which every item was
independently re-verified against current `main` and then adversarially
critiqued; the critics' corrections are folded into each step below.*

**Branch:** `fix/phase0b-hardening` off `main` @ `499c042`
**Gate after every commit:** `ruff check` · `mypy` · `pytest` (388 passing at start) · `alembic heads` = one head
**Migration chain (in landing order):** `f6a7b8c9d0e1` → `g7b8c9d0e1f2` → `i9d0e1f2a3b4` → `j0e1f2a3b4c5`

---

## Order and rationale

Dependency first, then risk. Items 1–3 are the ones that change what the
product *does*; 4–9 close holes and remove foot-guns.

| # | Item | Commit subject | Migration | Est. |
|---|---|---|---|---|
| 1 | Ingress, forwarded headers, env passthrough, start_period | `fix(compose): make nginx the only ingress and pass .env through` | — | 1 h |
| 2 | Tier 1 divides by DB insert time | `fix(detection): rate physics on device sample time, not arrival time` | `g7b8c9d0e1f2` | 2–3 h |
| 3 | Alert suppression race / resolved-incident suppression / silent escalation | `fix(incidents): serialise per-drone writes, suppress only against live incidents, broadcast escalations` | — | 3–4 h |
| 4 | `system_settings.organization_id` unique in model, not DB | `fix(db): enforce one settings row per organization` | `i9d0e1f2a3b4` | 1 h |
| 5 | Email-collision account lockout | `fix(auth): resolve login by exact username before email` | — | 1 h |
| 6 | JWT in nginx access log; idle socket reconnects every 31 s | `fix(ws): answer keepalive pings and stop logging the socket token` | — | 1 h |
| 7 | MAVLink ingest blocks the event loop | `fix(mavlink): persist packets off the event loop` | — | 1 h |
| 8 | `/telemetry/latest` unbounded sort; `/incidents/stats` in Python | `perf(api): index the latest-per-drone read and aggregate stats in SQL` | `j0e1f2a3b4c5` | 2 h |
| 9 | `/ai/explain` attributes from NaN features | `fix(ai): refuse to explain an undefined feature vector` | — | 1 h |

Then: push → PR to `main` → merge → re-enable LiveReview hooks.

---

## 1. Ingress, forwarded headers, env passthrough, healthcheck start_period

**Defect (verified).** `docker-compose.yml:41-42` publishes the API on all
interfaces; `entrypoint.sh:24` runs uvicorn with `--forwarded-allow-ips "*"`.
uvicorn 0.52.1's `ProxyHeadersMiddleware` then takes the *first* hop of any
`X-Forwarded-For` as the client (`always_trust` path), so rotating that header
per request defeats the `5/minute` login limit and forges the audit IP.
`environment:` is an explicit list with no `env_file:`, so every `GUARD_*`,
`AI_INCIDENTS_ENABLED`, `MODEL_VERSION`, `LOGIN_RATE_LIMIT` in `.env` is silently
ignored in Docker — an operator raising the fixed-wing speed limit keeps the
multirotor default. Healthchecks have no `start_period`.

**Facts checked directly.** uvicorn parses `ip_network`/`ip_address` — a single
IP or CIDR works, `*` means trust-all. Compose network is `172.18.0.0/16`,
gateway `172.18.0.1`; trusting the `/16` would trust the gateway, which is
exactly where host-published traffic enters — so pin a **static IP** instead.
`environment:` overrides `env_file:` for the same key (tested with
`docker compose config`), so a native-run `.env` with `DATABASE_URL=…@localhost`
cannot clobber the in-network value.

**Change.**
- `docker-compose.yml`: user-defined network with a pinned subnet; frontend gets
  `ipv4_address`; backend `ports: "127.0.0.1:8000:8000"` (loopback only — keeps
  the documented demo, `/docs`, `simulate_attack.py`, `verify_demo.py` working
  unchanged, while nothing off-host can bypass nginx); `env_file: .env` on the
  backend **before** `environment:`; `FORWARDED_ALLOW_IPS` set to the frontend's
  static IP via a YAML anchor so the two cannot drift; `start_period` on all four
  healthchecks (backend 60 s for first migration).
- `backend/entrypoint.sh`: fallback changes from `*` to `127.0.0.1` so a
  misconfigured deploy fails closed, not open.
- `backend/tests/test_compose_contract.py`: parses `docker-compose.yml` and
  asserts the invariants (no `0.0.0.0` publish of 8000, `env_file` present,
  `FORWARDED_ALLOW_IPS` ≠ `*`, `start_period` on every healthcheck).

---

## 2. Tier 1 divides by DB insert time (0b.1)

**Defect (verified).** `kinematic_guard.py:295-300` `_interval_seconds` reads
`created_at` = server `now()` at insert. Every rate is `distance / arrival_dt`.
Tier 2 is off, so this is the whole detector.

**Change.** Optional bounded `sample_time_ms: int | None` (device monotonic
clock; MAVLink `time_boot_ms` is the canonical source) on `TelemetryPacket`;
nullable `BigInteger` column on `telemetry_logs` (migration `g7b8c9d0e1f2`,
`add_column` only — safe on a hypertable); passed through `_load_history` with
**arrival ordering unchanged** (device-time ordering evaluated and rejected:
reboots reset the clock). `_interval_seconds` prefers device interval when both
packets carry one and it is positive and sane, else falls back to arrival. The
verdict records `time_base: "device"|"arrival"` in incident evidence so an
analyst knows which clock rated it. MAVLink receiver populates it;
`simulate_attack.py` sends a monotonic ms so the demo exercises the path.

**Critic's correction applied.** The headline regression test must use a pair
that is *silent* under arrival time and *fires* under device time: 5,560 m jump
with `created_at` 300 s apart (18.5 m/s, silent) and `sample_time_ms` 2,000
apart (2,780 m/s, fires).

**Deferred, deliberately.** Tier 2 `time_delta` stays on `created_at` — the model
was trained on that definition and is disabled.

---

## 3. Alert suppression (0b.4)

**Defect (verified).** `alert_service.py:155-162` check-then-insert; matches
resolved/closed incidents; `incident_engine.py:122-130` escalation path returns
`None` so `detection_pipeline` never broadcasts.

**Change (no migration).** A transaction-scoped
`pg_advisory_xact_lock(organization_id, hashtext(drone_id))` in
`IncidentEngine` before the suppression check, dialect-gated so SQLite suites
are untouched — released by the commit every path already performs. Rejected
the partial unique index: the intended key (commit `1d17747`) is a 60 s window
per drone, not "one live incident per drone". `LIVE_INCIDENT_STATUSES` and a
status filter in `is_alert_suppressed`. `process_ai_detection` gains a
`record_detection` core returning `(incident, created)`; an escalation returns
the updated incident so `detection_pipeline` broadcasts it as
`INCIDENT_ESCALATED` with the same payload shape (`WebSocketContext.tsx`
keys alerts by `drone_id`, so the banner updates rather than duplicates).

**Critic's corrections applied.** Concurrency tests: daemon threads, commits in
`finally`, `Barrier(timeout=)`, and skip unless DB `TimeZone` is UTC (the
suppression cutoff compares a naive column against `utcnow()`).

---

## 4. `system_settings` uniqueness (0b.5a)

**Defect (verified on live DB).** Model declares `unique=True`; no migration
ever created it; `get_or_create_settings` is SELECT-then-INSERT.

**Change.** Migration `i9d0e1f2a3b4`: delete duplicates keeping the **lowest
id** (deterministic; logged), then create `ix_system_settings_organization_id`
UNIQUE with the model's exact name so autogenerate shows no drift.
`get_or_create_settings` catches `IntegrityError`, rolls back, re-selects.

---

## 5. Email-collision lockout (0b.5b)

**Defect (verified).** `auth.py:46-48` `or_(username == x, email == x).first()`
with no ORDER BY — EXPLAIN shows `Limit → Seq Scan`, so the lowest-ctid row
wins. `users.py:79-80` accepts any string as email.

**Change.** Two-step lookup: exact username first, email only if no username
matched. Light structural email validation (one `@`, dotted domain, ≤254,
blank→None) on `UserCreate` and `UserUpdate`. No `email-validator` dependency
added — deferred with reason.

---

## 6. WebSocket (0b.5c + 0b.5e)

**Defect (verified).** Client sends `{"type":"ping"}` every interval and closes
if nothing arrives within `staleAfterMs`; `routers/websocket.py:66-69` reads
and discards, never replies. Handshake URL carries the JWT; nginx logs it.

**Change.** `access_log off;` in nginx `/ws/`. Backend loop parses the ping,
**re-checks token expiry on each ping** (critic: the idle-reconnect was an
accidental expiry re-check; keep the property) and replies `{"type":"pong"}`,
which the client already treats as liveness. Moving the token out of the URL
(`Sec-WebSocket-Protocol`) is the real fix — specified, deferred: needs
coordinated client+server change and rewrites 14 passing vitest tests.

**Critic's correction applied.** A pre-accept 1008 renders as HTTP 403 →
browser close 1006, not 1008; test docstrings say so.

---

## 7. MAVLink blocking (0b.5f)

**Defect (verified).** `mavlink_receiver.py:148,225` calls sync
`process_telemetry` (psycopg2 INSERT+COMMIT) on the loop.

**Change.** Persist/deliver split exactly as `run_detection` does: sync
`_persist_packet` opens its own `SessionLocal()`, awaited via
`asyncio.to_thread`; broadcast scheduled on the loop after. **Scope trimmed per
critic:** wiring MAVLink into `run_detection` is a behaviour change, filed
separately, not bundled here. Test uses `ClassVar` for the fake session's
class-level list (ruff RUF012).

---

## 8. Query performance (0b.5g)

**Defect (verified; EXPLAIN on live DB: `Unique → Sort → Seq Scan`).**

**Change.** `/telemetry/latest`: drive from `drones` (one row per
`(organization_id, drone_id)` since `uq_drones_org_drone_id`) with
`JOIN LATERAL` for the newest packet; composite index
`(organization_id, drone_id, created_at DESC)` via migration `j0e1f2a3b4c5`.
`/incidents/stats`: `GROUP BY` aggregates producing **byte-identical JSON**
(all keys enumerated, `{"total": 0}` for an empty tenant), portable SQLAlchemy
so `test_tenant_isolation_live`'s SQLite still passes.

**Critic's corrections applied.** Seed test telemetry relative to `utcnow()` —
the retention sweep runs at app startup and would purge fixed 2026 dates. Do not
claim "no retention": telemetry keeps 3 days; the cost is ~13 M rows sorted on
every dashboard poll.

---

## 9. NaN explanations (0b.5h)

**Defect (verified).** `explanation_service.py:155-165` recomputes features
independently of `ai_service.predict`'s warm-up check and passes NaN to the
scaler and SHAP.

**Change.** Shared `undefined_features()` helper in `preprocess.py`; explain
returns `{"error", "status": "insufficient_data", "nan_features"}` on warm-up
or any NaN — before the scaler; `_score` raises on NaN so no caller can get a
prediction from an undefined vector. Router maps it to a clean 4xx. Tests use
`datetime.UTC` (ruff UP).

---

## Unattended run

If this is to run without you present, the LiveReview gate must be open first —
its token is expired and every commit is otherwise refused. Either
re-authenticate in the git-lrc UI, or `lrc hooks disable` in the repo and
re-enable after the merge.
