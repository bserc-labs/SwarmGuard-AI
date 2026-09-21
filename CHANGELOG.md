# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **The telemetry ingest audit trail was silently discarded.** `audit_service.log()`
  stages a row for the caller's transaction to commit; `/telemetry/ingest` staged
  one after `process_telemetry` had already committed, then returned, so
  `get_db`'s `close()` rolled it back. Measured on the compose stack: 315
  ingests, 0 audit rows. Routine ingest is no longer audited at all (a row per
  packet at 50 req/s is ~4.3M rows a day, and `telemetry_logs` is already the
  record); rejected device keys and first-seen drones are.
- **Silent-drone and RF-jamming alerts never reached an operator.** The heartbeat
  loop called `ws_manager.broadcast_secure()`, which does not exist. The
  AttributeError was swallowed by a bare `except Exception`, so CRITICAL
  `SIGNAL_LOSS_JAMMING` incidents were written and committed every 10 seconds
  and never broadcast.
- **A Redis outage returned `500` from `/auth/login`.** The rate limiter now
  falls back to in-process counters and fails open, and `/system/health` reports
  `DEGRADED` with a `rate_limiter` field so the degradation is visible.
- **`alembic revision --autogenerate` would have dropped every table.** `env.py`
  assigned `Base.metadata` to `target_metadata` without importing `models`, so
  autogenerate compared the live database against 0 registered tables.
- Stale headline ML metric in `.env.example`, `kinematic_guard.py` and
  `detection_pipeline.py` (F1 0.041 / FPR 0.813). The authoritative v2 numbers in
  `models_ml/v2/evaluation.json` are **F1 0.086 / FPR 0.862**.
- `docs/API_REFERENCE.md` listed three telemetry endpoints that do not exist,
  and described `/telemetry/ingest` as needing only a device key rather than a
  bearer token *and* a device key.
- `frontend/.env.example` recommended a cross-origin API URL that the
  `connect-src 'self'` CSP in `nginx.conf` blocks outright.
- `backend/.dockerignore` did not exclude virtualenvs, so following the README's
  own local-dev instructions made the Docker build context 634 MB and added a
  251-second `chown` layer.

### Added

- **Append-only enforcement on `audit_logs`** (migration `e5f6a7b8c9d0`). A
  `BEFORE UPDATE OR DELETE` trigger rejects UPDATE outright and permits DELETE
  only for a retention pass that sets `swarmguard.audit_maintenance` first.
  `docs/SECURITY.md` had claimed immutability; there were no triggers.
- **A CI job that runs the live security suite.** `test_sprint7_security.py` had
  never executed in CI: with no server listening every test skipped and the job
  stayed green, so auth, RBAC, tenant isolation, audit and rate limiting were
  reported passing while none of them ran. Under `CI=true` the suite now fails
  rather than skips when it cannot run.
- `Settings.LOGIN_RATE_LIMIT`, defaulting to the production `5/minute`.
  Configurable so the integration suite — every test of which authenticates —
  fits inside one rate-limit window.
- `tests/test_audit_persistence.py` and `tests/test_alert_delivery.py`, which
  assert durability through a second session and that `main.py` only calls
  `ws_manager` methods that exist.

### Security

- `backend/swarmguard.db` untracked. It was a committed SQLite database holding
  pbkdf2-sha256 hashes for four role-bearing accounts, in every clone and fork,
  for an engine the application refuses to run on. **The blob remains reachable
  in git history** — purging it needs `git-filter-repo`/BFG and a force-push,
  and any password ever reused elsewhere should be rotated.

### Known gaps

Not addressed here; see `reports/03-PRODUCTION-ROADMAP.md`. No TLS anywhere in
the stack, no backup or restore story, no metrics or tracing, no container
resource limits, and no deploy pipeline. `/health` still returns `200` with the
database down, so the container healthcheck certifies a backend that cannot
serve a request.

## [0.1.0] — initial

### Added
- Initial project structure and documentation.
- Standard repository files: `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `LICENSE`.
- GitHub issue and pull request templates.
- Base `.gitignore` for Python and Node.js environments.
