"""/ready answers 503 when a dependency that matters is down; /health does not.

Verified by experiment before this existed: postgres stopped, /health 200,
container "healthy", login 500. The probes here are the signal that was missing.
"""

import asyncio
import os
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import main
from config import Settings
from services import readiness
from services.readiness import Probe, Readiness, check_readiness, probe_database, probe_redis
from tests.conftest import engine as test_engine

client = TestClient(main.app)


class TestTheProbes:
    def test_the_test_database_is_reachable(self):
        assert probe_database(test_engine).ok

    def test_an_unreachable_database_is_reported_not_raised(self):
        dead = create_engine("postgresql://u:p@127.0.0.1:1/none", connect_args={"connect_timeout": 1})
        probe = probe_database(dead)
        assert not probe.ok and "postgres unreachable" in probe.detail

    def test_redis_not_configured_is_not_a_requirement(self):
        probe = probe_redis(None, required=True, timeout_s=1)
        assert probe.ok and not probe.required

    def test_an_unreachable_redis_is_reported_not_raised(self):
        probe = probe_redis("redis://127.0.0.1:1/0", required=True, timeout_s=0.5)
        assert not probe.ok and "redis unreachable" in probe.detail and probe.required

    @pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="no REDIS_URL in this environment")
    def test_the_configured_redis_answers(self):
        assert probe_redis(os.environ["REDIS_URL"], required=True, timeout_s=2).ok


class TestTheDecision:
    def test_a_required_failure_means_not_ready(self):
        r = Readiness({"database": Probe(True, "ok"), "redis": Probe(False, "down", required=True)})
        assert not r.ready and r.as_dict()["status"] == "not_ready"

    def test_an_optional_failure_is_reported_but_still_ready(self):
        r = Readiness({"database": Probe(True, "ok"), "redis": Probe(False, "down", required=False)})
        assert r.ready
        assert r.as_dict()["checks"]["redis"] == {"ok": False, "required": False, "detail": "down"}

    def test_a_probe_that_hangs_is_not_ready_once_the_deadline_passes(self, monkeypatch):
        def hangs(engine):
            time.sleep(2)
            return Probe(True, "too late")

        monkeypatch.setattr(readiness, "probe_database", hangs)

        async def scenario():
            # Timed inside the loop: asyncio.run() joins the executor's threads
            # on the way out, which is the hung probe finishing, not the answer.
            started = time.monotonic()
            r = await check_readiness(test_engine, None, redis_required=True, timeout_s=0.3)
            return r, time.monotonic() - started

        r, elapsed = asyncio.run(scenario())
        assert elapsed < 1.5, "the answer must not wait for the hung probe"
        assert not r.ready and "did not answer" in r.checks["database"].detail


class TestTheRoute:
    def test_ready_when_everything_answers(self):
        res = client.get("/ready")
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "ready" and body["checks"]["database"]["ok"]

    def test_503_with_the_reason_when_the_database_is_down(self, monkeypatch):
        monkeypatch.setattr(main, "engine", create_engine("postgresql://u:p@127.0.0.1:1/none",
                                                          connect_args={"connect_timeout": 1}))
        res = client.get("/ready")
        assert res.status_code == 503
        assert res.json()["status"] == "not_ready"
        assert "postgres unreachable" in res.json()["checks"]["database"]["detail"]

    def test_health_stays_a_bare_liveness_answer(self, monkeypatch):
        """Docker restarts on liveness; a database outage must not cause a restart storm."""
        monkeypatch.setattr(main, "engine", create_engine("postgresql://u:p@127.0.0.1:1/none",
                                                          connect_args={"connect_timeout": 1}))
        assert client.get("/health").status_code == 200

    def test_redis_down_is_503_by_default_and_a_warning_when_not_required(self, monkeypatch):
        monkeypatch.setattr(main, "REDIS_URL", "redis://127.0.0.1:1/0")
        assert client.get("/ready").status_code == 503
        settings = main.get_settings()
        monkeypatch.setattr(settings, "READINESS_REQUIRES_REDIS", False)
        res = client.get("/ready")
        assert res.status_code == 200
        assert res.json()["checks"]["redis"] == {
            "ok": False, "required": False, "detail": "redis unreachable: ConnectionError",
        }

    def test_it_needs_no_token(self):
        assert client.get("/ready").status_code != 401


def test_defaults():
    assert Settings.model_fields["READINESS_REQUIRES_REDIS"].default is True
    assert Settings.model_fields["READINESS_TIMEOUT_S"].default == 3.0
