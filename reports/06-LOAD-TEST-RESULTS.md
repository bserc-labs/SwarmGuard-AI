# Load test results — 2026-09-22

Roadmap item 3.5. The pool size, the 50 packets/second ingest limit and the
10 Hz broadcast were argued in comments and never measured. This measures them,
and records what broke.

Raw results: `reports/loadtest/2026-09-22-baseline.json` and
`reports/loadtest/2026-09-22-capacity.json`. Tool: `scripts/loadtest.py`.

## Set-up

- The development compose stack on one laptop (Docker Desktop, 10 CPUs), with
  the Phase 1 limits in force: backend 1 GiB / 2 CPUs, one uvicorn worker.
- An **open-loop** generator: packets leave on schedule whatever the server is
  doing, so a slow server shows as latency and errors, not as a politely reduced
  offered load. It reports its own **schedule lag**; when that grows, the
  generator is the bottleneck and its numbers are not the server's.
- A fleet of drones flying clean circles at 15 m/s, **each with its own device
  key** issued for the run and revoked after it. Every packet costs a full
  detection cycle.
- WebSocket listeners timing each packet from send to delivery.
- The API's `/metrics` sampled every second; container memory and CPU sampled
  alongside.

## 1. At the documented limit — through nginx and TLS

20 drones, 10 WebSocket listeners, `https://localhost/api`.

| Phase | Offered | Result | Latency p50 / p95 / p99 | Delivered to every listener | Detection mean | Pool in use (max) | Memory |
|---|---|---|---|---|---|---|---|
| warm-up | 10/s | all accepted | 18 / 26 / 32 ms | 1,000 / 1,000 | 3.2 ms | 1 | 204 MiB |
| under the cap | 40/s | all accepted | 7 / 11 / 17 ms | 24,000 / 24,000, p95 12 ms | 1.9 ms | 1 | 206 MiB |
| at the cap | 50/s | **41 of 3,000 refused (1.4%)** | 6 / 9 / 14 ms | 29,590 / 29,590, p95 10 ms | 1.7 ms | 1 | 205 MiB |
| over the cap | 100/s | exactly 50/s accepted, 1,000 refused | 5 / 8 / 14 ms | 10,000 / 10,000 | 1.4 ms | 1 | 206 MiB |

(This run predates the tool's schedule-lag measurement. Every listener received
every packet with p95 delivery under 30 ms, which a lagging generator would not
produce.)

**What it says.**

- Below the limit the system is unhurried: single-digit milliseconds, every
  packet delivered to every listener, detection under 2 ms.
- **The limiter is precise, and it is the ceiling.** Offered 100/s, exactly
  50/s went through.
- **Offering exactly the limit loses packets.** 1.4% refused at 50/s: the limit
  counts in fixed one-second windows, and ordinary scheduling jitter puts 51 in
  some of them. A fleet should be sized below the limit, not at it.
- **The limit is per client address, so a fleet behind one uplink shares it.**
  Twenty drones behind one ground station get 2.5 Hz each. The limit is now a
  setting, `INGEST_RATE_LIMIT`, and the README says so.
- **The pool is nowhere near a constraint.** Never more than one connection in
  use at a sample, against 60 available. The "two connections per packet"
  reasoning in `database.py` is right about the pattern and irrelevant at this
  load: requests and detections finish in milliseconds.

## 2. Capacity — the limit lifted, straight at the API

To find where the *server* gives out, the limit was raised for this run only
(`INGEST_RATE_LIMIT=100000/second` through a throwaway compose override, the
normal stack restored afterwards), and the generator talked to
`http://127.0.0.1:8000` directly with one listener, so the measurement is of
the API rather than of Python decoding WebSocket frames. 40 drones.

| Offered | Generator lag p95 | Result | Latency p50 / p95 | Pool in use / overflow (max) | Memory |
|---|---|---|---|---|---|
| 100/s | 0.8 ms | 2,000 / 2,000 accepted, all delivered | 4 / 7 ms | 1 / 0 | 206 MiB |
| 200/s | 0.5 ms | 4,000 / 4,000 accepted, all delivered | 4 / 8 ms | 1 / 0 | 209 MiB |
| 400/s | 1.7 s | 6,281 accepted, 40 × 500, 1,679 client timeouts | 25 s / 86 s | 19 / 15 | 233 MiB |
| 800/s | 1.1 s | 15,995 accepted, eventually | 122 s / 185 s | 2 / 0 | 234 MiB |

Backend CPU peaked at 1.43 cores of its 2. Above 200/s the generator lagged
too, so those two rows describe a system that is behind on both ends: they
locate the knee, and are not a measurement of throughput past it. The client
timeouts are the generator's own connection pool running dry (1,371) and
requests left unanswered for 10 s (308).

**What it says.**

- **The server sustains 200 packets/second cleanly** — four times the
  configured limit — and falls over between 200 and 400/s. The limit leaves
  real headroom.
