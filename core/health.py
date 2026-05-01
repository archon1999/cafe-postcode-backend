import os

import redis
from django.db import connections
from django.http import JsonResponse


def healthz(request):
    return JsonResponse({'status': 'ok'})


def readyz(request):
    checks = {
        'database': _check_database(),
        'redis': _check_redis(),
    }
    is_ready = all(checks.values())
    return JsonResponse(
        {
            'status': 'ok' if is_ready else 'error',
            'checks': checks,
        },
        status=200 if is_ready else 503,
    )


def _check_database() -> bool:
    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return True
    except Exception:
        return False


def _check_redis() -> bool:
    redis_url = os.getenv('REDIS_URL', '').strip()
    if not redis_url:
        return False

    client = redis.from_url(redis_url, socket_connect_timeout=1, socket_timeout=1)
    try:
        return bool(client.ping())
    except Exception:
        return False
    finally:
        client.close()
