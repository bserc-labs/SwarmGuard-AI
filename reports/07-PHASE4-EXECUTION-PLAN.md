# Phase 4 — what is left, and how to do it

**Status: six of the eight items are done** (4.1, 4.2, 4.3, 4.6, 4.7, 4.8, plus
the small corrections in 4.9), each with tests and, where it is a capacity
claim, a measurement. Two remain, and both need a decision rather than an
afternoon:

| Open | Why it is not done here |
|---|---|
| 4.4 mTLS for device identity | About a week, and most of it is certificate issuance and rotation for devices — an operational design, not a code change. Per-device keys made it optional rather than urgent. |
| 4.5 Purge the committed database blobs | Rewrites history and force-pushes, so every clone has to be re-made. That is the repository owner's call and a moment everyone agrees on, not something to slip into a pull request. |

What each item was, and what it is now, follows. Phases 0 to 3 are done; this
plan covers what they deliberately left open, what the load test recommended,
and what the audit found and nobody had fixed.

Each item says what is wrong, how we know, what the fix is, and **how we will
know it worked** — because Phase 3's lesson is that a system is only as good as
the thing that measures it. Two of its ten commits exist because a load test
was finally written; nothing in the suite had caught either defect.

Order and effort are at the end.

---

## A. From the load test

The measurements are in [`06-LOAD-TEST-RESULTS.md`](06-LOAD-TEST-RESULTS.md).
These two are its open recommendations.

### 4.1 Shed load before the queue outgrows the detector's tolerance ✅

**What is wrong.** One process handles about 200 packets/second. Past that the
queue grows in front of the application, where admission cannot see it: at
800/s packets are stored 40–80 s after they were sampled. The guard no longer
files false alerts over that — it declines to rate a pair it cannot time — but
declining is not free. Detection goes quiet exactly when the system is under
stress, and `swarmguard_guard_declined_total` is the only thing that says so.

**The fix**, in the order that gets the most for the least:

1. **More workers.** ✅ Done. `UVICORN_WORKERS` runs N uvicorn processes; the
   entrypoint turns on prometheus_client's multiprocess mode so a scrape
   reports the whole application, start-up refuses a worker count whose pools
   would exceed PostgreSQL's `max_connections`, and background passes are
   claimed in Redis so they run once per interval rather than once per worker.
   Measured: two workers hold 400 packets/second with a half-second median,
   where one was at six seconds.
2. **Refuse telemetry the server cannot reach in time.** A packet whose
   detection cannot run for a minute is not worth the alert it might raise.
   The ingest route can compare the device's sample clock against the window
   the drone's recent packets occupy and reject the ones that are already
   stale, with `503` and `Retry-After`, before they reach storage.

**How we will know.** Rerun the capacity phases: the backlog visible as 503s
rather than as minutes of latency, and `swarmguard_guard_declined_total` at
zero, meaning every packet was timed rather than waved through. Those two
numbers, not the incident count, which is already zero.

**Effort.** 2–3 days for workers plus multiprocess metrics; 1 day for staleness
rejection.

### 4.2 Rate-limit per device credential, not per client address ✅

**What is wrong.** `INGEST_RATE_LIMIT` counts per client address, so every
drone behind one ground station shares 50 packets/second: twenty drones get
2.5 Hz each. One noisy airframe can starve its neighbours, and the fleet's
shape changes the limit each drone actually gets.

**The fix.** Key the limiter on the device credential id resolved in
`device_credentials.authenticate`, falling back to the client address when the
shared key is used. Per-device credentials exist as of Phase 3, so the key is
already in hand at the point the limiter runs.

**How we will know.** A load test with two drones behind one address, one of
them sending at ten times its share: the well-behaved drone keeps its full rate.
Today it does not.

**Effort.** 1 day, including the test.

---

## B. Identity and secrets

### 4.3 Get the WebSocket token out of the URL ✅

**What is wrong.** `frontend/src/services/websocket.ts` appends the JWT as
`?token=…`. Query strings land in proxy logs, browser history and referrer
headers. Phase 0b stopped nginx and uvicorn logging it, which reduces the
exposure but does not remove it: it is still a credential in a URL.

**The fix.** Either a short-lived, single-use ticket (`POST /auth/ws-ticket`
returns an opaque id valid for seconds, redeemed on connect), or the
`Sec-WebSocket-Protocol` header, which browsers allow to carry a value. The
ticket is more work and strictly better: it cannot be replayed.

**How we will know.** A test that connects with a ticket, and a second that
proves the same ticket is refused twice; plus a grep test that no route accepts
a token from the query string.