- **At the knee the pool starts to matter, but is still not the ceiling**: 19
  in use plus 15 overflow, of 60. The single uvicorn worker is the likely
  ceiling; `--workers N` would need Prometheus multiprocess mode, noted in the
  operations guide.
- **Memory never moved**: 204 to 234 MiB under every load, a quarter of the
  1 GiB limit.
- The 40 server errors at 400/s are explained in section 5: the API was
  deadlocking on its own connection pool. They are pool checkout timeouts.
- "Sustains 200/s" means for the 20 s this run offered it. Section 5 offers
  200/s for a minute, and the queue grows: just under 200/s is the edge, not
  comfortable headroom.

## 3. What broke: false GPS-spoofing alerts under overload

Once the server fell behind, the kinematic guard filed **200 GPS_SPOOFING
incidents against the 40 drones of this run, all of them flying clean
circles**. That is the worst way for this system to fail: false CRITICAL
alerts, exactly when it is already under stress. (The metrics sampled during
the phases counted 141; the rest were filed while the backlog drained after
the phase windows closed. The database count is the true one. The discarded
first run filed 393 more the same way.)

Every one of them reads *"Time Base: server arrival time"*. The guard is meant
to rate on the device's own clock, and fell back to arrival time for every one.

- The guard rates the **newest stored packet against the one stored just
  before it**.
- Under overload a drone's requests queue for seconds to minutes and are
  **stored out of order**.
- The device clock is then disbelieved in two ways. If the newest packet was
  sampled *earlier*, the clock runs backwards, which the guard reads as a
  reboot. If the packet stored before it was a straggler sampled more than
  10 s earlier, the device interval outruns the arrival interval by more than
  the 10 s bound, which the guard reads as a broken clock.
- Either way it divides by arrival spacing, and packets flushed from one queue
  arrive milliseconds to a second apart.

The drones fly 300 m circles at 15 m/s, so each incident's reported distance
converts back to how far apart on the device clock its two samples were:

| Samples apart | Incidents | What happened |
|---|---|---|
| under 1 s | 34 | neighbouring packets swapped: *"5 m in 0.06 s, implying 77 m/s"* |
| 1 – 10 s | 83 | a packet stored seconds late; only a backwards clock can fire here |
| 10 s or more | 69 | a straggler more than 10 s late, either way: *"219 m in 0.90 s, implying 242 m/s"* |
| not recoverable | 14 | only the speed-mismatch check fired, so no distance is recorded |

This is the class of false positive Phase 0b removed by rating on the device
clock, re-entering through its fallbacks. Those fallbacks exist for a **reboot
or counter wrap**, where the clock jumps back by the whole uptime, and for a
**mis-scaled clock**. A late packet is neither: its sample time is still true,
and the flight time to its real neighbour on the device clock is still known.
The guard just compares it with the wrong neighbour.

The 40 signal-loss incidents at the end of the run are correct: the generator
stops mid-flight, and those drones did go silent for 30 s.

Status: **open in this commit; fixed in the next**, with the rerun in section 5.

## 4. The generator, too, was wrong once

The first capacity run reported hundreds of seconds of latency, lost its
listeners after the first phase, and ended with 793 "revoked key" rejections.
None of that was the server. Ten listeners in one Python process were decoding
up to 8,000 frames a second and starving the sender; the tool divided by the
*planned* phase length, so a stretched phase would have reported rates that
never happened; and it revoked the run's keys while thousands of stale requests
were still queued, which the server then correctly refused — incidentally
proving revocation is immediate. The tool now measures its own schedule lag,
divides by the real send window, drains every request before revoking, and
records listener errors. That run's results were discarded.

## 5. After the fixes

Two commits followed this measurement: the guard now rates a late packet
against its nearest neighbour on the device clock, and the API bounds how many
requests can hold a database connection. Same stack, same fleet, same phases.
Raw results: `reports/loadtest/2026-09-22-capacity-rerun.json`.

| Offered | Result | Latency p50 / p95 | False spoof incidents | Pool in use / overflow | Memory |
|---|---|---|---|---|---|
| 100/s | 2,000 / 2,000 accepted | 5 / 18 ms | 0 | 1 / 0 | 216 MiB |
| 200/s | 4,000 / 4,000 accepted | 6 ms / 985 ms | 0 | 39 / 20 | 222 MiB |
| 400/s | 8,000 / 8,000 accepted | 6.2 s / 22.5 s | 0 | 30 / 18 | 233 MiB |
| 800/s | 16,000 / 16,000 accepted | 41 s / 80 s | 23 | 38 / 19 | 237 MiB |

**No server errors, no pool timeouts, no detection errors, and every request
answered.** The 40 unexplained 500s of section 2 were the deadlock below.

**False spoofing incidents fell from 200 to 23, and none at all below 800/s.**
(Section 6 is what happened to the 23.)
The 23 that remain are all the large-skew kind: 19 report 10 s or more of
flight between their two samples, 4 carry only the speed mismatch. The swapped
neighbours and the seconds-late stragglers — 117 of the original 200 — are
gone.

### What the rerun found first: the API deadlocked on its own pool

