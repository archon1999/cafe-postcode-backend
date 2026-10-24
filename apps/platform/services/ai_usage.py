"""Best-effort metadata audit; never log provider bodies, prompts, documents or keys.

Verified exact-model Standard rates and optional operator overrides are defined
in ai_pricing. Cached application responses create no new provider requests.
"""
import logging
import re
from time import monotonic
from uuid import UUID

import httpx
from django.db import transaction

from .ai_pricing import MAX_TOKENS, estimated_cost

logger = logging.getLogger(__name__)
PROVIDER_STATUSES = {'completed', 'incomplete', 'failed', 'cancelled', 'queued', 'in_progress'}


def _count(value):
    return value if type(value) is int and 0 <= value <= MAX_TOKENS else None


def _identifier(value, prefix=None, limit=128):
    if not isinstance(value, str) or len(value) > limit or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*', value):
        return ''
    if value.startswith(('sk-', 'sk_')) or (prefix and not value.startswith(prefix)):
        return ''
    return value


def _uuid(value):
    try:
        return UUID(str(getattr(value, 'pk', value))) if value is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def token_usage(result):
    usage = result.get('usage') if isinstance(result, dict) else None
    if not isinstance(usage, dict):
        return dict(input_tokens=None, cached_input_tokens=None, output_tokens=None, total_tokens=None)
    incoming, outgoing = _count(usage.get('input_tokens')), _count(usage.get('output_tokens'))
    details = usage.get('input_tokens_details')
    cached = _count(details.get('cached_tokens')) if isinstance(details, dict) else None
    if cached is not None and (incoming is None or cached > incoming):
        cached = None
    total = _count(usage.get('total_tokens'))
    if incoming is not None and outgoing is not None:
        expected = incoming + outgoing
        total = expected if total is None and expected <= MAX_TOKENS else total
        if total != expected:
            total = None
    return dict(input_tokens=incoming, cached_input_tokens=cached, output_tokens=outgoing, total_tokens=total)


def _error(exception, http_status, provider_status):
    if http_status and http_status >= 400:
        return f'provider_http_{http_status}', f'AI provider returned HTTP {http_status}.'
    current = exception
    for _ in range(5):
        if isinstance(current, httpx.TimeoutException):
            return 'provider_timeout', 'AI provider did not respond in time.'
        if isinstance(current, httpx.TransportError):
            return 'provider_connection_error', 'Could not connect to the AI provider.'
        current = getattr(current, '__context__', None)
        if current is None:
            break
    if provider_status in ('incomplete', 'failed', 'cancelled'):
        return f'provider_{provider_status}', 'AI provider did not complete the response.'
    return 'invalid_response', 'AI response could not be validated for this feature.'


def _persist_usage(values):
    from apps.platform.models import AIUsageLog
    # A savepoint keeps an accounting failure from poisoning a caller transaction.
    with transaction.atomic():
        AIUsageLog.objects.create(**values)


class audit_ai_usage:
    """Wrap only an actual provider attempt, after config, input and cache checks."""
    def __init__(self, feature, model, *, restaurant=None, user=None):
        self.feature = feature
        self.model = _identifier(model, limit=120) or 'unknown'
        self.restaurant, self.user = restaurant, user
        self.usage = token_usage({})
        self.request_id = ''
        self.provider_status = ''
        self.http_status = None

    def __enter__(self):
        self.started = monotonic()
        return self

    def observe_http(self, response):
        value = getattr(response, 'status_code', None)
        self.http_status = value if type(value) is int else None
        headers = getattr(response, 'headers', None)
        self.request_id = _identifier(headers.get('x-request-id'), 'req_') if hasattr(headers, 'get') else ''
        if self.http_status and self.http_status >= 400:
            try:
                self.observe_result(response.json())
            except (ValueError, TypeError, AttributeError):
                pass

    def observe_result(self, result):
        if not isinstance(result, dict):
            return
        self.usage = token_usage(result)
        self.model = _identifier(result.get('model'), limit=120) or self.model
        status = result.get('status')
        self.provider_status = status if isinstance(status, str) and status in PROVIDER_STATUSES else ''
        self.request_id = self.request_id or _identifier(result.get('id'), 'resp_')

    def __exit__(self, exception_type, exception, traceback):
        try:
            partner = getattr(self.restaurant, 'business_partner', None)
            cost, pricing = estimated_cost(self.model, self.usage)
            error_code, summary = _error(exception, self.http_status, self.provider_status) if exception_type else ('', '')
            _persist_usage({
                'restaurant_id': _uuid(self.restaurant), 'business_partner_id': _uuid(partner), 'user_id': _uuid(self.user),
                'restaurant_name': str(getattr(self.restaurant, 'name', '') or '')[:255],
                'business_partner_name': str(getattr(partner, 'company_name', '') or '')[:255],
                'user_name': str(getattr(self.user, 'full_name', '') or getattr(self.user, 'username', '') or '')[:255],
                'feature': self.feature, 'provider': 'openai', 'model': self.model,
                'status': 'error' if exception_type else 'success', **self.usage,
                'estimated_cost_usd': cost, 'pricing': pricing,
                'duration_ms': min(2147483647, max(0, round((monotonic() - self.started) * 1000))),
                'request_id': self.request_id, 'provider_status': self.provider_status,
                'error_code': error_code, 'error_summary': summary,
            })
        except Exception as error:
            # Audit must not break a valid business response or hide its failure.
            # Do not stringify errors: DB exceptions can include sensitive values.
            logger.warning('AI usage audit could not be persisted (%s).', type(error).__name__)
        return False
