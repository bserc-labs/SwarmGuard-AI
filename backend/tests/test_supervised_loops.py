"""The two background loops run under the supervisor, and a stalled one fails /ready.

The heartbeat monitor is what detects a jammed, silent drone. Before this it
was a bare asyncio task: an unexpected exit killed it silently, and its death
was indistinguishable from "no drone is jammed". Now a loop that stops ticking
is a dependency that is down.
"""

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_both_loops_are_registered_with_their_intervals():
    status = main.supervisor.status()
    assert status["heartbeat-monitor"]["interval_s"] == 10.0
    assert status["telemetry-retention"]["interval_s"] == 3600.0
    assert status["audit-retention"]["interval_s"] == 86400.0


def test_the_heartbeat_monitor_gives_drones_one_interval_before_judging_them():
    state = main.supervisor._loops["heartbeat-monitor"]
    assert state.run_first is False
    assert main.supervisor._loops["telemetry-retention"].run_first is True


def test_a_stalled_loop_makes_the_instance_not_ready(monkeypatch):
    monkeypatch.setattr(main.supervisor, "stalled", lambda: ["heartbeat-monitor"])
    res = client.get("/ready")
    assert res.status_code == 503
    body = res.json()
    assert body["checks"]["background"] == {
        "ok": False, "required": True, "detail": "stalled: heartbeat-monitor",
    }
    assert "heartbeat-monitor" in body["background"]


def test_ready_reports_each_loop_when_nothing_is_stalled():
    monkeypatched = main.supervisor.stalled()  # whatever the real state is
    res = client.get("/ready")
    body = res.json()
    assert set(body["background"]) == {"heartbeat-monitor", "telemetry-retention", "audit-retention"}
    if not monkeypatched:
        assert body["checks"]["background"]["ok"]


def test_the_loops_run_for_real_under_the_app():
    """Inside a TestClient context the lifespan starts them; they must be alive."""
    with TestClient(main.app) as live:
        body = live.get("/ready").json()
        assert all(loop["alive"] for loop in body["background"].values()), body["background"]
