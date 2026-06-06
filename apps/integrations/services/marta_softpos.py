from __future__ import annotations

import time

import httpx
from django.utils import timezone


SUPPORTED_MARTA_PAYMENT_PROVIDERS = frozenset({'marta-softpos'})

JAVA_LONG_MAX = 9_223_372_036_854_775_807
DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_AMOUNT_MULTIPLIER = 100
DEFAULT_TRANSACTION_POLL_INTERVAL_SECONDS = 1.0
FINAL_TRANSACTION_STATUSES = frozenset({'SUCCESS', 'DECLINED', 'ERROR', 'FAILED', 'CANCELLED', 'CANCELED', 'TIMEOUT'})
PENDING_TRANSACTION_STATUSES = frozenset({'', 'ACCEPTED', 'ACTIVE', 'CREATED', 'PENDING', 'PROCESSING', 'WAITING', 'IN_PROGRESS'})


class MartaSoftPOSPaymentService:
    def __init__(self, config, *, client_factory=httpx.Client):
        self.config = config
        self.settings = dict(getattr(config, 'settings', {}) or {})
        self.client_factory = client_factory

    def charge_payment(self, *, order, payment):
        endpoint_url = self._endpoint_url()
        amount_multiplier = self._amount_multiplier()
        pid = self._pid(payment=payment)
        provider_payload = {
            'provider': self.config.provider,
            'endpoint_url': endpoint_url,
            'amount_multiplier': amount_multiplier,
            'pid': pid,
            'method': payment.method,
            'processed_at': timezone.now().isoformat(),
            'debug': {},
        }
        if not endpoint_url:
            return self._failure(
                payload=provider_payload,
                status='CONFIG_ERROR',
                detail='MARTA SoftPOS endpoint URL is not configured.',
            )

        with self._client() as client:
            health_request = self._request_snapshot(endpoint_url=endpoint_url, path='/health')
            health = self._get(client=client, path='/health')
            provider_payload['health'] = health
            provider_payload['debug']['health'] = {
                'request': health_request,
                'response': self._response_snapshot(health),
            }
            if not self._is_ready(health):
                return self._failure(
                    payload=provider_payload,
                    status=str(health.get('status') or 'NOT_READY'),
                    detail=str(
                        health.get('message')
                        or 'SoftPOS is not ready. Open standby screen and keep the app in foreground'
                    ),
                )

            transaction_params = {
                'type': 'PURCHASE',
                'amount': self._charge_amount(payment=payment) * amount_multiplier,
                'pid': pid,
                'tin': self._tax_number(order=order),
            }
            provider_payload['debug']['transaction'] = {
                'request': self._request_snapshot(
                    endpoint_url=endpoint_url,
                    path='/transaction',
                    params=transaction_params,
                ),
            }
            transaction = self._poll_transaction(
                request_transaction=lambda: self._get(client=client, path='/transaction', params=transaction_params),
                debug_payload=provider_payload['debug']['transaction'],
            )
            provider_payload['debug']['transaction']['response'] = self._response_snapshot(transaction)

        params = dict(transaction.get('params') or {})
        status = str(transaction.get('status') or '').strip().upper()
        message = str(transaction.get('message') or '').strip()
        provider_payload.update(
            {
                'requestId': transaction.get('requestId'),
                'status': status,
                'message': message,
                'params': params,
                'ac': params.get('ac'),
                'response': transaction,
            }
        )
        reference = str(params.get('trxId') or params.get('rrn') or transaction.get('requestId') or '')

        if transaction.get('ok') is True and status == 'SUCCESS':
            return {
                **provider_payload,
                'ok': True,
                'reference': reference,
            }

        return self._failure(
            payload=provider_payload,
            status=status or 'ERROR',
            detail=message or f'MARTA SoftPOS payment failed with status {status or "ERROR"}.',
            reference=reference,
        )

    def _client(self):
        return self.client_factory(base_url=self._endpoint_url(), timeout=self._timeout())

    def _endpoint_url(self) -> str:
        explicit = (
            self.settings.get('endpoint_url')
            or self.settings.get('endpointUrl')
            or self.settings.get('service_url')
            or self.settings.get('serviceUrl')
        )
        return str(explicit or '').rstrip('/')

    def _timeout(self) -> float:
        try:
            return float(
                self.settings.get('timeout_seconds')
                or self.settings.get('timeoutSeconds')
                or DEFAULT_TIMEOUT_SECONDS
            )
        except (TypeError, ValueError):
            return DEFAULT_TIMEOUT_SECONDS

    def _amount_multiplier(self) -> int:
        try:
            multiplier = int(
                self.settings.get('amount_multiplier')
                or self.settings.get('amountMultiplier')
                or DEFAULT_AMOUNT_MULTIPLIER
            )
        except (TypeError, ValueError):
            return DEFAULT_AMOUNT_MULTIPLIER
        return multiplier if multiplier > 0 else DEFAULT_AMOUNT_MULTIPLIER

    def _poll_interval(self) -> float:
        try:
            interval = float(
                self.settings.get('transaction_poll_interval_seconds')
                or self.settings.get('transactionPollIntervalSeconds')
                or DEFAULT_TRANSACTION_POLL_INTERVAL_SECONDS
            )
        except (TypeError, ValueError):
            return DEFAULT_TRANSACTION_POLL_INTERVAL_SECONDS
        return interval if interval > 0 else DEFAULT_TRANSACTION_POLL_INTERVAL_SECONDS

    def _poll_transaction(self, *, request_transaction, debug_payload: dict) -> dict:
        timeout_seconds = max(float(self._timeout()), 1.0)
        interval_seconds = min(max(self._poll_interval(), 0.1), 5.0)
        deadline = time.monotonic() + timeout_seconds
        attempts = []
        last_transaction = {}

        while True:
            transaction = request_transaction()
            last_transaction = transaction
            attempts.append(self._response_snapshot(transaction))
            if not self._is_pending_transaction(transaction):
                break
            if time.monotonic() + interval_seconds > deadline:
                break
            time.sleep(interval_seconds)

        debug_payload['attempts'] = attempts
        return last_transaction

    @staticmethod
    def _is_pending_transaction(transaction: dict) -> bool:
        status = str(transaction.get('status') or '').strip().upper()
        message = str(transaction.get('message') or '').strip().lower()
        if status in FINAL_TRANSACTION_STATUSES:
            return False
        if status in PENDING_TRANSACTION_STATUSES:
            return True
        return 'waiting for payment screen' in message or 'waiting' in message or 'accepted' in message

    def _tax_number(self, *, order) -> str:
        return str(
            self.settings.get('tax_number')
            or self.settings.get('taxNumber')
            or getattr(order.restaurant, 'tax_number', '')
            or ''
        ).strip()

    @staticmethod
    def _charge_amount(*, payment) -> int:
        mixed_method = getattr(getattr(payment, 'Method', None), 'MIXED', 'mixed')
        if str(payment.method) == str(mixed_method):
            return int(getattr(payment, 'card_amount', 0) or 0)
        return int(payment.amount or 0)

    def _pid(self, *, payment) -> int:
        pid = int(payment.id.int % JAVA_LONG_MAX)
        return pid or 1

    def _get(self, *, client, path: str, params: dict | None = None):
        cleaned_params = {key: value for key, value in (params or {}).items() if value not in (None, '')}
        try:
            response = client.get(
                path,
                params=cleaned_params,
            )
        except httpx.TimeoutException as error:
            raise MartaSoftPOSRequestError('MARTA SoftPOS request timed out.') from error
        except httpx.RequestError as error:
            raise MartaSoftPOSRequestError(f'MARTA SoftPOS request failed: {error}') from error

        try:
            payload = response.json()
        except ValueError as error:
            raise MartaSoftPOSRequestError(f'MARTA SoftPOS returned invalid JSON with HTTP {response.status_code}.') from error

        if isinstance(payload, dict):
            payload.setdefault('http_status', response.status_code)
            return payload
        raise MartaSoftPOSRequestError('MARTA SoftPOS returned an invalid response payload.')

    def _request_snapshot(self, *, endpoint_url: str, path: str, params: dict | None = None) -> dict:
        cleaned_params = {key: value for key, value in (params or {}).items() if value not in (None, '')}
        query = ''
        if cleaned_params:
            query = '?' + '&'.join(f'{key}={value}' for key, value in cleaned_params.items())
        return {
            'method': 'GET',
            'url': f'{endpoint_url}{path}{query}',
            'path': path,
            'params': cleaned_params,
        }

    @staticmethod
    def _response_snapshot(payload: dict) -> dict:
        return {
            'http_status': payload.get('http_status'),
            'body': payload,
        }

    def _is_ready(self, health: dict) -> bool:
        return (
            health.get('ok') is True
            and str(health.get('status') or '').upper() == 'READY'
            and health.get('busy') is False
            and health.get('standbyVisible') is True
        )

    def _failure(self, *, payload: dict, status: str, detail: str, reference: str = ''):
        return {
            **payload,
            'ok': False,
            'reference': reference,
            'status': status,
            'detail': detail,
        }


class MartaSoftPOSRequestError(Exception):
    pass
