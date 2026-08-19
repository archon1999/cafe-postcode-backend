from django.test import RequestFactory, SimpleTestCase, override_settings

from common.api.client_ip import get_client_ip
from common.api.throttling import LoginRateThrottle, PinDeviceRateThrottle


class TrustedClientIPTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(CLIENT_IP_TRUSTED_PROXY_CIDRS=['127.0.0.1/32', '10.0.0.0/8'])
    def test_untrusted_peer_cannot_spoof_cloudflare_or_forwarded_headers(self):
        request = self.factory.get(
            '/',
            REMOTE_ADDR='198.51.100.20',
            HTTP_CF_CONNECTING_IP='10.20.30.40',
            HTTP_X_FORWARDED_FOR='10.20.30.40',
        )
        self.assertEqual(get_client_ip(request), '198.51.100.20')

    @override_settings(CLIENT_IP_TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
    def test_trusted_edge_may_supply_cloudflare_client_ip(self):
        request = self.factory.get(
            '/',
            REMOTE_ADDR='127.0.0.1',
            HTTP_CF_CONNECTING_IP='203.0.113.7',
        )
        self.assertEqual(get_client_ip(request), '203.0.113.7')

    @override_settings(CLIENT_IP_TRUSTED_PROXY_CIDRS=['127.0.0.1/32', '10.0.0.0/8'])
    def test_forwarded_chain_is_walked_only_through_trusted_proxies(self):
        request = self.factory.get(
            '/',
            REMOTE_ADDR='127.0.0.1',
            HTTP_X_FORWARDED_FOR='192.0.2.8, 198.51.100.9, 10.0.0.4',
        )
        self.assertEqual(get_client_ip(request), '198.51.100.9')

    @override_settings(CLIENT_IP_TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
    def test_malformed_forwarded_value_fails_back_to_socket_peer(self):
        request = self.factory.get(
            '/',
            REMOTE_ADDR='127.0.0.1',
            HTTP_X_FORWARDED_FOR='not-an-ip',
        )
        self.assertEqual(get_client_ip(request), '127.0.0.1')

    @override_settings(CLIENT_IP_TRUSTED_PROXY_CIDRS=['127.0.0.1/32'])
    def test_rate_limit_identity_cannot_be_rotated_with_spoofed_forwarded_headers(self):
        throttle = LoginRateThrottle()
        first = self.factory.post('/', REMOTE_ADDR='198.51.100.20', HTTP_X_FORWARDED_FOR='1.1.1.1')
        second = self.factory.post('/', REMOTE_ADDR='198.51.100.20', HTTP_X_FORWARDED_FOR='8.8.8.8')

        self.assertEqual(throttle.get_cache_key(first, None), throttle.get_cache_key(second, None))

    def test_valid_device_has_an_independent_pin_rate_limit_identity(self):
        throttle = PinDeviceRateThrottle()
        request = self.factory.post(
            '/',
            HTTP_X_DEVICE_ID='11111111-1111-4111-8111-111111111111',
        )

        self.assertEqual(throttle.rate, '5/min')
        self.assertIn('11111111-1111-4111-8111-111111111111', throttle.get_cache_key(request, None))
        malformed = self.factory.post('/', HTTP_X_DEVICE_ID='spoofed')
        self.assertIsNone(throttle.get_cache_key(malformed, None))
