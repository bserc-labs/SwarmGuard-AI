"""Supervised background loops.

The heartbeat monitor is what notices a jammed, silent drone. It ran as a bare
asyncio task: if it ever exited -- an unexpected exception type, a cancellation
from somewhere, a BaseException -- nothing restarted it and nothing reported
it, and "the monitor is dead" looked exactly like "no drone is jammed". For
this product that is the worst silent failure there is.

A Supervisor owns each loop. It runs the loop's work on an interval, restarts
it with backoff when the work raises, recreates the task if it ever ends for
any reason other than shutdown, and records the time of the last successful
pass. That last timestamp is the point: a loop that has not ticked within a
few intervals is *stalled*, and stalled is something /ready can refuse on and
/metrics can graph, instead of something an operator infers from an absence.
"""

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

Work = Callable[[], Awaitable[None]]


@dataclass
class LoopState:
    name: str
    interval_s: float
    work: Work
    run_first: bool
    started_at: float | None = None
    last_tick: float | None = None
    ticks: int = 0
    failures: int = 0
    restarts: int = 0
    last_error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)

    def stall_after_s(self, grace_s: float) -> float:
        """Three missed intervals plus a grace for slow single passes."""
        return self.interval_s * 3 + grace_s


class Supervisor:
    def __init__(
        self,
        logger,
        *,
        initial_backoff_s: float = 1.0,
        max_backoff_s: float = 60.0,
        stall_grace_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._logger = logger
        self._initial_backoff_s = initial_backoff_s
        self._max_backoff_s = max_backoff_s
        self._stall_grace_s = stall_grace_s
        self._clock = clock
        self._loops: dict[str, LoopState] = {}
        self._running = False

    # --- registration --------------------------------------------------------
    def register(self, name: str, work: Work, interval_s: float, *, run_first: bool = True) -> None:
        """`work` is one pass. It is awaited, then the loop sleeps `interval_s`.

        run_first=False sleeps first: the heartbeat monitor gives drones ten
        seconds to report after a start before declaring any of them silent.
        """
        if name in self._loops:
            raise ValueError(f"loop {name!r} is already registered")
        self._loops[name] = LoopState(name=name, interval_s=interval_s, work=work, run_first=run_first)

    # --- lifecycle ----------------------------------------------------------------
    def start(self) -> None:
        self._running = True
        for state in self._loops.values():
            self._spawn(state)

    def _spawn(self, state: LoopState) -> None:
        state.started_at = self._clock()
        state.task = asyncio.create_task(self._run(state), name=state.name)
        state.task.add_done_callback(functools.partial(self._on_task_done, state))

    def _on_task_done(self, state: LoopState, task: asyncio.Task) -> None:
        # Only cancellation during shutdown is a normal end. Anything else --
        # including a BaseException the loop body could not catch -- is an
        # unexpected exit, and the loop comes back.
        if not self._running or task.cancelled():
            return
        error = task.exception() if not task.cancelled() else None
        state.restarts += 1
        state.last_error = f"{type(error).__name__}: {error}" if error else "exited"
        self._logger.error(
            f"Background loop {state.name!r} exited unexpectedly ({state.last_error}); restarting",
            exc_info=error,
        )
        self._spawn(state)

    async def _run(self, state: LoopState) -> None:
        backoff = self._initial_backoff_s
        if not state.run_first:
            await asyncio.sleep(state.interval_s)
        while True:
            try:
                await state.work()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state.failures += 1
                state.last_error = f"{type(exc).__name__}: {exc}"
                self._logger.error(
                    f"Background loop {state.name!r} failed ({state.last_error}); "
                    f"retrying in {backoff:.0f}s",
                    exc_info=True,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff_s)
                continue
            state.ticks += 1
            state.last_tick = self._clock()
            backoff = self._initial_backoff_s
            await asyncio.sleep(state.interval_s)

    async def stop(self, grace_s: float) -> list[str]:
        """Cancel every loop and wait up to `grace_s`. Returns the names that did not stop."""
        self._running = False
        # Only live tasks. A task from an earlier start -- finished, or bound to
        # an event loop that has since closed -- has nothing left to stop.
        tasks = [s.task for s in self._loops.values() if s.task is not None and not s.task.done()]
        for task in tasks:
            task.cancel()
        if not tasks:
            return []
        _, pending = await asyncio.wait(tasks, timeout=grace_s)
        return [t.get_name() for t in pending]

    # --- observation ----------------------------------------------------------------
    def stalled(self) -> list[str]:
        """Loops whose last successful pass is older than they can explain."""
        now = self._clock()
        names = []
        for state in self._loops.values():
            reference = state.last_tick if state.last_tick is not None else state.started_at
            if reference is None:
                continue  # not started
            if now - reference > state.stall_after_s(self._stall_grace_s):
                names.append(state.name)
        return names

    def status(self) -> dict[str, dict]:
        now = self._clock()
        stalled = set(self.stalled())
        return {
            name: {
                "interval_s": s.interval_s,
                "ticks": s.ticks,
                "failures": s.failures,
                "restarts": s.restarts,
                "seconds_since_tick": None if s.last_tick is None else round(now - s.last_tick, 1),
                "stalled": name in stalled,
                "last_error": s.last_error,
                "alive": s.task is not None and not s.task.done(),
            }
            for name, s in self._loops.items()
        }

    @property
    def names(self) -> list[str]:
        return list(self._loops)
