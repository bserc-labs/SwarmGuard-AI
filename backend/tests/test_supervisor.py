"""The supervisor keeps a background loop alive and says when it is not.

A bare asyncio task that raises or exits is simply gone. The heartbeat monitor
running as one meant "monitor dead" was indistinguishable from "no drone is
jammed". Everything here is about making that distinguishable.
"""

import asyncio
import logging

import pytest

from services.supervisor import Supervisor


class ManualClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def logger():
    return logging.getLogger("supervisor-test")


def run(coro):
    return asyncio.run(coro)


class TestTicks:
    def test_each_successful_pass_is_a_tick(self, logger):
        async def scenario():
            count = 0

            async def work():
                nonlocal count
                count += 1

            sup = Supervisor(logger)
            sup.register("probe", work, interval_s=0.01)
            sup.start()
            await asyncio.sleep(0.1)
            status = sup.status()["probe"]
            await sup.stop(1)
            return count, status

        count, status = run(scenario())
        assert count >= 3 and status["ticks"] == count
        assert status["alive"] and not status["stalled"] and status["failures"] == 0

    def test_run_first_false_sleeps_before_the_first_pass(self, logger):
        async def scenario():
            calls = []

            async def work():
                calls.append(1)

            sup = Supervisor(logger)
            sup.register("later", work, interval_s=0.2, run_first=False)
            sup.start()
            await asyncio.sleep(0.05)
            early = len(calls)
            await asyncio.sleep(0.25)
            late = len(calls)
            await sup.stop(1)
            return early, late

        early, late = run(scenario())
        assert early == 0 and late >= 1


class TestFailures:
    def test_a_raising_pass_is_retried_with_backoff_and_the_loop_survives(self, logger, caplog):
        async def scenario():
            attempts = 0

            async def work():
                nonlocal attempts
                attempts += 1
                if attempts < 3:
                    raise RuntimeError(f"boom {attempts}")

            sup = Supervisor(logger, initial_backoff_s=0.01, max_backoff_s=0.05)
            sup.register("flaky", work, interval_s=0.01)
            sup.start()
            await asyncio.sleep(0.3)
            status = sup.status()["flaky"]
            await sup.stop(1)
            return attempts, status

        with caplog.at_level(logging.ERROR):
            attempts, status = run(scenario())
        assert attempts >= 3, "the loop must keep trying after an exception"
        assert status["failures"] == 2 and status["ticks"] >= 1
        assert "retrying in" in caplog.text and "boom 1" in caplog.text
        assert status["last_error"] is not None and status["last_error"].endswith("boom 2")

    def test_a_task_that_ends_for_any_other_reason_is_recreated(self, logger, caplog):
        """BaseException is exactly what an except-Exception loop body cannot catch."""

        class Escapes(BaseException):
            pass

        async def scenario():
            calls = 0

            async def work():
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise Escapes("out")

            sup = Supervisor(logger)
            sup.register("escaper", work, interval_s=0.01)
            sup.start()
            await asyncio.sleep(0.1)
            status = sup.status()["escaper"]
            await sup.stop(1)
            return calls, status

        with caplog.at_level(logging.ERROR):
            calls, status = run(scenario())
        assert calls >= 2, "the loop was not brought back"
        assert status["restarts"] == 1 and status["alive"]
        assert "exited unexpectedly" in caplog.text


class TestStall:
    def test_a_loop_that_stops_ticking_is_reported(self, logger):
        clock = ManualClock()

        async def scenario():
            gate = asyncio.Event()

            async def work():
                await gate.wait()  # hangs until told otherwise

            sup = Supervisor(logger, stall_grace_s=1.0, clock=clock)
            sup.register("hung", work, interval_s=10.0)
            sup.start()
            await asyncio.sleep(0.01)
            before = sup.stalled()
            clock.now += 10 * 3 + 1.5  # past three intervals plus grace
            after = sup.stalled()
            gate.set()
            await sup.stop(1)
            return before, after

        before, after = run(scenario())
        assert before == [] and after == ["hung"]

    def test_a_healthy_loop_is_never_reported(self, logger):
        clock = ManualClock()

        async def scenario():
            async def work():
                pass

            sup = Supervisor(logger, stall_grace_s=1.0, clock=clock)
            sup.register("fine", work, interval_s=10.0)
            sup.start()
            await asyncio.sleep(0.01)  # first tick lands
            clock.now += 10 * 3  # within the window
            result = sup.stalled()
            await sup.stop(1)
            return result

        assert run(scenario()) == []


class TestStop:
    def test_stop_cancels_and_reports_what_did_not_comply(self, logger):
        async def scenario():
            async def polite():
                await asyncio.sleep(3600)

            async def stubborn():
                ignored = False
                while True:
                    try:
                        await asyncio.sleep(3600)
                    except asyncio.CancelledError:
                        if not ignored:
                            ignored = True
                            continue  # swallows the supervisor's cancellation
                        raise  # honours the next one, so this test's loop can close

            sup = Supervisor(logger)
            sup.register("polite", polite, interval_s=1)
            sup.register("stubborn", stubborn, interval_s=1)
            sup.start()
            await asyncio.sleep(0.01)
            left = await sup.stop(0.2)
            # the test's own loop must be able to close: end the stubborn one for real
            task = next(s.task for s in sup._loops.values() if s.name == "stubborn")
            task.cancel()
            await asyncio.sleep(0.01)
            return left, sup.status()["polite"]["alive"]

        left, polite_alive = run(scenario())
        assert left == ["stubborn"] and not polite_alive

    def test_a_task_ending_during_stop_is_not_restarted(self, logger):
        async def scenario():
            async def work():
                pass

            sup = Supervisor(logger)
            sup.register("once", work, interval_s=0.01)
            sup.start()
            await asyncio.sleep(0.03)
            await sup.stop(1)
            await asyncio.sleep(0.03)
            return sup.status()["once"]

        status = run(scenario())
        assert status["restarts"] == 0 and not status["alive"]


def test_duplicate_names_are_refused(logger):
    sup = Supervisor(logger)

    async def work():
        pass

    sup.register("x", work, interval_s=1)
    with pytest.raises(ValueError):
        sup.register("x", work, interval_s=1)
