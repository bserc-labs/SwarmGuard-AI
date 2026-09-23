"""Admission control, and the pool deadlock it exists to prevent.

The load test of 2026-09-22 stopped the API at 100 packets/second: every pooled
connection "idle in transaction" after the authentication lookup, its request
waiting for a worker thread, every worker thread running a newer request
waiting for a connection. middleware/admission.py bounds how many requests can
be inside at once; config.Settings._connections_fit_the_pool keeps that bound,
plus the background threads, inside the pool.
"""

import asyncio
import json
import threading
import time

import anyio.to_thread
import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import ValidationError
from sqlalchemy.pool import QueuePool

import main
from config import Settings, get_settings
from middleware.admission import AdmissionLimit
from utils.metrics import HTTP_ADMISSION_REJECTED, HTTP_IN_FLIGHT


# ----------------------------------------------------------------- the model
class _FakeDBAPIConnection:
    def rollback(self):
        pass

    def commit(self):
        pass

    def close(self):
        pass


def _deadlock_prone_app(pool: QueuePool) -> FastAPI:
    """The shape of an authenticated route, on a real SQLAlchemy pool.

    A connection is checked out in one worker-thread hop (the user lookup) and
    held across the next two (permission check, endpoint) -- as the request
    session's transaction is in the real app.
    """
    app = FastAPI()

    def session():
        conn = pool.connect()
        try:
            yield conn
        finally:
            conn.close()

    def current_user(conn=Depends(session)):
        return conn

    def permitted(user=Depends(current_user)):
        return user

    @app.get("/work")
    def work(_=Depends(permitted)):
        return {"ok": True}

    return app


async def _burst(app, n: int) -> list[int]:
    # Two worker threads for a pool of two: the proportions of the real app
    # (40 threads, 60 connections) where the deadlock needs a burst beyond the pool.
    anyio.to_thread.current_default_thread_limiter().total_tokens = 2
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        responses = await asyncio.gather(*(client.get("/work") for _ in range(n)))
    return [r.status_code for r in responses]


def _pool() -> QueuePool:
    return QueuePool(_FakeDBAPIConnection, pool_size=2, max_overflow=0, timeout=0.3)


class TestTheDeadlock:
    def test_without_admission_a_burst_starves_on_the_pool(self):
        # Requests 1-2 take both connections and queue for their next thread
        # hop; 3-8 take the threads and wait on the pool until it times out.
        statuses = asyncio.run(_burst(_deadlock_prone_app(_pool()), 8))
        assert statuses.count(500) >= 4, statuses

    def test_with_admission_the_same_burst_all_succeeds(self):
        app = AdmissionLimit(_deadlock_prone_app(_pool()), limit=2, wait_s=10.0)
        statuses = asyncio.run(_burst(app, 8))
        assert statuses == [200] * 8


# ----------------------------------------------------------- the middleware
def _gated_app():
    """An ASGI app whose requests wait on `gate`; `inside` counts them."""
    state = {"inside": 0, "peak": 0}
    gate = asyncio.Event()

    async def app(scope, receive, send):
        state["inside"] += 1
        state["peak"] = max(state["peak"], state["inside"])
        try:
            if scope["path"] == "/boom":
                raise RuntimeError("boom")
            await gate.wait()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        finally:
            state["inside"] -= 1

    return app, gate, state


async def _call(app, path: str = "/x", scope_type: str = "http"):
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        sent.append(message)

    await app({"type": scope_type, "path": path, "method": "GET", "headers": []}, receive, send)
    return sent


