"""One worker per pass.

The background loops -- the heartbeat monitor, the two retention checks -- are
one-per-application work, not one-per-worker. With a single uvicorn process
that distinction did not exist. With `--workers N` every worker would run every
pass: N sweeps for silent drones, N retention checks, N audit purges, all on the
same interval and mostly at the same instant.

None of it would corrupt anything -- the incident engine's advisory lock and
suppression see to the heartbeat monitor, and the retention passes are
idempotent -- but it is N times the work and N times the log lines for one
result, and "the heartbeat monitor ran" stops meaning what an operator thinks.

So each pass is claimed first. The claim is a Redis key with a lifetime just
under the interval, taken with SET NX: whichever worker gets there first does
the work, and the others return without doing it. No leader election, no
failover to arrange: the next interval is a fresh race, so a worker that dies
holding a claim costs one skipped pass.

Without Redis there is nothing to coordinate through, and the pass runs. That is
right for the single-worker deployment that has no Redis, and duplicated for a
multi-worker one that lost it -- which is a degradation of the same kind as the
rate limiter's, and visible in the same place.
"""

from collections.abc import Awaitable, Callable

from utils.logger import logger
from utils.shared_store import redis_client

_CLAIM = "swarmguard:pass-claim:"


def claim(name: str, ttl_s: float) -> bool:
    """Claim this interval's pass of `name`. False when another worker has it."""
    store = redis_client()
    if store is None:
        return True
    try:
        return bool(store.set(_CLAIM + name, "1", nx=True, ex=max(1, int(ttl_s))))
    except Exception as exc:
        # A store that cannot answer must not stop the work happening at all.
        logger.warning(f"Could not claim the {name!r} pass ({exc}); running it here.")
        return True


def once_across_workers(
    name: str, interval_s: float, work: Callable[[], Awaitable[None]]
) -> Callable[[], Awaitable[None]]:
    """Wrap a background pass so only one worker runs each interval's."""

    async def guarded() -> None:
        # Just under the interval, so the next one is claimable when it comes
        # round and a crash costs one pass rather than a stalled loop.
        if not claim(name, interval_s * 0.9):
            return
        await work()

    guarded.__name__ = f"{getattr(work, '__name__', name)}_once_across_workers"
    return guarded
