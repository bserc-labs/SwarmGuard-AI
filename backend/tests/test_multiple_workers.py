"""Running more than one uvicorn worker.

One worker handles about 200 telemetry packets a second on two cores, and the
load test's recommendation was to run more. Three things have to be true first:
each worker's pool has to fit PostgreSQL's ceiling, a background pass must run
once per interval rather than once per worker, and a scrape has to report the
whole application rather than whichever worker answered.
"""

import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from config import Settings, get_settings
from services import leader
from utils import shared_store


class TestTheConnectionBudgetAcrossWorkers:
    def test_the_defaults_fit_one_worker(self):
        s = get_settings()
        assert (s.DB_POOL_SIZE + s.DB_MAX_OVERFLOW) * s.UVICORN_WORKERS <= s.DB_SERVER_MAX_CONNECTIONS

    def test_workers_whose_pools_would_exhaust_the_server_are_refused(self):
        # Four workers x 60 connections is 240 against PostgreSQL's default 100.
        with pytest.raises(ValidationError) as caught:
            Settings(UVICORN_WORKERS=4, DB_POOL_SIZE=20, DB_MAX_OVERFLOW=40)
        message = str(caught.value)
        assert "240 connections" in message
        assert "max_connections" in message

    def test_a_pool_sized_for_the_worker_count_is_accepted(self):
        # The same four workers with a pool each that fits: 4 x 24 = 96 < 100.
        s = Settings(UVICORN_WORKERS=4, DB_POOL_SIZE=8, DB_MAX_OVERFLOW=16, HTTP_MAX_IN_FLIGHT=8,
                     BACKGROUND_THREADS=8, DB_POOL_RESERVE=4)
        assert s.UVICORN_WORKERS == 4

    def test_a_worker_count_below_one_is_refused(self):
        with pytest.raises(ValidationError):
            Settings(UVICORN_WORKERS=0)


class TestOnePassPerInterval:
    @pytest.fixture
    def store(self, monkeypatch):
        """A stand-in for Redis with just the one operation that matters."""

        class FakeRedis:
            def __init__(self):
                self.keys: dict[str, str] = {}

            def set(self, key, value, nx=False, ex=None):
                if nx and key in self.keys:
                    return None
                self.keys[key] = value
                return True

        fake = FakeRedis()
        monkeypatch.setattr(leader, "redis_client", lambda: fake)
        return fake

    def test_only_the_first_worker_runs_the_pass(self, store):
        ran = []

        async def work():
            ran.append(1)

        guarded = leader.once_across_workers("probe", 10.0, work)

        asyncio.run(guarded())  # this worker claims it
        asyncio.run(guarded())  # the others find it claimed
        asyncio.run(guarded())

        assert ran == [1]

    def test_the_next_interval_is_a_fresh_race(self, store):
        ran = []

        async def work():
            ran.append(1)

        guarded = leader.once_across_workers("probe", 10.0, work)
        asyncio.run(guarded())
        store.keys.clear()  # the claim's lifetime ran out
        asyncio.run(guarded())

        assert ran == [1, 1]

    def test_without_a_shared_store_the_pass_still_runs(self, monkeypatch):
        # One worker and no Redis is a supported deployment; the work must
        # happen. Several workers without Redis duplicate it, which is the
        # documented degradation.
        monkeypatch.setattr(leader, "redis_client", lambda: None)
        ran = []

        async def work():
            ran.append(1)

        guarded = leader.once_across_workers("probe", 10.0, work)
        asyncio.run(guarded())
        asyncio.run(guarded())

        assert ran == [1, 1]

    def test_a_store_that_errors_does_not_stop_the_work(self, monkeypatch):
        class Broken:
            def set(self, *a, **k):
                raise RuntimeError("redis is down")

        monkeypatch.setattr(leader, "redis_client", lambda: Broken())
        ran = []

        async def work():
            ran.append(1)

        asyncio.run(leader.once_across_workers("probe", 10.0, work)())
        assert ran == [1]


class TestAScrapeReportsEveryWorker:
    """Counters live per process; the scrape has to add them up.

    Run in subprocesses because that is the situation: prometheus_client writes
    one file per process id, and aggregation only means anything across them.
    """

    def _worker(self, tmp_path, snippet: str) -> str:
        import os
        import subprocess
        import sys

        env = {
            **os.environ,
            "PROMETHEUS_MULTIPROC_DIR": str(tmp_path),
            "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
        }
        result = subprocess.run(  # noqa: S603 - this interpreter, a literal snippet
            [sys.executable, "-c", snippet], env=env, capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr[-2000:]
        return result.stdout

    def test_counters_from_two_workers_are_summed(self, tmp_path):
        count = "from utils import metrics; metrics.INGEST.labels('accepted').inc()"
        self._worker(tmp_path, count)
        self._worker(tmp_path, count)

        rendered = self._worker(
            tmp_path,
            "from utils import metrics; print(metrics.render()[0].decode())",
        )

        line = next(
            line for line in rendered.splitlines()
            if line.startswith('swarmguard_telemetry_ingest_total{outcome="accepted"}')
        )
        assert line.endswith(" 2.0"), line

    def test_a_gauge_sums_the_workers_holding_it(self, tmp_path):
        hold = "from utils import metrics; metrics.HTTP_IN_FLIGHT.inc(3)"
        self._worker(tmp_path, hold)
        self._worker(tmp_path, hold)

        rendered = self._worker(
            tmp_path, "from utils import metrics; print(metrics.render()[0].decode())"
        )

        line = next(
            line for line in rendered.splitlines()
            if line.startswith("swarmguard_http_in_flight ")
        )
        assert line.endswith(" 6.0"), line

    def test_without_the_directory_nothing_changes(self):
        # The single-worker path stays exactly as it was: one registry, read live.
        from utils import metrics

        assert metrics.MULTIPROCESS is False
        text, content_type = metrics.render()
        assert b"swarmguard_" in text
        assert "text/plain" in content_type


class TestTheSharedStore:
    def test_no_redis_url_means_no_client(self, monkeypatch):
        monkeypatch.setattr(shared_store, "REDIS_URL", "")
        shared_store.reset_for_tests()
        try:
            assert shared_store.redis_client() is None
        finally:
            shared_store.reset_for_tests()

    def test_an_unreachable_redis_is_survivable(self, monkeypatch):
        monkeypatch.setattr(shared_store, "REDIS_URL", "redis://127.0.0.1:6399/0")
        shared_store.reset_for_tests()
        try:
            assert shared_store.redis_client() is None
        finally:
            shared_store.reset_for_tests()
