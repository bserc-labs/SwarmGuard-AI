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
    async def _slow_loop(self, log: list[str]) -> None:
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            log.append("cancelled")
            raise

    def test_background_tasks_are_cancelled_and_awaited(self, monkeypatch):
        log: list[str] = []

        async def scenario():
            task = asyncio.create_task(self._slow_loop(log), name="probe")
            await asyncio.sleep(0)  # let it enter its loop, as a real one would have long ago
            monkeypatch.setattr(main.app.state, "background_tasks", [task], raising=False)
            await main.shutdown()
            return task

        task = asyncio.run(scenario())
        assert task.cancelled(), "shutdown must cancel the loop, not abandon it"
        assert log == ["cancelled"], "and wait for the cancellation to land"
        assert main.app.state.background_tasks == []

    def test_a_task_that_ignores_cancellation_does_not_hang_shutdown(self, monkeypatch, caplog):
        monkeypatch.setattr(main, "SHUTDOWN_GRACE_S", 0.2)

        async def stubborn():
            ignored = False
            while True:
                try:
                    await asyncio.sleep(3600)
                except asyncio.CancelledError:
                    if not ignored:
                        ignored = True
                        continue  # swallows the first cancellation
                    raise  # honours the second, so the test's loop can close

        async def scenario():
            task = asyncio.create_task(stubborn(), name="stubborn")
            await asyncio.sleep(0)
            monkeypatch.setattr(main.app.state, "background_tasks", [task], raising=False)
            await asyncio.wait_for(main.shutdown(), timeout=5)
            task.cancel()
            return task

        asyncio.run(scenario())
        assert "did not stop within" in caplog.text

    def test_shutdown_is_safe_to_call_with_nothing_started(self):
        """A failed start-up (schema behind) still runs the shutdown half."""
        main.app.state.background_tasks = []
        asyncio.run(main.shutdown())


@pytest.mark.parametrize("name", ["heartbeat-monitor", "telemetry-retention"])
def test_the_loops_are_named_so_a_log_line_says_which_one(name):
    """Named tasks: the supervisor and the shutdown log refer to them by name."""
    import inspect

    assert f'name="{name}"' in inspect.getsource(main.startup)
