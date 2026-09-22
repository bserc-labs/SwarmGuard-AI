"""Prometheus metrics: what the system is doing, as numbers a scraper can graph.

Nothing was measured before this. "How many packets per second?", "how long
does detection take?", "is the connection pool full?" had no answer except a
log file and a guess. Every metric here is something an operator would ask
during an incident or a capacity review.

Names carry the `swarmguard_` prefix so they cannot collide with anything else
a Prometheus happens to scrape. Labels are kept to bounded sets on purpose:
a route *template* (`/incidents/{id}`), never a raw path, and never a
drone id or an organization id -- a label value per drone would be a time
series per drone, and the fleet is the one thing that grows without bound.

Single process. uvicorn runs one worker here; with `--workers N` each worker
would keep its own counters and a scrape would see one of them at random.
That is the multiprocess mode of prometheus_client (PROMETHEUS_MULTIPROC_DIR),
which is a deliberate later step, not a default.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector

# --- HTTP ---------------------------------------------------------------------------
HTTP_REQUESTS = Counter(
    "swarmguard_http_requests_total",
    "HTTP requests handled, by method, route template and status code.",
    ["method", "route", "status"],
)
HTTP_LATENCY = Histogram(
    "swarmguard_http_request_duration_seconds",
    "Time to produce the response, by method and route template.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
UNMATCHED_ROUTE = "unmatched"

# --- ingest -------------------------------------------------------------------------------
INGEST = Counter(
    "swarmguard_telemetry_ingest_total",
    "Telemetry packets by outcome: accepted, rejected_device_key, rejected_bad_request, error.",
    ["outcome"],
)

# --- detection ----------------------------------------------------------------------------------
DETECTION_RUNS = Counter(
    "swarmguard_detection_runs_total",
    "Detection cycles by outcome: no_incident, incident_created, incident_escalated, "
    "suppressed, insufficient_history, error.",
    ["outcome"],
)
DETECTION_LATENCY = Histogram(
    "swarmguard_detection_duration_seconds",
    "Wall time of one detection cycle, from history load to incident decision.",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
INCIDENTS = Counter(
    "swarmguard_incidents_raised_total",
    "Incidents created, by detector tier, severity and attack type.",
    ["tier", "severity", "attack_type"],
)

# --- websockets ------------------------------------------------------------------------------------
WS_CONNECTIONS = Gauge(
    "swarmguard_websocket_connections",
    "Open WebSocket connections held by this process.",
)
WS_BROADCASTS = Counter(
    "swarmguard_websocket_broadcasts_total",
    "Broadcasts by delivery path: published (via Redis), local, fallback (publish failed).",
    ["path"],
)
WS_BROADCAST_LATENCY = Histogram(
    "swarmguard_websocket_broadcast_duration_seconds",
    "Time to hand a message to every local socket.",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0),
)


def detection_tier(detection: dict) -> str:
    """Which detector produced a detection dict: kinematic, geofence or ml.

    Read off the explanation metadata the detectors already write, so the
    dict itself is not changed for the incident engine downstream.
    """
    metadata = (detection.get("explanation") or {}).get("metadata") or {}
    detector = metadata.get("detector")
    if detector == "kinematic_guard":
        return "kinematic"
    if detector == "geofence" or "zones" in metadata:
        return "geofence"
    return "ml"


# --- collectors that read live state at scrape time --------------------------------------------------
class PoolCollector(Collector):
    """The SQLAlchemy pool, read when scraped rather than sampled on a timer.

    The pool was sized to 20 + 40 by reasoning in database.py and never
    measured. `checked_out` against `max` is the number that says whether that
    reasoning held.
    """

    def __init__(self, engine) -> None:
        self._engine = engine

    def collect(self) -> Iterable:
        pool = self._engine.pool
        size = pool.size()
        overflow = pool.overflow()
        yield GaugeMetricFamily(
            "swarmguard_db_pool_checked_out", "Connections currently in use.", value=pool.checkedout()
        )
        yield GaugeMetricFamily("swarmguard_db_pool_checked_in", "Idle connections in the pool.", value=pool.checkedin())
        yield GaugeMetricFamily("swarmguard_db_pool_overflow", "Connections open beyond pool_size.", value=overflow)
        yield GaugeMetricFamily("swarmguard_db_pool_size", "Configured pool_size.", value=size)
        yield GaugeMetricFamily(
            "swarmguard_db_pool_max",
            "pool_size + max_overflow: the hard ceiling before a checkout waits.",
            value=size + getattr(pool, "_max_overflow", 0),
        )


class SupervisorCollector(Collector):
    """The background loops, from the supervisor's own bookkeeping."""

    def __init__(self, supervisor) -> None:
        self._supervisor = supervisor

    def collect(self) -> Iterable:
        status = self._supervisor.status()
        ticks = CounterMetricFamily("swarmguard_background_loop_ticks", "Successful passes.", labels=["loop"])
        failures = CounterMetricFamily("swarmguard_background_loop_failures", "Passes that raised.", labels=["loop"])
        restarts = CounterMetricFamily(
            "swarmguard_background_loop_restarts", "Times the task ended unexpectedly and was recreated.", labels=["loop"]
        )
        since = GaugeMetricFamily(
            "swarmguard_background_loop_seconds_since_tick", "Age of the last successful pass.", labels=["loop"]
        )
        stalled = GaugeMetricFamily(
            "swarmguard_background_loop_stalled", "1 if the loop has not ticked for three intervals plus grace.", labels=["loop"]
        )
        alive = GaugeMetricFamily("swarmguard_background_loop_alive", "1 if the task exists and has not ended.", labels=["loop"])
        for name, loop in status.items():
            ticks.add_metric([name], loop["ticks"])
            failures.add_metric([name], loop["failures"])
            restarts.add_metric([name], loop["restarts"])
            if loop["seconds_since_tick"] is not None:
                since.add_metric([name], loop["seconds_since_tick"])
            stalled.add_metric([name], 1 if loop["stalled"] else 0)
            alive.add_metric([name], 1 if loop["alive"] else 0)
        yield from (ticks, failures, restarts, since, stalled, alive)


