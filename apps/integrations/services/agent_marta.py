from __future__ import annotations

import time

from django.utils import timezone

from apps.integrations.services.marta_softpos import (
    DEFAULT_AMOUNT_MULTIPLIER,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_TRANSACTION_POLL_INTERVAL_SECONDS,
    FINAL_TRANSACTION_STATUSES,
    JAVA_LONG_MAX,
    PENDING_TRANSACTION_STATUSES,
)
from apps.local_agents.services import LocalAgentCommandError, LocalAgentCommandService, LocalAgentUnavailableError


class MartaSoftPOSAgentPaymentService:
    def __init__(self, config, *, command_service=None):
        self.config = config
        self.settings = dict(getattr(config, 'settings', {}) or {})
        self.command_service = command_service or LocalAgentCommandService()

    def charge_payment(self, *, order, payment):
        endpoint_url = self._endpoint_url()
        amount_multiplier = self._amount_multiplier()
        pid = self._pid(payment=payment)
        provider_payload = {
            'provider': self.config.provider,
            'transport': 'local-agent',
            'endpoint_url': endpoint_url,
            'amount_multiplier': amount_multiplier,
            'pid': pid,
            'method': payment.method,
            'processed_at': timezone.now().isoformat(),
            'debug': {},
        }

        try:
            endpoint_url = self._resolve_endpoint_url(order=order, payload=provider_payload)
            provider_payload['endpoint_url'] = endpoint_url
            if not endpoint_url:
                return self._failure(
                    payload=provider_payload,
                    status='NOT_FOUND',
                    detail='MARTA SoftPOS terminal was not found on the local network.',
                    code='MARTA_NOT_FOUND',
                )

            try:
                health_result = self._request_health(order=order, endpoint_url=endpoint_url, payload=provider_payload)
            except LocalAgentCommandError as error:
                rediscovered_url = self._discover_endpoint_url(order=order, payload=provider_payload, reason=error.code)
                if not rediscovered_url or rediscovered_url == endpoint_url:
                    raise
                endpoint_url = rediscovered_url
                provider_payload['endpoint_url'] = endpoint_url
                health_result = self._request_health(order=order, endpoint_url=endpoint_url, payload=provider_payload)

            health = self._body(health_result)
            provider_payload['health'] = health
            if not self._looks_like_marta_health(health):
                rediscovered_url = self._discover_endpoint_url(order=order, payload=provider_payload, reason='invalid_health')
                if rediscovered_url and rediscovered_url != endpoint_url:
                    endpoint_url = rediscovered_url
                    provider_payload['endpoint_url'] = endpoint_url
                    health_result = self._request_health(order=order, endpoint_url=endpoint_url, payload=provider_payload)
                    health = self._body(health_result)
                    provider_payload['health'] = health
            if not self._is_ready(health):
                return self._failure(
                    payload=provider_payload,
                    status=str(health.get('status') or 'NOT_READY'),
                    detail=str(
                        health.get('message')
                        or 'SoftPOS is not ready. Open standby screen and keep the app in foreground'
                    ),
                    code='MARTA_NOT_READY',
                )

            transaction_params = {
                'type': 'PURCHASE',
                'amount': self._charge_amount(payment=payment) * amount_multiplier,
                'pid': pid,
                'tin': self._tax_number(order=order),
            }
            provider_payload['debug']['transaction'] = {
                'request': self._request_snapshot(endpoint_url=endpoint_url, path='/transaction', params=transaction_params)
            }
            transaction_result = self._poll_transaction(
                request_transaction=lambda: self._request_transaction(
                    order=order,
                    endpoint_url=endpoint_url,
                    params=transaction_params,
                    payload=provider_payload,
                ),
                debug_payload=provider_payload['debug']['transaction'],
            )
        except LocalAgentUnavailableError as error:
            return self._failure(payload=provider_payload, status='AGENT_OFFLINE', detail=str(error), code=error.code)
        except LocalAgentCommandError as error:
            return self._failure(
                payload=provider_payload,
                status=error.code,
                detail=str(error),
                code=error.code,
                response=error.result,
            )

        transaction = self._body(transaction_result)
        provider_payload['debug']['transaction']['response'] = self._response_snapshot(transaction_result)
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
            return {**provider_payload, 'ok': True, 'reference': reference}

        return self._failure(
            payload=provider_payload,
            status=status or 'ERROR',
            detail=message or f'MARTA SoftPOS payment failed with status {status or "ERROR"}.',
            reference=reference,
            code=f'MARTA_{status or "ERROR"}',
        )

    def _resolve_endpoint_url(self, *, order, payload: dict) -> str:
        endpoint_url = self._endpoint_url()
        if endpoint_url:
            return endpoint_url
        return self._discover_endpoint_url(order=order, payload=payload, reason='missing_endpoint')

    def _discover_endpoint_url(self, *, order, payload: dict, reason: str) -> str:
        discovery_payload = {
            'port': self._positive_int('discovery_port', 'discoveryPort', fallback=8090),
            'timeoutMillis': self._positive_int(
                'discovery_timeout_millis',
                'discoveryTimeoutMillis',
                fallback=900,
            ),
            'maxConcurrency': self._positive_int(
                'discovery_max_concurrency',
                'discoveryMaxConcurrency',
                fallback=96,
            ),
        }
        payload['debug']['discovery'] = {
            'reason': reason,
            'request': discovery_payload,
        }
        result = self.command_service.execute(
            restaurant=order.restaurant,
            command_type='marta.discover',
            payload=discovery_payload,
            timeout_seconds=35,
        )
        payload['debug']['discovery']['response'] = result
        devices = result.get('devices') if isinstance(result.get('devices'), list) else []
        first_device = devices[0] if devices and isinstance(devices[0], dict) else {}
        endpoint_url = str(first_device.get('endpointUrl') or first_device.get('endpoint_url') or '').rstrip('/')
        if endpoint_url:
            self._persist_endpoint_url(endpoint_url)
        return endpoint_url

    def _request_health(self, *, order, endpoint_url: str, payload: dict) -> dict:
        payload['debug']['health'] = {'request': self._request_snapshot(endpoint_url=endpoint_url, path='/health')}
        result = self.command_service.local_http_request(
            restaurant=order.restaurant,
            method='GET',
            url=f'{endpoint_url}/health',
            purpose='marta',
            integration_id=getattr(self.config, 'pk', None),
            timeout_seconds=int(self._timeout()),
        )
        payload['debug']['health']['response'] = self._response_snapshot(result)
        return result

    def _request_transaction(self, *, order, endpoint_url: str, params: dict, payload: dict) -> dict:
        payload['debug'].setdefault(
            'transaction',
            {'request': self._request_snapshot(endpoint_url=endpoint_url, path='/transaction', params=params)},
        )
        result = self.command_service.local_http_request(
            restaurant=order.restaurant,
            method='GET',
            url=f'{endpoint_url}/transaction',
            purpose='marta',
            integration_id=getattr(self.config, 'pk', None),
            query=params,
            timeout_seconds=int(self._timeout()),
        )
        return result

    def _persist_endpoint_url(self, endpoint_url: str):
        self.settings['endpoint_url'] = endpoint_url
        self.config.settings = self.settings
        if not hasattr(self.config, 'save'):
            return
        try:
            self.config.save(update_fields=['settings', 'updated_at'])
        except Exception:
            return

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

    def _positive_int(self, *keys: str, fallback: int) -> int:
        for key in keys:
            value = self.settings.get(key)
            if value in (None, ''):
                continue
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed > 0:
                return parsed
        return fallback

    def _poll_transaction(self, *, request_transaction, debug_payload: dict) -> dict:
        timeout_seconds = max(float(self._timeout()), 1.0)
        interval_seconds = min(max(self._poll_interval(), 0.1), 5.0)
        deadline = time.monotonic() + timeout_seconds
        attempts = []
        last_result = {}

        while True:
            result = request_transaction()
            last_result = result
            attempts.append(self._response_snapshot(result))
            if not self._is_pending_transaction(self._body(result)):
                break
            if time.monotonic() + interval_seconds > deadline:
                break
            time.sleep(interval_seconds)

        debug_payload['attempts'] = attempts
        return last_result

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

    @staticmethod
    def _body(result: dict) -> dict:
        body = result.get('body') if isinstance(result.get('body'), dict) else {}
        if 'httpStatus' not in body and result.get('httpStatus') is not None:
            body = {**body, 'httpStatus': result.get('httpStatus'), 'http_status': result.get('httpStatus')}
        return body

    @staticmethod
    def _request_snapshot(*, endpoint_url: str, path: str, params: dict | None = None) -> dict:
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
    def _response_snapshot(result: dict) -> dict:
        return {
            'ok': result.get('ok'),
            'httpStatus': result.get('httpStatus'),
            'body': result.get('body'),
            'rawBody': result.get('rawBody'),
            'durationMs': result.get('durationMs'),
        }

    @staticmethod
    def _is_ready(health: dict) -> bool:
        return (
            health.get('ok') is True
            and str(health.get('status') or '').upper() == 'READY'
            and health.get('busy') is False
            and health.get('standbyVisible') is True
        )

    @staticmethod
    def _looks_like_marta_health(health: dict) -> bool:
        if not health:
            return False
        if health.get('httpStatus') is not None:
            try:
                http_status = int(health.get('httpStatus') or 0)
            except (TypeError, ValueError):
                return False
            if not 200 <= http_status < 300:
                return False
        if 'standbyVisible' in health or 'flowGuardBusy' in health:
            return True
        if str(health.get('status') or '').strip().upper() in {'READY', 'NOT_READY', 'BUSY', 'IDLE', 'ACTIVE'}:
            return True
        return all(key in health for key in ('ok', 'port', 'phase'))

    @staticmethod
    def _failure(*, payload: dict, status: str, detail: str, reference: str = '', code: str = '', response=None):
        result = {
            **payload,
            'ok': False,
            'reference': reference,
            'status': status,
            'detail': detail,
        }
        if code:
            result['code'] = code
        if response is not None:
            result['response'] = response
        return result
