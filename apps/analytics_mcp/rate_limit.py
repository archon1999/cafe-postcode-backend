from hashlib import sha256
from time import time

from django.core.cache import cache


def rate_allowed(identity, limit, window=60):
    """Atomic counter with bounded TTL; Redis shares the budget across workers."""
    key = (
        "mcp:rate:"
        + sha256(identity.encode()).hexdigest()
        + ":"
        + str(int(time()) // window)
    )
    if cache.add(key, 1, timeout=window + 1):
        return True
    try:
        return cache.incr(key) <= limit
    except ValueError:
        return False
