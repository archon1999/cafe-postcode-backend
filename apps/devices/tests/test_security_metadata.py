from django.test import SimpleTestCase

from apps.devices.security import sanitize_security_metadata


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