def _status(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


class TestAdmissionLimit:
    def test_requests_beyond_the_limit_wait_and_then_run(self):
        async def scenario():
            inner, gate, state = _gated_app()
            app = AdmissionLimit(inner, limit=2, wait_s=5.0)
            calls = [asyncio.create_task(_call(app)) for _ in range(5)]
            await asyncio.sleep(0.05)
            inside_while_gated = state["inside"]
            gate.set()
            results = await asyncio.gather(*calls)
            return inside_while_gated, state["peak"], [_status(r) for r in results]

        inside, peak, statuses = asyncio.run(scenario())
        assert inside == 2
        assert peak == 2
        assert statuses == [200] * 5

    def test_a_request_that_waits_too_long_is_told_to_retry(self):
        async def scenario():
            inner, gate, _ = _gated_app()
            app = AdmissionLimit(inner, limit=1, wait_s=0.05)
            first = asyncio.create_task(_call(app))
            await asyncio.sleep(0.01)
            before = HTTP_ADMISSION_REJECTED._value.get()
            rejected = await _call(app)
            after = HTTP_ADMISSION_REJECTED._value.get()
            gate.set()
            await first
            return rejected, after - before

        sent, counted = asyncio.run(scenario())
        start = sent[0]
        assert start["status"] == 503
        headers = dict(start["headers"])
        assert headers[b"retry-after"] == b"1"
        assert headers[b"content-type"] == b"application/json"
        body = json.loads(sent[1]["body"])
        assert body["error"] == "Service Unavailable"
        assert counted == 1

    def test_liveness_metrics_and_websockets_are_never_queued(self):
        async def scenario():
            inner, gate, _ = _gated_app()
            app = AdmissionLimit(inner, limit=1, wait_s=0.05, exempt_paths=("/health",))
            held = asyncio.create_task(_call(app))
            await asyncio.sleep(0.01)
            # Exempt and non-HTTP calls reach the app although the only slot is
            # taken; release the gate shortly so they can finish.
            asyncio.get_running_loop().call_later(0.1, gate.set)
            health = await _call(app, "/health")
            socket = await _call(app, "/ws", scope_type="websocket")
            await held
            return health, socket

        health, socket = asyncio.run(scenario())
        assert _status(health) == 200
        assert _status(socket) == 200

    def test_a_failing_request_gives_its_slot_back(self):
        async def scenario():
            inner, gate, _ = _gated_app()
            app = AdmissionLimit(inner, limit=1, wait_s=0.2)
            with pytest.raises(RuntimeError):
                await _call(app, "/boom")
            gate.set()
            return await _call(app)

        assert _status(asyncio.run(scenario())) == 200

    def test_the_in_flight_gauge_returns_to_where_it_was(self):
        async def scenario():
            inner, gate, _ = _gated_app()
            app = AdmissionLimit(inner, limit=3, wait_s=1.0)
            base = HTTP_IN_FLIGHT._value.get()
            calls = [asyncio.create_task(_call(app)) for _ in range(3)]
            await asyncio.sleep(0.02)
            during = HTTP_IN_FLIGHT._value.get() - base
            gate.set()
            await asyncio.gather(*calls)
            return during, HTTP_IN_FLIGHT._value.get() - base

        during, after = asyncio.run(scenario())
        assert during == 3
        assert after == 0

    def test_a_limit_below_one_is_refused(self):
        with pytest.raises(ValueError):
            AdmissionLimit(lambda *a: None, limit=0, wait_s=1.0)


# ------------------------------------------------------------ the budget
class TestTheConnectionBudget:
    def test_the_defaults_fit_the_pool(self):
        s = get_settings()
        demand = s.HTTP_MAX_IN_FLIGHT + s.BACKGROUND_THREADS + s.DB_POOL_RESERVE
        assert demand <= s.DB_POOL_SIZE + s.DB_MAX_OVERFLOW

    def test_settings_that_could_exhaust_the_pool_are_refused(self):
        with pytest.raises(ValidationError) as caught:
            Settings(HTTP_MAX_IN_FLIGHT=60, DB_POOL_SIZE=20, DB_MAX_OVERFLOW=40)
        message = str(caught.value)
        assert "HTTP_MAX_IN_FLIGHT (60)" in message
        assert "deadlock" in message

    def test_raising_the_pool_admits_more(self):
        s = Settings(HTTP_MAX_IN_FLIGHT=80, DB_POOL_SIZE=40, DB_MAX_OVERFLOW=60)
        assert s.HTTP_MAX_IN_FLIGHT == 80


# ----------------------------------------------------------- the wiring
class TestWiring:
    def test_admission_sits_inside_cors_and_inside_metrics(self):
        # user_middleware runs outermost first.
        names = [m.cls.__name__ for m in main.app.user_middleware]
        assert names.index("MetricsMiddleware") < names.index("CORSMiddleware")
        assert names.index("CORSMiddleware") < names.index("AdmissionLimit")

    def test_startup_bounds_the_threads_behind_to_thread(self, monkeypatch):
        monkeypatch.setattr(main.supervisor, "start", lambda: None)
        monkeypatch.setattr(main, "assert_schema_current", lambda *a, **k: None)

        def name_after_a_pause():
            time.sleep(0.02)
            return threading.current_thread().name

        async def scenario():
            await main.startup()
            return await asyncio.gather(*(asyncio.to_thread(name_after_a_pause) for _ in range(40)))

        names = asyncio.run(scenario())
        assert all(n.startswith("swarmguard-bg") for n in names), set(names)
        assert len(set(names)) <= get_settings().BACKGROUND_THREADS