_registered: set[str] = set()


def register_collector(key: str, collector: Collector, registry=REGISTRY) -> None:
    """Register once per process. Tests import the app repeatedly; the registry does not forgive twice."""
    if key in _registered:
        return
    registry.register(collector)
    _registered.add(key)


# --- the ASGI middleware ------------------------------------------------------------------------------
class MetricsMiddleware:
    """Counts and times every HTTP request by its route template.

    Pure ASGI rather than BaseHTTPMiddleware, which buffers responses and
    interferes with streaming and with WebSocket upgrades. The route template
    is read from the route FastAPI records on the scope once it has matched --
    the original route object, so a route that arrived through an included
    router carries its full template -- so `/incidents/42` and `/incidents/43`
    are one series, and a path that matched nothing is `unmatched` rather than
    a series per probe. `route_of_endpoint` is a fallback for a plain Starlette
    app that records only the endpoint.
    """

    def __init__(self, app, route_of_endpoint: dict | None = None) -> None:
        self._app = app
        self._route_of_endpoint = route_of_endpoint or {}

    def _template(self, scope) -> str:
        route = scope.get("route")
        path = getattr(route, "path", None)
        if isinstance(path, str):
            return path
        return self._route_of_endpoint.get(scope.get("endpoint"), UNMATCHED_ROUTE)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        status_holder = {"status": 500}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        started = time.perf_counter()
        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            elapsed = time.perf_counter() - started
            route = self._template(scope)
            method = scope.get("method", "GET")
            HTTP_REQUESTS.labels(method, route, str(status_holder["status"])).inc()
            HTTP_LATENCY.labels(method, route).observe(elapsed)


def route_templates(app) -> dict:
    """endpoint callable -> path template, for every route the app knows."""
    templates = {}
    for route in app.routes:
        endpoint = getattr(route, "endpoint", None)
        path = getattr(route, "path", None)
        if endpoint is not None and path is not None:
            templates[endpoint] = path
    return templates


def render(registry=REGISTRY) -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
