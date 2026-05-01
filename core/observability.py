import logging
import time
import uuid
from contextvars import ContextVar


request_id_context = ContextVar('request_id', default='')
user_id_context = ContextVar('user_id', default='')
restaurant_id_context = ContextVar('restaurant_id', default='')


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
        request_id = request.headers.get('X-Request-ID') or uuid.uuid4().hex
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
        except Exception:
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
            self.logger.exception(
                'request failed',
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
