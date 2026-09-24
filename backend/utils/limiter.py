import hashlib
import os

from slowapi import Limiter
from slowapi.util import get_remote_address

from utils.logger import logger

# Per-device credentials carry this prefix (services/device_credentials.py).
# Matched here rather than imported, so the limiter -- which runs before any
# dependency resolves -- stays free of the service layer and its database.
DEVICE_KEY_PREFIX = "sgd_"

# Counters live in Redis so they survive a restart and are shared across
# workers and replicas. In memory they reset on every restart and are per
# process, which makes the limit close to meaningless under any real deployment.
REDIS_URL = os.environ.get("REDIS_URL")

if REDIS_URL:
    # Rate limiting must not be able to take down authentication.
    #
    # It could, and did. With REDIS_URL set and Redis unreachable, the storage
    # backend raised ConnectionError, main.py's catch-all handler turned it into
    # a 500, and every rate-limited route failed -- including /auth/login. A
    # Redis restart or a network blip locked every operator out of the product.
    # compose's `depends_on: condition: service_healthy` only covers startup; it
    # says nothing about the next hour.
    #
    # Two settings, in order of preference:
    #
    # in_memory_fallback_enabled  -- when Redis is unreachable, keep enforcing
    #   the limits from process memory. Counters are per-worker and reset on
    #   restart, so the effective limit is looser than configured, but a brute
    #   force still meets a wall. This is degradation, not removal.
    #
    # swallow_errors -- backstop for any storage failure the fallback does not
    #   cover. Serves the request rather than 500ing.
    #
    # Both fail *open*. That is the deliberate trade: a window of weaker rate
    # limiting is a smaller risk than a total authentication outage. It is only
    # the right trade if someone finds out, which is what the `rate_limiter`
    # field on /system/health and the error log below are for -- alert on
    # "Rate limiter storage unavailable".
    limiter = Limiter(
        key_func=get_remote_address,
        storage_uri=REDIS_URL,
        in_memory_fallback_enabled=True,
        swallow_errors=True,
    )
else:
    logger.warning(
        "REDIS_URL is not set: rate limiting falls back to in-memory storage. "
        "Counters will not be shared across workers and reset on restart."
    )
    limiter = Limiter(key_func=get_remote_address)


def device_or_address(request) -> str:
    """Rate-limit a drone by its own credential, or by address if it has none.

    Keyed on the client address, one ground station's uplink is one bucket, and
    the fleet behind it divides the ingest limit between them: the load test of
    2026-09-22 measured twenty drones sharing 50 packets/second, 2.5 Hz each,
    and one noisy airframe can spend the whole allowance.

    A per-device credential is a stable identity that arrives with the packet,
    so each drone gets its own bucket and cannot starve its neighbours. The key
    is a digest, never the credential itself: limiter keys end up in Redis and
    in error messages.

    The shared fleet key identifies no one -- every drone presents the same
    string -- so it keeps the old address bucket rather than putting the whole
    fleet in one. That is another reason to finish migrating off it.
    """
    presented = request.headers.get("x-drone-api-key") or ""
    if presented.startswith(DEVICE_KEY_PREFIX):
        return "device:" + hashlib.sha256(presented.encode()).hexdigest()[:32]
    return get_remote_address(request)


def storage_healthy() -> tuple[bool, str]:
    """Whether the limiter's backing store is reachable.

    Surfaced on /system/health so a degraded limiter is visible to an operator
    instead of being inferred from a quiet log line.
    """
    if not REDIS_URL:
        return True, "in-memory (no REDIS_URL configured)"
    try:
        limiter.limiter.storage.check()
        return True, "redis"
    except Exception as exc:  # any storage failure means "degraded"
        logger.error(f"Rate limiter storage unavailable, failing open: {exc}")
        return False, f"redis unreachable: {exc}"
