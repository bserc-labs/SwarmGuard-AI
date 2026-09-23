"""Admission control: a bounded number of HTTP requests inside the application.

The load test of 2026-09-22 found the API deadlocked at 100 packets/second,
four times below where it had just measured its knee. Sampling
pg_stat_activity during the stall showed every one of the 60 pooled
connections "idle in transaction" on the authentication lookup.

A request runs in several worker-thread hops: the user lookup, the permission
check, the endpoint. The lookup opens a transaction on the request's session,
and the connection stays checked out while the request waits for a thread for
its next hop. The threads, meanwhile, were all running newer requests that
were waiting for a connection. Each side held what the other needed. SQLAlchemy's
10 s pool timeout broke it by failing requests, and it formed again at once --
the log shows waves of QueuePool errors ten seconds apart for sixteen minutes.

Nothing bounded how many requests could hold a connection, so any burst larger
than the pool could start it. This bounds it. With at most HTTP_MAX_IN_FLIGHT
requests inside, each holding at most one request-session connection, and
BACKGROUND_THREADS bounding everything that runs through asyncio.to_thread,
demand cannot exceed the pool (config.Settings._connections_fit_the_pool), and
a checkout never waits.

Requests beyond the limit wait here holding nothing. One that waits longer
than HTTP_ADMISSION_WAIT_S is answered 503 with Retry-After: shedding load at
the door, where it costs nothing, instead of queueing it inside, where the
backlog has already cost the capacity test minutes of latency.

A slot is held until the whole ASGI call returns, background tasks included,
so an ingest's detection counts against its request. That is deliberate: it is
backpressure on detection too, rather than an unbounded queue behind the
response.

WebSocket and lifespan traffic pass straight through, as do the paths given as
exempt (liveness and metrics, which touch no database and must answer under
load precisely because that is when someone is looking).
"""

import asyncio
import json
from collections.abc import Iterable
from typing import Any

from utils.metrics import HTTP_ADMISSION_REJECTED, HTTP_IN_FLIGHT


class AdmissionLimit:
    """Pure ASGI middleware: at most `limit` HTTP requests in the app at once."""

    def __init__(self, app: Any, *, limit: int, wait_s: float, exempt_paths: Iterable[str] = ()) -> None:
        if limit < 1:
            raise ValueError("admission limit must be at least 1")
        self.app = app
        self.limit = limit
        self.wait_s = wait_s
        self.exempt = frozenset(exempt_paths)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._slots: asyncio.Semaphore | None = None

    def _semaphore(self) -> asyncio.Semaphore:
        # An asyncio primitive belongs to the loop it first waits on. There is
        # one loop in production; a test suite starts one per client.
        loop = asyncio.get_running_loop()
        if self._slots is None or self._loop is not loop:
            self._loop, self._slots = loop, asyncio.Semaphore(self.limit)
        return self._slots

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") in self.exempt:
            await self.app(scope, receive, send)
            return

        slots = self._semaphore()
        try:
            await asyncio.wait_for(slots.acquire(), timeout=self.wait_s)
        except TimeoutError:
            HTTP_ADMISSION_REJECTED.inc()
            await _busy(send)
            return

        HTTP_IN_FLIGHT.inc()
        try:
            await self.app(scope, receive, send)
        finally:
            HTTP_IN_FLIGHT.dec()
            slots.release()


async def _busy(send: Any) -> None:
    # Same envelope as every other error response (main.py).
    body = json.dumps(
        {"error": "Service Unavailable", "detail": "Server busy; retry shortly."}
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 503,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"retry-after", b"1"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
