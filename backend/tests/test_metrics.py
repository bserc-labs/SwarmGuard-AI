"""Prometheus metrics: every series an operator would ask for, with bounded labels.

Nothing was measured before this. The tests here run the middleware over a
real ASGI app, read the collectors against fakes with known numbers, and pin
the one property that keeps a metrics endpoint from becoming its own outage:
label values are route templates and outcome names, never paths, drone ids or
organization ids.
"""

import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from services.supervisor import Supervisor
from utils import metrics
from utils.metrics import (
    HTTP_LATENCY,
    HTTP_REQUESTS,
    UNMATCHED_ROUTE,
    MetricsMiddleware,
    PoolCollector,
    SupervisorCollector,
    detection_tier,
    register_collector,
    route_templates,
)


def _counter(counter, **labels) -> float:
    return counter.labels(**labels)._value.get()


class TestDetectionTier:
    def test_the_kinematic_guard_is_read_off_its_metadata(self):
        d = {"explanation": {"metadata": {"detector": "kinematic_guard"}}}
        assert detection_tier(d) == "kinematic"

    def test_a_geofence_breach_is_recognised_by_its_zones(self):
        d = {"explanation": {"metadata": {"zones": [{"name": "runway"}]}}}
        assert detection_tier(d) == "geofence"

    def test_anything_else_is_the_ml_tier(self):
        assert detection_tier({"prediction": {"is_anomaly": True}}) == "ml"
        assert detection_tier({}) == "ml"


class TestMiddleware:
    @pytest.fixture
    def app(self):
        app = FastAPI()

        @app.get("/items/{item_id}")
        def item(item_id: int):
            return {"id": item_id}

        @app.get("/boom")
        def boom():
            raise RuntimeError("no")

        app.add_middleware(MetricsMiddleware, route_of_endpoint=route_templates(app))
        return app

    def test_requests_are_counted_by_route_template_not_path(self, app):
        before = _counter(HTTP_REQUESTS, method="GET", route="/items/{item_id}", status="200")
        client = TestClient(app)
        client.get("/items/1")
        client.get("/items/2")
        client.get("/items/3")
        assert _counter(HTTP_REQUESTS, method="GET", route="/items/{item_id}", status="200") == before + 3
        for series in HTTP_REQUESTS.collect()[0].samples:
            assert "/items/1" not in series.labels.get("route", ""), "a raw path leaked into a label"

    def test_a_route_from_an_included_router_carries_its_full_template(self):
        """This FastAPI keeps included routers nested; the live scrape showed every
        route as `unmatched` until the lookup used the route FastAPI records."""
        from fastapi import APIRouter

        app = FastAPI()
        router = APIRouter(prefix="/things")

        @router.get("/{thing_id}")
        def thing(thing_id: int):
            return {"id": thing_id}

        app.include_router(router)
        app.add_middleware(MetricsMiddleware)  # no endpoint map at all

        @app.get("/late")  # defined after the middleware, as main.py's own routes are
        def late():
            return {}

        before_thing = _counter(HTTP_REQUESTS, method="GET", route="/things/{thing_id}", status="200")
        before_late = _counter(HTTP_REQUESTS, method="GET", route="/late", status="200")
        client = TestClient(app)
        client.get("/things/7")
        client.get("/late")
        assert _counter(HTTP_REQUESTS, method="GET", route="/things/{thing_id}", status="200") == before_thing + 1
        assert _counter(HTTP_REQUESTS, method="GET", route="/late", status="200") == before_late + 1

    def test_a_path_that_matches_nothing_is_one_series(self, app):
        before = _counter(HTTP_REQUESTS, method="GET", route=UNMATCHED_ROUTE, status="404")
        client = TestClient(app)
        client.get("/nope/1")
        client.get("/nope/2")
        assert _counter(HTTP_REQUESTS, method="GET", route=UNMATCHED_ROUTE, status="404") == before + 2

    def test_an_exception_is_still_counted_as_a_500(self, app):
        before = _counter(HTTP_REQUESTS, method="GET", route="/boom", status="500")
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/boom").status_code == 500
        assert _counter(HTTP_REQUESTS, method="GET", route="/boom", status="500") == before + 1

    def test_latency_is_observed_per_route(self, app):
        histogram = HTTP_LATENCY.labels(method="GET", route="/items/{item_id}")
        before = histogram._sum.get()
        TestClient(app).get("/items/9")
        assert histogram._sum.get() > before

    def test_websocket_scopes_pass_straight_through(self):
        seen = []

        async def inner(scope, receive, send):
            seen.append(scope["type"])

        mw = MetricsMiddleware(inner, {})
        asyncio.run(mw({"type": "websocket"}, None, None))
        assert seen == ["websocket"]


