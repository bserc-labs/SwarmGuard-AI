"""Readiness: can this instance do useful work right now?

/health says the process is up. It does not touch the database, so when
postgres was stopped it kept answering 200, the container stayed "healthy" for
as long as anyone watched, and every real request failed with a 500. Docker did
not restart it; a load balancer would have kept routing to it. The only signal
was user complaints.

/ready is the other question. Each dependency is probed with a short timeout,
off the event loop, and the answer is 503 the moment one that matters is down.
The probes are cheap on purpose -- SELECT 1, PING -- because an orchestrator
asks every few seconds and a slow probe is its own outage.

Redis is a judgement call, made explicit in READINESS_REQUIRES_REDIS. Without
it, live alerts do not reach an operator's screen and the login rate limiter
falls back to per-process memory, so by default a Redis outage makes the
instance not ready. With several replicas behind a load balancer that turns a
partial outage into a total one, and the setting turns it into a reported
warning instead.
"""

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class Probe:
    ok: bool
    detail: str
    required: bool = True


@dataclass
class Readiness:
    checks: dict[str, Probe] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return all(p.ok for p in self.checks.values() if p.required)

    def as_dict(self) -> dict:
        return {
            "status": "ready" if self.ready else "not_ready",
            "checks": {
                name: {"ok": p.ok, "required": p.required, "detail": p.detail}
                for name, p in self.checks.items()
            },
        }


def probe_database(engine: Engine) -> Probe:
    """One SELECT 1 on a pooled connection. pool_pre_ping means a dead
    connection is replaced rather than reported, so this reflects the server."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return Probe(True, "postgres")
    except Exception as exc:  # any failure to answer is "not ready"
        return Probe(False, f"postgres unreachable: {type(exc).__name__}")


def probe_redis(url: str | None, *, required: bool, timeout_s: float) -> Probe:
    if not url:
        return Probe(True, "not configured (in-memory limiter, single instance)", required=False)
    try:
        import redis

        client = redis.Redis.from_url(url, socket_connect_timeout=timeout_s, socket_timeout=timeout_s)
        try:
            client.ping()
        finally:
            client.close()
        return Probe(True, "redis", required=required)
    except Exception as exc:
        return Probe(False, f"redis unreachable: {type(exc).__name__}", required=required)


async def _bounded(name: str, call, timeout_s: float, required: bool) -> tuple[str, Probe]:
    """Run a blocking probe in a worker thread with a deadline.

    A probe that hangs (a half-dead network, a database accepting TCP but not
    answering) is reported as not ready when the deadline passes. The thread
    itself finishes whenever the driver gives up; the answer does not wait for
    it.
    """
    try:
        return name, await asyncio.wait_for(asyncio.to_thread(call), timeout_s)
    except TimeoutError:
        return name, Probe(False, f"{name} did not answer within {timeout_s}s", required=required)


async def check_readiness(
    engine: Engine, redis_url: str | None, *, redis_required: bool, timeout_s: float
) -> Readiness:
    results = await asyncio.gather(
        _bounded("database", lambda: probe_database(engine), timeout_s, True),
        _bounded(
            "redis",
            lambda: probe_redis(redis_url, required=redis_required, timeout_s=timeout_s),
            timeout_s,
            redis_required,
        ),
    )
    return Readiness(checks=dict(results))