Rerunning this test stopped the API at **100 packets/second**, half the rate
section 2 had just called comfortable, and it stayed stopped: waves of
`QueuePool limit of size 20 overflow 40 reached` ten seconds apart for sixteen
minutes, readiness failing, the heartbeat monitor unable to run.

Sampling `pg_stat_activity` during a reproduction named it. All 60 connections
sat **idle in transaction** on the authentication query. A request runs in
several worker-thread hops — user lookup, permission check, endpoint — and the
lookup's transaction holds its connection while the request waits for a thread
for the next hop. The 40 threads were meanwhile running newer requests, each
waiting for a connection. Each side held what the other needed; the 10 s pool
timeout broke it by failing requests, and it re-formed at once.

The same minute, offered to each build in turn — 200/s for 60 s, same fleet,
same data:

| | before (this commit's code) | after (both fixes) |
|---|---|---|
| packets accepted | 206 | 11,935 |
| pool timeouts | 631, over 81 s | 0 |
| readiness checks failed | 6 | 0 |
| shed with 503 | — | 63 |
| outcome | stopped answering; the generator gave up | finished the minute |

**Sustained 200/s is past this deployment's edge.** The fixed build answers
everything, but the queue grows to a 7 s median and 63 requests are shed. The
clean 20 s at 200/s in section 2 was a burst, not capacity. One process on two
cores handles roughly 200 packets/second, which is four times the configured
ingest limit.

## 6. The last 23, and what they turned out to be

The 23 that survived section 5 were packets stored so long after they were
sampled that no neighbour on the device clock remained in the window. The guard
then fell back to arrival time, which for a packet arriving among the packets
that overtook it is milliseconds.

**Overload produces that by accident and not reliably.** Three further runs —
800/s twice and 1,600/s once, the last with a two-minute backlog — produced
**zero** false incidents without any change to the guard. That is not a fix, it
is a measurement that failed to reproduce, and the difference between the two
is the whole reason this report exists.

So the tool learned to produce it on purpose. `--late-fraction 0.1 --late-by 60`
holds one packet in ten for a minute, which is what a congested link does. At
an unremarkable 100 packets/second:

| | before | after |
|---|---|---|
| false GPS_SPOOFING incidents | **40** | **0** |
| guard alerts | 40 | 0 |
| cycles the guard declined to rate | 0 | 40 |
| packets accepted | 12,000 | 12,000 |

Every one of the 40 read *"arrival clock, note=device_clock_not_monotonic"*: the
late packet's clock appeared to step back, which the guard read as a reboot.

**A reset takes time.** No flight controller reboots in the gap between two
packets delivered milliseconds apart, so below `GUARD_MIN_RESET_GAP_S` (1 s) a
backwards clock is a late packet, not a reboot, and there is no interval worth
dividing by. The guard now returns **no verdict** there, and counts it:
`swarmguard_guard_declined_total`. A detector that has gone quiet must not be
mistaken for a quiet sky.

What this costs: during congestion the guard rates fewer pairs. It still rates
every pair whose device clock is usable, which a backlog does not touch — a
spoof delivered late still fires, and a test pins exactly that. What it buys is
that a congested link cannot ground a healthy aircraft.

An earlier attempt counted how scrambled the window was and would not have
caught this: a single straggler is one step back, which is what a reboot looks
like too. It was replaced, not extended.

The runs behind this section: `2026-09-23-capacity-rerun.json` and
`2026-09-23-overload-1600.json` (the ones that did not reproduce it), and
`2026-09-23-late-delivery-before-fix.json` and `-after-fix.json` (the one that
did, either side of the fix).

## Recommendations

1. **Size fleets below the ingest limit per uplink**, or raise
   `INGEST_RATE_LIMIT`: 1.4% loss at exactly the limit.
2. **Key the ingest limit on the device credential, not the client address**,
   now that per-device keys exist: one drone could not then starve its
   neighbours behind the same uplink. A behaviour change; not made here.
3. **Leave the pool as it is.** Its size was never the constraint; what it
   lacked was a bound on how many requests could hold it, which admission now
   provides.
4. **Fix the reorder false positive** — done, section 5.
5. **Shed load before the queue grows.** Admission bounds work inside the
   application, but at 800/s requests pile up in front of it, in the socket and
   the event loop, and packets arrive 40–80 s late. The guard no longer files
   false alerts over it, but it does stop rating those pairs, so detection is
   degraded exactly when it matters. Either run more workers (needs Prometheus
   multiprocess mode) or refuse telemetry the server cannot reach in time.
   Watch `swarmguard_guard_declined_total`: it is the number that says the
   detector is coasting.
6. **Plan for about 200 packets/second per process.** Four times the ingest
   limit, so one process serves a fleet behind several uplinks, and the number
   to divide when sizing for more. **Done in Phase 4**: `UVICORN_WORKERS` runs
   more of them, and two hold 400/s with a half-second median where one was at
   six seconds. Each worker opens its own pool, so start-up refuses a worker
   count whose pools would exceed PostgreSQL's `max_connections`.
