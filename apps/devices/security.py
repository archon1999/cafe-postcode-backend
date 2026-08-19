import logging
import re

from apps.devices.models import SecurityEvent
from common.api.client_ip import get_client_ip


logger = logging.getLogger(__name__)

_SENSITIVE_METADATA_KEY = re.compile(
    r'(?:authorization|cookie|credential|password|passwd|secret|token|claim|poll|private[_-]?key|pin)',
    re.IGNORECASE,
)
_MAX_METADATA_DEPTH = 4
_MAX_METADATA_ITEMS = 50
_MAX_METADATA_STRING = 500
_MAX_METADATA_BUDGET = 8_000


def sanitize_security_metadata(metadata) -> dict:
    budget = [_MAX_METADATA_BUDGET]

    def consume(value: str) -> str:
        remaining = max(0, budget[0])
        if remaining == 0:
            return '[TRUNCATED]'
        limited = value[: min(_MAX_METADATA_STRING, remaining)]
        budget[0] -= len(limited)
        if len(limited) < len(value):
            return f'{limited}[TRUNCATED]'
        return limited

    def clean(value, *, depth: int, key: str = ''):
        if key and _SENSITIVE_METADATA_KEY.search(key):
            return '[REDACTED]'
        if depth > _MAX_METADATA_DEPTH or budget[0] <= 0:
            return '[TRUNCATED]'
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return consume(value)
        if isinstance(value, dict):
            result = {}
            for index, (item_key, item_value) in enumerate(value.items()):
                if index >= _MAX_METADATA_ITEMS:
                    result['_truncated'] = True
                    break
                safe_key = consume(str(item_key))
                result[safe_key] = clean(item_value, depth=depth + 1, key=safe_key)
            return result
        if isinstance(value, (list, tuple)):
            result = [clean(item, depth=depth + 1) for item in value[:_MAX_METADATA_ITEMS]]
            if len(value) > _MAX_METADATA_ITEMS:
                result.append('[TRUNCATED]')
            return result
        return consume(f'<{type(value).__name__}>')

    cleaned = clean(metadata if isinstance(metadata, dict) else {}, depth=0)
    return cleaned if isinstance(cleaned, dict) else {}


def record_security_event(
    *,
    event_type: str,
    severity=SecurityEvent.Severity.INFO,
    request=None,
    restaurant=None,
    actor=None,
    device=None,
    auth_session=None,
    result='',
    metadata=None,
):
    safe_metadata = sanitize_security_metadata(metadata)
    # Never access request.user while authentication itself is still running;
    # doing so recursively invokes the authenticator. DRF stores an already
    # authenticated principal in _user.
    request_actor = getattr(request, '_user', None) if request is not None else None
    if request_actor is not None and not getattr(request_actor, 'is_authenticated', False):
        request_actor = None
    try:
        return SecurityEvent.objects.create(
            event_type=str(event_type)[:80],
            severity=severity,
            restaurant=restaurant or getattr(device, 'restaurant', None),
            actor=actor or request_actor,
            device=device,
            auth_session_id=getattr(auth_session, 'pk', None),
            request_id=(
                str(
                    getattr(request, 'request_id', '')
                    or request.headers.get('X-Request-Id', '')
                )[:100]
                if request is not None
                else ''
            ),
            client_ip=get_client_ip(request) if request is not None else None,
            result=str(result or '')[:32],
            metadata=safe_metadata,
        )
    except Exception:
        logger.exception('Unable to persist security event %s', event_type)
        return None
