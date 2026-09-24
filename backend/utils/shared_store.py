"""The Redis the application already depends on, for the few things that must
be shared between workers rather than kept per process.

Rate limiting has used it since Phase 0b and WebSocket fan-out since Phase 2.
With `--workers N` two more things need it: a ticket must be spendable exactly
once however many processes there are, and a background pass must run once per
interval rather than once per worker.

Every caller must cope with `None`. Redis being unreachable is a degradation
the system is designed to survive -- see the fail-open reasoning in
utils/limiter.py -- not a reason to stop serving.
"""

import os

from utils.logger import logger

REDIS_URL = os.environ.get("REDIS_URL", "")

_client = None
_tried = False


def redis_client():
    """A shared Redis client, or None when there is none to be had.

    Connected once and reused: a client per call would open a socket per ticket
    and per background pass.
    """
    global _client, _tried
    if _client is not None or _tried:
        return _client
    _tried = True
    if not REDIS_URL:
        return None
    try:
        import redis

        client = redis.Redis.from_url(REDIS_URL, socket_timeout=1, socket_connect_timeout=1)
        client.ping()
        _client = client
    except Exception as exc:
        logger.warning(
            f"No shared store: {exc}. Single-use tickets and background passes "
            "fall back to per-process behaviour, which is correct with one worker "
            "and duplicated with several."
        )
    return _client


def reset_for_tests() -> None:
    """Forget the cached client so a test can change REDIS_URL."""
    global _client, _tried
    _client, _tried = None, False
