# Assessment Reports

Produced 2026-09-20/21 from a full build-and-run of `SwarmGuard-AI` @ `main`
(`06b21ca`). Every claim in these documents was verified against a running
system — nothing is inferred from reading the README.

| Report | Read it if you want… |
|---|---|
| [`01-PROJECT-ORIENTATION.md`](01-PROJECT-ORIENTATION.md) | To understand what the project is, how it works, and what is real vs. aspirational. **Start here.** |
| [`02-TASK-UNDERSTANDING.md`](02-TASK-UNDERSTANDING.md) | What was asked, how it was interpreted, the method, and the full evidence log. |
| [`03-PRODUCTION-ROADMAP.md`](03-PRODUCTION-ROADMAP.md) | The phased plan to get to production, ordered by risk. |

## The short version

**The project builds, runs, and does what it claims.** It passes every gate its
CI defines — 366 backend tests, 105 frontend tests, ruff, mypy, typecheck, build
— and it catches a real GPS-spoofing pattern end to end, pushing an explainable
incident over a WebSocket in under a second. Against 315 packets from 12
simulated drones it raised 3 incidents and **zero false positives on nominal
flight**.

**It is not production-ready**, but the gap is operational, not architectural:
no TLS, no backups, no metrics, no resource limits, no deploy pipeline. Plus two
correctness blockers:

1. **The audit trail silently discards every telemetry ingest.** 315 ingests →
   0 audit rows, verified on the Docker stack. `docs/SECURITY.md` names this
   audit log as the mitigation for action repudiation.
2. **A Redis outage returns 500 from `/auth/login`.** Nobody can log in until
   Redis returns.

And one testing blocker: **the live security suite has never run.** All six
tests skip when no server is listening, and CI never starts one — so auth, RBAC,
tenant isolation, audit and rate limiting have been green-by-omission. Run
properly, all six pass.

Estimated effort to a defensible production deployment: **5–7 weeks** for one
engineer.

## The one change made to the codebase

`backend/.dockerignore` did not exclude virtualenvs, so following the README's
own local-dev instructions poisoned every Docker build:

| | Before | After |
|---|---|---|
| Build context | 634.32 MB | 12.06 kB |
| `chown -R /app` layer | 251.6 s | negligible |
| Outcome | I/O error on image export | builds clean |

Nothing else was modified.