**Effort.** 2 days.

### 4.4 mTLS for device identity

**What is wrong.** A device key is a bearer secret. Anyone who reads it from a
recovered airframe can send telemetry as that drone until it is revoked.

**The fix.** Client certificates terminated at nginx, with the certificate's
subject checked against the drone. This is the long-term answer 3.2 named; the
per-device keys are the step that made it optional rather than urgent.

**How we will know.** A drone with a valid certificate ingests; the same
payload without one is refused at the proxy, not the application.

**Effort.** 1 week, most of it certificate issuance and rotation for devices.

### 4.5 Purge the committed database blobs from history

**What is wrong.** Three commits in history add a `.db` file
(`1447c14`, `bd6903e`, `d32ac73`). The file is untracked today, but the blobs —
including four password hashes — are still in the repository and in every
clone.

**The fix.** `git filter-repo` to drop the paths, force-push, and rotate
anything the blobs contained that is still valid. This rewrites history, so it
needs a quiet moment and everyone re-cloning.

**How we will know.** The blobs are unreachable (`git log --all -- '*.db'`
returns nothing) and the hashes no longer authenticate anywhere.

**Effort.** Half a day, plus coordination.

---

## C. Detection completeness

### 4.6 Wire MAVLink telemetry into detection ✅

**What is wrong.** `services/mavlink_receiver.py` validates and stores packets,
and stops there. Telemetry that arrives over MAVLink is never scored: the
kinematic guard, the geofence and the incident engine see only what came
through the HTTP route. A deployment ingesting over MAVLink has a detector
that never fires.

**The fix.** Call the same background detection the ingest route calls, and
count it in the same metrics. Note that MAVLink packets bypass admission, so
the connection budget in `config.py` needs a term for them, or the receiver
needs its own bound.

**How we will know.** A test that feeds a spoofed MAVLink track and asserts an
incident, mirroring the HTTP test that exists.

**Effort.** 2 days, including the budget question.

### 4.7 Route heartbeat incidents through the incident engine ✅

**What is wrong.** `services/heartbeat_service.py` writes `Incident` rows
directly. It therefore skips suppression, escalation and the advisory lock that
Phase 0b added, so a silent drone can produce one incident per pass rather than
one incident that escalates.

**The fix.** Give the engine a detection dict the way the guard does, and let
it decide create, escalate or suppress.

**How we will know.** A drone silent for ten passes produces one incident that
escalates, not ten incidents.

**Effort.** 1 day.

---

## D. Product gaps

### 4.8 Administration of users ✅

`routers/users.py` can create a user, list users, and let one edit their own
profile and password. There is no route to change another user's role, disable
an account, or delete one. Today an operator who leaves cannot be removed
except in the database. **Effort:** 2 days with tenancy tests and audit rows.

### 4.9 Small things ✅

- `docs/DATABASE_SCHEMA.md` still advertises "SQLite 3 (Development)".
  `database.py` refuses to start on SQLite. Correct the document.
- The API reference describes a subset of 40 routes; say which are missing or
  generate the list.

---

## E. What needs you, not code

| Needed | For | Until then |
|---|---|---|
| A domain and a real certificate | TLS without warnings | self-signed, browser warning |
| A server | `deploy.sh` in anger | tested locally and in CI only |
| An object-storage bucket | minute-level RPO | 6-hour dumps on a volume |
| A Sentry project DSN | error tracking | stays off; scrubbing is tested |
| An alert receiver (email, chat, pager) | Prometheus rules | alerts fire into Prometheus only |
| A LiveReview AI key (BYOK) | the commit gate | reviews cannot run on the free plan |

---

## Order of work

| Order | Item | Why here |
|---|---|---|
| 1 | 4.1 shed load / workers | It is the one open defect with false CRITICAL alerts behind it |
| 2 | 4.7 heartbeat through the engine | One day, removes duplicate incidents an operator sees today |
| 3 | 4.6 MAVLink into detection | A whole ingest path with no detector is a bigger hole than it looks |
| 4 | 4.2 per-device rate limit | Cheap now that credentials exist |
| 5 | 4.3 WebSocket ticket | Security debt with a known shape |
| 6 | 4.5 history purge | Needs a quiet moment and everyone re-cloning |
| 7 | 4.8 user administration | Product gap, no security consequence today |
| 8 | 4.4 mTLS | The largest, and optional while device keys are revocable |

**Total:** about three weeks, 4.4 excluded.

Everything above is testable. Anything that cannot be stated as "how we will
know it worked" should be argued about before it is built, not after.
