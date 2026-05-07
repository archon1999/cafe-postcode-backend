from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from apps.integrations.services.marta_softpos import MartaSoftPOSPaymentService


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses, calls, *, base_url='', timeout=0):
        self.responses = list(responses)
        self.calls = calls
        self.base_url = base_url
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def get(self, path, params=None):
        self.calls.append(
            {'path': path, 'params': params or {}, 'base_url': self.base_url, 'timeout': self.timeout}
        )
        return FakeResponse(self.responses.pop(0))


class MartaSoftPOSTests(SimpleTestCase):
    def test_successful_payment_multiplies_amount_and_stores_reference_payload(self):
        calls = []
        responses = [
            {'ok': True, 'status': 'READY', 'busy': False, 'standbyVisible': True},
            {
                'ok': True,
                'status': 'SUCCESS',
                'requestId': 'request-1',
                'params': {'trxId': 'trx-1', 'rrn': 'rrn-1', 'ac': 0},
            },
        ]
        config = SimpleNamespace(
            provider='marta-softpos',
            mode='live',
            settings={
                'endpoint_url': 'http://terminal.local:8090',
                'amount_multiplier': 100,
                'tax_number': '307678400',
            },
        )
        service = MartaSoftPOSPaymentService(
            config,
            client_factory=lambda **kwargs: FakeClient(responses, calls, **kwargs),
        )
        order = SimpleNamespace(restaurant=SimpleNamespace(tax_number='111111111'))
        payment = SimpleNamespace(id=uuid4(), amount=30000, method='card')

        result = service.charge_payment(order=order, payment=payment)

        self.assertTrue(result['ok'])
        self.assertEqual(result['reference'], 'trx-1')
        self.assertEqual(result['params']['rrn'], 'rrn-1')
        self.assertEqual(calls[1]['path'], '/transaction')
        self.assertEqual(calls[1]['params']['amount'], 3000000)
        self.assertEqual(calls[1]['params']['tin'], '307678400')
        self.assertGreater(calls[1]['params']['pid'], 0)

    def test_not_ready_health_returns_failure_without_transaction(self):
        calls = []
        responses = [
            {
                'ok': True,
                'status': 'NOT_READY',
                'busy': False,
                'standbyVisible': False,
                'message': 'SoftPOS is not ready. Open standby screen and keep the app in foreground',
            },
        ]
        config = SimpleNamespace(
            provider='marta-softpos',
            mode='live',
            settings={'endpoint_url': 'http://terminal.local:8090'},
        )
        service = MartaSoftPOSPaymentService(
            config,
            client_factory=lambda **kwargs: FakeClient(responses, calls, **kwargs),
        )
        order = SimpleNamespace(restaurant=SimpleNamespace(tax_number='307678400'))
        payment = SimpleNamespace(id=uuid4(), amount=30000, method='card')

        result = service.charge_payment(order=order, payment=payment)

        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'NOT_READY')
        self.assertIn('standby screen', result['detail'])
        self.assertEqual([call['path'] for call in calls], ['/health'])

    def test_declined_transaction_returns_failure_with_response_payload(self):
        calls = []
        responses = [
            {'ok': True, 'status': 'READY', 'busy': False, 'standbyVisible': True},
            {
                'ok': False,
                'status': 'DECLINED',
                'requestId': 'request-2',
                'message': 'Declined by host',
                'params': {'rrn': 'rrn-2', 'ac': 5},
            },
        ]
        config = SimpleNamespace(
            provider='marta-softpos',
            mode='live',
            settings={'endpoint_url': 'http://terminal.local:8090'},
        )
        service = MartaSoftPOSPaymentService(
            config,
            client_factory=lambda **kwargs: FakeClient(responses, calls, **kwargs),
        )
        order = SimpleNamespace(restaurant=SimpleNamespace(tax_number='307678400'))
        payment = SimpleNamespace(id=uuid4(), amount=30000, method='card')

        result = service.charge_payment(order=order, payment=payment)

        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'DECLINED')
        self.assertEqual(result['reference'], 'rrn-2')
        self.assertEqual(result['params']['ac'], 5)

    def test_missing_endpoint_returns_configuration_failure_without_request(self):
        calls = []
        config = SimpleNamespace(provider='marta-softpos', mode='live', settings={})
        service = MartaSoftPOSPaymentService(
            config,
            client_factory=lambda **kwargs: FakeClient([], calls, **kwargs),
        )
        order = SimpleNamespace(restaurant=SimpleNamespace(tax_number='307678400'))
        payment = SimpleNamespace(id=uuid4(), amount=30000, method='card')

        result = service.charge_payment(order=order, payment=payment)

        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'CONFIG_ERROR')
        self.assertIn('endpoint URL', result['detail'])
        self.assertEqual(calls, [])
