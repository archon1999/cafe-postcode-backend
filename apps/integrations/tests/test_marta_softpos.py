from types import SimpleNamespace
from uuid import uuid4

from django.test import SimpleTestCase

from apps.integrations.services.agent_marta import MartaSoftPOSAgentPaymentService
from apps.integrations.services.marta_softpos import MartaSoftPOSPaymentService
from apps.local_agents.services import LocalAgentCommandError


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
        response = self.responses.pop(0)
        if isinstance(response, tuple):
            payload, status_code = response
            return FakeResponse(payload, status_code=status_code)
        return FakeResponse(response)


class FakeAgentCommandService:
    def __init__(self, *, fail_first_health=False, invalid_first_health=False):
        self.calls = []
        self.fail_first_health = fail_first_health
        self.invalid_first_health = invalid_first_health
        self.health_failures = 0

    def execute(self, *, restaurant, command_type, payload, timeout_seconds=30):
        self.calls.append({'command_type': command_type, 'payload': payload, 'timeout_seconds': timeout_seconds})
        if command_type == 'marta.discover':
            return {
                'ok': True,
                'devices': [
                    {
                        'endpointUrl': 'http://192.168.88.125:8090',
                        'status': 'READY',
                        'busy': False,
                        'standbyVisible': True,
                    }
                ],
                'scannedCount': 254,
                'port': 8090,
            }
        raise AssertionError(f'Unexpected command type: {command_type}')

    def local_http_request(self, *, restaurant, method, url, query=None, json_body=None, timeout_seconds=30):
        self.calls.append(
            {
                'command_type': 'local_http.request',
                'method': method,
                'url': url,
                'query': query or {},
                'timeout_seconds': timeout_seconds,
            }
        )
        if url.endswith('/health'):
            if self.fail_first_health and self.health_failures == 0:
                self.health_failures += 1
                raise LocalAgentCommandError('Connection refused.', code='LOCAL_HTTP_ERROR')
            if self.invalid_first_health and self.health_failures == 0:
                self.health_failures += 1
                return {
                    'ok': False,
                    'httpStatus': 404,
                    'body': {'message': 'Not found'},
                    'durationMs': 10,
                }
            return {
                'ok': True,
                'httpStatus': 200,
                'body': {'ok': True, 'status': 'READY', 'busy': False, 'standbyVisible': True},
                'durationMs': 10,
            }
        if url.endswith('/transaction'):
            return {
                'ok': True,
                'httpStatus': 200,
                'body': {
                    'ok': True,
                    'status': 'SUCCESS',
                    'requestId': 'request-agent-1',
                    'params': {'trxId': 'trx-agent-1', 'rrn': 'rrn-agent-1'},
                },
                'durationMs': 20,
            }
        raise AssertionError(f'Unexpected local HTTP URL: {url}')


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
        self.assertEqual(result['debug']['transaction']['request']['params']['amount'], 3000000)
        self.assertEqual(result['debug']['transaction']['response']['http_status'], 200)
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

    def test_non_2xx_transaction_failure_keeps_request_and_response_debug_payload(self):
        calls = []
        responses = [
            {'ok': True, 'status': 'READY', 'busy': False, 'standbyVisible': True},
            (
                {
                    'ok': False,
                    'status': 'ERROR',
                    'requestId': 'request-500',
                    'message': 'Terminal error',
                    'params': {},
                },
                500,
            ),
        ]
        config = SimpleNamespace(
            provider='marta-softpos',
            mode='live',
            settings={'endpoint_url': 'http://terminal.local:8090', 'tax_number': '307678400'},
        )
        service = MartaSoftPOSPaymentService(
            config,
            client_factory=lambda **kwargs: FakeClient(responses, calls, **kwargs),
        )
        order = SimpleNamespace(restaurant=SimpleNamespace(tax_number='111111111'))
        payment = SimpleNamespace(id=uuid4(), amount=10000, method='card')

        result = service.charge_payment(order=order, payment=payment)

        self.assertFalse(result['ok'])
        self.assertEqual(result['status'], 'ERROR')
        debug = result['debug']['transaction']
        self.assertEqual(debug['request']['path'], '/transaction')
        self.assertEqual(debug['request']['params']['type'], 'PURCHASE')
        self.assertEqual(debug['request']['params']['amount'], 1000000)
        self.assertEqual(debug['response']['http_status'], 500)
        self.assertEqual(debug['response']['body']['message'], 'Terminal error')

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


