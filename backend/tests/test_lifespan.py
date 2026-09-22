"""Start-up and shutdown run through a lifespan handler, and shutdown is graceful.

The deprecated on_event hooks did not wait for anything on the way out: the
heartbeat monitor and the retention loop were abandoned wherever they were,
and the event loop was torn down under them. The lifespan cancels them, waits
for them to acknowledge, and only then stops the receiver and the sockets.
"""

import asyncio

import pytest

import main


def test_the_deprecated_hooks_are_gone():
    assert not getattr(main.app.router, "on_startup", []), "use the lifespan, not on_event"
    assert not getattr(main.app.router, "on_shutdown", [])
    assert main.app.router.lifespan_context is not None


class TestShutdown:
    def test_it_stops_the_supervisor_and_waits_for_its_loops(self, monkeypatch):
        calls = []

        async def fake_stop(grace_s):
            calls.append(grace_s)
            return []

        monkeypatch.setattr(main.supervisor, "stop", fake_stop)
        asyncio.run(main.shutdown())
        assert calls == [main.SHUTDOWN_GRACE_S]

    def test_a_loop_that_does_not_stop_is_named_not_hung_on(self, monkeypatch, caplog):
        async def fake_stop(grace_s):
            return ["heartbeat-monitor"]

        monkeypatch.setattr(main.supervisor, "stop", fake_stop)
        asyncio.run(main.shutdown())
        assert "'heartbeat-monitor' did not stop within" in caplog.text

    def test_shutdown_is_safe_to_call_with_nothing_started(self):
        """A failed start-up (schema behind) still runs the shutdown half."""
        asyncio.run(main.shutdown())


@pytest.mark.parametrize("name", ["heartbeat-monitor", "telemetry-retention"])
def test_the_loops_are_named_so_a_log_line_says_which_one(name):
    """The supervisor and the shutdown log refer to the loops by these names."""
    assert name in main.supervisor.names
