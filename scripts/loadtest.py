#!/usr/bin/env python3
"""Load test: drive telemetry ingest at stated rates and measure what the system does.

The pool size, the 50 packets/second ingest limit and the 10 Hz broadcast were
reasoned about in comments and never measured. This measures them, end to end,
through nginx and TLS as a real client would see the system:

  * an open-loop sender: packets go out on schedule whatever the responses are
    doing, so a slow server shows up as latency and errors, not as a politely
    reduced offered load;
  * a fleet of drones, each with its own per-device key (issued for the run,
    revoked after it), flying plausible circles so the kinematic guard stays
    quiet and every packet costs a full detection cycle;
  * WebSocket listeners timing each packet from send to delivery;
  * the API's own /metrics, sampled every second: pool checkout, detection
    outcomes and duration, broadcast timing;
  * the backend container's memory, sampled with `docker stats`.

    backend/.venv/bin/python scripts/loadtest.py --insecure
    backend/.venv/bin/python scripts/loadtest.py --phases "50@60:at-cap" --drones 40

Credentials: SWARMGUARD_USER / SWARMGUARD_PASSWORD, or ADMIN_USERNAME from .env
and ./secrets/admin_password. The account must be an admin (it issues the
per-drone keys). Nothing secret is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]
DEG_LAT_M = 111_320.0


# ------------------------------------------------------------------ plumbing
def env_value(key: str) -> str:
    env = ROOT / ".env"
    if not env.exists():
        return ""
    for line in env.read_text().splitlines():
        if line.strip().startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def credentials() -> tuple[str, str]:
    user = os.environ.get("SWARMGUARD_USER") or env_value("ADMIN_USERNAME") or "admin"
    password = os.environ.get("SWARMGUARD_PASSWORD")
    if not password:
        secret = ROOT / "secrets" / "admin_password"
        password = secret.read_text() if secret.exists() else ""
    if not password:
        sys.exit("No admin password: set SWARMGUARD_PASSWORD or create ./secrets/admin_password.")
    return user, password


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1)] * 1000, 1)


@dataclass
class Phase:
    name: str
    rate: float
    seconds: float


def parse_phases(spec: str) -> list[Phase]:
    phases = []
    for part in spec.split(","):
        rate_dur, name = part.split(":")
        rate, dur = rate_dur.split("@")
        phases.append(Phase(name=name, rate=float(rate), seconds=float(dur)))
    return phases


# ------------------------------------------------------------------ the fleet
@dataclass
class Drone:
    drone_id: str
    key: str
    credential_id: int
    center_lat: float
    center_lon: float
    radius_m: float
    speed_mps: float
    t0: float
    client: httpx.AsyncClient
    seq: int = 0

    def packet(self, now: float) -> dict:
        t = now - self.t0
        omega = self.speed_mps / self.radius_m
        angle = omega * t
        lat = self.center_lat + (self.radius_m * math.sin(angle)) / DEG_LAT_M
        lon = self.center_lon + (self.radius_m * math.cos(angle)) / (DEG_LAT_M * math.cos(math.radians(self.center_lat)))
        heading = (math.degrees(angle) + 90.0) % 360.0
        self.seq += 1
        return {
            "drone_id": self.drone_id, "latitude": round(lat, 7), "longitude": round(lon, 7),
            "altitude": 120.0 + 5 * math.sin(angle / 3), "speed": self.speed_mps, "heading": round(heading, 2),
            "battery": max(20.0, 95.0 - t / 60), "flight_mode": "AUTO", "armed_status": True,
            "satellites": 14, "packet_sequence": self.seq, "sample_time_ms": int(t * 1000),
        }


# ------------------------------------------------------------------ recording
@dataclass
class PhaseResult:
    phase: Phase
    started: float = 0.0
    ended: float = 0.0
    sent: int = 0
    last_send: float = 0.0
    lag: list[float] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)
    latencies: list[float] = field(default_factory=list)
    delivered: list[float] = field(default_factory=list)
    pool_checked_out_max: float = 0.0
    pool_overflow_max: float = 0.0
    memory_mib_max: float = 0.0
    detection_before: dict[str, float] = field(default_factory=dict)
    detection_after: dict[str, float] = field(default_factory=dict)
    declined_before: dict[str, float] = field(default_factory=dict)
    declined_after: dict[str, float] = field(default_factory=dict)
    detection_sum_before: float = 0.0
    detection_count_before: float = 0.0
    detection_sum_after: float = 0.0
    detection_count_after: float = 0.0


def parse_metrics(text: str) -> dict:
    out: dict = {"detection": {}, "declined": {}}
    for line in text.splitlines():
        if line.startswith("#"):
            continue
        m = re.match(r'swarmguard_detection_runs_total\{outcome="([^"]+)"\} ([0-9.e+]+)', line)
        if m:
            out["detection"][m.group(1)] = float(m.group(2))
            continue
        # Cycles the kinematic guard could not rate at all. Under a backlog this
        # is the detector saying so rather than filing a false CRITICAL.
        m = re.match(r'swarmguard_guard_declined_total\{reason="([^"]+)"\} ([0-9.e+]+)', line)
        if m:
            out["declined"][m.group(1)] = float(m.group(2))
            continue
        for name in ("swarmguard_db_pool_checked_out", "swarmguard_db_pool_overflow", "swarmguard_db_pool_max",
                     "swarmguard_detection_duration_seconds_sum", "swarmguard_detection_duration_seconds_count",
                     "swarmguard_websocket_connections"):
            if line.startswith(name + " "):
                out[name] = float(line.split()[-1])
    return out


# ------------------------------------------------------------------ the run
async def run(args) -> dict:
    ctx = ssl.create_default_context()
    if args.insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    # One small connection pool per drone, as real drones each hold their own
    # link. A single shared pool of hundreds of connections costs httpcore time
    # quadratic in its size on every request; a rerun stalled on exactly that,
    # the generator at full CPU while the server sat idle.
    per_drone = max(1, math.ceil(args.connections / args.drones))
    drone_limits = httpx.Limits(max_connections=per_drone, max_keepalive_connections=per_drone)
    client = httpx.AsyncClient(verify=ctx, limits=httpx.Limits(max_connections=10), timeout=10.0)
    user, password = credentials()

    res = await client.post(f"{args.api}/auth/login", data={"username": user, "password": password})
    res.raise_for_status()
    token = res.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    stamp = time.strftime("%H%M%S")
    now = time.monotonic()
    fleet: list[Drone] = []
    for i in range(args.drones):
        drone_id = f"LOAD-{stamp}-{i:02d}"
        issued = await client.post(f"{args.api}/drones/{drone_id}/credentials", headers=auth, json={"label": "loadtest"})
        issued.raise_for_status()
        body = issued.json()
        fleet.append(Drone(drone_id, body["key"], body["id"], 34.05 + 0.01 * (i % 10), -118.25 + 0.01 * (i // 10),
                           radius_m=300.0, speed_mps=15.0, t0=now,
                           client=httpx.AsyncClient(verify=ctx, limits=drone_limits, timeout=10.0)))
    print(f"fleet: {len(fleet)} drones, each with its own key", flush=True)

    sent_at: dict[tuple[str, int], float] = {}
    current: list[PhaseResult] = []
    stop = asyncio.Event()
    all_requests: set[asyncio.Task] = set()
    listener_errors: list[str] = []

    async def listener(n: int) -> None:
        base = args.ws or args.api.replace("https://", "wss://").replace("http://", "ws://").replace("/api", "")
        ws_url = base + f"/ws/telemetry?token={token}"
        try:
            async with websockets.connect(ws_url, ssl=ctx if ws_url.startswith("wss") else None, max_queue=None) as ws:
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except TimeoutError:
                        continue
                    arrived = time.monotonic()
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    key = (msg.get("drone_id"), msg.get("packet_sequence"))
                    t_sent = sent_at.get(key)
                    if t_sent is not None and current:
                        current[-1].delivered.append(arrived - t_sent)
        except Exception as exc:  # noqa: BLE001 - a listener dying, for any reason, is itself a finding
            listener_errors.append(f"listener {n}: {type(exc).__name__}: {exc}")
            print(f"listener {n} ended: {type(exc).__name__}: {exc}", flush=True)

    sample_failures = {"metrics": 0, "memory": 0}
    docker = shutil.which("docker") or "docker"

    async def sampler() -> None:
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            try:
                text = (await client.get(args.metrics_url)).text
                m = parse_metrics(text)
                if current:
                    r = current[-1]
                    r.pool_checked_out_max = max(r.pool_checked_out_max, m.get("swarmguard_db_pool_checked_out", 0))
                    r.pool_overflow_max = max(r.pool_overflow_max, m.get("swarmguard_db_pool_overflow", 0))
            except httpx.HTTPError:
                sample_failures["metrics"] += 1  # reported: a gap in sampling is not a zero
            if args.container:
                try:
                    out = await loop.run_in_executor(None, lambda: subprocess.run(
                        [docker, "stats", "--no-stream", "--format", "{{.MemUsage}}", args.container],
                        capture_output=True, text=True, timeout=10, check=False).stdout)
                    used = out.split("/")[0].strip()
                    mib = float(re.sub(r"[^0-9.]", "", used)) * (1024 if "GiB" in used else 1)
                    if current:
                        current[-1].memory_mib_max = max(current[-1].memory_mib_max, mib)
                except (OSError, ValueError, subprocess.SubprocessError):
                    sample_failures["memory"] += 1
            await asyncio.sleep(1.0)

    async def send_one(r: PhaseResult, drone: Drone) -> None:
        packet = drone.packet(time.monotonic())
        # A congested link delivers some packets long after they were sampled,
        # which is what scrambles the stored window. Overload produces this by
        # accident and not reliably; --late-fraction produces it on purpose, so
        # the detector's behaviour under it can be tested rather than waited for.
        if args.late_fraction and (drone.seq % max(1, round(1 / args.late_fraction))) == 0:
            await asyncio.sleep(args.late_by)
        t = time.monotonic()
        sent_at[(drone.drone_id, packet["packet_sequence"])] = t
        try:
            resp = await drone.client.post(f"{args.api}/telemetry/ingest", json=packet,
                                     headers={**auth, "X-Drone-API-Key": drone.key})
            code = str(resp.status_code)
        except httpx.HTTPError as exc:
            code = type(exc).__name__
        r.latencies.append(time.monotonic() - t)
        r.statuses[code] = r.statuses.get(code, 0) + 1

    listeners = [asyncio.create_task(listener(i)) for i in range(args.listeners)]
    sampling = asyncio.create_task(sampler())
    await asyncio.sleep(2.0)  # let the sockets subscribe

    results: list[PhaseResult] = []
    for phase in parse_phases(args.phases):
        r = PhaseResult(phase)
        current.append(r)
        m = parse_metrics((await client.get(args.metrics_url)).text)
        r.detection_before = m["detection"]
        r.declined_before = m["declined"]
        r.detection_sum_before = m.get("swarmguard_detection_duration_seconds_sum", 0)
        r.detection_count_before = m.get("swarmguard_detection_duration_seconds_count", 0)
        print(f"phase {phase.name}: {phase.rate:g}/s for {phase.seconds:g}s", flush=True)
        interval = 1.0 / phase.rate
        r.started = time.monotonic()
        in_flight: set[asyncio.Task] = set()
        i = 0
        while True:
            due = r.started + i * interval
            if due >= r.started + phase.seconds:
                break
            delay = due - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            # How late this send left against its schedule. If this grows, the
            # generator -- not the server -- is the bottleneck, and every rate
            # below is what was achieved, not what was asked for.
            r.lag.append(max(0.0, time.monotonic() - due))
            r.last_send = time.monotonic()
            task = asyncio.create_task(send_one(r, fleet[i % len(fleet)]))
            in_flight.add(task)
            all_requests.add(task)
            task.add_done_callback(in_flight.discard)
            task.add_done_callback(all_requests.discard)
            r.sent += 1
            i += 1
        if in_flight:
            await asyncio.wait(in_flight, timeout=15)
        await asyncio.sleep(2.0)  # let detections and deliveries drain into this phase
        r.ended = time.monotonic()
        m = parse_metrics((await client.get(args.metrics_url)).text)
        r.detection_after = m["detection"]
        r.declined_after = m["declined"]
        r.detection_sum_after = m.get("swarmguard_detection_duration_seconds_sum", 0)
        r.detection_count_after = m.get("swarmguard_detection_duration_seconds_count", 0)
        results.append(r)

    # Revoking a key while requests carrying it are still queued turns them into
    # 403s after the fact -- the first capacity run did exactly that. Drain first.
    if all_requests:
        print(f"draining {len(all_requests)} outstanding request(s) before revoking keys", flush=True)
        await asyncio.wait(set(all_requests))
    stop.set()
    await asyncio.gather(*listeners, sampling, return_exceptions=True)
    for drone in fleet:
        await client.delete(f"{args.api}/drones/{drone.drone_id}/credentials/{drone.credential_id}", headers=auth)
        await drone.client.aclose()
    await client.aclose()

    report = {"api": args.api, "drones": args.drones, "listeners": args.listeners,
              "listener_errors": listener_errors, "sample_failures": sample_failures, "phases": []}
    for r in results:
        # The real send window. A starved generator stretches a phase; dividing
        # by the planned length would then report a rate that never happened.
        elapsed = max(r.last_send - r.started, 1e-9)
        ok = r.statuses.get("200", 0)
        det = {k: r.detection_after.get(k, 0) - r.detection_before.get(k, 0) for k in r.detection_after}
        det_n = r.detection_count_after - r.detection_count_before
        det_mean = (r.detection_sum_after - r.detection_sum_before) / det_n if det_n else None
        expected_deliveries = ok * args.listeners
        report["phases"].append({
            "name": r.phase.name, "planned_per_s": r.phase.rate, "planned_seconds": r.phase.seconds,
            "actual_seconds": round(elapsed, 1), "achieved_send_per_s": round(r.sent / elapsed, 1),
            "schedule_lag_ms": {"p50": pct(r.lag, 0.50), "p95": pct(r.lag, 0.95), "max": pct(r.lag, 1.0)},
            "sent": r.sent, "statuses": dict(sorted(r.statuses.items())),
            "accepted_per_s": round(ok / elapsed, 1),
            "latency_ms": {"p50": pct(r.latencies, 0.50), "p95": pct(r.latencies, 0.95),
                           "p99": pct(r.latencies, 0.99), "max": pct(r.latencies, 1.0)},
            "detection_runs": {k: int(v) for k, v in sorted(det.items()) if v},
            "guard_declined": {k: int(r.declined_after.get(k, 0) - r.declined_before.get(k, 0))
                               for k in r.declined_after
                               if r.declined_after.get(k, 0) - r.declined_before.get(k, 0)},
            "detection_mean_ms": round(det_mean * 1000, 1) if det_mean is not None else None,
            "pool_checked_out_max": r.pool_checked_out_max, "pool_overflow_max": r.pool_overflow_max,
            "ws_delivered": len(r.delivered), "ws_expected": expected_deliveries,
            "ws_delivery_ms": {"p50": pct(r.delivered, 0.50), "p95": pct(r.delivered, 0.95), "max": pct(r.delivered, 1.0)},
            "backend_memory_mib_max": r.memory_mib_max or None,
        })
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--api", default="https://localhost/api")
    ap.add_argument("--ws", default="", help="WebSocket base URL; default derived from --api (e.g. ws://127.0.0.1:8000)")
    ap.add_argument("--metrics-url", default="http://127.0.0.1:8000/metrics")
    ap.add_argument("--phases", default="10@10:warm-up,40@60:under-cap,50@60:at-cap,100@20:over-cap")
    ap.add_argument("--drones", type=int, default=20)
    ap.add_argument("--listeners", type=int, default=10)
    ap.add_argument("--connections", type=int, default=100, help="connections across the fleet, split evenly per drone")
    ap.add_argument("--container", default="swarmguard-backend", help="docker container to sample memory from; '' to skip")
    ap.add_argument("--late-fraction", type=float, default=0.0,
                    help="fraction of packets held back, simulating a congested link (0.05 = one in twenty)")
    ap.add_argument("--late-by", type=float, default=30.0, help="how long a held-back packet waits, in seconds")
    ap.add_argument("--insecure", action="store_true", help="skip TLS verification (self-signed development certificate)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    report = asyncio.run(run(args))
    text = json.dumps(report, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n")


if __name__ == "__main__":
    main()