class FakePool:
    def size(self):
        return 20

    def overflow(self):
        return 3

    def checkedout(self):
        return 7

    def checkedin(self):
        return 16

    _max_overflow = 40


class FakeEngine:
    pool = FakePool()


class TestCollectors:
    def _families(self, collector) -> dict:
        return {family.name: family for family in collector.collect()}

    def test_the_pool_collector_reads_the_engine_at_scrape_time(self):
        families = self._families(PoolCollector(FakeEngine()))
        value = lambda name: families[name].samples[0].value  # noqa: E731
        assert value("swarmguard_db_pool_checked_out") == 7
        assert value("swarmguard_db_pool_checked_in") == 16
        assert value("swarmguard_db_pool_overflow") == 3
        assert value("swarmguard_db_pool_size") == 20
        assert value("swarmguard_db_pool_max") == 60

    def test_the_supervisor_collector_reports_each_loop(self):
        async def scenario():
            sup = Supervisor(logging.getLogger("t"))

            async def work():
                pass

            sup.register("a-loop", work, interval_s=0.01)
            sup.start()
            await asyncio.sleep(0.05)
            families = self._families(SupervisorCollector(sup))
            await sup.stop(1)
            return families

        families = asyncio.run(scenario())
        ticks = {s.labels["loop"]: s.value for s in families["swarmguard_background_loop_ticks"].samples if s.name.endswith("_total")}
        assert ticks["a-loop"] >= 1
        stalled = {s.labels["loop"]: s.value for s in families["swarmguard_background_loop_stalled"].samples}
        assert stalled == {"a-loop": 0}
        assert "swarmguard_background_loop_seconds_since_tick" in families

    def test_registration_is_idempotent_per_key(self):
        registry = CollectorRegistry()
        metrics._registered.discard("test-pool")
        register_collector("test-pool", PoolCollector(FakeEngine()), registry)
        register_collector("test-pool", PoolCollector(FakeEngine()), registry)  # a second import of main
        assert len([n for n in registry.collect() if n.name == "swarmguard_db_pool_size"]) == 1
        metrics._registered.discard("test-pool")


class TestTheApp:
    """main.py wires the middleware, the collectors and /metrics."""

    @pytest.fixture(scope="class")
    def client(self):
        import main

        return TestClient(main.app)

    def test_metrics_is_served_in_the_exposition_format(self, client):
        res = client.get("/metrics")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("text/plain")
        body = res.text
        for name in (
            "swarmguard_http_requests_total",
            "swarmguard_telemetry_ingest_total",
            "swarmguard_detection_runs_total",
            "swarmguard_incidents_raised_total",
            "swarmguard_db_pool_checked_out",
            "swarmguard_background_loop_stalled",
            "swarmguard_websocket_connections",
        ):
            assert name in body, f"{name} is not exported"

    def test_a_request_shows_up_under_its_template(self, client):
        client.get("/incidents/999999")  # 401 or 404; either is a counted status
        body = client.get("/metrics").text
        assert 'route="/incidents/{id}"' in body
        assert "/incidents/999999" not in body

    def test_a_token_gates_the_endpoint_when_configured(self, client, monkeypatch):
        import main

        monkeypatch.setattr(main.get_settings(), "METRICS_TOKEN", "s3cret-metrics-token-value")
        assert client.get("/metrics").status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert client.get("/metrics", headers={"Authorization": "Bearer s3cret-metrics-token-value"}).status_code == 200
