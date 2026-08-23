import os

from slowapi import Limiter
from slowapi.util import get_remote_address

from utils.logger import logger

# Counters live in Redis so they survive a restart and are shared across
# workers and replicas. In memory they reset on every restart and are per
# process, which makes the limit close to meaningless under any real deployment.
REDIS_URL = os.environ.get("REDIS_URL")

if REDIS_URL:
    limiter = Limiter(key_func=get_remote_address, storage_uri=REDIS_URL)
else:
    logger.warning(
        "REDIS_URL is not set: rate limiting falls back to in-memory storage. "
        "Counters will not be shared across workers and reset on restart."
    )
    limiter = Limiter(key_func=get_remote_address)
