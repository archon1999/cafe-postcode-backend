"""Keep long-lived web workers within the container's memory budget."""

import ctypes
import gc
import os
import time


graceful_timeout = 60
_rss_limit = int(os.getenv("GUNICORN_GC_RSS_MB", "384")) * 1024 * 1024
_cleanup_interval = float(os.getenv("GUNICORN_GC_INTERVAL_SECONDS", "1"))
_page_size = os.sysconf("SC_PAGE_SIZE")
_last_cleanup = 0.0

try:
    _malloc_trim = ctypes.CDLL(None).malloc_trim
    _malloc_trim.argtypes = [ctypes.c_size_t]
    _malloc_trim.restype = ctypes.c_int
except (AttributeError, OSError):
    _malloc_trim = None


def _resident_bytes():
    try:
        with open("/proc/self/statm", encoding="ascii") as status:
            return int(status.read().split()[1]) * _page_size
    except (OSError, ValueError, IndexError):
        return 0


def pre_request(worker, request):
    """Release completed response graphs before allocating the next one."""
    global _last_cleanup

    if _rss_limit <= 0:
        return
    now = time.monotonic()
    if now - _last_cleanup < _cleanup_interval:
        return
    if _resident_bytes() < _rss_limit:
        return

    _last_cleanup = now
    gc.collect()
    if _malloc_trim is not None:
        _malloc_trim(0)


def child_exit(server, worker):
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)