class MartaSoftPOSAgentTests(SimpleTestCase):
    def test_missing_endpoint_discovers_terminal_and_uses_it_for_payment(self):
        command_service = FakeAgentCommandService()
        config = SimpleNamespace(provider='marta-softpos', settings={'amount_multiplier': 100})
        service = MartaSoftPOSAgentPaymentService(config, command_service=command_service)
        order = SimpleNamespace(restaurant=SimpleNamespace(tax_number='307678400'))
        payment = SimpleNamespace(id=uuid4(), amount=10000, method='card')

        result = service.charge_payment(order=order, payment=payment)

        self.assertTrue(result['ok'])
        self.assertEqual(result['reference'], 'trx-agent-1')
        self.assertEqual(result['endpoint_url'], 'http://192.168.88.125:8090')
        self.assertEqual(config.settings['endpoint_url'], 'http://192.168.88.125:8090')
        self.assertEqual(command_service.calls[0]['command_type'], 'marta.discover')
        self.assertEqual(command_service.calls[1]['url'], 'http://192.168.88.125:8090/health')
        self.assertEqual(command_service.calls[2]['url'], 'http://192.168.88.125:8090/transaction')
        self.assertEqual(command_service.calls[2]['query']['amount'], 1000000)
        self.assertEqual(command_service.calls[2]['query']['tin'], '307678400')

    def test_stale_endpoint_rediscovery_retries_health_with_discovered_terminal(self):
        command_service = FakeAgentCommandService(fail_first_health=True)
        config = SimpleNamespace(
            provider='marta-softpos',
            settings={'endpoint_url': 'http://192.168.88.99:8090', 'amount_multiplier': 100},
        )
        service = MartaSoftPOSAgentPaymentService(config, command_service=command_service)
        order = SimpleNamespace(restaurant=SimpleNamespace(tax_number='307678400'))
        payment = SimpleNamespace(id=uuid4(), amount=10000, method='card')

        result = service.charge_payment(order=order, payment=payment)

        self.assertTrue(result['ok'])
        self.assertEqual(result['endpoint_url'], 'http://192.168.88.125:8090')
        self.assertEqual(command_service.calls[0]['url'], 'http://192.168.88.99:8090/health')
        self.assertEqual(command_service.calls[1]['command_type'], 'marta.discover')
        self.assertEqual(command_service.calls[2]['url'], 'http://192.168.88.125:8090/health')
        self.assertEqual(command_service.calls[3]['url'], 'http://192.168.88.125:8090/transaction')

    def test_stale_endpoint_with_non_marta_health_rediscovery_retries_discovered_terminal(self):
        command_service = FakeAgentCommandService(invalid_first_health=True)
        config = SimpleNamespace(
            provider='marta-softpos',
            settings={'endpoint_url': 'http://192.168.88.99:8090', 'amount_multiplier': 100},
        )
        service = MartaSoftPOSAgentPaymentService(config, command_service=command_service)
        order = SimpleNamespace(restaurant=SimpleNamespace(tax_number='307678400'))
        payment = SimpleNamespace(id=uuid4(), amount=10000, method='card')

        result = service.charge_payment(order=order, payment=payment)

        self.assertTrue(result['ok'])
        self.assertEqual(result['endpoint_url'], 'http://192.168.88.125:8090')
        self.assertEqual(command_service.calls[0]['url'], 'http://192.168.88.99:8090/health')
        self.assertEqual(command_service.calls[1]['command_type'], 'marta.discover')
        self.assertEqual(command_service.calls[2]['url'], 'http://192.168.88.125:8090/health')
        self.assertEqual(command_service.calls[3]['url'], 'http://192.168.88.125:8090/transaction')
