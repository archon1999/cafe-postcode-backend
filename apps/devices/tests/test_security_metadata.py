from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from apps.devices.models import SecurityEvent
from apps.devices.security import record_security_event, sanitize_security_metadata


class SecurityMetadataSanitizationTests(SimpleTestCase):
    def test_recursive_secrets_are_redacted_and_safe_context_is_preserved(self):
        result = sanitize_security_metadata(
            {
                'purpose': 'marta',
                'nested': {
                    'claimToken': 'one-use-secret',
                    'password': 'hidden',
                    'pin': '1234',
                    'reason': 'endpoint_denied',
                },
            }
        )

        self.assertEqual(result['purpose'], 'marta')
        self.assertEqual(result['nested']['reason'], 'endpoint_denied')
        self.assertEqual(result['nested']['claimToken'], '[REDACTED]')
        self.assertEqual(result['nested']['password'], '[REDACTED]')
        self.assertEqual(result['nested']['pin'], '[REDACTED]')

    def test_metadata_depth_item_count_and_string_size_are_bounded(self):
        result = sanitize_security_metadata(
            {
                'long': 'x' * 2_000,
                'many': list(range(100)),
                'deep': {'a': {'b': {'c': {'d': {'e': 'too deep'}}}}},
            }
        )

        self.assertLessEqual(len(result['long']), 512)
        self.assertEqual(result['many'][-1], '[TRUNCATED]')
        self.assertIn('[TRUNCATED]', str(result['deep']))


class SecurityEventDeduplicationTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_identical_events_are_persisted_once_inside_the_deduplication_window(self):
        first = record_security_event(
            event_type='DEVICE_PROOF_FAILED',
            severity=SecurityEvent.Severity.HIGH,
            result='DENIED',
            metadata={'reason': 'nonce_replay', 'path': '/api/v1/pos/orders/'},
            deduplicate_for_seconds=60,
        )
        duplicate = record_security_event(
            event_type='DEVICE_PROOF_FAILED',
            severity=SecurityEvent.Severity.HIGH,
            result='DENIED',
            metadata={'reason': 'nonce_replay', 'path': '/api/v1/pos/orders/'},
            deduplicate_for_seconds=60,
        )
        distinct = record_security_event(
            event_type='DEVICE_PROOF_FAILED',
            severity=SecurityEvent.Severity.HIGH,
            result='DENIED',
            metadata={'reason': 'nonce_replay', 'path': '/api/v1/pos/payments/'},
            deduplicate_for_seconds=60,
        )

        self.assertIsNotNone(first)
        self.assertIsNone(duplicate)
        self.assertIsNotNone(distinct)
        self.assertEqual(SecurityEvent.objects.count(), 2)
