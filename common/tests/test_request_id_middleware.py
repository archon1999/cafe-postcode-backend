import logging

from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from core.observability import RequestLogMiddleware, SensitiveLogFilter, redact_sensitive_log_text


class RequestIDMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = RequestLogMiddleware(lambda request: JsonResponse({'requestId': request.request_id}))

    def test_preserves_safe_caller_request_id(self):
        request = self.factory.get('/health/', HTTP_X_REQUEST_ID='client-request_123')

        response = self.middleware(request)

        self.assertEqual(response.headers['X-Request-ID'], 'client-request_123')
        self.assertEqual(request.request_id, 'client-request_123')

    def test_replaces_log_injection_or_oversized_request_id(self):
        for unsafe in ('short', 'trusted\r\nX-Forged: yes', 'x' * 101):
            with self.subTest(unsafe=unsafe):
                request = self.factory.get('/health/', HTTP_X_REQUEST_ID=unsafe)

                response = self.middleware(request)

                generated = response.headers['X-Request-ID']
                self.assertRegex(generated, r'^[a-f0-9]{32}$')
                self.assertEqual(request.request_id, generated)

    def test_sensitive_log_filter_redacts_query_and_bearer_credentials(self):
        token = 'cpa_this-secret-must-not-appear'
        raw = f"Unauthorized /sync/?token={token} Authorization: Bearer opaque.jwt.secret"

        redacted = redact_sensitive_log_text(raw)
        record = logging.LogRecord('test', logging.WARNING, __file__, 1, 'failed %s', (raw,), None)
        SensitiveLogFilter().filter(record)

        self.assertNotIn(token, redacted)
        self.assertNotIn(token, record.getMessage())
        self.assertNotIn('opaque.jwt.secret', record.getMessage())
        self.assertIn('[REDACTED]', record.getMessage())

    def test_sensitive_log_filter_never_formats_raw_exception_message(self):
        secret = 'provider-password-that-does-not-match-a-token-pattern'
        try:
            raise RuntimeError(secret)
        except RuntimeError:
            import sys

            record = logging.LogRecord(
                'test', logging.ERROR, __file__, 1, 'request failed', (), sys.exc_info()
            )

        SensitiveLogFilter().filter(record)

        self.assertNotIn(secret, record.getMessage())
        self.assertNotIn(secret, str(record.exc_text))
        self.assertEqual(record.exc_text, 'builtins.RuntimeError')

    def test_sensitive_log_filter_redacts_request_object_and_nested_extra_fields(self):
        token = 'cpa_request-extra-secret'
        request = self.factory.get(f'/sync/?token={token}')
        record = logging.LogRecord(
            'django.request', logging.WARNING, __file__, 1, 'Unauthorized', (), None
        )
        record.request = request
        record.provider = {
            'authorization': 'arbitrary-value-that-does-not-look-like-a-bearer-token',
            'telegram_link_token_id': 'safe-correlation-id',
        }

        SensitiveLogFilter().filter(record)

        self.assertNotIn(token, str(record.request))
        self.assertIn('[REDACTED]', str(record.request))
        self.assertEqual(record.provider['authorization'], '[REDACTED]')
        self.assertEqual(record.provider['telegram_link_token_id'], 'safe-correlation-id')
