import logging
import re
import time
import uuid
from contextvars import ContextVar


request_id_context = ContextVar('request_id', default='')
user_id_context = ContextVar('user_id', default='')
restaurant_id_context = ContextVar('restaurant_id', default='')

_SAFE_REQUEST_ID_RE = re.compile(r'^[A-Za-z0-9._-]{8,100}$')
_QUERY_SECRET_RE = re.compile(
    r'(?i)([?&](?:token|access_token|refresh_token|claim_token|claimToken|poll_token|pollToken|secret|password)=)'
    r'([^&\s\'"<>]+)'
)
_BEARER_RE = re.compile(r'(?i)(\bBearer\s+)[A-Za-z0-9._~+\-/=]+')
_AGENT_TOKEN_RE = re.compile(r'\bcpa_[A-Za-z0-9_-]+')
_LOG_SECRET_KEY_RE = re.compile(
    r'(?i)(?:^|_)(?:token|secret|password|passwd|authorization|credential|cookie|api_?key)(?:$|_)'
)
_STANDARD_LOG_RECORD_FIELDS = frozenset(
    logging.LogRecord('', 0, '', 0, '', (), None).__dict__
)


def normalize_request_id(value) -> str:
    candidate = str(value or '').strip()
    if _SAFE_REQUEST_ID_RE.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def redact_sensitive_log_text(value) -> str:
    text = str(value)
    text = _QUERY_SECRET_RE.sub(r'\1[REDACTED]', text)
    text = _BEARER_RE.sub(r'\1[REDACTED]', text)
    return _AGENT_TOKEN_RE.sub('[REDACTED]', text)


def _redact_log_value(value, *, key='', depth=0):
    normalized_key = re.sub(r'[^a-z0-9]+', '_', str(key).lower()).strip('_')
    if (
        normalized_key
        and not normalized_key.endswith('_id')
        and _LOG_SECRET_KEY_RE.search(normalized_key)
    ):
        return '[REDACTED]'
    if depth >= 5:
        return '[TRUNCATED]'
    if isinstance(value, str):
        return redact_sensitive_log_text(value)
    if isinstance(value, bytes):
        return redact_sensitive_log_text(value.decode('utf-8', errors='replace'))
    if isinstance(value, dict):
        return {
            redact_sensitive_log_text(item_key): _redact_log_value(
                item_value,
                key=item_key,
                depth=depth + 1,
            )
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_redact_log_value(item, depth=depth + 1) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    # Django's request logger attaches the WSGIRequest object as an extra
    # field. Its string representation includes the complete query string.
    return redact_sensitive_log_text(value)


class SensitiveLogFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact_sensitive_log_text(record.getMessage())
        record.args = ()
        if record.exc_info:
            # Provider payloads, SQL values and credentials may appear in an
            # arbitrary exception message. Keep only the class and correlate
            # diagnostics through the request ID.
            record.exc_text = f'{record.exc_info[0].__module__}.{record.exc_info[0].__name__}'
            record.exc_info = None
        if record.stack_info:
            record.stack_info = redact_sensitive_log_text(record.stack_info)
        for key, value in list(record.__dict__.items()):
            if key not in _STANDARD_LOG_RECORD_FIELDS:
                record.__dict__[key] = _redact_log_value(value, key=key)
        return True


def _get_user_id(request) -> str:
    user = getattr(request, 'user', None)
    if not getattr(user, 'is_authenticated', False):
        return ''
    return str(getattr(user, 'pk', '') or '')


def _get_restaurant_id(request) -> str:
    user = getattr(request, 'user', None)
    if not getattr(user, 'is_authenticated', False):
        return ''

    restaurant = getattr(user, 'get_restaurant_scope', lambda: None)()
    if restaurant is not None:
        return str(getattr(restaurant, 'pk', '') or '')

    header_value = request.headers.get('X-Admin-Restaurant-Id', '')
    return str(header_value).strip()


class RequestContextFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_context.get()
        record.user_id = user_id_context.get()
        record.restaurant_id = restaurant_id_context.get()
        for field in ('method', 'path', 'status_code', 'latency_ms'):
            if not hasattr(record, field):
                setattr(record, field, '')
        return True


class RequestLogMiddleware:
    logger = logging.getLogger('core.request')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = normalize_request_id(request.headers.get('X-Request-ID'))
        request.request_id = request_id
        request_id_token = request_id_context.set(request_id)
        user_id_token = user_id_context.set(_get_user_id(request))
        restaurant_id_token = restaurant_id_context.set(_get_restaurant_id(request))
        started_at = time.perf_counter()

        try:
            response = self.get_response(request)
            response_user_id_token = user_id_context.set(_get_user_id(request))
            response_restaurant_id_token = restaurant_id_context.set(_get_restaurant_id(request))
            try:
                self._log_response(request, response, started_at)
            finally:
                restaurant_id_context.reset(response_restaurant_id_token)
                user_id_context.reset(response_user_id_token)
            response.headers['X-Request-ID'] = request_id
            return response
        except Exception as error:
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            self.logger.error(
                'request failed (type=%s)',
                type(error).__name__,
                extra={
                    'method': request.method,
                    'path': request.path,
                    'status_code': 500,
                    'latency_ms': latency_ms,
                },
            )
            raise
        finally:
            restaurant_id_context.reset(restaurant_id_token)
            user_id_context.reset(user_id_token)
            request_id_context.reset(request_id_token)

    def _log_response(self, request, response, started_at):
        if request.path == '/metrics':
            return

        status_code = getattr(response, 'status_code', 0)
        latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
        log_method = self.logger.warning if status_code >= 400 else self.logger.info
        log_method(
            'request finished',
            extra={
                'method': request.method,
                'path': request.path,
                'status_code': status_code,
                'latency_ms': latency_ms,
            },
        )
